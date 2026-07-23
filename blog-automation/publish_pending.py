#!/usr/bin/env python3
"""검토 대기 포스트를 Blogger에 게시하는 수동 게시 스크립트.

사용법:
  python publish_pending.py --id <post_id>
  python publish_pending.py --ids "id1,id2,id3"
  python publish_pending.py --all-pending
  python publish_pending.py --retry-failed
"""

import argparse
import io
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


def upload_with_log_capture(post_data: dict) -> tuple[dict | None, str]:
    """upload_post 호출 + 에러 로그 캡처."""
    from blogger_uploader import upload_post

    log_stream = io.StringIO()
    capture = logging.StreamHandler(log_stream)
    capture.setLevel(logging.WARNING)
    root = logging.getLogger()
    root.addHandler(capture)
    result = None
    try:
        result = upload_post(post_data)
    except Exception as exc:
        logger.error(f"upload_post 예외: {exc}")
        log_stream.write(f"EXCEPTION: {exc}")
    finally:
        root.removeHandler(capture)
    captured = log_stream.getvalue().strip()
    return result, captured


def main() -> None:
    parser = argparse.ArgumentParser(description="검토 대기 포스트를 Blogger에 게시")
    parser.add_argument("--id", dest="post_id", default="", help="게시할 포스트 ID")
    parser.add_argument("--ids", default="", help="쉼표로 구분된 포스트 ID 목록")
    parser.add_argument("--all-pending", action="store_true", help="모든 pending/failed 포스트 게시")
    parser.add_argument("--retry-failed", action="store_true", help="failed 상태 포스트 재시도")
    args = parser.parse_args()

    pending = load_pending()
    if not pending:
        logger.error("pending_posts.json이 비어있거나 로드 실패")
        sys.exit(1)

    ids_to_publish: list[str] = []
    if args.post_id.strip():
        ids_to_publish.append(args.post_id.strip())
    if args.ids.strip():
        ids_to_publish.extend(i.strip() for i in args.ids.split(",") if i.strip())
    if args.all_pending:
        ids_to_publish = [
            p["id"] for p in pending
            if p.get("status") in ("pending", "failed")
        ]
    if args.retry_failed:
        failed_ids = [p["id"] for p in pending if p.get("status") == "failed"]
        ids_to_publish = list(dict.fromkeys(ids_to_publish + failed_ids))

    if not ids_to_publish:
        logger.warning("게시할 포스트 없음 (pending/failed 상태 없음)")
        sys.exit(0)

    logger.info(f"게시 대상 {len(ids_to_publish)}개")

    success, fail = 0, 0
    for post_id in ids_to_publish:
        post = next(
            (p for p in pending
             if p["id"] == post_id and p.get("status") not in ("published",)),
            None
        )
        if not post:
            logger.warning(f"처리 건너뜀 (없거나 이미 게시됨): {post_id}")
            continue

        title = post.get("title", "")
        logger.info(f"게시 중: {title[:60]}")

        result, err_log = upload_with_log_capture({
            "title": post["title"],
            "content": post["content"],
            "labels": post.get("labels", []),
            "keyword": post.get("keyword", ""),
            "faq": post.get("faq", []),
            "meta_description": post.get("metaDescription", ""),
            "sources": post.get("sources", []),
        })

        if result and not result.get("_error"):
            post["status"] = "published"
            post["publishedAt"] = datetime.now().isoformat()
            post["blogUrl"] = result.get("url", "")
            post.pop("failReason", None)
            logger.info(f"  ✅ 성공: {post['blogUrl']}")
            success += 1
        else:
            post["status"] = "failed"
            post["failedAt"] = datetime.now().isoformat()
            # 에러 로그를 failReason에 저장 (다음 진단용)
            post["failReason"] = (err_log or "upload_post returned None (로그 없음)")[:800]
            logger.error(f"  ❌ 실패: {title[:50]}")
            logger.error(f"     → {post['failReason'][:200]}")
            fail += 1

    save_pending(pending)
    logger.info(f"완료: 성공 {success} / 실패 {fail}")
    if fail > 0 and success == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
