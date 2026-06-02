#!/usr/bin/env python3
"""구글 블로그 수익형 자동화 - 메인 실행 파일"""

import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import schedule

from config import POSTS_PER_RUN, TREND_COUNTRY, SCHEDULE_CRON, POST_STATUS
from trend_fetcher import get_trending_topics
from content_generator import generate_post
from blogger_uploader import upload_post

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("blog_automation.log", encoding="utf-8-sig"),
    ],
)
logger = logging.getLogger(__name__)

HISTORY_FILE = Path("posted_keywords.json")


def _load_history() -> set:
    if HISTORY_FILE.exists():
        return set(json.loads(HISTORY_FILE.read_text(encoding="utf-8")))
    return set()


def _save_history(history: set):
    HISTORY_FILE.write_text(json.dumps(list(history), ensure_ascii=False, indent=2), encoding="utf-8")


def run_pipeline():
    """트렌드 탐색 → 글 생성 → 업로드 파이프라인 실행."""
    logger.info("=" * 50)
    logger.info(f"자동 포스팅 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    history = _load_history()
    topics = get_trending_topics(country=TREND_COUNTRY, limit=POSTS_PER_RUN * 3)

    # 이미 사용한 키워드 제외
    new_topics = [t for t in topics if t["keyword"] not in history]
    if not new_topics:
        logger.info("새로운 트렌드 키워드가 없습니다. 히스토리를 초기화합니다.")
        history.clear()
        new_topics = topics

    posted = 0
    for topic in new_topics:
        if posted >= POSTS_PER_RUN:
            break

        keyword = topic["keyword"]
        traffic = topic["traffic"]

        post_data = generate_post(keyword, traffic)
        if not post_data:
            logger.warning(f"포스트 생성 실패, 다음 키워드로 이동: {keyword}")
            continue

        result = upload_post(post_data)
        if result:
            history.add(keyword)
            _save_history(history)
            posted += 1
            logger.info(f"✓ 업로드 완료 [{posted}/{POSTS_PER_RUN}]: {post_data['title']}")
            logger.info(f"  URL: {result.get('url', 'N/A')}")
        else:
            logger.error(f"업로드 실패: {keyword}")

        # API 레이트 리밋 방지
        if posted < POSTS_PER_RUN:
            time.sleep(3)

    logger.info(f"완료: {posted}개 포스트 업로드됨")
    logger.info("=" * 50)


def _parse_cron_to_schedule(cron: str):
    """간단한 cron 파싱 (분 시 * * * 형식만 지원)."""
    parts = cron.strip().split()
    if len(parts) < 2:
        return None
    minute, hour = parts[0], parts[1]
    if minute.isdigit() and hour.isdigit():
        return f"{hour.zfill(2)}:{minute.zfill(2)}"
    return None


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        # 즉시 한 번 실행
        run_pipeline()
        return

    schedule_times = ["08:00", "13:00", "18:00"]
    for t in schedule_times:
        schedule.every().day.at(t).do(run_pipeline)
    logger.info(f"스케줄러 시작: 매일 {', '.join(schedule_times)} 실행")

    # 시작 시 즉시 한 번 실행
    run_pipeline()

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
