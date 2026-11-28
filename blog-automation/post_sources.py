"""점검 도구가 읽을 '발행된 글' 모음 — 백업 파일 또는 Blogger API.

점검 도구(link_policy_audit·cross_blog_dup_report)는 글을 고치지 않고 읽기만
합니다. 글을 어디서 읽는지는 이 모듈 한 곳에서 정합니다.

  · backup  — blog-automation/backups/live_posts_*.json 중 가장 최근 파일.
              인증 없이 로컬에서 돌릴 수 있지만, 백업 시점 이후 글은 없습니다.
  · live    — Blogger API로 지금 공개된 글 전체(GitHub Actions에서 사용).

어느 쪽이든 반환 모양은 같습니다:
  {"blogId", "url", "title", "content", "published"}

목록을 끝까지 못 읽은 블로그는 ``incomplete``에 이름을 남깁니다. 부분 결과를
전체처럼 보고하면 안 되기 때문입니다(blogger_posts.ListingTruncated 참고).
"""

from __future__ import annotations

import glob
import json
import logging
import os

logger = logging.getLogger(__name__)

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(HERE, "backups")
DOCS_DATA = os.path.normpath(os.path.join(HERE, "..", "docs", "data"))


def latest_backup(path: str = BACKUP_DIR) -> str | None:
    files = sorted(glob.glob(os.path.join(path, "live_posts_*.json")))
    return files[-1] if files else None


def _norm(p: dict, blog_id: str = "") -> dict:
    return {
        "blogId": p.get("blogId") or blog_id,
        "url": p.get("url", ""),
        "title": p.get("title", ""),
        "content": p.get("content", "") or "",
        "published": p.get("published", ""),
    }


def from_backup(path: str | None = None) -> tuple[list[dict], dict]:
    """백업 파일의 글. (글 목록, 메타) — 메타에 파일 이름과 백업 시각."""
    path = path or latest_backup()
    if not path:
        raise FileNotFoundError("backups/live_posts_*.json 이 없습니다")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    posts = data.get("posts", []) if isinstance(data, dict) else data
    meta = {"source": "backup", "file": os.path.basename(path),
            "asOf": (data.get("backedUpAt") if isinstance(data, dict) else "") or "",
            "incomplete": []}
    return [_norm(p) for p in posts], meta


def from_live(blog_ids: list[str] | None = None) -> tuple[list[dict], dict]:
    """Blogger API로 지금 공개된 글. 토큰이 없거나 목록이 잘리면 incomplete에 기록."""
    from datetime import datetime, timezone

    from blogger_posts import ListingTruncated, iter_posts
    from blogger_uploader import _get_access_token
    from config import get_blog_configs

    out: list[dict] = []
    incomplete: list[str] = []
    for cfg in get_blog_configs():
        bid = cfg.get("id", "")
        if blog_ids and bid not in blog_ids:
            continue
        token = _get_access_token(cfg)
        if not token or not cfg.get("blog_id"):
            logger.error(f"[{bid}] 토큰 또는 blog_id 없음 — 이 블로그는 읽지 못함")
            incomplete.append(bid)
            continue
        try:
            for p in iter_posts(cfg["blog_id"], token):
                out.append(_norm(p, bid))
        except ListingTruncated as e:
            logger.error(f"[{bid}] 목록을 끝까지 읽지 못함: {e}")
            incomplete.append(bid)
    meta = {"source": "live", "file": "",
            "asOf": datetime.now(timezone.utc).isoformat(), "incomplete": incomplete}
    return out, meta


def load(source: str = "backup", backup_path: str | None = None,
         blog_ids: list[str] | None = None) -> tuple[list[dict], dict]:
    if source == "live":
        return from_live(blog_ids)
    posts, meta = from_backup(backup_path)
    if blog_ids:
        posts = [p for p in posts if p["blogId"] in blog_ids]
    return posts, meta


def write_report(name: str, payload: dict) -> str:
    """docs/data/<name> 에 JSON을 씁니다(대시보드·사무실 화면이 읽는 곳)."""
    os.makedirs(DOCS_DATA, exist_ok=True)
    path = os.path.join(DOCS_DATA, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path
