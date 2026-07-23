"""blog1 주제 변경에 따른 구주제 글 정리 — 이전·보관

blog1(HOGU What?)이 여행·드라마·연예·K-POP 블로그로 개편되어,
예전 주제 글을 분류해 정리합니다:

  · 금융·투자·재테크 글  → blog3(금융NEWS)로 이전
                           (blog3에 동일 내용 발행 후 blog1 원본은 draft 전환)
  · 건강·생활·IT 등 기타 구주제 글 → blog1에서 draft 전환 (보관)
  · 여행·드라마·연예·K-POP 글      → 유지
  · 분류 애매한 글                 → 리포트만 (수동 판단)

post_registry도 최선껏 동기화하며, 결과는
docs/data/offtopic_migration.json에 저장됩니다.

Usage:
  python migrate_offtopic.py --dry-run   # 분류 결과만 확인 (권장 선행)
  python migrate_offtopic.py             # 실제 이전·보관 실행
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime

import requests
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"
_BASE_DIR   = os.path.dirname(__file__)
REPORT_PATH = os.path.join(_BASE_DIR, "..", "docs", "data", "offtopic_migration.json")

# ── 주제 분류 키워드 ──────────────────────────────────────────────────────────
_KEEP_KW = {  # 새 blog1 주제 — 유지
    "여행", "관광", "명소", "맛집", "숙소", "호텔", "항공", "제주", "부산", "온천",
    "휴양", "패키지", "배낭", "캠핑",
    "드라마", "영화", "넷플릭스", "티빙", "왓챠", "ott", "결말", "출연진", "배우",
    "개봉", "박스오피스",
    "아이돌", "컴백", "k-pop", "kpop", "콘서트", "팬미팅", "음반", "신곡", "걸그룹",
    "보이그룹", "티케팅", "시상식", "연예", "예능",
}
_FINANCE_KW = {  # blog3로 이전
    "투자", "etf", "주식", "펀드", "재테크", "금융", "부동산", "세금", "절세",
    "연금", "적금", "대출", "금리", "환율", "청약", "배당", "코인", "월세", "전세",
    "가계부", "저축", "경제", "증시", "코스피", "소득세", "종소세", "세금신고",
}
_ARCHIVE_KW = {  # 기타 구주제 — 보관
    "건강", "다이어트", "운동", "건강검진", "영양", "수면", "혈압", "면역",
    "생활", "절약", "살림", "청소", "미니멀", "정리수납",
    "ai", "챗gpt", "it", "스마트폰", "앱", "코딩",
    "독서", "자격증", "공부", "교육", "취업", "부업", "캠프", "장마",
}


def classify(title: str, labels: list[str]) -> str:
    """keep / migrate_blog3 / archive / review 분류."""
    hay = (title + " " + " ".join(labels or [])).lower()
    keep    = sum(1 for w in _KEEP_KW if w in hay)
    finance = sum(1 for w in _FINANCE_KW if w in hay)
    archive = sum(1 for w in _ARCHIVE_KW if w in hay)

    # 새 주제 신호가 있으면 유지 우선 (예: "여행 경비 절약"은 여행 글)
    if keep and keep >= max(finance, archive):
        return "keep"
    if finance > archive:
        return "migrate_blog3"
    if archive > 0:
        return "archive"
    if finance > 0:
        return "migrate_blog3"
    return "review"  # 신호 없음 — 수동 판단


def _revert_to_draft(api: str, blog_id: str, post_id: str, token: str) -> bool:
    r = requests.post(
        f"{api}/blogs/{blog_id}/posts/{post_id}/revert",
        headers={"Authorization": f"Bearer {token}"}, timeout=20,
    )
    if r.status_code == 200:
        return True
    logger.error(f"    draft 전환 실패 [{r.status_code}]: {r.text[:150]}")
    return False


def _create_on_blog3(api: str, blog3_id: str, post: dict, token: str) -> str:
    payload = {
        "title": post.get("title", ""),
        "content": post.get("content", ""),
        "labels": (post.get("labels") or [])[:5],
    }
    r = requests.post(
        f"{api}/blogs/{blog3_id}/posts/",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        params={"isDraft": "false"},
        json=payload, timeout=30,
    )
    if r.status_code == 200:
        return r.json().get("url", "")
    logger.error(f"    blog3 발행 실패 [{r.status_code}]: {r.text[:200]}")
    return ""


def _sync_registry(title: str, action: str, new_url: str = "") -> None:
    """post_registry를 최선껏 동기화 (실패해도 무시)."""
    try:
        from post_manager import load_registry, save_registry, export_for_dashboard
        registry = load_registry()
        changed = False
        for p in registry:
            if p.get("title") == title and p.get("blogId") == "blog1":
                if action == "migrate":
                    p["blogId"], p["blogName"] = "blog3", "금융NEWS"
                    if new_url:
                        p["blogUrl"] = new_url
                    p["migratedAt"] = datetime.now().isoformat()
                elif action == "archive":
                    p["status"] = "skipped"
                    p["errorMessage"] = "blog1 주제 개편 — 보관"
                changed = True
        if changed:
            save_registry(registry)
            export_for_dashboard(os.path.abspath(os.path.join(_BASE_DIR, "..", "docs", "data")))
    except Exception as e:
        logger.debug(f"레지스트리 동기화 실패 (무시): {e}")


def main() -> int:
    parser = argparse.ArgumentParser(description="blog1 구주제 글 이전·보관")
    parser.add_argument("--dry-run", action="store_true", help="분류만 하고 변경 없음")
    args = parser.parse_args()

    from config import get_blog_configs
    from blogger_uploader import _get_access_token

    blogs = {b.get("id"): b for b in get_blog_configs()}
    b1, b3 = blogs.get("blog1"), blogs.get("blog3")
    if not b1 or not b3:
        logger.error("BLOGS_CONFIG에 blog1/blog3이 필요합니다")
        return 1

    token1 = _get_access_token(b1)
    token3 = _get_access_token(b3)
    if not (token1 and token3):
        logger.error("Blogger 액세스 토큰 없음")
        return 1

    b1_id, b3_id = b1["blog_id"], b3["blog_id"]

    counts = {"keep": 0, "migrate_blog3": 0, "archive": 0, "review": 0, "failed": 0}
    actions = []

    page_token = ""
    while True:
        params = {"maxResults": 100, "status": "live", "fetchBodies": "true",
                  "fields": "nextPageToken,items(id,title,url,content,labels)"}
        if page_token:
            params["pageToken"] = page_token
        r = requests.get(f"{BLOGGER_API_BASE}/blogs/{b1_id}/posts",
                         headers={"Authorization": f"Bearer {token1}"}, params=params, timeout=30)
        if r.status_code != 200:
            logger.error(f"blog1 글 목록 조회 실패 [{r.status_code}]: {r.text[:200]}")
            return 1
        data = r.json()

        for post in data.get("items", []):
            title = post.get("title", "")
            cat = classify(title, post.get("labels", []))
            counts[cat] = counts.get(cat, 0) + 1
            entry = {"title": title, "url": post.get("url", ""), "action": cat}

            if cat == "keep":
                continue
            label = {"migrate_blog3": "→ blog3 이전", "archive": "보관(draft)",
                     "review": "수동 판단 필요"}[cat]
            logger.info(f"  [{label}] '{title[:50]}'")

            if cat == "review" or args.dry_run:
                actions.append(entry)
                continue

            if cat == "migrate_blog3":
                new_url = _create_on_blog3(BLOGGER_API_BASE, b3_id, post, token3)
                if new_url and _revert_to_draft(BLOGGER_API_BASE, b1_id, post["id"], token1):
                    logger.info(f"    ✅ 이전 완료: {new_url}")
                    entry["newUrl"] = new_url
                    _sync_registry(title, "migrate", new_url)
                else:
                    counts["failed"] += 1
                    entry["action"] = "failed"
                time.sleep(1.5)

            elif cat == "archive":
                if _revert_to_draft(BLOGGER_API_BASE, b1_id, post["id"], token1):
                    logger.info("    ✅ 보관 완료 (draft 전환 — Blogger 관리자에서 복원 가능)")
                    _sync_registry(title, "archive")
                else:
                    counts["failed"] += 1
                    entry["action"] = "failed"
                time.sleep(1)

            actions.append(entry)

        page_token = data.get("nextPageToken", "")
        if not page_token:
            break

    report = {
        "migratedAt": datetime.now().isoformat(),
        "dryRun": args.dry_run,
        "counts": counts,
        "actions": actions,
    }
    try:
        os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info(f"리포트 저장: {REPORT_PATH}")
    except Exception as e:
        logger.warning(f"리포트 저장 실패 (무시): {e}")

    mode = "(dry-run) " if args.dry_run else ""
    logger.info("=" * 55)
    logger.info(
        f"{mode}완료 — 유지 {counts['keep']} / blog3 이전 {counts['migrate_blog3']} / "
        f"보관 {counts['archive']} / 수동판단 {counts['review']} / 실패 {counts['failed']}"
    )
    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
