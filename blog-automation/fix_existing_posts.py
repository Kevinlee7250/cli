"""
기존 Blogger 포스트 AdSense 기준 미달 글 일괄 수정 스크립트

사용법:
  python fix_existing_posts.py [--batch-size N] [--blog-id blog1] [--min-words 4000] [--dry-run]

동작:
  1. docs/data/post_registry.json에서 published + wordCount < min-words 포스트 목록 조회
  2. 각 포스트의 Blogger 숫자 ID를 URL로 조회
  3. 키워드 기반으로 새 콘텐츠 생성 (4500자+ 목표)
  4. AdSense 검증 통과 시 Blogger API로 업데이트
  5. 결과를 fix_history.json에 기록
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/fix_posts.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("fix_posts")

from config import get_blog_configs, ADSENSE_MIN_SCORE
from content_generator import generate_post
from blogger_uploader import get_post_id_by_url, update_post
from adsense_validator import validate_adsense

# ── 경로 설정 ────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent
_REGISTRY_PATH = _ROOT / "docs/data/post_registry.json"
_FIX_HISTORY_PATH = Path(__file__).parent / "logs/fix_history.json"


def _load_registry() -> list[dict]:
    if not _REGISTRY_PATH.exists():
        logger.error(f"post_registry.json 없음: {_REGISTRY_PATH}")
        return []
    return json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))


def _load_fix_history() -> dict:
    if _FIX_HISTORY_PATH.exists():
        try:
            return json.loads(_FIX_HISTORY_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"fixed": [], "failed": [], "skipped": []}


def _save_fix_history(history: dict) -> None:
    _FIX_HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_failing_posts(registry: list[dict], min_words: int, blog_id_filter: str | None) -> list[dict]:
    """AdSense 기준 미달 published 포스트 목록 반환."""
    failing = []
    for p in registry:
        if p.get("status") != "published":
            continue
        if not p.get("blogUrl"):
            continue
        wc = p.get("wordCount") or 0
        if wc >= min_words:
            continue
        if blog_id_filter and p.get("blogId") != blog_id_filter:
            continue
        failing.append(p)
    # 짧은 것부터 우선 처리
    return sorted(failing, key=lambda p: p.get("wordCount") or 0)


def _already_fixed(post_id: str, history: dict) -> bool:
    return any(r.get("post_id") == post_id for r in history.get("fixed", []))


def main() -> None:
    parser = argparse.ArgumentParser(description="AdSense 미달 포스트 일괄 수정")
    parser.add_argument("--batch-size", type=int, default=10, help="한 번에 처리할 포스트 수 (기본 10)")
    parser.add_argument("--blog-id", help="특정 블로그만 처리 (예: blog1)")
    parser.add_argument("--min-words", type=int, default=4000, help="최소 글자 수 기준 (기본 4000)")
    parser.add_argument("--dry-run", action="store_true", help="실제 업데이트 없이 대상만 출력")
    parser.add_argument("--offset", type=int, default=0, help="처리 시작 인덱스 (pagination용)")
    args = parser.parse_args()

    registry = _load_registry()
    if not registry:
        logger.error("레지스트리 로드 실패")
        sys.exit(1)

    failing = _get_failing_posts(registry, args.min_words, args.blog_id)
    history = _load_fix_history()

    # 이미 수정된 것 제외
    remaining = [p for p in failing if not _already_fixed(p.get("post_id", ""), history)]
    batch = remaining[args.offset : args.offset + args.batch_size]

    logger.info(f"AdSense 미달 게시 포스트: 전체 {len(failing)}개 / 미수정 {len(remaining)}개")
    logger.info(f"이번 배치: {len(batch)}개 (offset={args.offset}, batch_size={args.batch_size})")
    if args.dry_run:
        logger.info("=== DRY RUN 모드 ===")

    if not batch:
        logger.info("처리할 포스트 없음 — 완료")
        return

    blog_configs = {cfg["id"]: cfg for cfg in get_blog_configs()}

    processed = success = failed_count = skipped = 0

    for post_info in batch:
        post_id     = post_info.get("post_id", "unknown")
        title       = post_info.get("title", "?")[:50]
        keyword     = post_info.get("keyword", "")
        blog_id_key = post_info.get("blogId", "blog1")
        blog_url    = post_info.get("blogUrl", "")
        old_wc      = post_info.get("wordCount") or 0

        logger.info(f"\n[{processed + 1}/{len(batch)}] '{title}' ({old_wc}자) — {blog_id_key}")

        # 제목 A/B 테스트 진행 중이면 본문 수정 금지 (제목·본문 동시 변경 방지)
        try:
            from title_ab_tracker import title_changed_recently
            if title_changed_recently(blog_url):
                logger.info("  제목 A/B 테스트 진행 중 (28일 미경과) — 본문 수정 건너뜀")
                history["skipped"].append({"post_id": post_id, "reason": "title_ab_in_progress", "at": datetime.now().isoformat()})
                skipped += 1
                processed += 1
                continue
        except Exception:
            pass

        blog_config = blog_configs.get(blog_id_key)
        if not blog_config and blog_id_key == "default":
            # 구형 포스트는 blogId="default"로 기록됨 — blog1로 폴백
            blog_config = blog_configs.get("blog1")
            if blog_config:
                logger.info(f"  blogId='default' → blog1 폴백 적용")
        if not blog_config:
            logger.warning(f"  블로그 설정 없음: {blog_id_key} — 건너뜀")
            history["skipped"].append({"post_id": post_id, "reason": "no_blog_config", "at": datetime.now().isoformat()})
            skipped += 1
            processed += 1
            continue

        # ① Blogger 숫자 포스트 ID 조회
        blogger_post_id = get_post_id_by_url(blog_url, blog_config)
        if not blogger_post_id:
            logger.warning(f"  Blogger 포스트 ID 조회 실패: {blog_url}")
            history["failed"].append({"post_id": post_id, "reason": "id_lookup_failed", "url": blog_url, "at": datetime.now().isoformat()})
            failed_count += 1
            processed += 1
            time.sleep(2)
            continue

        logger.info(f"  Blogger ID: {blogger_post_id}")

        # ② 새 콘텐츠 생성 (기존 labels 재활용)
        labels = post_info.get("labels", [])
        new_post_data = generate_post(
            keyword=keyword,
            blog_config=blog_config,
        )

        if not new_post_data:
            logger.warning(f"  콘텐츠 생성 실패")
            history["failed"].append({"post_id": post_id, "reason": "generation_failed", "keyword": keyword, "at": datetime.now().isoformat()})
            failed_count += 1
            processed += 1
            time.sleep(3)
            continue

        new_wc = new_post_data.get("word_count", 0)
        logger.info(f"  새 콘텐츠 생성 완료: {new_wc}자")

        if new_wc < 4000:
            logger.warning(f"  생성 분량 부족 ({new_wc}자 < 4000자) — 건너뜀")
            history["skipped"].append({"post_id": post_id, "reason": f"too_short_{new_wc}", "at": datetime.now().isoformat()})
            skipped += 1
            processed += 1
            time.sleep(2)
            continue

        # ③ AdSense 검증
        validation = validate_adsense(new_post_data)
        score = validation.get("score", 0)
        rec   = validation.get("recommendation", "reject")
        logger.info(f"  AdSense 검증: {rec.upper()} ({score}/100)")

        if rec == "reject":
            logger.warning(f"  AdSense 검증 REJECT — 건너뜀")
            history["skipped"].append({"post_id": post_id, "reason": f"adsense_reject_{score}", "at": datetime.now().isoformat()})
            skipped += 1
            processed += 1
            _save_fix_history(history)
            time.sleep(2)
            continue

        if rec == "review" or score < ADSENSE_MIN_SCORE:
            logger.warning(f"  AdSense 점수 미달 ({score}/100 < {ADSENSE_MIN_SCORE}) — 건너뜀")
            history["skipped"].append({"post_id": post_id, "reason": f"adsense_score_{score}", "at": datetime.now().isoformat()})
            skipped += 1
            processed += 1
            _save_fix_history(history)
            time.sleep(2)
            continue

        # ④ 업데이트
        if args.dry_run:
            logger.info(f"  [DRY RUN] 업데이트 예정: {new_wc}자, AdSense {score}/100")
            success += 1
        else:
            result = update_post(blogger_post_id, new_post_data, blog_config)
            if result:
                new_url = result.get("url", blog_url)
                logger.info(f"  ✅ 업데이트 성공: {old_wc}자 → {new_wc}자 | {new_url}")
                history["fixed"].append({
                    "post_id":          post_id,
                    "title":            new_post_data.get("title", title),
                    "keyword":          keyword,
                    "blog_id":          blog_id_key,
                    "old_word_count":   old_wc,
                    "new_word_count":   new_wc,
                    "adsense_score":    score,
                    "url":              new_url,
                    "at":               datetime.now().isoformat(),
                })
                success += 1
            else:
                logger.error(f"  ❌ 업데이트 실패")
                history["failed"].append({"post_id": post_id, "reason": "update_api_failed", "at": datetime.now().isoformat()})
                failed_count += 1

        processed += 1
        _save_fix_history(history)
        time.sleep(5)  # Blogger API rate limit 방지

    # 최종 요약
    logger.info("\n" + "=" * 60)
    logger.info(f"완료: 성공 {success} / 실패 {failed_count} / 건너뜀 {skipped} / 전체 {processed}")
    logger.info(f"누적 수정 완료: {len(history['fixed'])}개 / 전체 미달 {len(failing)}개")
    remaining_after = len(remaining) - success
    logger.info(f"남은 미수정: {remaining_after}개")
    _save_fix_history(history)


if __name__ == "__main__":
    main()
