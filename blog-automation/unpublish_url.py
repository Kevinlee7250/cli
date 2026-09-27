# -*- coding: utf-8 -*-
"""발행된 글 하나를 URL로 지목해 비공개(draft)로 내립니다.

  python unpublish_url.py --url https://.../2026/09/x.html            # 확인만
  python unpublish_url.py --url https://.../2026/09/x.html --apply    # 실제 전환

왜 이 도구가 따로 필요한가
  기존 경로는 조건으로 고릅니다 — adsense_audit는 글자수 미달을,
  curate_site는 품질 점수를 봅니다. 그런데 "이 글 하나만 내려라"가 실제로
  필요할 때가 있습니다. 잘못된 블로그에 올라간 글, 사실관계가 틀린 글처럼
  조건으로는 잡히지 않는 경우입니다. 그때 조건을 억지로 맞추려 하면
  (기준을 임시로 낮추는 식) 의도하지 않은 글까지 같이 내려갑니다.

안전 규칙
  · 기본은 확인만입니다. --apply를 붙여야 실제로 내려갑니다.
  · URL 하나만 받습니다. 목록이나 패턴을 받지 않습니다.
  · draft 전환이라 삭제가 아닙니다. Blogger 관리자에서 다시 공개할 수 있습니다.
  · 어느 블로그의 글인지는 URL로 판별합니다. 못 찾으면 아무것도 하지 않습니다.
"""
import argparse
import logging
import os
import sys
from urllib.parse import urlparse

import requests

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("unpublish_url")

BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"


def _blog_for_url(url: str) -> dict | None:
    """URL의 호스트로 어느 블로그인지 찾습니다."""
    # lstrip("www.")를 쓰면 문자 집합을 깎아서 'wow.example.com'까지 망칩니다.
    host = (urlparse(url).hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    if not host:
        return None

    # 설정에서 호스트가 적힌 필드는 하나로 정해져 있지 않습니다
    # (blogs.json은 gsc_site_url, BLOGS_CONFIG는 url/blog_url을 씁니다).
    _HOST_FIELDS = ("gsc_site_url", "url", "blog_url", "site_url")

    from config import get_blog_configs
    for cfg in get_blog_configs():
        for field in _HOST_FIELDS:
            cfg_host = (urlparse(cfg.get(field) or "").hostname or "").lower()
            cfg_host = cfg_host[4:] if cfg_host.startswith("www.") else cfg_host
            if cfg_host and cfg_host == host:
                return cfg
    return None


def _post_by_url(blogger_blog_id: str, url: str, token: str) -> dict | None:
    r = requests.get(
        f"{BLOGGER_API_BASE}/blogs/{blogger_blog_id}/posts/bypath",
        headers={"Authorization": f"Bearer {token}"},
        params={"path": urlparse(url).path},
        timeout=20,
    )
    if r.status_code == 200:
        return r.json()
    logger.error(f"글 조회 실패 [{r.status_code}]: {r.text[:200]}")
    return None


def run(url: str, apply_changes: bool = False) -> int:
    cfg = _blog_for_url(url)
    if not cfg:
        logger.error(f"이 URL이 어느 블로그인지 찾지 못했습니다: {url}")
        logger.error("blogs.json / BLOGS_CONFIG의 url 값과 호스트가 같은지 확인하세요.")
        return 1

    logger.info(f"블로그: {cfg.get('name')} ({cfg.get('id')})")

    from blogger_uploader import _get_access_token
    token = _get_access_token(cfg)
    if not token:
        logger.error("액세스 토큰을 얻지 못했습니다.")
        return 1

    post = _post_by_url(str(cfg.get("blog_id")), url, token)
    if not post:
        return 1

    logger.info(f"제목: {post.get('title', '')[:70]}")
    logger.info(f"현재 상태: {post.get('status', 'LIVE')}")

    if post.get("status") == "DRAFT":
        logger.info("이미 비공개입니다 — 할 일이 없습니다.")
        return 0

    if not apply_changes:
        logger.info("확인만 했습니다. 실제로 내리려면 --apply를 붙이세요.")
        return 0

    r = requests.post(
        f"{BLOGGER_API_BASE}/blogs/{cfg.get('blog_id')}/posts/{post['id']}/revert",
        headers={"Authorization": f"Bearer {token}"}, timeout=20,
    )
    if r.status_code != 200:
        logger.error(f"비공개 전환 실패 [{r.status_code}]: {r.text[:200]}")
        return 1

    logger.info("✅ 비공개(draft)로 내렸습니다. Blogger 관리자에서 다시 공개할 수 있습니다.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="발행된 글 하나를 URL로 지목해 비공개로 내립니다")
    parser.add_argument("--url", required=True, help="내릴 글의 전체 URL")
    parser.add_argument("--apply", action="store_true",
                        help="실제로 내립니다 (기본은 확인만)")
    args = parser.parse_args()
    return run(args.url, apply_changes=args.apply)


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
