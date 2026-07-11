"""포스트 단건 관리 — 발행·보관·삭제·복원

Usage:
  python manage_post.py --action publish  --post-id <post_id>
  python manage_post.py --action archive  --post-id <post_id>  # → skipped
  python manage_post.py --action delete   --post-id <post_id>  # registry에서 제거
  python manage_post.py --action restore  --post-id <post_id>  # skipped → pending
"""

import argparse
import json
import logging
import os
import sys

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_BASE_DIR   = os.path.dirname(__file__)
DOCS_DATA   = os.path.join(_BASE_DIR, "..", "docs", "data")


def _load_registry():
    from post_manager import load_registry
    return load_registry()


def _save_and_export(registry):
    from post_manager import save_registry, export_for_dashboard
    save_registry(registry)
    export_for_dashboard(os.path.abspath(DOCS_DATA))


def action_archive(post_id: str) -> int:
    from post_manager import update_post_status, Status, load_registry
    registry = load_registry()
    entry = next((p for p in registry if p.get("post_id") == post_id), None)
    if not entry:
        logger.error(f"포스트를 찾을 수 없습니다: {post_id}")
        return 1
    current = entry.get("status", "")
    if current == Status.PUBLISHED:
        logger.error(f"게시 완료 포스트는 보관할 수 없습니다 (현재 상태: {current})")
        return 1
    update_post_status(post_id, Status.SKIPPED, error="수동 보관")
    _save_and_export(_load_registry())
    logger.info(f"✅ 보관 완료: {post_id}")
    return 0


def action_delete(post_id: str) -> int:
    from post_manager import load_registry, save_registry, export_for_dashboard, delete_draft
    registry = load_registry()
    before = len(registry)
    registry = [p for p in registry if p.get("post_id") != post_id]
    if len(registry) == before:
        logger.error(f"포스트를 찾을 수 없습니다: {post_id}")
        return 1
    save_registry(registry)
    export_for_dashboard(os.path.abspath(DOCS_DATA))
    delete_draft(post_id)
    logger.info(f"✅ 삭제 완료: {post_id}")
    return 0


def action_restore(post_id: str) -> int:
    from post_manager import update_post_status, Status, load_registry
    registry = load_registry()
    entry = next((p for p in registry if p.get("post_id") == post_id), None)
    if not entry:
        logger.error(f"포스트를 찾을 수 없습니다: {post_id}")
        return 1
    update_post_status(post_id, Status.PENDING, error=None)
    # errorMessage 초기화
    reg2 = _load_registry()
    for p in reg2:
        if p.get("post_id") == post_id:
            p["errorMessage"] = None
            break
    _save_and_export(reg2)
    logger.info(f"✅ 복원 완료 (→ pending): {post_id}")
    return 0


def action_publish(post_id: str) -> int:
    from post_manager import (
        load_draft, update_post_status, Status, load_registry, export_for_dashboard
    )
    from blogger_uploader import upload_post

    registry = _load_registry()
    entry = next((p for p in registry if p.get("post_id") == post_id), None)
    if not entry:
        logger.error(f"포스트를 찾을 수 없습니다: {post_id}")
        return 1

    current = entry.get("status", "")
    if current == Status.PUBLISHED:
        logger.warning(f"이미 게시된 포스트입니다: {entry.get('blogUrl', '')}")
        return 0

    # 초안 파일 로드 시도
    post_data = load_draft(post_id)
    if not post_data:
        # pending_posts.json에서 검색
        pending_path = os.path.join(DOCS_DATA, "pending_posts.json")
        if os.path.exists(pending_path):
            try:
                with open(pending_path, encoding="utf-8") as f:
                    pending = json.load(f)
                for item in pending:
                    if item.get("id") == post_id or item.get("post_id") == post_id:
                        post_data = item
                        break
            except Exception:
                pass

    if not post_data:
        logger.error(f"포스트 콘텐츠를 찾을 수 없습니다 (초안/pending 없음): {post_id}")
        logger.error("초안 파일 위치: blog-automation/logs/post_drafts/{post_id}.json")
        return 1

    # 블로그 config 탐색 (BLOGS_CONFIG 환경변수에서)
    blog_config = None
    blogs_config_raw = os.getenv("BLOGS_CONFIG", "")
    if blogs_config_raw:
        try:
            blogs_list = json.loads(blogs_config_raw)
            blog_id = entry.get("blogId", "")
            if blog_id and blog_id != "default":
                blog_config = next((b for b in blogs_list if b.get("id") == blog_id), None)
            if not blog_config and blogs_list:
                blog_config = blogs_list[0]
        except Exception:
            pass

    logger.info(f"📤 발행 시도: {entry.get('keyword', '')} — {entry.get('title', '')}")
    update_post_status(post_id, Status.RETRY_QUEUED)

    result = upload_post(post_data, blog_config)
    if result:
        url = result.get("url", "")
        update_post_status(post_id, Status.PUBLISHED, blog_url=url)
        from post_manager import delete_draft
        delete_draft(post_id)
        export_for_dashboard(os.path.abspath(DOCS_DATA))
        logger.info(f"✅ 발행 완료: {url}")
        return 0
    else:
        update_post_status(post_id, Status.FAILED, error="수동 발행 실패")
        export_for_dashboard(os.path.abspath(DOCS_DATA))
        logger.error("❌ 발행 실패")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="포스트 단건 관리")
    parser.add_argument("--action", required=True, choices=["publish", "archive", "delete", "restore"])
    parser.add_argument("--post-id", required=True, dest="post_id")
    args = parser.parse_args()

    dispatch = {
        "publish": action_publish,
        "archive": action_archive,
        "delete":  action_delete,
        "restore": action_restore,
    }
    return dispatch[args.action](args.post_id)


if __name__ == "__main__":
    sys.exit(main())
