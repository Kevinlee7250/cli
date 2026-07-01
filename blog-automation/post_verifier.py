#!/usr/bin/env python3
"""
post_verifier.py — 게시 완료글 검증 엔진 + 자동 재게시
---------------------------------------------------------
기능:
  1. posts.json에서 published 포스트 목록 로드
  2. 각 포스트에 대해 7개 레이어 검증
  3. 점수화 → verify_report.json 저장
  4. 실패 포스트 → pending_posts.json 재등록 (재게시 큐)
  5. 재게시 큐 포스트 → publish_pending.py 자동 호출
  6. 심각 실패 → GitHub Issue 생성

검증 항목:
  [게시] URL 접근성, 게시 상태
  [콘텐츠] 최소 분량, 이미지, 내부 링크, 관련 포스트 섹션
  [SEO] JSON-LD Schema, 라벨 수
  [광고] AdSense 코드 포함 여부

사용법:
  python post_verifier.py                      # 최근 25시간 내 게시 포스트 검증
  python post_verifier.py --all                # 전체 포스트 재검증
  python post_verifier.py --hours 48           # 최근 48시간 내 포스트
  python post_verifier.py --post-id POST_ID    # 특정 포스트만
  python post_verifier.py --report             # 기존 리포트 출력
  python post_verifier.py --grade C            # 특정 등급 포스트 재검증
  python post_verifier.py --repost-failed      # verify_report의 repost 항목 즉시 재게시
"""

import os
import sys
import json
import logging
import argparse
import re
import time
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# ─────────────────────────────────────────────
# 환경 설정
# ─────────────────────────────────────────────
GITHUB_TOKEN      = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "Kevinlee7250/cli")
BLOGGER_BLOG_ID   = os.environ.get("BLOGGER_BLOG_ID", "")

OWNER, REPO = GITHUB_REPOSITORY.split("/") if "/" in GITHUB_REPOSITORY else ("", GITHUB_REPOSITORY)
BRANCH = os.environ.get("GITHUB_REF_NAME", "claude/blog-automation-system-KAbtE")

BASE_DIR      = Path(__file__).parent
DATA_DIR      = BASE_DIR.parent / "docs" / "data"
POSTS_FILE    = DATA_DIR / "posts.json"
PENDING_FILE  = DATA_DIR / "pending_posts.json"
REPORT_FILE   = DATA_DIR / "verify_report.json"

# 검증 가중치 (합계 100)
WEIGHTS = {
    "url_accessible":    20,
    "min_content_len":   15,
    "has_image":         15,
    "has_internal_link": 10,
    "has_related_posts": 10,
    "has_schema_ld":     20,
    "has_label":          5,
    "has_adsense":        5,
}
PASS_THRESHOLD  = 60   # 이 점수 미만이면 warn/repost 액션
REPOST_MAX_RETRY = 2   # 최대 재게시 시도 횟수

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# GitHub API 헬퍼
# ─────────────────────────────────────────────
def _gh_headers() -> dict:
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }


def _gh_post(path: str, payload: dict) -> dict:
    url = f"https://api.github.com{path}"
    resp = requests.post(url, headers=_gh_headers(), json=payload, timeout=20)
    resp.raise_for_status()
    return resp.json()


# ─────────────────────────────────────────────
# 데이터 로드 / 저장
# ─────────────────────────────────────────────
def load_posts() -> list:
    if not POSTS_FILE.exists():
        logger.error(f"posts.json 없음: {POSTS_FILE}")
        return []
    return json.loads(POSTS_FILE.read_text(encoding="utf-8"))


def load_pending() -> list:
    if not PENDING_FILE.exists():
        return []
    return json.loads(PENDING_FILE.read_text(encoding="utf-8"))


