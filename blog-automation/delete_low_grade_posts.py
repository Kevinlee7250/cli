"""등급(S/A/B/C) 기준 저성과 발행 글 삭제 — Blogger 실제 삭제 포함

blog_analytics.py 가 매긴 등급(docs/data/posts.json 의 "grade" 필드)을 기준으로
지정 등급 이하 글을 실제로 Blogger에서 삭제하고 로컬 대시보드 데이터(posts.json,
post_registry.json)에서도 제거합니다. Blogger 삭제는 되돌릴 수 없습니다.

Usage:
  python delete_low_grade_posts.py --dry-run                  # 미리보기만
  python delete_low_grade_posts.py --grades B,C               # 실제 삭제
  python delete_low_grade_posts.py --grades C --blog blog1
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_BASE_DIR = os.path.dirname(__file__)
_DOCS_DATA = os.path.join(_BASE_DIR, "..", "docs", "data")
_POSTS_JSON = os.path.join(_DOCS_DATA, "posts.json")
_REGISTRY_JSON = os.path.join(_DOCS_DATA, "post_registry.json")
_REGISTRY_LOGS = os.path.join(_BASE_DIR, "logs", "post_registry.json")
_ANALYTICS_SUMMARY = os.path.join(_DOCS_DATA, "analytics_summary.json")


def _load(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _save(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _measurement_gate_blocked() -> str | None:
    """등급이 '실제 저성과'가 아니라 '측정 불가'로 나온 상태에서 삭제를 막습니다.

    2026-07-22 실제로 겪은 근접 사고: Blogger API·GSC 연동이 전부 깨진 상태에서
    분석을 돌렸더니 91개 글이 전부 "B등급"으로 나왔음 — 이건 저성과가 아니라
    측정 자체가 안 된 것이었는데, 하마터면 발행 글 47개를 무근거로 삭제할 뻔함.
    dataSource가 신호 없음을 보고하면 --force 없이는 삭제를 거부합니다.
    """
    summary = _load(_ANALYTICS_SUMMARY, None)
    if not summary:
        return "analytics_summary.json 없음 — blog_analytics.py를 먼저 실행해 실제 등급을 매기세요"
    ds = summary.get("dataSource", {})
    if not ds.get("bloggerApi") and not ds.get("gscPageData"):
        return (
            "실제 성과 데이터(Blogger 조회수/GSC 클릭)가 전혀 수집되지 않았습니다 — "
            "지금의 등급은 '저성과'가 아니라 '측정 불가'를 의미할 수 있습니다. "
            "GOOGLE_REFRESH_TOKEN 등 인증 상태를 확인하고 재분석 후 다시 시도하거나, "
            "정말 이 상태로 진행하려면 --force를 명시하세요."
        )
    return None


def scan_and_delete(grades: set[str], blog_filter: str, dry_run: bool, force: bool = False) -> dict:
    from config import get_blog_configs
    from blogger_uploader import get_post_id_by_url, delete_post

    if not dry_run and not force:
        gate_msg = _measurement_gate_blocked()
        if gate_msg:
            logger.error(f"⛔ 삭제 중단: {gate_msg}")
            return {"error": gate_msg, "gated": True}

    blogs = {c.get("id", "blog1"): c for c in get_blog_configs()}
    posts = _load(_POSTS_JSON, [])
    if not posts:
        logger.error("posts.json 없음 또는 빈 파일 — 먼저 blog_analytics.py 를 실행해 등급을 매겨야 합니다")
        return {"error": "posts.json 없음"}

    ungraded = sum(1 for p in posts if not p.get("grade"))
    if ungraded == len(posts):
        logger.error("모든 포스트에 등급(grade)이 없습니다 — blog_analytics.py 를 먼저 실행하세요")
        return {"error": "등급 데이터 없음"}

    targets = [
        p for p in posts
        if p.get("grade") in grades
        and p.get("blogUrl")
        and (not blog_filter or p.get("blogId") == blog_filter)
    ]

    logger.info(f"대상 등급: {sorted(grades)} / 전체 {len(posts)}개 중 {len(targets)}개 삭제 대상")

    deleted_urls: set[str] = set()
    items = []
    failed = 0

    for p in targets:
        blog_id = p.get("blogId", "blog1")
        cfg = blogs.get(blog_id, {})
        title = p.get("title", "")[:60]
        url = p.get("blogUrl", "")
        grade = p.get("grade", "")
        item = {"blogId": blog_id, "title": title, "url": url, "grade": grade}

        if dry_run:
            item["result"] = "미리보기 (삭제 안 함)"
            items.append(item)
            continue

        blogger_post_id = get_post_id_by_url(url, cfg)
        if not blogger_post_id:
            item["result"] = "실패 (Blogger post ID 조회 불가 — 이미 삭제됐거나 URL 불일치)"
            items.append(item)
            failed += 1
            continue

        ok = delete_post(blogger_post_id, cfg)
        if ok:
            item["result"] = "삭제 완료"
            deleted_urls.add(url)
            logger.info(f"  ✅ 삭제: [{grade}] {title} ({blog_id})")
        else:
            item["result"] = "실패 (Blogger API 오류)"
            failed += 1
            logger.error(f"  ❌ 삭제 실패: {title} ({blog_id})")
        items.append(item)
        time.sleep(1)

    if not dry_run and deleted_urls:
        remaining_posts = [p for p in posts if p.get("blogUrl") not in deleted_urls]
        _save(_POSTS_JSON, remaining_posts)
        logger.info(f"posts.json 갱신: {len(posts)} → {len(remaining_posts)}개")

        registry = _load(_REGISTRY_JSON, [])
        if registry:
            remaining_registry = [r for r in registry if r.get("blogUrl") not in deleted_urls]
            _save(_REGISTRY_JSON, remaining_registry)
            _save(_REGISTRY_LOGS, remaining_registry)
            logger.info(f"post_registry.json 갱신: {len(registry)} → {len(remaining_registry)}개")

    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "grades": sorted(grades),
        "blog_filter": blog_filter or "전체",
        "total_posts": len(posts),
        "targets_found": len(targets),
        "deleted": len(deleted_urls),
        "failed": failed,
        "items": items,
    }
    try:
        _save(os.path.join(_DOCS_DATA, "grade_cleanup.json"), report)
    except Exception as e:
        logger.warning(f"리포트 저장 실패: {e}")

    mode = "(미리보기) " if dry_run else ""
    logger.info("=" * 55)
    logger.info(
        f"{mode}완료 — 대상 {len(targets)}건 / 삭제 {len(deleted_urls)}건 / 실패 {failed}건"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="등급 기준 저성과 발행 글 삭제 (Blogger 실제 삭제 포함)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--grades", default="B,C", help="삭제 대상 등급 (쉼표 구분, 기본 B,C)")
    parser.add_argument("--blog", default="", help="특정 블로그 ID만 대상 (비우면 전체)")
    parser.add_argument("--force", action="store_true",
                         help="실제 성과 데이터 없이(측정 불가 상태) 등급만으로도 강제 삭제 진행")
    args = parser.parse_args()

    grades = {g.strip().upper() for g in args.grades.split(",") if g.strip()}
    report = scan_and_delete(grades, args.blog, args.dry_run, force=args.force)
    return 0 if not report.get("error") and report.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
