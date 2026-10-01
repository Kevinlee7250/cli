# -*- coding: utf-8 -*-
"""면책 조항 페이지로 가는 링크를 다른 필수 페이지 하단에 넣습니다.

  python link_disclaimer.py --blog blog2            # 확인만
  python link_disclaimer.py --blog blog2 --apply    # 실제 반영
  python link_disclaimer.py --blog all --apply

왜 필요한가
  면책 조항 페이지는 만들어져 있는데 상단 메뉴 가젯에는 올라가지 않는
  블로그가 있습니다. Blogger API로는 레이아웃 가젯을 건드릴 수 없어
  사람이 직접 체크해야 하는데, 그 전까지 이 페이지는 주소를 아는
  사람만 볼 수 있습니다.

  심사 쪽에서 중요한 것은 '메뉴에 있다'가 아니라 '사이트를 돌아다니다
  닿을 수 있다'입니다. 그래서 이미 메뉴에 있는 페이지들(개인정보처리방침·
  소개·문의) 하단에서 면책 조항으로 이어 둡니다. 메뉴에 올리면 이 링크는
  그대로 둬도 해롭지 않습니다 — 푸터 상호링크는 흔한 형태입니다.

안전 규칙
  · 기본은 확인만입니다. --apply를 붙여야 실제로 고칩니다.
  · 면책 조항 페이지가 없으면 아무것도 하지 않습니다.
  · 이미 링크가 있으면 건너뜁니다 (marker로 판정, 몇 번 돌려도 같음).
  · 본문 끝에 덧붙이기만 합니다. 기존 내용은 건드리지 않습니다.
"""
import argparse
import logging
import os
import sys

import requests

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("link_disclaimer")

BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"

#: 이 문자열이 본문에 있으면 이미 넣은 것으로 봅니다.
MARKER = "hogu-disclaimer-link"

#: 링크를 넣을 페이지들. 면책 조항 자신은 제외합니다.
TARGET_ALIASES = {
    "개인정보처리방침": ["개인정보", "privacy"],
    "블로그 소개": ["소개", "about"],
    "문의": ["문의", "contact"],
}

DISCLAIMER_ALIASES = ["면책", "disclaimer"]


def _norm(t: str) -> str:
    return "".join((t or "").lower().split())


def _find_page(pages: list[dict], aliases: list[str]) -> dict | None:
    for p in pages:
        title = _norm(p.get("title"))
        if any(_norm(a) in title for a in aliases):
            return p
    return None


def _link_block(url: str) -> str:
    """면책 조항으로 가는 안내 한 줄."""
    return (
        f'\n<p class="{MARKER}" style="margin-top:32px;padding-top:16px;'
        'border-top:1px solid #e5e7eb;font-size:14px;color:#4b5563;'
        'line-height:1.7;">'
        '이 블로그의 콘텐츠 이용에 관한 안내는 '
        f'<a href="{url}" style="color:#1d4ed8;font-weight:600;">면책 조항</a>'
        '에서 확인하실 수 있습니다.'
        '</p>'
    )


def run_for_blog(cfg: dict, apply_changes: bool = False) -> int:
    from blogger_uploader import _get_access_token

    name = cfg.get("name") or cfg.get("id", "")
    blog_id = str(cfg.get("blog_id") or "")
    logger.info(f"\n── {name} ({cfg.get('id')})")

    token = _get_access_token(cfg)
    if not token:
        logger.error("   액세스 토큰을 얻지 못했습니다")
        return 1

    r = requests.get(
        f"{BLOGGER_API_BASE}/blogs/{blog_id}/pages",
        headers={"Authorization": f"Bearer {token}"},
        params={"status": "live"}, timeout=20,
    )
    if r.status_code != 200:
        logger.error(f"   페이지 목록 조회 실패 [{r.status_code}]: {r.text[:200]}")
        return 1
    pages = r.json().get("items", [])

    disclaimer = _find_page(pages, DISCLAIMER_ALIASES)
    if not disclaimer:
        logger.warning("   면책 조항 페이지가 없습니다 — 먼저 만들어야 합니다")
        return 1
    url = disclaimer.get("url", "")
    logger.info(f"   면책 조항: {url}")

    changed = 0
    for label, aliases in TARGET_ALIASES.items():
        page = _find_page(pages, aliases)
        if not page:
            logger.info(f"   [건너뜀] {label} — 페이지가 없습니다")
            continue
        if page.get("id") == disclaimer.get("id"):
            continue

        content = page.get("content", "") or ""
        if MARKER in content:
            logger.info(f"   [이미 있음] {label}")
            continue

        if not apply_changes:
            logger.info(f"   [넣을 예정] {label} ({page.get('url', '')})")
            changed += 1
            continue

        new_content = content + _link_block(url)
        pr = requests.put(
            f"{BLOGGER_API_BASE}/blogs/{blog_id}/pages/{page['id']}",
            json={"title": page.get("title", label), "content": new_content},
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            timeout=30,
        )
        if pr.status_code in (200, 201):
            logger.info(f"   [넣음] {label}")
            changed += 1
        else:
            logger.error(f"   [실패] {label} [{pr.status_code}]: {pr.text[:200]}")

    if not apply_changes and changed:
        logger.info(f"   → 확인만 했습니다. 실제로 넣으려면 --apply를 붙이세요 ({changed}곳)")
    elif not changed:
        logger.info("   → 할 일이 없습니다")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="면책 조항 링크를 다른 필수 페이지 하단에 넣습니다")
    parser.add_argument("--blog", default="blog1", help="블로그 ID ('all'=전체)")
    parser.add_argument("--apply", action="store_true",
                        help="실제로 반영합니다 (기본은 확인만)")
    args = parser.parse_args()

    from config import get_blog_configs
    blogs = get_blog_configs()
    if args.blog != "all":
        blogs = [b for b in blogs if b.get("id") == args.blog]
        if not blogs:
            logger.error(f"블로그 '{args.blog}' 없음")
            return 1

    rc = 0
    for cfg in blogs:
        rc |= run_for_blog(cfg, apply_changes=args.apply)
    return rc


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
