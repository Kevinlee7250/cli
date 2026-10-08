# -*- coding: utf-8 -*-
"""라벨을 카테고리로 정리합니다 — 글마다 큰 분류 1개 + 세부 라벨 최대 2개.

  python normalize_labels.py --blog blog1           # 확인만
  python normalize_labels.py --blog blog1 --apply   # 실제 반영

왜 필요한가
  2026-10-08: blog1 글 107편에 서로 다른 라벨이 402개 있었습니다. 글마다
  5~7개씩 붙어 있고 대부분 한 번만 쓰인 라벨이라, 카테고리가 아니라
  키워드 나열이었습니다. 글 끝에 해시태그가 일곱 개 달려 있으면 사람 눈에도
  '정리된 블로그'로 보이지 않습니다.

  솔직히 말해 이 작업의 검색 효과는 작습니다 — blog1의 robots.txt가
  `Disallow: /search` 라서 라벨 페이지는 애초에 구글이 보지 않습니다.
  효과가 있는 쪽은 (1) 사람이 둘러볼 수 있는 분류가 생기는 것,
  (2) 애드센스 심사에서 '큐레이션된 블로그'로 보이는 것,
  (3) 이 카테고리로 목차 페이지를 만들 수 있는 것입니다.
  검색 쪽 실제 효과는 목차 페이지(build_toc_page.py)에서 나옵니다.

안전 규칙
  · 기본은 확인만입니다. --apply 를 붙여야 실제로 고칩니다.
  · 어느 카테고리에도 들어가지 않는 글은 건드리지 않고 보고만 합니다.
  · 라벨 외에는 아무것도 바꾸지 않습니다 (제목·본문 그대로).
  · 429·5xx는 기다렸다 다시 보냅니다.
"""
import argparse
import logging
import os
import re
import sys
import time
from collections import Counter

import requests

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("normalize_labels")

BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"

#: 글 하나에 붙일 라벨 수 상한 (카테고리 1 + 세부 2)
MAX_LABELS = 3
#: 세부 라벨로 남길 최소 등장 횟수 — 한 번만 쓰인 라벨은 분류가 아닙니다
MIN_KEEP_COUNT = 2

_RETRY_STATUS = {429, 500, 502, 503, 504}
_RETRY_WAITS = (5, 15, 45)
_PACE_SECONDS = 2

# ── 카테고리 ────────────────────────────────────────────────────────────────
# 순서가 곧 동점일 때의 우선순위입니다. 블로그마다 다릅니다.
_CATEGORIES_BLOG1 = [
    ("드라마리뷰", {
        "드라마", "회차", "몇부작", "결말", "등장인물", "출연진", "편성표",
        "재벌x형사", "신병", "포핸즈", "ena", "tvn", "jtbc", "sbs드라마",
        "kbs드라마", "mbc드라마", "본방", "시청률", "스포",
    }),
    ("영화리뷰", {
        "영화", "개봉", "박스오피스", "특선영화", "ott", "넷플릭스", "티빙",
        "왓챠", "디즈니플러스", "쿠팡플레이", "웨이브", "상영",
    }),
    ("해외여행", {
        "해외여행", "면세점", "유류할증료", "항공권", "환승", "비자", "여권",
        "여행자보험", "일본여행", "도쿄", "오사카", "후쿠오카", "베트남",
        "다낭", "태국", "방콕", "대만", "타이베이", "유럽", "파리", "미국",
        "하와이", "괌", "사이판", "싱가포르", "홍콩", "세부", "발리",
        "대사관", "영사", "로밍", "환전",
    }),
    ("국내여행", {
        "국내여행", "제주", "부산", "강원", "속초", "강릉", "경주", "전주",
        "여수", "가평", "남해", "통영", "단풍", "명산", "등산", "둘레길",
        "온천", "캠핑", "글램핑", "펜션", "리조트", "축제", "해수욕장",
        "국내", "맛집", "숙소", "호텔", "관광", "명소",
    }),
    ("연예소식", {
        "아이돌", "k-pop", "kpop", "컴백", "콘서트", "팬미팅", "음반",
        "신곡", "걸그룹", "보이그룹", "티케팅", "시상식", "예능", "가수",
        "배우", "연예",
    }),
]

_CATEGORIES_BY_BLOG = {"blog1": _CATEGORIES_BLOG1}

#: 이 라벨들은 카테고리이므로 세부 라벨 후보에서 빼야 합니다.
_CATEGORY_NAMES = {name for name, _ in _CATEGORIES_BLOG1}

_ASCII_KW_RE = re.compile(r"^[a-z0-9][a-z0-9&.\-]*$")


def _hits(words: set[str], hay: str) -> int:
    """migrate_offtopic 과 같은 규칙 — 영문만 단어 경계를 봅니다.

    'ott'가 'ottawa' 안에서, 'ena'가 'arena' 안에서 걸리면 안 됩니다.
    """
    n = 0
    for w in words:
        if _ASCII_KW_RE.match(w):
            if re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", hay):
                n += 1
        elif w in hay:
            n += 1
    return n


def category_for(title: str, labels: list[str], blog_id: str = "blog1") -> str | None:
    """이 글의 큰 분류. 신호가 없으면 None (건드리지 않습니다)."""
    cats = _CATEGORIES_BY_BLOG.get(blog_id)
    if not cats:
        return None
    hay = (title + " " + " ".join(labels or [])).lower()
    best, best_score = None, 0
    for name, words in cats:
        score = _hits(words, hay)
        if score > best_score:
            best, best_score = name, score
    return best


