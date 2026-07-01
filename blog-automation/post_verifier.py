#!/usr/bin/env python3
"""
post_verifier.py — 게시 완료글 검증 엔진
------------------------------------------
기능:
  1. posts.json에서 published 포스트 목록 로드
  2. 각 포스트에 대해 7개 레이어 검증
  3. 점수화 → verify_report.json 저장
  4. 실패 포스트 GitHub Issue 생성

검증 항목:
  [게시] URL 접근성, 게시 상태
  [콘텐츠] 최소 분량, 이미지, 내부 링크, 관련 포스트 섹션
  [SEO] JSON-LD Schema, 라벨 수
  [광고] AdSense 코드 포함 여부

사용법:
  python post_verifier.py                      # 최근 24시간 내 게시 포스트 검증
  python post_verifier.py --all                # 전체 포스트 재검증
  python post_verifier.py --hours 48           # 최근 48시간 내 포스트
  python post_verifier.py --post-id POST_ID    # 특정 포스트만
  python post_verifier.py --report             # 기존 리포트 출력
  python post_verifier.py --grade C            # 특정 등급 포스트 재검증
"""

import os
import sys
import json
import logging
import argparse
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# ─────────────────────────────────────────────
# 환경 설정
# ─────────────────────────────────────────────
GITHUB_TOKEN      = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "Kevinlee7250/cli")
BLOGGER_BLOG_ID   = os.environ.get("BLOGGER_BLOG_ID", "")
GOOGLE_API_KEY    = os.environ.get("GOOGLE_API_KEY", "")  # Blogger Data API용 (옵션)

OWNER, REPO = GITHUB_REPOSITORY.split("/") if "/" in GITHUB_REPOSITORY else ("", GITHUB_REPOSITORY)
BRANCH = os.environ.get("GITHUB_REF_NAME", "claude/blog-automation-system-KAbtE")

BASE_DIR      = Path(__file__).parent
DATA_DIR      = BASE_DIR.parent / "docs" / "data"
POSTS_FILE    = DATA_DIR / "posts.json"
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
PASS_THRESHOLD = 60   # 이 점수 미만이면 warn/repost 액션

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
# 데이터 로드
# ─────────────────────────────────────────────
def load_posts() -> list:
    """posts.json 로드."""
    if not POSTS_FILE.exists():
        logger.error(f"posts.json 없음: {POSTS_FILE}")
        return []
    return json.loads(POSTS_FILE.read_text(encoding="utf-8"))


def load_report() -> dict:
    """기존 verify_report.json 로드."""
    if REPORT_FILE.exists():
        return json.loads(REPORT_FILE.read_text(encoding="utf-8"))
    return {"results": {}, "summary": {}, "last_updated": None}


def save_report(report: dict):
    """verify_report.json 저장."""
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
    """검증 대상 포스트 필터링."""
    # 게시된 포스트만
    published = [
        p for p in posts
        if p.get("status") in ("published", "live", "LIVE")
        and p.get("url") or p.get("blogUrl") or p.get("link")
    ]

    if args.post_id:
        return [p for p in published if p.get("id") == args.post_id or p.get("postId") == args.post_id]

    if args.grade:
        return [p for p in published if p.get("grade", "").upper() == args.grade.upper()]

    if args.all:
        return published

    # 기본: 최근 N시간 내 게시
    hours = getattr(args, "hours", 25)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    result = []
    for p in published:
        ts = p.get("publishedAt") or p.get("savedAt") or p.get("createdAt") or ""
        # savedAt: 14자리 숫자 (YYYYMMDDHHMMSS)
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
# URL 가져오기 (HTML 파싱용)
# ─────────────────────────────────────────────
def fetch_html(url: str, timeout: int = 15) -> tuple[int, str]:
    """URL GET 요청 → (status_code, html)"""
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
    return {
        "pass":  passed,
        "value": status,
        "note":  "접근 성공" if passed else f"HTTP {status}",
    }


