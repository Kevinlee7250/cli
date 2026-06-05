#!/usr/bin/env python3
"""검토 대기 포스트를 Blogger에 게시하는 수동 게시 스크립트.

사용법:
  python publish_pending.py --id <post_id>
  python publish_pending.py --ids "id1,id2,id3"
  python publish_pending.py --all-pending
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("publish_pending")

PENDING_FILE = os.path.join(os.path.dirname(__file__), "..", "docs", "data", "pending_posts.json")


def load_pending() -> list[dict]:
    if not os.path.exists(PENDING_FILE):
        logger.error(f"pending_posts.json 없음: {PENDING_FILE}")
        return []
    try:
        with open(PENDING_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"pending_posts.json 로드 실패: {e}")
        return []


def save_pending(pending: list[dict]) -> None:
    try:
        os.makedirs(os.path.dirname(PENDING_FILE), exist_ok=True)
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(pending, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error(f"pending_posts.json 저장 실패: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="검토 대기 포스트를 Blogger에 게시")
    parser.add_argument("--id", dest="post_id", default="", help="게시할 포스트 ID")
    parser.add_argument("--ids", default="", help="쉼표로 구분된 포스트 ID 목록")
    parser.add_argument("--all-pending", action="store_true", help="모든 pending 포스트 게시")
    args = parser.parse_args()

    pending = load_pending()
    if not pending:
        logger.error("게시할 포스트가 없습니다")
        sys.exit(1)

    ids_to_publish: list[str] = []
    if args.post_id.strip():
        ids_to_publish.append(args.post_id.strip())
    if args.ids.strip():
        ids_to_publish.extend(i.strip() for i in args.ids.split(",") if i.strip())
    if args.all_pending:
        ids_to_publish = [p["id"] for p in pending if p.get("status") == "pending"]

    if not ids_to_publish:
        logger.error("게시할 포스트 ID 없음 (--id, --ids, 또는 --all-pending 필요)")
        sys.exit(1)

    logger.info(f"게시 대상 {len(ids_to_publish)}개: {ids_to_publish}")

    from blogger_uploader import upload_post

    success, fail = 0, 0
    for post_id in ids_to_publish:
        post = next((p for p in pending if p["id"] == post_id), None)
        if not post:
            logger.error(f"포스트 ID 없음: {post_id}")
            fail += 1
            continue
        if post.get("status") == "published":
            logger.warning(f"이미 게시됨 (건너뜀): {post.get('title', post_id)}")
            continue

        logger.info(f"[{post_id}] 게시 중: {post.get('title', '')}")
        result = upload_post({
            "title": post["title"],
            "content": post["content"],
            "labels": post.get("labels", []),
            "keyword": post.get("keyword", ""),
            "faq": post.get("faq", []),
            "meta_description": post.get("metaDescription", ""),
            "sources": post.get("sources", []),
        })

        if result:
            post["status"] = "published"
            post["publishedAt"] = datetime.now().isoformat()
            post["blogUrl"] = result.get("url", "")
            logger.info(f"  ✅ 완료: {post['blogUrl']}")
            success += 1
        else:
            post["status"] = "failed"
            logger.error(f"  ❌ 실패: {post.get('title', post_id)}")
            fail += 1

    save_pending(pending)
    logger.info(f"\n완료: 성공 {success}개 / 실패 {fail}개")
    if fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
