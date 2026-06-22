#!/usr/bin/env python3
"""
블로그 자동화 시스템 — 메인 실행 파일

사용법:
  python main.py                                              # 스케줄 모드
  python main.py --once                                       # 즉시 1회 실행
  python main.py --test                                       # 글 생성만 (업로드 없음)
  python main.py --keyword "재테크" --once                    # 특정 키워드로 1회 실행
  python main.py --interactive                                # 키워드 직접 입력 후 실행
  python main.py --series --keyword "재테크 완전정복"         # 시리즈 4편 자동 기획·생성·게시
  python main.py --series --series-count 3 --keyword "ETF"   # 시리즈 3편 실행
  python main.py --series --keyword "재테크" --test           # 시리즈 테스트 (업로드 없음)
  python main.py --series --keyword "재테크" --review         # 시리즈 검토 모드
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
_log_dir = os.path.dirname(_log_file)
if _log_dir:
    os.makedirs(_log_dir, exist_ok=True)

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
    BLOGGER_CLIENT_SECRET,
    BLOGGER_BLOG_ID,
    BLOGGER_REFRESH_TOKEN,
    BLOG_LANGUAGE,
    POSTS_PER_RUN,
    TREND_COUNTRY,
    SCHEDULE_CRON,
)
from content_generator import generate_post, generate_series_post
from blogger_uploader import upload_post
from keyword_collector import get_trending_keywords, _migrate_used_keywords
from dashboard_exporter import log_run, export_dashboard, save_pending_posts


# ──────────────────────────────────────────────────────────────────────────────
# 사전 점검
# ──────────────────────────────────────────────────────────────────────────────

def _check_config(skip_blogger: bool = False) -> bool:
    """필수 환경 변수가 모두 설정됐는지 확인합니다.
    skip_blogger=True 이면 Blogger OAuth 키 검사를 생략합니다 (test/review 모드).
    """
    errors = []
    if not ANTHROPIC_API_KEY.strip() or ANTHROPIC_API_KEY.startswith("sk-ant-xxx"):
        errors.append("ANTHROPIC_API_KEY")
    if not skip_blogger:
        if not BLOGGER_CLIENT_ID.strip() or BLOGGER_CLIENT_ID.startswith("your_"):
            errors.append("GOOGLE_CLIENT_ID")
        if not BLOGGER_CLIENT_SECRET.strip() or BLOGGER_CLIENT_SECRET.startswith("your_"):
            errors.append("GOOGLE_CLIENT_SECRET")
        if not BLOGGER_BLOG_ID.strip() or BLOGGER_BLOG_ID.startswith("your_"):
            errors.append("BLOGGER_BLOG_ID")
        if not BLOGGER_REFRESH_TOKEN.strip() or BLOGGER_REFRESH_TOKEN.startswith("your_"):
            errors.append("GOOGLE_REFRESH_TOKEN")

    if errors:
        for e in errors:
            logger.error(f"⚠️  설정 누락: {e} (.env 또는 GitHub Secrets 확인)")
        return False
    return True


# ──────────────────────────────────────────────────────────────────────────────
# 단일 실행
# ──────────────────────────────────────────────────────────────────────────────

def run_once(keywords: list[str] | None = None, dry_run: bool = False, review: bool = False) -> None:
    """키워드를 수집해 포스트를 생성하고 Blogger에 업로드합니다."""
    # 구버전 used_keywords.json 포맷 자동 마이그레이션
    _migrate_used_keywords()

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
    completed_posts: list[dict] = []

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

        if dry_run or review:
            mode_label = "검토 모드" if review else "테스트 모드"
            logger.info(f"  [{mode_label}] 업로드 건너뜀")
            completed_posts.append(post_data)
            success_count += 1
            continue

        # Blogger 업로드
        result = upload_post(post_data)
        if result:
            url = result.get("url", "")
            post_data["blogUrl"] = url
            logger.info(f"  ✅ 업로드 성공: {url}")
            completed_posts.append(post_data)
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

    # 대시보드 데이터 업데이트
    try:
        if review and completed_posts:
            save_pending_posts(completed_posts)
            logger.info("검토 대기 포스트 저장 완료")
        log_run(
            keywords=keywords,
            results=completed_posts,
            blogger_uploaded=success_count if not (dry_run or review) else 0,
            errors=fail_count,
        )
        export_dashboard()
        logger.info("대시보드 데이터 업데이트 완료")
    except Exception as e:
        logger.warning(f"대시보드 업데이트 실패 (무시): {e}")


# ──────────────────────────────────────────────────────────────────────────────
# 시리즈 모드
# ──────────────────────────────────────────────────────────────────────────────

def run_series(keyword: str, count: int = 4, dry_run: bool = False, review: bool = False) -> None:
    """시리즈 포스트를 순서대로 기획·생성·게시합니다."""
    from series_planner import plan_series, build_series_nav, save_series

    logger.info("=" * 60)
    logger.info(f"시리즈 모드 시작: '{keyword}' {count}편")
    logger.info("=" * 60)

    series_plan = plan_series(keyword, count)
    if not series_plan:
        logger.error("시리즈 기획 실패 — 종료")
        return
    save_series(series_plan)
    logger.info(f"시리즈 기획 완료: '{series_plan.get('series_title')}'")
    for ep in series_plan.get("episodes", []):
        logger.info(f"  편 {ep['episode']}: {ep.get('title', '')}")

    generated_posts: list[dict] = []
    pending_list: list[dict] = []
    episodes = series_plan.get("episodes", [])

    for ep in episodes:
        ep_num = ep["episode"]
        ep_keyword = ep.get("search_keyword", keyword)

        logger.info(f"\n--- [{ep_num}/{len(episodes)}편] '{ep_keyword}' 생성 중 ---")

        series_context = {
            **series_plan,
            "episode": ep_num,
            "focus": ep.get("focus", ""),
            "title": ep.get("title", ""),
        }

        post_data = generate_series_post(ep_keyword, "N/A", series_context)
        if not post_data:
            logger.error(f"편 {ep_num} 생성 실패 — 건너뜀")
            ep["status"] = "failed"
            save_series(series_plan)
            continue

        ep["status"] = "generated"
        nav_html = build_series_nav(series_plan, ep_num)
        post_data["series_nav"] = nav_html
        post_data["series_label"] = series_plan.get("series_label", "")

        if dry_run:
            logger.info(f"[테스트] 편 {ep_num}: '{post_data.get('title','?')}' ({post_data.get('word_count',0)}자)")
            ep["status"] = "done"
            generated_posts.append(post_data)
            save_series(series_plan)
            continue

        if review:
            post_data["status"] = "pending"
            pending_list.append(post_data)
            ep["status"] = "pending_review"
            generated_posts.append(post_data)
            save_series(series_plan)
            continue

        result = upload_post(post_data)
        if result:
            blogger_url = result.get("url", "")
            ep["status"] = "done"
            ep["blogger_url"] = blogger_url
            ep["post_id"] = result.get("id", "")
            post_data["blogUrl"] = blogger_url
            logger.info(f"  ✅ 편 {ep_num} 업로드 완료: {blogger_url}")
        else:
            ep["status"] = "upload_failed"
            logger.error(f"  ❌ 편 {ep_num} 업로드 실패")

        generated_posts.append(post_data)
        save_series(series_plan)

        if ep_num < len(episodes):
            time.sleep(3)

    all_done = all(ep.get("status") in ("done", "pending_review") for ep in episodes)
    series_plan["status"] = "completed" if all_done else "partial"
    save_series(series_plan)

    uploaded = sum(1 for ep in episodes if ep.get("status") == "done")
    errors = sum(1 for ep in episodes if ep.get("status") in ("failed", "upload_failed"))

    try:
        if pending_list:
            save_pending_posts(pending_list)
        if generated_posts:
            log_run(
                keywords=[keyword],
                results=generated_posts,
                blogger_uploaded=uploaded if not (dry_run or review) else 0,
                errors=errors,
            )
            export_dashboard()
            logger.info("대시보드 데이터 업데이트 완료")
    except Exception as e:
        logger.warning(f"대시보드 업데이트 실패 (무시): {e}")

    logger.info("\n" + "=" * 60)
    logger.info(f"시리즈 완료: {uploaded}/{len(episodes)}편 성공")
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

    try:
        minute, hour = int(parts[0]), int(parts[1])
        time_str = f"{hour:02d}:{minute:02d}"
    except (ValueError, IndexError):
        logger.error(f"잘못된 SCHEDULE_CRON 형식: '{SCHEDULE_CRON}'")
        sys.exit(1)
    schedule.every().day.at(time_str).do(run_once)
    logger.info(f"스케줄 등록: 매일 {time_str} 실행 (cron: {SCHEDULE_CRON})")
    logger.info("Ctrl+C로 종료")

    while True:
        schedule.run_pending()
        time.sleep(30)


# ──────────────────────────────────────────────────────────────────────────────
# 인터랙티브 키워드 입력
# ──────────────────────────────────────────────────────────────────────────────

def _prompt_keywords(preset: list[str] | None = None) -> list[str] | None:
    """
    키워드를 대화형으로 입력받습니다.
    - preset 이 있으면 미리 표시하고 수정 여부를 묻습니다.
    - 빈 입력 시 트렌드 자동 수집으로 진행합니다.
    """
    print("\n" + "=" * 60)
    print("  블로그 자동화 — 키워드 직접 입력")
    print("=" * 60)

    if preset:
        print(f"  현재 키워드: {', '.join(preset)}")
        ans = input("  이대로 사용하시겠습니까? [Y/n] ").strip().lower()
        if ans in ("", "y", "yes"):
            print("=" * 60 + "\n")
            return preset

    print("  여러 키워드는 쉼표(,)로 구분하세요.")
    print("  예) 2026년 ETF 투자 전략, AI 업무 자동화, 건강보험 환급금")
    print("  (비워두면 트렌드 자동 수집)")
    raw = input("\n  키워드 입력: ").strip()
    print("=" * 60 + "\n")

    if not raw:
        logger.info("키워드 미입력 — 트렌드 자동 수집으로 진행")
        return None

    keywords = [k.strip() for k in raw.split(",") if k.strip()]
    if not keywords:
        logger.info("유효한 키워드 없음 — 트렌드 자동 수집으로 진행")
        return None

    logger.info(f"수동 입력 키워드 {len(keywords)}개: {keywords}")
    return keywords


# ──────────────────────────────────────────────────────────────────────────────
# 진입점
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="블로그 자동화 시스템")
    parser.add_argument("--once", action="store_true", help="즉시 1회 실행")
    parser.add_argument("--test", action="store_true", help="글 생성만 (업로드 없음)")
    parser.add_argument("--review", action="store_true", help="검토 모드 — 글 생성 후 pending_posts.json에 저장 (업로드 없음)")
    parser.add_argument("--keyword", type=str, help="특정 키워드로 실행 (쉼표로 복수 지정)")
    parser.add_argument("--interactive", "-i", action="store_true", help="키워드 직접 입력 후 즉시 실행")
    parser.add_argument("--series", action="store_true", help="시리즈 모드 — 주제를 N편으로 분할 기획·생성·게시 (--keyword 필수)")
    parser.add_argument("--series-count", type=int, default=4, metavar="N", help="시리즈 편수 (2~5, 기본값 4)")
    args = parser.parse_args()

    keywords = None
    if args.keyword:
        keywords = [k.strip() for k in args.keyword.split(",") if k.strip()]

    if args.interactive:
        keywords = _prompt_keywords(keywords)

    if args.series:
        if not keywords:
            logger.error("시리즈 모드는 --keyword 가 필수입니다 (예: --series --keyword '재테크 완전정복')")
            sys.exit(1)
        series_kw = keywords[0]
        series_count = max(2, min(getattr(args, "series_count", 4), 5))
        skip_blogger = args.test or args.review
        if not _check_config(skip_blogger=skip_blogger):
            sys.exit(1)
        if not skip_blogger and not _check_config():
            sys.exit(1)
        if args.test:
            logger.info(f"[시리즈 테스트] '{series_kw}' {series_count}편 — 업로드 없이 생성만")
            run_series(series_kw, series_count, dry_run=True)
        elif args.review:
            logger.info(f"[시리즈 검토] '{series_kw}' {series_count}편 — pending에 저장")
            run_series(series_kw, series_count, review=True)
        else:
            run_series(series_kw, series_count)
        return

    if not _check_config(skip_blogger=(args.test or args.review)):
        sys.exit(1)

    if args.test:
        logger.info("테스트 모드 — 업로드 없이 글만 생성합니다")
        run_once(keywords=keywords, dry_run=True)
        return

    if args.review:
        logger.info("검토 모드 — pending_posts.json에 저장합니다")
        run_once(keywords=keywords, review=True)
        return

    if not _check_config():
        sys.exit(1)

    if args.once or args.interactive or keywords:
        run_once(keywords=keywords)
    else:
        run_scheduled()


if __name__ == "__main__":
    main()
