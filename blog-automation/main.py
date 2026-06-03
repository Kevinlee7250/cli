#!/usr/bin/env python3
"""
블로그 자동화 시스템 — 메인 실행 파일

사용법:
  python main.py            # 스케줄 모드 (SCHEDULE_CRON 기준 자동 실행)
  python main.py --once     # 즉시 1회 실행
  python main.py --test     # 글 생성만 (Blogger 업로드 없음)
  python main.py --keyword "재테크" --once   # 특정 키워드로 1회 실행
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

# 로그 설정
_log_level = os.getenv("LOG_LEVEL", "info").upper()
_log_file = os.getenv("LOG_FILE", "./logs/automation.log")
os.makedirs(os.path.dirname(_log_file), exist_ok=True)

logging.basicConfig(
    level=getattr(logging, _log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(_log_file, encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")

from config import (
    ANTHROPIC_API_KEY,
    BLOGGER_CLIENT_ID,
    BLOGGER_BLOG_ID,
    BLOGGER_REFRESH_TOKEN,
    BLOG_LANGUAGE,
    POSTS_PER_RUN,
    TREND_COUNTRY,
    SCHEDULE_CRON,
)
from content_generator import generate_post
from blogger_uploader import upload_post
from keyword_collector import get_trending_keywords


# ──────────────────────────────────────────────────────────────────────────────
# 사전 점검
# ──────────────────────────────────────────────────────────────────────────────

def _check_config() -> bool:
    """필수 환경 변수가 모두 설정됐는지 확인합니다."""
    errors = []
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("sk-ant-xxx"):
        errors.append("ANTHROPIC_API_KEY 미설정")
    if not BLOGGER_CLIENT_ID or BLOGGER_CLIENT_ID.startswith("your_"):
        errors.append("GOOGLE_CLIENT_ID(Blogger OAuth) 미설정")
    if not BLOGGER_BLOG_ID or BLOGGER_BLOG_ID.startswith("your_"):
        errors.append("BLOGGER_BLOG_ID 미설정")
    if not BLOGGER_REFRESH_TOKEN or BLOGGER_REFRESH_TOKEN.startswith("your_"):
        errors.append("GOOGLE_REFRESH_TOKEN 미설정")

    if errors:
        for e in errors:
            logger.error(f"⚠️  설정 누락: {e}")
        logger.error(".env 파일을 확인하세요 (참고: .env.example)")
        return False
    return True


# ──────────────────────────────────────────────────────────────────────────────
# 단일 실행
# ──────────────────────────────────────────────────────────────────────────────

def run_once(keywords: list[str] | None = None, dry_run: bool = False) -> None:
    """키워드를 수집해 포스트를 생성하고 Blogger에 업로드합니다."""
    logger.info("=" * 60)
    logger.info(f"블로그 자동화 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    # 키워드 수집
    if not keywords:
        keywords = get_trending_keywords(
            country=TREND_COUNTRY,
            language=BLOG_LANGUAGE,
            count=POSTS_PER_RUN,
            naver_client_id=os.getenv("NAVER_CLIENT_ID", ""),
            naver_client_secret=os.getenv("NAVER_CLIENT_SECRET", ""),
        )
    keywords = keywords[:POSTS_PER_RUN]
    logger.info(f"대상 키워드 {len(keywords)}개: {keywords}")

    success_count = 0
    fail_count = 0

    for i, keyword in enumerate(keywords, 1):
        logger.info(f"\n[{i}/{len(keywords)}] 키워드: '{keyword}'")

        # 포스트 생성
        post_data = generate_post(keyword)
        if not post_data:
            logger.error(f"  포스트 생성 실패: '{keyword}'")
            fail_count += 1
            continue

        title = post_data.get("title", "?")
        images = post_data.get("images_inserted", 0)
        logger.info(f"  제목: {title}")
        logger.info(f"  이미지: {images}개 삽입")

        if dry_run:
            logger.info(f"  [테스트 모드] 업로드 건너뜀")
            success_count += 1
            continue

        # Blogger 업로드
        result = upload_post(post_data)
        if result:
            url = result.get("url", "")
            logger.info(f"  ✅ 업로드 성공: {url}")
            success_count += 1
        else:
            logger.error(f"  ❌ 업로드 실패: '{title}'")
            fail_count += 1

        # API 과부하 방지 (포스트 사이 2초 대기)
        if i < len(keywords):
            time.sleep(2)

    logger.info("\n" + "=" * 60)
    logger.info(f"완료: 성공 {success_count}개 / 실패 {fail_count}개")
    logger.info("=" * 60)


# ──────────────────────────────────────────────────────────────────────────────
# 스케줄 모드
# ──────────────────────────────────────────────────────────────────────────────

def run_scheduled() -> None:
    """SCHEDULE_CRON 설정에 따라 주기적으로 실행합니다."""
    try:
        import schedule
    except ImportError:
        logger.error("schedule 패키지가 필요합니다: pip install schedule")
        sys.exit(1)

    parts = SCHEDULE_CRON.strip().split()
    if len(parts) < 2:
        logger.error(f"잘못된 SCHEDULE_CRON 형식: '{SCHEDULE_CRON}'")
        sys.exit(1)

    minute, hour = parts[0], parts[1]
    time_str = f"{int(hour):02d}:{int(minute):02d}"
    schedule.every().day.at(time_str).do(run_once)
    logger.info(f"스케줄 등록: 매일 {time_str} 실행 (cron: {SCHEDULE_CRON})")
    logger.info("Ctrl+C로 종료")

    while True:
        schedule.run_pending()
        time.sleep(30)


# ──────────────────────────────────────────────────────────────────────────────
# 진입점
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="블로그 자동화 시스템")
    parser.add_argument("--once", action="store_true", help="즉시 1회 실행")
    parser.add_argument("--test", action="store_true", help="글 생성만 (업로드 없음)")
    parser.add_argument("--keyword", type=str, help="특정 키워드로 실행 (쉼표로 복수 지정)")
    args = parser.parse_args()

    dry_run = args.test
    keywords = None
    if args.keyword:
        keywords = [k.strip() for k in args.keyword.split(",") if k.strip()]

    if args.test:
        logger.info("테스트 모드 — 업로드 없이 글만 생성합니다")
        # 테스트 모드는 config 오류가 있어도 글 생성까지는 확인 가능
        run_once(keywords=keywords, dry_run=True)
        return

    if not _check_config():
        sys.exit(1)

    if args.once or keywords:
        run_once(keywords=keywords, dry_run=dry_run)
    else:
        run_scheduled()


if __name__ == "__main__":
    main()
