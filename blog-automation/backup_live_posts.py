"""공개 글의 제목·본문 HTML을 통째로 저장소에 백업합니다.

왜 필요한가
──────────
다음 작업(관련 포스트 블록 교체)은 살아있는 글의 본문 HTML을 직접
PATCH합니다. 지금까지의 작업은 전부 되돌릴 수 있었습니다 — 비공개는
임시저장이고, 제목·본문 정정은 감사 기록이 남고, 코드는 PR입니다.
본문을 정규식으로 잘라내는 작업은 다릅니다. 카드 경계를 잘못 잡으면
본문 일부가 사라지고, Blogger에는 되돌릴 버전 기록이 없습니다.

그래서 먼저 원본을 git에 넣습니다. 실수하면 restore로 되돌립니다.

사용
────
  python backup_live_posts.py                 # 전체 백업
  python backup_live_posts.py --blog blog1
  python backup_live_posts.py --restore backups/live_posts_20260913.json --dry-run
  python backup_live_posts.py --restore backups/live_posts_20260913.json --url <주소>
"""
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"
_HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(_HERE, "backups")


def _iter_live(blog_id: str, token: str):
    """공개 글 전체를 본문까지 받아 순회합니다."""
    page_token = ""
    while True:
        params = {"maxResults": 50, "status": "live", "fetchBodies": "true",
                  "fields": "nextPageToken,items(id,title,url,content,published,updated)"}
        if page_token:
            params["pageToken"] = page_token
        r = requests.get(f"{BLOGGER_API_BASE}/blogs/{blog_id}/posts",
                         headers={"Authorization": f"Bearer {token}"},
                         params=params, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"글 목록 조회 실패 [{r.status_code}]: {r.text[:200]}")
        data = r.json()
        yield from data.get("items", [])
        page_token = data.get("nextPageToken", "")
        if not page_token:
            return


def backup(blog_filter: str = "") -> dict:
    """모든 공개 글의 원본을 모읍니다. 한 블로그라도 실패하면 예외."""
    from blogger_uploader import _get_access_token
    from config import get_blog_configs

    posts, by_blog = [], {}
    for cfg in get_blog_configs():
        bid = cfg.get("id", "")
        if blog_filter and bid != blog_filter:
            continue
        token = _get_access_token(cfg)
        if not token:
            raise RuntimeError(f"[{cfg.get('name')}] 토큰 발급 실패")
        n = 0
        for p in _iter_live(cfg.get("blog_id", ""), token):
            posts.append({
                "blogId": bid, "blog": cfg.get("name", ""),
                "postId": p.get("id", ""), "url": (p.get("url") or "").rstrip("/"),
                "title": p.get("title", ""), "content": p.get("content", ""),
                "published": p.get("published", ""), "updated": p.get("updated", ""),
            })
            n += 1
        by_blog[bid] = n
        logger.info(f"[{cfg.get('name')}] {n}편 백업")
    return {"posts": posts, "byBlog": by_blog}


def verify(payload: dict) -> list[str]:
    """백업이 복원에 쓸 만한지 검사합니다. 문제를 문자열 목록으로 반환.

    빈 본문이 섞인 백업은 백업이 아니라 함정입니다 — 그걸로 복원하면
    글이 지워집니다. 저장하기 전에 걸러냅니다.
    """
    problems = []
    posts = payload.get("posts") or []
    if not posts:
        return ["백업된 글이 0편입니다"]
    for p in posts:
        if not p.get("postId"):
            problems.append(f"postId 없음: {p.get('url', '?')}")
        if not (p.get("content") or "").strip():
            problems.append(f"본문이 비어 있음: {p.get('title', '?')[:40]}")
        if not (p.get("title") or "").strip():
            problems.append(f"제목이 비어 있음: {p.get('url', '?')}")
    return problems


def restore(path: str, only_url: str = "", dry_run: bool = True) -> dict:
    """백업 파일의 제목·본문을 Blogger에 되돌립니다."""
    from blogger_uploader import _get_access_token
    from config import get_blog_configs

    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    problems = verify(payload)
    if problems:
        raise RuntimeError(f"백업 파일이 온전하지 않습니다 ({len(problems)}건): "
                           f"{problems[:3]}")

    cfgs = {c.get("id", ""): c for c in get_blog_configs()}
    tokens, done, failed = {}, 0, 0
    for p in payload["posts"]:
        if only_url and p["url"].rstrip("/") != only_url.rstrip("/"):
            continue
        cfg = cfgs.get(p["blogId"])
        if not cfg:
            logger.error(f"블로그 설정 없음: {p['blogId']}")
            failed += 1
            continue
        if dry_run:
            logger.info(f"  (dry-run) 복원 대상: {p['title'][:50]}")
            done += 1
            continue
        if p["blogId"] not in tokens:
            tokens[p["blogId"]] = _get_access_token(cfg)
        r = requests.patch(
            f"{BLOGGER_API_BASE}/blogs/{cfg['blog_id']}/posts/{p['postId']}",
            headers={"Authorization": f"Bearer {tokens[p['blogId']]}",
                     "Content-Type": "application/json"},
            json={"title": p["title"], "content": p["content"]}, timeout=60)
        if r.status_code == 200:
            done += 1
            logger.info(f"  ↩️  복원: {p['title'][:50]}")
        else:
            failed += 1
            logger.error(f"    ❌ 복원 실패 [{r.status_code}]: {r.text[:140]}")
        time.sleep(1)
    return {"restored": done, "failed": failed, "dryRun": dry_run}


def main() -> int:
    p = argparse.ArgumentParser(description="공개 글 원본 백업 / 복원")
    p.add_argument("--blog", default="", help="특정 블로그 ID만")
    p.add_argument("--restore", default="", help="이 백업 파일로 되돌립니다")
    p.add_argument("--url", default="", help="--restore와 함께: 이 글 하나만")
    p.add_argument("--dry-run", action="store_true", help="--restore 미리보기")
    args = p.parse_args()

    if args.restore:
        res = restore(args.restore, args.url, args.dry_run)
        logger.info(f"복원 {res['restored']}편 / 실패 {res['failed']}편"
                    f"{' (dry-run)' if res['dryRun'] else ''}")
        return 0 if res["failed"] == 0 else 1

    data = backup(args.blog)
    payload = {
        "backedUpAt": datetime.now(timezone.utc).isoformat(),
        "count": len(data["posts"]),
        "byBlog": data["byBlog"],
        "posts": data["posts"],
    }
    problems = verify(payload)
    if problems:
        logger.error(f"백업이 온전하지 않아 저장하지 않습니다 ({len(problems)}건):")
        for x in problems[:10]:
            logger.error(f"  - {x}")
        return 1

    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = os.path.join(BACKUP_DIR, f"live_posts_{stamp}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    size = os.path.getsize(out) / 1024
    logger.info(f"{payload['count']}편 백업 완료 ({size:.0f} KB): {out}")
    logger.info("되돌리려면: python backup_live_posts.py --restore "
                f"backups/{os.path.basename(out)} --dry-run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