def check_min_content_len(html: str, min_len: int = 500) -> dict:
    # HTML 태그 제거 후 텍스트 길이
    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"\s+", " ", text).strip()
    length = len(text)
    return {
        "pass":  length >= min_len,
        "value": length,
        "note":  f"{length}자 (최소 {min_len}자)",
    }


def check_has_image(html: str) -> dict:
    imgs = re.findall(r"<img[^>]+>", html, re.IGNORECASE)
    count = len(imgs)
    return {
        "pass":  count >= 1,
        "value": count,
        "note":  f"이미지 {count}개",
    }


def check_has_internal_link(html: str, blog_url: str) -> dict:
    # 같은 blogspot 도메인 링크
    domain_match = re.search(r"https?://([^/]+\.blogspot\.com)", blog_url)
    if not domain_match:
        return {"pass": None, "note": "블로그 도메인 알 수 없음"}
    
    domain = domain_match.group(1)
    links = re.findall(rf'href=["\']https?://{re.escape(domain)}[^"\']+["\']', html, re.IGNORECASE)
    count = len(links)
    return {
        "pass":  count >= 1,
        "value": count,
        "note":  f"내부 링크 {count}개",
    }


def check_has_related_posts(html: str) -> dict:
    # related_posts.py가 삽입하는 클래스
    has = bool(re.search(r'class=["\'][^"\']*rp-wrap[^"\']*["\']', html, re.IGNORECASE))
    return {
        "pass": has,
        "note": "관련 포스트 섹션 있음" if has else "관련 포스트 섹션 없음",
    }


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
            t = obj.get("@type") or obj.get("@graph", [{}])[0].get("@type", "")
            if t:
                types_found.append(t)
        except Exception:
            pass
    return {
        "pass":  count >= 1,
        "value": count,
        "note":  f"Schema {count}개: {', '.join(types_found)}" if types_found else f"JSON-LD {count}개",
    }


def check_has_label(post: dict, min_labels: int = 1) -> dict:
    labels = post.get("labels") or post.get("tags") or post.get("categories") or []
    count = len(labels)
    return {
        "pass":  count >= min_labels,
        "value": count,
        "note":  f"라벨 {count}개",
    }


def check_has_adsense(html: str) -> dict:
    has = "adsbygoogle" in html or "google_ad_client" in html
    return {
        "pass": has,
        "note": "AdSense 코드 있음" if has else "AdSense 코드 없음",
    }


# ─────────────────────────────────────────────
# 포스트 1개 검증
# ─────────────────────────────────────────────
def verify_post(post: dict) -> dict:
    url = post.get("url") or post.get("blogUrl") or post.get("link") or ""
    post_id = post.get("id") or post.get("postId") or post.get("postid") or ""
    title = post.get("title") or post.get("keyword") or ""

    if not url:
        return {
            "post_id": post_id,
            "title":   title,
            "url":     url,
            "error":   "URL 없음",
            "score":   0,
            "grade":   "F",
            "action":  "repost",
        }

    logger.info(f"검증 중: {title[:40]} ({url[:60]})")

    # HTML 가져오기 (최대 2회 시도)
    status, html = fetch_html(url)
    if status == 0:
        time.sleep(3)
        status, html = fetch_html(url)

    # 각 항목 검증
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

    # 점수 계산
    score = 0
    for key, weight in WEIGHTS.items():
        result = checks.get(key, {})
        passed = result.get("pass")
        if passed is True:
            score += weight
        elif passed is None:
            score += weight // 2  # 판별 불가 → 절반 점수

    # 등급 산정
    if score >= 90:   grade = "S"
    elif score >= 75: grade = "A"
    elif score >= 60: grade = "B"
    elif score >= 40: grade = "C"
    else:             grade = "F"

    # 액션 결정
    if score >= PASS_THRESHOLD:
        action = "pass"
    elif status != 200:
        action = "repost"
    else:
        action = "warn"

    # 실패 항목 목록
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
    }