def save_pending(pending: list):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PENDING_FILE.write_text(
        json.dumps(pending, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def load_report() -> dict:
    if REPORT_FILE.exists():
        return json.loads(REPORT_FILE.read_text(encoding="utf-8"))
    return {"results": {}, "summary": {}, "last_updated": None}


def save_report(report: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    report["last_updated"] = datetime.now(timezone.utc).isoformat()
    REPORT_FILE.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    logger.info(f"리포트 저장: {REPORT_FILE}")


# ─────────────────────────────────────────────
# 포스트 필터링
# ─────────────────────────────────────────────
def filter_posts(posts: list, args) -> list:
    published = [
        p for p in posts
        if p.get("status") in ("published", "live", "LIVE")
        and (p.get("url") or p.get("blogUrl") or p.get("link"))
    ]

    if getattr(args, "post_id", None):
        return [p for p in published
                if p.get("id") == args.post_id or p.get("postId") == args.post_id]

    if getattr(args, "grade", None):
        return [p for p in published
                if p.get("grade", "").upper() == args.grade.upper()]

    if getattr(args, "all", False):
        return published

    # 기본: 최근 N시간 내 게시
    hours = getattr(args, "hours", 25)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    result = []
    for p in published:
        ts = p.get("publishedAt") or p.get("savedAt") or p.get("createdAt") or ""
        if len(ts) == 14 and ts.isdigit():
            try:
                dt = datetime(int(ts[:4]), int(ts[4:6]), int(ts[6:8]),
                              int(ts[8:10]), int(ts[10:12]), int(ts[12:14]),
                              tzinfo=timezone.utc)
                if dt >= cutoff:
                    result.append(p)
            except ValueError:
                pass
        elif ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt >= cutoff:
                    result.append(p)
            except ValueError:
                pass
    return result


# ─────────────────────────────────────────────
# URL 가져오기
# ─────────────────────────────────────────────
def fetch_html(url: str, timeout: int = 15) -> tuple:
    try:
        resp = requests.get(url, timeout=timeout, headers={
            "User-Agent": "Mozilla/5.0 (compatible; BlogVerifier/1.0)"
        })
        return resp.status_code, resp.text
    except requests.RequestException as e:
        logger.warning(f"URL 접근 실패 ({url}): {e}")
        return 0, ""


# ─────────────────────────────────────────────
# 개별 검증 함수
# ─────────────────────────────────────────────
def check_url_accessible(url: str, html: str, status: int) -> dict:
    passed = status == 200
    return {"pass": passed, "value": status,
            "note": "접근 성공" if passed else f"HTTP {status}"}


def check_min_content_len(html: str, min_len: int = 500) -> dict:
    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"\s+", " ", text).strip()
    length = len(text)
    return {"pass": length >= min_len, "value": length,
            "note": f"{length}자 (최소 {min_len}자)"}


def check_has_image(html: str) -> dict:
    count = len(re.findall(r"<img[^>]+>", html, re.IGNORECASE))
    return {"pass": count >= 1, "value": count, "note": f"이미지 {count}개"}


def check_has_internal_link(html: str, blog_url: str) -> dict:
    m = re.search(r"https?://([^/]+\.blogspot\.com)", blog_url)
    if not m:
        return {"pass": None, "note": "블로그 도메인 알 수 없음"}
    domain = m.group(1)
    count = len(re.findall(
        rf'href=["\']https?://{re.escape(domain)}[^"\']+["\']', html, re.IGNORECASE
    ))
    return {"pass": count >= 1, "value": count, "note": f"내부 링크 {count}개"}


def check_has_related_posts(html: str) -> dict:
    has = bool(re.search(r'class=["\'][^"\']*rp-wrap[^"\']*["\']', html, re.IGNORECASE))
    return {"pass": has, "note": "관련 포스트 섹션 있음" if has else "관련 포스트 섹션 없음"}


def check_has_schema_ld(html: str) -> dict:
    scripts = re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.IGNORECASE | re.DOTALL
    )
    count = len(scripts)
    types_found = []
    for s in scripts:
        try:
            obj = json.loads(s)
            t = obj.get("@type") or (obj.get("@graph") or [{}])[0].get("@type", "")
            if t:
                types_found.append(t)
        except Exception:
            pass
    note = f"Schema {count}개: {', '.join(types_found)}" if types_found else f"JSON-LD {count}개"
    return {"pass": count >= 1, "value": count, "note": note}


def check_has_label(post: dict, min_labels: int = 1) -> dict:
    labels = post.get("labels") or post.get("tags") or post.get("categories") or []
    count = len(labels)
    return {"pass": count >= min_labels, "value": count, "note": f"라벨 {count}개"}


def check_has_adsense(html: str) -> dict:
    has = "adsbygoogle" in html or "google_ad_client" in html
    return {"pass": has, "note": "AdSense 코드 있음" if has else "AdSense 코드 없음"}


# ─────────────────────────────────────────────
# 포스트 1개 검증
# ─────────────────────────────────────────────
def verify_post(post: dict) -> dict:
    url = post.get("url") or post.get("blogUrl") or post.get("link") or ""
    post_id = post.get("id") or post.get("postId") or post.get("postid") or ""
    title = post.get("title") or post.get("keyword") or ""

    if not url:
        return {"post_id": post_id, "title": title, "url": url,
                "error": "URL 없음", "score": 0, "grade": "F", "action": "repost",
                "failed_items": ["url_accessible"], "retry_count": 0}

    logger.info(f"검증 중: {title[:40]} ({url[:60]})")

    status, html = fetch_html(url)
    if status == 0:
        time.sleep(3)
        status, html = fetch_html(url)

    checks = {
        "url_accessible":    check_url_accessible(url, html, status),
        "min_content_len":   check_min_content_len(html),
        "has_image":         check_has_image(html),
        "has_internal_link": check_has_internal_link(html, url),
        "has_related_posts": check_has_related_posts(html),
        "has_schema_ld":     check_has_schema_ld(html),
        "has_label":         check_has_label(post),
        "has_adsense":       check_has_adsense(html),
    }

    score = 0
    for key, weight in WEIGHTS.items():
        passed = checks.get(key, {}).get("pass")
        if passed is True:
            score += weight
        elif passed is None:
            score += weight // 2

    if   score >= 90: grade = "S"
    elif score >= 75: grade = "A"
    elif score >= 60: grade = "B"
    elif score >= 40: grade = "C"
    else:             grade = "F"

    if   status != 200:         action = "repost"
    elif score >= PASS_THRESHOLD: action = "pass"
    else:                       action = "warn"

    failed_items = [k for k, v in checks.items() if v.get("pass") is False]

    return {
        "post_id":      post_id,
        "title":        title,
        "url":          url,
        "verified_at":  datetime.now(timezone.utc).isoformat(),
        "http_status":  status,
        "checks":       checks,
        "score":        score,
        "grade":        grade,
        "action":       action,
        "failed_items": failed_items,
        "retry_count":  0,          # 재게시 시도 횟수
    }


# ─────────────────────────────────────────────
# 자동 재게시 — pending_posts.json 재등록
# ─────────────────────────────────────────────
def queue_for_repost(failed_results: list, posts: list) -> int:
    """
    URL 접근 불가 포스트를 pending_posts.json에 재등록.
    posts.json 원본 데이터 복원 → status='pending'으로 변경.
    반환값: 재등록된 포스트 수
    """
    # posts.json 인덱스 (id 기준)
    posts_by_id = {}
    for p in posts:
        pid = p.get("id") or p.get("postId") or p.get("postid") or ""
        if pid:
            posts_by_id[pid] = p

    pending = load_pending()
    pending_ids = {p.get("id") for p in pending}

    queued = 0
    for r in failed_results:
        if r.get("action") != "repost":
            continue

        # 최대 재시도 횟수 초과 체크
        retry_count = r.get("retry_count", 0)
        if retry_count >= REPOST_MAX_RETRY:
            logger.warning(f"재게시 최대 시도 초과({REPOST_MAX_RETRY}회): {r['title'][:40]}")
            continue

        pid = r.get("post_id", "")
        original = posts_by_id.get(pid)

        if not original:
            logger.warning(f"posts.json에서 원본 없음: {pid}")
            continue

        if pid in pending_ids:
            # 이미 pending에 있으면 status만 pending으로 재설정
            for p in pending:
                if p.get("id") == pid:
                    p["status"] = "pending"
                    p["requeue_reason"] = "verify_failed"
                    p["requeue_at"] = datetime.now(timezone.utc).isoformat()
                    p["retry_count"] = retry_count + 1
                    logger.info(f"pending 상태 재설정: {r['title'][:40]}")
                    queued += 1
                    break
        else:
            # 새로 pending에 추가
            repost_entry = {
                **original,
                "status":          "pending",
                "requeue_reason":  "verify_failed",
                "requeue_at":      datetime.now(timezone.utc).isoformat(),
                "retry_count":     retry_count + 1,
                "original_url":    r.get("url", ""),
                "verify_score":    r.get("score", 0),
                "verify_grade":    r.get("grade", "F"),
                "failed_items":    r.get("failed_items", []),
            }
            pending.append(repost_entry)
            pending_ids.add(pid)
            logger.info(f"재게시 큐 추가: {r['title'][:40]}")
            queued += 1

    if queued:
        save_pending(pending)
        logger.info(f"pending_posts.json 업데이트: {queued}건 재등록")

    return queued


def run_repost(queued_count: int) -> bool:
    """publish_pending.py --all-pending 호출하여 즉시 재게시."""
    if queued_count == 0:
        return True

    logger.info(f"재게시 실행: {queued_count}건 → publish_pending.py --all-pending")
    script = BASE_DIR / "publish_pending.py"

    if not script.exists():
        logger.error(f"publish_pending.py 없음: {script}")
        return False

    try:
        result = subprocess.run(
            [sys.executable, str(script), "--all-pending"],
            capture_output=True, text=True, timeout=300
        )
        if result.stdout:
            for line in result.stdout.strip().split("\n")[-20:]:  # 마지막 20줄
                logger.info(f"[publish] {line}")
        if result.stderr:
            for line in result.stderr.strip().split("\n")[-10:]:
                logger.warning(f"[publish-err] {line}")
        
        success = result.returncode == 0
        logger.info(f"재게시 {'완료' if success else '실패'} (exit {result.returncode})")
        return success
    except subprocess.TimeoutExpired:
        logger.error("재게시 타임아웃 (300초)")
        return False
    except Exception as e:
        logger.error(f"재게시 실행 오류: {e}")
        return False


# ─────────────────────────────────────────────
# GitHub Issue 생성
# ─────────────────────────────────────────────
def create_verify_issue(failed_results: list, repost_results: list):
    if not GITHUB_TOKEN or (not failed_results and not repost_results):
        return

    # warn 항목
    warn_lines = []
    for r in failed_results:
        failed_str = ", ".join(r.get("failed_items", []))
        warn_lines.append(
            f"| [{r['title'][:40]}]({r['url']}) | {r['score']}점 ({r['grade']}) | {failed_str} |"
        )

    # repost 항목
    repost_lines = []
    for r in repost_results:
        repost_lines.append(
            f"| [{r['title'][:40]}]({r.get('url', '—')}) "
            f"| HTTP {r.get('http_status', 0)} "
            f"| 시도 {r.get('retry_count', 1)}회 |"
        )

    warn_table = ""
    if warn_lines:
        warn_table = f"""### ⚠️ 품질 미달 (warn) — {len(warn_lines)}건

| 포스트 | 점수 | 실패 항목 |
|--------|------|---------|
{chr(10).join(warn_lines)}
"""

    repost_table = ""
    if repost_lines:
        repost_table = f"""### 🔄 재게시 실행됨 (repost) — {len(repost_lines)}건

| 포스트 | HTTP 상태 | 재시도 |
|--------|----------|--------|
{chr(10).join(repost_lines)}

> 재게시 포스트는 `pending_posts.json`에 재등록되어 자동 게시 시도됩니다.
"""

    body = f"""## 🔍 게시 완료글 검증 결과

**검증 일시:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}

{warn_table}
{repost_table}

---
*자동 생성: post_verifier.py*
"""

    total = len(failed_results) + len(repost_results)
    payload = {
        "title": f"[검증] 게시 완료글 {total}건 조치 필요 — warn {len(failed_results)}건 / repost {len(repost_results)}건",
        "body": body,
        "labels": ["verification", "content-quality"],
    }

    try:
        result = _gh_post(f"/repos/{OWNER}/{REPO}/issues", payload)
        logger.info(f"이슈 생성: #{result['number']}")
    except Exception as e:
        logger.error(f"이슈 생성 실패: {e}")


# ─────────────────────────────────────────────
# 리포트 출력
# ─────────────────────────────────────────────
def print_report(report: dict):
    results = report.get("results", {})
    summary = report.get("summary", {})

    print("\n" + "="*65)
    print("✅ 게시 완료글 검증 리포트")
    print(f"   마지막 업데이트: {report.get('last_updated', '없음')[:16]}")
    print("="*65)

    grade_icon = {"S": "🏆", "A": "✅", "B": "🟡", "C": "🟠", "F": "❌"}
    for post_id, r in sorted(results.items(), key=lambda x: x[1].get("score", 0), reverse=True):
        icon = grade_icon.get(r.get("grade", "F"), "❓")
        title = r.get("title", "")[:45]
        score = r.get("score", 0)
        grade = r.get("grade", "?")
        action = r.get("action", "")
        failed = r.get("failed_items", [])
        retry = r.get("retry_count", 0)
        retry_str = f" [재시도:{retry}회]" if retry else ""
        print(f"\n{icon} [{grade}] {score}점  {title}{retry_str}")
        if action != "pass" and failed:
            print(f"   실패: {', '.join(failed)}")

    print(f"\n📊 요약")
    print(f"   전체: {summary.get('total', 0)}건  |  "
          f"통과: {summary.get('passed', 0)}건  |  "
          f"경고: {summary.get('warned', 0)}건  |  "
          f"재게시: {summary.get('repost', 0)}건")
    print(f"   평균 점수: {summary.get('avg_score', 0)}점")
    print("="*65 + "\n")


# ─────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="게시 완료글 검증 + 자동 재게시")
    parser.add_argument("--all",          action="store_true", help="전체 포스트 재검증")
    parser.add_argument("--hours",        type=int, default=25, help="최근 N시간 내 포스트 (기본 25)")
    parser.add_argument("--post-id",      dest="post_id", help="특정 포스트 ID만 검증")
    parser.add_argument("--grade",        help="특정 등급 포스트만 (S/A/B/C/F)")
    parser.add_argument("--report",       action="store_true", help="기존 리포트 출력")
    parser.add_argument("--no-issue",     action="store_true", help="GitHub Issue 생성 안 함")
    parser.add_argument("--no-repost",    action="store_true", help="자동 재게시 비활성화")
    parser.add_argument("--repost-failed",action="store_true", help="verify_report의 repost 항목 즉시 재게시")
    args = parser.parse_args()

    report = load_report()
    posts  = load_posts()

    # ── 리포트만 출력
    if args.report:
        print_report(report)
        return

    # ── 기존 repost 항목만 즉시 재게시
    if args.repost_failed:
        repost_items = [
            r for r in report.get("results", {}).values()
            if r.get("action") == "repost"
            and r.get("retry_count", 0) < REPOST_MAX_RETRY
        ]
        if not repost_items:
            logger.info("재게시 대상 없음")
            return
        queued = queue_for_repost(repost_items, posts)
        if queued:
            run_repost(queued)
        return

    # ── 일반 검증 흐름
    targets = filter_posts(posts, args)
    logger.info(f"검증 대상: {len(targets)}건")

    if not targets:
        logger.info("검증 대상 포스트 없음")
        print_report(report)
        return

    # 검증 실행
    new_results = {}
    for post in targets:
        result = verify_post(post)
        pid = result["post_id"] or result["url"]
        # 이전 retry_count 유지
        prev = report.get("results", {}).get(pid, {})
        result["retry_count"] = prev.get("retry_count", 0)
        new_results[pid] = result
        time.sleep(1)

    # 리포트 업데이트
    report["results"].update(new_results)
    all_results = list(report["results"].values())
    report["summary"] = {
        "total":     len(all_results),
        "passed":    sum(1 for r in all_results if r.get("action") == "pass"),
        "warned":    sum(1 for r in all_results if r.get("action") == "warn"),
        "repost":    sum(1 for r in all_results if r.get("action") == "repost"),
        "avg_score": round(
            sum(r.get("score", 0) for r in all_results) / len(all_results), 1
        ) if all_results else 0,
    }

    # 자동 재게시 (URL 접근 불가 포스트)
    repost_items = [r for r in new_results.values() if r.get("action") == "repost"]
    queued = 0
    if repost_items and not args.no_repost:
        logger.info(f"재게시 대상: {len(repost_items)}건")
        queued = queue_for_repost(repost_items, posts)
        if queued:
            repost_ok = run_repost(queued)
            # 재시도 카운트 업데이트
            for r in repost_items:
                pid = r.get("post_id") or r.get("url")
                if pid in report["results"]:
                    report["results"][pid]["retry_count"] += 1
                    report["results"][pid]["last_repost_at"] = datetime.now(timezone.utc).isoformat()
                    if repost_ok:
                        report["results"][pid]["action"] = "reposted"

    # 리포트 저장
    save_report(report)

    # GitHub Issue (warn + repost 합산)
    warn_items   = [r for r in new_results.values() if r.get("action") == "warn"]
    if (warn_items or repost_items) and not args.no_issue and GITHUB_TOKEN:
        create_verify_issue(warn_items, repost_items)

    print_report(report)

    # 재게시가 필요한 경우 exit 2 (warn은 exit 1, 이후 워크플로우에서 구분)
    if repost_items:
        sys.exit(2)   # repost 발생
    if warn_items:
        sys.exit(1)   # warn만 있음


if __name__ == "__main__":
    main()