def plan_labels(category: str, labels: list[str], keepable: set[str]) -> list[str]:
    """카테고리 1개 + 세부 라벨 최대 2개. 입력 순서를 유지합니다.

    세부 라벨은 '이 블로그에서 2번 이상 쓰인 것'만 남깁니다 — 한 번만
    쓰인 라벨은 분류가 아니라 키워드이기 때문입니다.
    """
    out = [category]
    for lab in labels or []:
        if len(out) >= MAX_LABELS:
            break
        if lab in out or lab in _CATEGORY_NAMES:
            continue
        if lab in keepable:
            out.append(lab)
    return out


# ── Blogger 호출 ────────────────────────────────────────────────────────────

def _request_with_retry(method: str, url: str, **kw):
    last = None
    for attempt, wait in enumerate((0,) + _RETRY_WAITS):
        if wait:
            code = last.status_code if last is not None else "연결 실패"
            logger.warning(f"     [{code}] {wait}초 뒤 재시도 ({attempt}/{len(_RETRY_WAITS)})")
            time.sleep(wait)
        try:
            r = requests.request(method, url, **kw)
        except requests.RequestException as exc:
            logger.error(f"     요청 실패: {exc}")
            last = None
            continue
        if r.status_code not in _RETRY_STATUS:
            return r
        last = r
    return last


def fetch_live_posts(blog_id: str, token: str) -> list[dict] | None:
    posts, page_token = [], ""
    while True:
        params = {"maxResults": 100, "status": "live", "fetchBodies": "false",
                  "fields": "nextPageToken,items(id,title,url,published,labels)"}
        if page_token:
            params["pageToken"] = page_token
        r = _request_with_retry(
            "GET", f"{BLOGGER_API_BASE}/blogs/{blog_id}/posts",
            headers={"Authorization": f"Bearer {token}"}, params=params, timeout=30)
        if r is None or r.status_code != 200:
            detail = f"[{r.status_code}] {r.text[:200]}" if r is not None else "응답 없음"
            logger.error(f"글 목록 조회 실패 {detail}")
            return None
        data = r.json()
        posts.extend(data.get("items", []))
        page_token = data.get("nextPageToken", "")
        if not page_token:
            return posts


def set_labels(blog_id: str, post_id: str, labels: list[str], token: str) -> bool:
    """라벨만 바꿉니다 — PATCH 라서 제목·본문은 건드리지 않습니다."""
    r = _request_with_retry(
        "PATCH", f"{BLOGGER_API_BASE}/blogs/{blog_id}/posts/{post_id}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"labels": labels}, timeout=30)
    if r is not None and r.status_code == 200:
        return True
    detail = f"[{r.status_code}] {r.text[:150]}" if r is not None else "응답 없음"
    logger.error(f"     라벨 변경 실패 {detail}")
    return False


# ── 실행 ────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="라벨을 카테고리로 정리")
    parser.add_argument("--blog", default="blog1", help="대상 블로그 (기본: blog1)")
    parser.add_argument("--apply", action="store_true", help="실제로 반영")
    args = parser.parse_args()

    from config import get_blog_configs
    from blogger_uploader import _get_access_token

    cfg = next((b for b in get_blog_configs() if b.get("id") == args.blog), None)
    if not cfg:
        logger.error(f"BLOGS_CONFIG 에 {args.blog} 이 없습니다")
        return 1
    if args.blog not in _CATEGORIES_BY_BLOG:
        logger.error(f"{args.blog} 의 카테고리 정의가 없습니다 — 먼저 정해야 합니다")
        return 1

    token = _get_access_token(cfg)
    if not token:
        logger.error("액세스 토큰을 얻지 못했습니다")
        return 1

    blog_id = str(cfg.get("blog_id") or "")
    logger.info(f"══ [{cfg.get('name', args.blog)}] 라벨 정리 ══")

    posts = fetch_live_posts(blog_id, token)
    if posts is None:
        return 1

    counts = Counter(lab for p in posts for lab in (p.get("labels") or []))
    keepable = {lab for lab, n in counts.items()
                if n >= MIN_KEEP_COUNT and lab not in _CATEGORY_NAMES}
    logger.info(
        f"공개 글 {len(posts)}편 · 서로 다른 라벨 {len(counts)}개 · "
        f"세부 라벨로 남길 것 {len(keepable)}개 ({MIN_KEEP_COUNT}회 이상)"
    )

    changed = skipped = failed = 0
    unclassified: list[str] = []
    by_category: Counter = Counter()

    for post in posts:
        title = post.get("title", "")
        labels = post.get("labels") or []
        cat = category_for(title, labels, args.blog)
        if not cat:
            unclassified.append(title)
            logger.info(f"  [그대로] {title[:46]} — 분류 신호 없음")
            continue

        by_category[cat] += 1
        want = plan_labels(cat, labels, keepable)
        if want == labels:
            skipped += 1
            continue

        logger.info(f"  [{cat}] {title[:44]}")
        logger.info(f"     {len(labels)}개 → {len(want)}개: {', '.join(want)}")
        if not args.apply:
            changed += 1
            continue
        if set_labels(blog_id, post["id"], want, token):
            changed += 1
        else:
            failed += 1
        time.sleep(_PACE_SECONDS)

    mode = "" if args.apply else "(확인만) "
    logger.info("=" * 55)
    logger.info(f"{mode}카테고리별: " + " / ".join(
        f"{k} {v}" for k, v in by_category.most_common()) or "없음")
    logger.info(
        f"{mode}바꿀 글 {changed} / 이미 맞음 {skipped} / "
        f"분류 안 됨 {len(unclassified)} / 실패 {failed}"
    )
    if unclassified:
        logger.warning("분류되지 않은 글 (손대지 않았습니다):")
        for t in unclassified:
            logger.warning(f"  · {t}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