# ─────────────────────────────────────────────
# GitHub Issue 생성
# ─────────────────────────────────────────────
def create_verify_issue(failed_results: list):
    """검증 실패 포스트 목록으로 GitHub Issue 생성."""
    if not GITHUB_TOKEN or not failed_results:
        return

    lines = []
    for r in failed_results:
        failed_str = ", ".join(r.get("failed_items", []))
        lines.append(
            f"| [{r['title'][:40]}]({r['url']}) | {r['score']}점 ({r['grade']}) "
            f"| {r['action']} | {failed_str} |"
        )

    body = f"""## ⚠️ 게시 완료글 검증 실패

**검증 일시:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
**실패 포스트:** {len(failed_results)}건

| 포스트 | 점수 | 액션 | 실패 항목 |
|--------|------|------|---------|
{chr(10).join(lines)}

### 액션 가이드
- `repost` : URL 접근 불가 → 수동 재게시 필요
- `warn`   : 콘텐츠/SEO 품질 미달 → 내용 보완 권장

---
*자동 생성: post_verifier.py @ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*
"""

    payload = {
        "title": f"[⚠️ 검증 실패] 게시 완료글 {len(failed_results)}건 품질 미달",
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
        failed = r.get("failed_items", [])
        print(f"\n{icon} [{grade}] {score}점  {title}")
        if failed:
            print(f"   실패: {', '.join(failed)}")

    print(f"\n📊 요약")
    print(f"   전체: {summary.get('total', 0)}건")
    print(f"   통과(≥{PASS_THRESHOLD}점): {summary.get('passed', 0)}건")
    print(f"   경고: {summary.get('warned', 0)}건")
    print(f"   재게시 필요: {summary.get('repost', 0)}건")
    print("="*65 + "\n")


# ─────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="게시 완료글 검증 엔진")
    parser.add_argument("--all",      action="store_true", help="전체 포스트 재검증")
    parser.add_argument("--hours",    type=int, default=25, help="최근 N시간 내 포스트 (기본 25)")
    parser.add_argument("--post-id",  dest="post_id", help="특정 포스트 ID만 검증")
    parser.add_argument("--grade",    help="특정 등급 포스트만 (S/A/B/C/F)")
    parser.add_argument("--report",   action="store_true", help="기존 리포트 출력")
    parser.add_argument("--no-issue", action="store_true", help="GitHub Issue 생성 안 함")
    args = parser.parse_args()

    report = load_report()

    if args.report:
        print_report(report)
        return

    posts = load_posts()
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
        new_results[pid] = result
        time.sleep(1)  # Blogger 과부하 방지

    # 리포트 업데이트
    report["results"].update(new_results)

    # 요약 통계
    all_results = list(report["results"].values())
    report["summary"] = {
        "total":   len(all_results),
        "passed":  sum(1 for r in all_results if r.get("action") == "pass"),
        "warned":  sum(1 for r in all_results if r.get("action") == "warn"),
        "repost":  sum(1 for r in all_results if r.get("action") == "repost"),
        "avg_score": round(
            sum(r.get("score", 0) for r in all_results) / len(all_results), 1
        ) if all_results else 0,
    }

    save_report(report)

    # 실패 포스트 이슈 생성
    failed = [r for r in new_results.values() if r.get("action") in ("warn", "repost")]
    if failed and not args.no_issue and GITHUB_TOKEN:
        logger.info(f"검증 실패 {len(failed)}건 → GitHub Issue 생성")
        create_verify_issue(failed)

    print_report(report)

    # 재게시 필요 포스트가 있으면 exit 1 (워크플로우에서 감지)
    repost_count = sum(1 for r in new_results.values() if r.get("action") == "repost")
    if repost_count:
        logger.warning(f"재게시 필요: {repost_count}건")
        sys.exit(1)


if __name__ == "__main__":
    main()
