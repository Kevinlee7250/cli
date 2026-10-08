# -*- coding: utf-8 -*-
"""카테고리별 글 목차 페이지를 만들거나 갱신합니다.

  python build_toc_page.py --blog blog1           # 확인만 (HTML 미리보기)
  python build_toc_page.py --blog blog1 --apply   # 실제 반영

왜 페이지인가 — 라벨이 아니라
  blog1의 robots.txt 는 `Disallow: /search` 입니다. Blogger 의 라벨 목록은
  /search/label/... 주소라서 구글이 아예 가져가지 않습니다. 사이드바에
  라벨 목록을 붙여도 검색 쪽에는 아무 변화가 없습니다.

  반면 Blogger 페이지는 /p/....html 이라 크롤됩니다. 그래서 '구조'를
  보여주려면 라벨이 아니라 페이지로 만들어야 합니다. 이 목차는
  · 사람에게는 둘러볼 입구이고,
  · 구글에게는 모든 글로 가는 내부 링크 묶음이며,
  · 애드센스 심사 쪽에서는 '구조적 유지관리'의 증거입니다.

안전 규칙
  · 기본은 확인만입니다. --apply 를 붙여야 실제로 고칩니다.
  · 이미 목차 페이지가 있으면 그 페이지를 갱신합니다 (새로 만들지 않음).
  · 목차 페이지는 전부 이 스크립트가 만든 내용이므로 통째로 다시 씁니다.
    다른 페이지는 손대지 않습니다.
"""
import argparse
import html
import logging
import sys
import time

import requests

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("build_toc_page")

BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"

PAGE_TITLE = "글 목차"
#: 이 문자열이 있으면 이 스크립트가 만든 목차로 봅니다.
MARKER = "hogu-toc-page"

#: 카테고리를 보여줄 순서. 여기 없는 라벨은 '그 외'로 묶습니다.
CATEGORY_ORDER_BY_BLOG = {
    "blog1": ["국내여행", "해외여행", "드라마리뷰", "영화리뷰", "연예소식"],
}
OTHER_LABEL = "그 외"

_RETRY_STATUS = {429, 500, 502, 503, 504}
_RETRY_WAITS = (5, 15, 45)


def _request_with_retry(method: str, url: str, **kw):
    last = None
    for attempt, wait in enumerate((0,) + _RETRY_WAITS):
        if wait:
            code = last.status_code if last is not None else "연결 실패"
            logger.warning(f"   [{code}] {wait}초 뒤 재시도 ({attempt}/{len(_RETRY_WAITS)})")
            time.sleep(wait)
        try:
            r = requests.request(method, url, **kw)
        except requests.RequestException as exc:
            logger.error(f"   요청 실패: {exc}")
            last = None
            continue
        if r.status_code not in _RETRY_STATUS:
            return r
        last = r
    return last


def group_posts(posts: list[dict], order: list[str]) -> dict[str, list[dict]]:
    """글을 카테고리별로 묶습니다. 글 하나는 한 곳에만 들어갑니다.

    라벨이 여러 개여도 order 에서 가장 앞선 것을 씁니다 — 같은 글이 두
    군데 나오면 목차가 아니라 중복 링크 더미가 됩니다.
    """
    groups: dict[str, list[dict]] = {name: [] for name in order}
    groups[OTHER_LABEL] = []
    for post in posts:
        labels = post.get("labels") or []
        bucket = next((name for name in order if name in labels), OTHER_LABEL)
        groups[bucket].append(post)
    for items in groups.values():
        items.sort(key=lambda p: p.get("published", ""), reverse=True)
    return {k: v for k, v in groups.items() if v}


def _date(published: str) -> str:
    """2026-10-07T01:48:43+09:00 → 2026.10.07"""
    head = (published or "")[:10]
    parts = head.split("-")
    return ".".join(parts) if len(parts) == 3 else head


def render_toc(groups: dict[str, list[dict]], total: int, updated: str) -> str:
    """목차 HTML. Blogger 페이지 본문에 그대로 들어갑니다.

    바깥 CSS에 의존하지 않도록 style 속성을 직접 붙입니다 — 테마가
    바뀌어도 읽을 수 있어야 합니다.
    """
    out = [
        f'<div class="{MARKER}" style="line-height:1.8;">',
        '<p style="font-size:15px;color:#4b5563;margin-bottom:28px;">',
        f'이 블로그의 글 {total}편을 주제별로 모았습니다. '
        f'마지막 정리: {updated}',
        '</p>',
    ]
    for name, items in groups.items():
        out.append(
            '<h2 style="font-size:20px;font-weight:700;margin:32px 0 12px;'
            'padding-bottom:8px;border-bottom:2px solid #e5e7eb;">'
            f'{html.escape(name)} '
            f'<span style="font-size:14px;font-weight:400;color:#6b7280;">'
            f'{len(items)}편</span></h2>'
        )
        out.append('<ul style="margin:0;padding-left:20px;">')
        for post in items:
            title = html.escape(post.get("title", "") or "(제목 없음)")
            url = html.escape(post.get("url", "") or "", quote=True)
            out.append(
                f'<li style="margin-bottom:8px;">'
                f'<a href="{url}" style="color:#1d4ed8;">{title}</a>'
                f' <span style="color:#9ca3af;font-size:13px;">'
                f'{_date(post.get("published", ""))}</span></li>'
            )
        out.append('</ul>')
    out.append('</div>')
    return "\n".join(out)


