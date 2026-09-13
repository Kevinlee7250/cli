"""현재 '발행 상태'인 글의 주소만 모아 docs/data/live_posts.json 에 적습니다.

왜 필요한가
──────────
2026-09-13 사이트 재편으로 409편을 임시저장으로 내렸습니다. 그런데
posts.json은 자동화 '실행 이력'으로 만들어지는 파일이라 글이 내려간 것을
모릅니다. 관련 포스트 추천(related_posts)은 그 posts.json을 읽으므로,
앞으로 발행하는 글이 내려간 글로 링크를 걸게 됩니다.

이 도구는 Blogger에 "지금 공개된 글이 무엇인지"만 묻고 그 목록을 적습니다.
글을 고치지도, 내리지도 않습니다 — 읽기 전용입니다.

사용
────
  python sync_live_posts.py            # 전체 블로그
  python sync_live_posts.py --blog blog1
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"
_HERE = os.path.dirname(os.path.abspath(__file__))
_DOCS_DATA = os.path.join(_HERE, "..", "docs", "data")
LIVE_PATH = os.path.join(_DOCS_DATA, "live_posts.json")


def _live_urls_for(cfg: dict, token: str) -> list[str]:
    """한 블로그의 공개(live) 글 주소 전체."""
    urls, page_token = [], ""
    while True:
        params = {"maxResults": 100, "status": "live", "fetchBodies": "false",
                  "fields": "nextPageToken,items(url)"}
        if page_token:
            params["pageToken"] = page_token
        r = requests.get(f"{BLOGGER_API_BASE}/blogs/{cfg['blog_id']}/posts",
                         headers={"Authorization": f"Bearer {token}"},
                         params=params, timeout=30)
        if r.status_code != 200:
            logger.error(f"[{cfg.get('name')}] 글 목록 조회 실패 "
                         f"[{r.status_code}]: {r.text[:160]}")
            return []
        data = r.json()
        urls += [(p.get("url") or "").rstrip("/") for p in data.get("items", [])
                 if p.get("url")]
        page_token = data.get("nextPageToken", "")
        if not page_token:
            return urls


def sync(blog_filter: str = "") -> dict:
    from blogger_uploader import _get_access_token
    from config import get_blog_configs

    by_blog, failed = {}, []
    for cfg in get_blog_configs():
        if blog_filter and cfg.get("id") != blog_filter:
            continue
        token = _get_access_token(cfg)
        if not token:
            logger.error(f"[{cfg.get('name')}] 토큰 발급 실패 — 건너뜀")
            failed.append(cfg.get("id", ""))
            continue
        urls = _live_urls_for(cfg, token)
        if not urls:
            failed.append(cfg.get("id", ""))
        by_blog[cfg.get("id", "")] = urls
        logger.info(f"[{cfg.get('name')}] 공개 글 {len(urls)}편")
    return {"by_blog": by_blog, "failed": failed}


def main() -> int:
    p = argparse.ArgumentParser(description="공개 상태인 글 주소를 모읍니다 (읽기 전용)")
    p.add_argument("--blog", default="", help="특정 블로그 ID만")
    args = p.parse_args()

    res = sync(args.blog)
    urls = sorted({u for v in res["by_blog"].values() for u in v})

    # 한 블로그라도 조회에 실패했으면 파일을 덮어쓰지 않습니다. 반쪽짜리
    # 목록을 적으면 related_posts가 멀쩡한 글을 '내려간 글'로 보고 링크에서
    # 빼버립니다 — 조용히 틀리는 쪽이 시끄럽게 실패하는 쪽보다 나쁩니다.
    if res["failed"]:
        logger.error(f"조회 실패한 블로그가 있어 {os.path.basename(LIVE_PATH)}를 "
                     f"갱신하지 않습니다: {res['failed']}")
        return 1

    payload = {
        "syncedAt": datetime.now(timezone.utc).isoformat(),
        "count": len(urls),
        "byBlog": {k: len(v) for k, v in res["by_blog"].items()},
        "urls": urls,
    }
    try:
        os.makedirs(_DOCS_DATA, exist_ok=True)
        with open(LIVE_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error(f"저장 실패: {e}")
        return 1
    logger.info(f"공개 글 {len(urls)}편 기록: {LIVE_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