def find_toc_page(pages: list[dict]) -> dict | None:
    """이미 있는 목차 페이지. 제목이 바뀌었어도 marker 로 찾습니다."""
    for p in pages:
        if MARKER in (p.get("content") or ""):
            return p
    for p in pages:
        if PAGE_TITLE in (p.get("title") or ""):
            return p
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="카테고리별 글 목차 페이지")
    parser.add_argument("--blog", default="blog1")
    parser.add_argument("--apply", action="store_true", help="실제로 반영")
    args = parser.parse_args()

    from config import get_blog_configs
    from blogger_uploader import _get_access_token
    from normalize_labels import fetch_live_posts

    cfg = next((b for b in get_blog_configs() if b.get("id") == args.blog), None)
    if not cfg:
        logger.error(f"BLOGS_CONFIG 에 {args.blog} 이 없습니다")
        return 1
    order = CATEGORY_ORDER_BY_BLOG.get(args.blog)
    if not order:
        logger.error(f"{args.blog} 의 카테고리 순서가 정의되지 않았습니다")
        return 1

    token = _get_access_token(cfg)
    if not token:
        logger.error("액세스 토큰을 얻지 못했습니다")
        return 1

    blog_id = str(cfg.get("blog_id") or "")
    logger.info(f"══ [{cfg.get('name', args.blog)}] 글 목차 ══")

    posts = fetch_live_posts(blog_id, token)
    if posts is None:
        return 1

    groups = group_posts(posts, order)
    if not groups:
        logger.error("공개 글이 없습니다 — 목차를 만들지 않습니다")
        return 1

    for name, items in groups.items():
        logger.info(f"  {name}: {len(items)}편")
    if OTHER_LABEL in groups:
        logger.warning(
            f"  ⚠ '{OTHER_LABEL}' 에 {len(groups[OTHER_LABEL])}편 있습니다 — "
            "normalize_labels.py 를 먼저 돌리면 줄어듭니다"
        )

    from datetime import datetime
    content = render_toc(groups, len(posts), datetime.now().strftime("%Y년 %m월 %d일"))

    r = _request_with_retry(
        "GET", f"{BLOGGER_API_BASE}/blogs/{blog_id}/pages",
        headers={"Authorization": f"Bearer {token}"},
        params={"status": "live"}, timeout=20)
    if r is None or r.status_code != 200:
        detail = f"[{r.status_code}] {r.text[:200]}" if r is not None else "응답 없음"
        logger.error(f"페이지 목록 조회 실패 {detail}")
        return 1
    existing = find_toc_page(r.json().get("items", []))

    if not args.apply:
        where = f"갱신 예정: {existing.get('url')}" if existing else "새로 만들 예정"
        logger.info(f"(확인만) {where} · 본문 {len(content):,}자")
        logger.info("─── 미리보기 (앞 600자) ───")
        logger.info(content[:600])
        return 0

    if existing:
        pr = _request_with_retry(
            "PUT", f"{BLOGGER_API_BASE}/blogs/{blog_id}/pages/{existing['id']}",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json={"title": PAGE_TITLE, "content": content}, timeout=30)
        action = "갱신"
    else:
        pr = _request_with_retry(
            "POST", f"{BLOGGER_API_BASE}/blogs/{blog_id}/pages/",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json={"title": PAGE_TITLE, "content": content}, timeout=30)
        action = "생성"

    if pr is None or pr.status_code != 200:
        detail = f"[{pr.status_code}] {pr.text[:200]}" if pr is not None else "응답 없음"
        logger.error(f"목차 페이지 {action} 실패 {detail}")
        return 1

    url = pr.json().get("url", "")
    logger.info(f"✅ 목차 페이지 {action} 완료: {url}")
    logger.info(
        "상단 메뉴에 자동으로 뜨지 않으면 Blogger 레이아웃에서 '페이지' 가젯에 "
        "추가해야 합니다 — API로는 메뉴를 건드릴 수 없습니다."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
