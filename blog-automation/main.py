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
  python main.py --setup                                       # AdSense 필수 페이지 생성 (개인정보처리방침·소개)
"""

import argparse
import logging
import os
import re
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
    AUTO_SERIES,
    AUTO_SERIES_COUNT,
    AUTO_SERIES_MIN_DAYS,
    ADSENSE_VALIDATION,
    ADSENSE_MIN_SCORE,
    SOCIAL_AUTO_PUBLISH,
    get_blog_configs,
)
from content_generator import generate_post, generate_series_post
from adsense_validator import validate_adsense
from blogger_uploader import upload_post
from keyword_collector import get_trending_keywords, _migrate_used_keywords
from dashboard_exporter import log_run, export_dashboard, save_pending_posts
from post_manager import (
    register_post, update_post_status, save_draft, get_failed_posts,
    retry_failed_posts,
    Status as PostStatus, migrate_from_run_history,
)

# ── 실패 없는 흐름 보장 상수 ─────────────────────────────────────────────────────
MAX_ADSENSE_RETRY = 2   # AdSense 사전검증 불합격 시 콘텐츠 재생성 최대 횟수
MAX_UPLOAD_RETRY  = 3   # Blogger API 업로드 실패 시 재시도 최대 횟수
# ─────────────────────────────────────────────────────────────────────────────


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

def run_once(
    keywords: list[str] | None = None,
    dry_run: bool = False,
    review: bool = False,
    blog_config: dict | None = None,
) -> None:
    """키워드를 수집해 포스트를 생성하고 Blogger에 업로드합니다."""
    # 구버전 used_keywords.json 포맷 자동 마이그레이션
    _migrate_used_keywords()

    cfg = blog_config or {}
    blog_label = f"[{cfg.get('name', '기본')}] " if cfg.get("name") else ""
    language = cfg.get("language") or BLOG_LANGUAGE

    logger.info("=" * 60)
    logger.info(f"{blog_label}블로그 자동화 시작: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    # 키워드 수집 (자동 시리즈를 위해 여유분 +1개 더 수집)
    if not keywords:
        collect_count = POSTS_PER_RUN + (1 if AUTO_SERIES and not dry_run and not review else 0)
        keywords = get_trending_keywords(
            country=TREND_COUNTRY,
            language=language,
            count=collect_count,
            naver_client_id=os.getenv("NAVER_CLIENT_ID", ""),
            naver_client_secret=os.getenv("NAVER_CLIENT_SECRET", ""),
            blog_config=blog_config,
        )
        # 주간 학습 키워드를 트렌드 키워드 부족 시 보완
        if len(keywords) < collect_count:
            learned_kw_path = os.path.join(os.path.dirname(__file__), "logs", "learned_keywords.json")
            if os.path.exists(learned_kw_path):
                try:
                    import json as _json
                    with open(learned_kw_path, encoding="utf-8") as _f:
                        learned = _json.load(_f)
                    need = collect_count - len(keywords)
                    existing_set = set(keywords)
                    extras = [kw for kw in learned if kw not in existing_set][:need]
                    if extras:
                        keywords += extras
                        logger.info(f"학습 키워드 {len(extras)}개 보완: {extras}")
                except Exception as e:
                    logger.warning(f"학습 키워드 로드 실패: {e}")
    keywords = keywords[:POSTS_PER_RUN + 1]
    logger.info(f"수집된 키워드 {len(keywords)}개: {keywords}")

    # ── 자동 시리즈 체크 ─────────────────────────────────────────
    # 조건: AUTO_SERIES=true + live 모드 + 마지막 시리즈로부터 MIN_DAYS 경과
    auto_series_keyword: str | None = None
    auto_series_plan: dict | None = None   # 드라마 기획 시 미리 생성된 플랜

    if AUTO_SERIES and not dry_run and not review:
        from series_planner import get_last_series_date, pick_series_keyword, plan_drama_series
        from keyword_collector import _naver_drama_news, extract_drama_titles

        last_date = get_last_series_date()
        days_elapsed = (datetime.now() - last_date).days if last_date else AUTO_SERIES_MIN_DAYS + 1

        if days_elapsed >= AUTO_SERIES_MIN_DAYS:
            logger.info(
                f"자동 시리즈 조건 충족 "
                f"(마지막 시리즈: {'없음' if not last_date else f'{days_elapsed}일 전'})"
            )

            # ① 인기 드라마 탐지 — 트렌드 키워드보다 우선
            drama_headlines = _naver_drama_news(
                os.getenv("NAVER_CLIENT_ID", ""),
                os.getenv("NAVER_CLIENT_SECRET", ""),
            )
            drama_titles = extract_drama_titles(drama_headlines)

            if drama_titles:
                drama_name = drama_titles[0]
                logger.info(f"[자동 드라마 시리즈] '{drama_name}' 감지 — 리뷰 시리즈 기획 시작")
                auto_series_plan = plan_drama_series(drama_name, AUTO_SERIES_COUNT)
                if auto_series_plan:
                    auto_series_keyword = drama_name
                else:
                    logger.warning("드라마 시리즈 기획 실패 — 일반 트렌드 시리즈로 폴백")

            # ② 드라마 없음 또는 기획 실패 → 일반 트렌드 키워드 중 시리즈 선정
            if not auto_series_keyword:
                auto_series_keyword = pick_series_keyword(keywords)

        else:
            logger.info(
                f"자동 시리즈 대기 중 "
                f"(마지막 시리즈 {days_elapsed}일 전, {AUTO_SERIES_MIN_DAYS - days_elapsed}일 후 활성화)"
            )

    # 시리즈 키워드를 단독 목록에서 제거하고 먼저 시리즈 실행
    if auto_series_keyword:
        remaining = [kw for kw in keywords if kw != auto_series_keyword][:POSTS_PER_RUN - 1]
        logger.info(
            f"[자동 시리즈] '{auto_series_keyword}' {AUTO_SERIES_COUNT}편 기획 시작 "
            f"(이후 단독 포스트 {len(remaining)}개)"
        )
        run_series(auto_series_keyword, AUTO_SERIES_COUNT, series_plan=auto_series_plan, blog_config=blog_config)
        keywords = remaining
    else:
        keywords = keywords[:POSTS_PER_RUN]
    # ─────────────────────────────────────────────────────────────

    logger.info(f"단독 포스트 대상 키워드 {len(keywords)}개: {keywords}")

    success_count = 0
    blogger_count = 0
    fail_count = 0
    completed_posts: list[dict] = []
    error_messages: list[str] = []

    # run_history → post_registry 마이그레이션 (최초 1회)
    try:
        from dashboard_exporter import _load_history as _lh
        _hist = _lh()
        if _hist:
            migrate_from_run_history(_hist)
    except Exception:
        pass

    _run_number = int(os.getenv("GITHUB_RUN_NUMBER", "0"))
    _source     = "manual" if (dry_run or review) else "auto"

    for i, keyword in enumerate(keywords, 1):
        logger.info(f"\n[{i}/{len(keywords)}] 키워드: '{keyword}'")

        # ── ① 콘텐츠 생성 + AdSense 사전 검증 (최대 MAX_ADSENSE_RETRY회) ─────────────
        # 목표: harmful_content 또는 심각한 품질 문제 조기 감지 → 재생성
        post_data = None
        for gen_attempt in range(1, MAX_ADSENSE_RETRY + 1):
            _post = generate_post(keyword, blog_config=cfg)
            if not _post:
                logger.warning(f"  콘텐츠 생성 실패 (시도 {gen_attempt}/{MAX_ADSENSE_RETRY})")
                if gen_attempt < MAX_ADSENSE_RETRY:
                    time.sleep(3)
                    continue
                break  # 전체 실패 → post_data=None

            # AdSense 사전 검증: 유해 콘텐츠 또는 점수 < 55이면 재생성
            if ADSENSE_VALIDATION:
                _pre = validate_adsense(_post)
                if _pre["recommendation"] == "reject" and gen_attempt < MAX_ADSENSE_RETRY:
                    logger.warning(
                        f"  ⚠️ 사전 검증 불합격 (점수: {_pre['score']}/100, "
                        f"이유: {_pre.get('issues', [])[:1]}) — "
                        f"재생성 {gen_attempt+1}/{MAX_ADSENSE_RETRY}"
                    )
                    time.sleep(3)
                    continue

            post_data = _post
            break

        if not post_data:
            msg = f"콘텐츠 생성 최종 실패 ({MAX_ADSENSE_RETRY}회 시도): '{keyword}'"
            logger.error(f"  ❌ {msg}")
            fail_count += 1
            error_messages.append(msg)
            continue
        # ─────────────────────────────────────────────────────────────────────────────

        # ── ② 내부 링크 삽입 (SEO — non-blocking) ───────────────────────────────────
        try:
            from internal_linker import insert_internal_links
            post_data["content"] = insert_internal_links(post_data)
        except Exception as _ile:
            logger.debug(f"내부 링크 삽입 건너뜀: {_ile}")

        title = post_data.get("title", "?")
        images = post_data.get("images_inserted", 0)
        word_count = post_data.get("word_count", 0)
        logger.info(f"  제목: {title}")
        logger.info(f"  이미지: {images}개 삽입")
        logger.info(f"  글자 수: {word_count}자")

        # 4000자 미달 → pending 저장 (thin content 업로드 방지)
        if not (dry_run or review) and word_count < 4000:
            msg = f"글자 수 미달 — pending 저장: '{title}' ({word_count}자 < 4000자)"
            logger.warning(f"  ⚠️ {msg}")
            post_data["status"] = "pending"
            _pid = register_post(post_data, PostStatus.PENDING, blog_config, source=_source, run_number=_run_number)
            save_draft(_pid, post_data)
            save_pending_posts([post_data], blog_config)
            completed_posts.append(post_data)
            success_count += 1
            continue

        if dry_run or review:
            mode_label = "검토 모드" if review else "테스트 모드"
            logger.info(f"  [{mode_label}] 업로드 건너뜀")
            register_post(post_data, PostStatus.PENDING, blog_config, source=_source, run_number=_run_number)
            completed_posts.append(post_data)
            success_count += 1
            continue

        # ── ③ AdSense 최종 검증 ──────────────────────────────────────────────────────
        # 정책: harmful_content → reject(skip) / 65-79(review) → pending 저장 / 80+ → 업로드
        if ADSENSE_VALIDATION:
            validation = validate_adsense(post_data)
            post_data["adsense_score"] = validation["score"]
            post_data["adsense_recommendation"] = validation["recommendation"]

            if validation["recommendation"] == "reject":
                # harmful_content fail = 유해 콘텐츠 → 업로드 불가
                msg = (
                    f"AdSense 유해 콘텐츠 감지 — 업로드 취소: '{title}' "
                    f"(점수: {validation['score']}/100)"
                )
                logger.error(f"  ❌ {msg}")
                for issue in validation.get("issues", []):
                    logger.error(f"     🔴 {issue}")
                register_post(post_data, PostStatus.SKIPPED, blog_config, source=_source, run_number=_run_number)
                fail_count += 1
                error_messages.append(msg)
                continue

            # review(65-79) 또는 ADSENSE_MIN_SCORE(80) 미달 → pending 저장, 업로드 건너뜀
            if validation["recommendation"] == "review" or validation["score"] < ADSENSE_MIN_SCORE:
                msg = (
                    f"AdSense 기준 미달 — pending 저장: '{title}' "
                    f"(점수: {validation['score']}/100, 권장: {validation['recommendation']})"
                )
                logger.warning(f"  ⚠️ {msg}")
                for issue in validation.get("issues", []):
                    logger.warning(f"     🟡 {issue}")
                post_data["status"] = "pending"
                _pid = register_post(post_data, PostStatus.PENDING, blog_config, source=_source, run_number=_run_number)
                save_draft(_pid, post_data)
                save_pending_posts([post_data], blog_config)
                completed_posts.append(post_data)
                success_count += 1
                continue

            logger.info(f"  ✅ AdSense 검증 통과 (점수: {validation['score']}/100) — 업로드")
        # ─────────────────────────────────────────────────────────────────────────────

        # ── ④ 레지스트리 등록 (pending) + 초안 저장 ─────────────────────────────────
        _post_id = register_post(post_data, PostStatus.PENDING, blog_config, source=_source, run_number=_run_number)
        save_draft(_post_id, post_data)

        # ── ⑤ Blogger 업로드 (최대 MAX_UPLOAD_RETRY회 재시도) ───────────────────────
        result = None
        for upload_try in range(1, MAX_UPLOAD_RETRY + 1):
            result = upload_post(post_data, blog_config)
            if result:
                break
            if upload_try < MAX_UPLOAD_RETRY:
                _wait = 5 * upload_try
                logger.warning(
                    f"  업로드 실패 — {_wait}s 대기 후 재시도 "
                    f"({upload_try}/{MAX_UPLOAD_RETRY})"
                )
                time.sleep(_wait)

        if result:
            url = result.get("url", "")
            post_data["blogUrl"] = url
            update_post_status(_post_id, PostStatus.PUBLISHED, blog_url=url)
            logger.info(f"  ✅ 업로드 성공: {url}")

            # ── ⑥ 소셜 미디어 콘텐츠 생성 (완전 non-blocking) ──────────────────────
            try:
                from social_publisher import publish_all, generate_social_content
                if SOCIAL_AUTO_PUBLISH:
                    _img_m = re.search(r'<img[^>]+src="([^"]+)"', post_data.get("content", ""))
                    social_result = publish_all(
                        post_data, blog_url=url,
                        image_url=_img_m.group(1) if _img_m else None,
                    )
                else:
                    social_content = generate_social_content(post_data, blog_url=url)
                    _skip = {"skipped": True, "reason": "SOCIAL_AUTO_PUBLISH=false"}
                    social_result = {
                        "socialContent": social_content,
                        "instagram": _skip, "threads": _skip, "tiktok": _skip,
                    }
                    logger.info(f"  📱 소셜 콘텐츠 생성 완료")
                post_data["socialContent"]    = social_result.get("socialContent")
                post_data["social_instagram"] = social_result.get("instagram")
                post_data["social_threads"]   = social_result.get("threads")
                post_data["social_tiktok"]    = social_result.get("tiktok")
            except Exception as _se:
                logger.warning(f"  ⚠️ 소셜 콘텐츠 생성 실패 (무시): {_se}")

            completed_posts.append(post_data)
            success_count += 1
            blogger_count += 1
        else:
            msg = f"Blogger 업로드 최종 실패 ({MAX_UPLOAD_RETRY}회 시도): '{title}'"
            update_post_status(_post_id, PostStatus.FAILED, error=msg)
            logger.error(f"  ❌ {msg}")
            fail_count += 1
            error_messages.append(msg)

        # API 과부하 방지 (포스트 사이 2초 대기)
        if i < len(keywords):
            time.sleep(2)

    logger.info("\n" + "=" * 60)
    logger.info(f"{blog_label}완료: 성공 {success_count}개 / 실패 {fail_count}개")
    logger.info("=" * 60)

    # 대시보드 데이터 업데이트
    try:
        if review and completed_posts:
            save_pending_posts(completed_posts, blog_config)
            logger.info("검토 대기 포스트 저장 완료")
        log_run(
            keywords=keywords,
            results=completed_posts,
            blogger_uploaded=blogger_count if not (dry_run or review) else 0,
            errors=fail_count,
            blog_config=blog_config,
            error_messages=error_messages,
        )
        export_dashboard()
        logger.info("대시보드 데이터 업데이트 완료")
    except Exception as e:
        logger.warning(f"대시보드 업데이트 실패 (무시): {e}")


# ──────────────────────────────────────────────────────────────────────────────
# 시리즈 모드
# ──────────────────────────────────────────────────────────────────────────────

def run_series(
    keyword: str,
    count: int = 4,
    dry_run: bool = False,
    review: bool = False,
    series_plan: dict | None = None,  # 기획이 이미 완료된 경우 바로 전달
    blog_config: dict | None = None,
) -> None:
    """시리즈 포스트를 순서대로 기획·생성·게시합니다."""
    from series_planner import plan_series, build_series_nav, save_series

    cfg = blog_config or {}
    blog_label = f"[{cfg.get('name', '기본')}] " if cfg.get("name") else ""

    logger.info("=" * 60)
    logger.info(f"{blog_label}시리즈 모드 시작: '{keyword}' {count}편")
    logger.info("=" * 60)

    if series_plan is None:
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

    for ep_idx, ep in enumerate(episodes):
        ep_num = ep["episode"]
        ep_keyword = ep.get("search_keyword", keyword)

        logger.info(f"\n--- [{ep_num}/{len(episodes)}편] '{ep_keyword}' 생성 중 ---")

        series_context = {
            **series_plan,
            "episode": ep_num,
            "focus": ep.get("focus", ""),
            "title": ep.get("title", ""),
        }

        post_data = generate_series_post(ep_keyword, "N/A", series_context, blog_config=blog_config)
        if not post_data:
            logger.error(f"편 {ep_num} 생성 실패 — 건너뜀")
            ep["status"] = "failed"
            save_series(series_plan)
            continue

        ep["status"] = "generated"
        nav_html = build_series_nav(series_plan, ep_num, blog_url=cfg.get("url", ""))
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

        # 4000자 미달 → pending 저장 (thin content 업로드 방지)
        series_wc = post_data.get("word_count", 0)
        if series_wc < 4000:
            logger.warning(f"  ⚠️ [편 {ep_num}] 글자 수 미달 ({series_wc}자 < 4000자) — pending 저장")
            post_data["status"] = "pending"
            pending_list.append(post_data)
            ep["status"] = "pending_review"
            generated_posts.append(post_data)
            save_series(series_plan)
            continue

        # AdSense 정책 검증
        if ADSENSE_VALIDATION:
            validation = validate_adsense(post_data)
            post_data["adsense_score"] = validation["score"]
            post_data["adsense_recommendation"] = validation["recommendation"]
            if validation["recommendation"] == "reject":
                logger.error(
                    f"  ❌ [편 {ep_num}] AdSense 정책 위반 — 업로드 취소 (점수: {validation['score']}/100)"
                )
                for issue in validation["issues"]:
                    logger.error(f"     🔴 {issue}")
                ep["status"] = "rejected_policy"
                save_series(series_plan)
                continue
            if validation["recommendation"] == "review" or validation["score"] < ADSENSE_MIN_SCORE:
                logger.warning(
                    f"  ⚠️ [편 {ep_num}] AdSense 검토 필요 — pending 저장 (점수: {validation['score']}/100)"
                )
                post_data["status"] = "pending"
                pending_list.append(post_data)
                ep["status"] = "pending_review"
                generated_posts.append(post_data)
                save_series(series_plan)
                continue

        result = upload_post(post_data, blog_config)
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

        if ep_idx < len(episodes) - 1:
            time.sleep(3)

    all_done = all(ep.get("status") in ("done", "pending_review") for ep in episodes)
    series_plan["status"] = "completed" if all_done else "partial"
    save_series(series_plan)

    uploaded = sum(1 for ep in episodes if ep.get("status") == "done")
    errors = sum(1 for ep in episodes if ep.get("status") in ("failed", "upload_failed"))
    series_error_messages = [
        f"시리즈 편 {ep['episode']} 생성 실패: {ep.get('title', '')}"
        for ep in episodes if ep.get("status") == "failed"
    ] + [
        f"시리즈 편 {ep['episode']} Blogger 업로드 실패: {ep.get('title', '')}"
        for ep in episodes if ep.get("status") == "upload_failed"
    ]

    try:
        if pending_list:
            save_pending_posts(pending_list, blog_config)
        if generated_posts:
            log_run(
                keywords=[keyword],
                results=generated_posts,
                blogger_uploaded=uploaded if not (dry_run or review) else 0,
                errors=errors,
                blog_config=blog_config,
                error_messages=series_error_messages,
            )
            export_dashboard()
            logger.info("대시보드 데이터 업데이트 완료")
    except Exception as e:
        logger.warning(f"대시보드 업데이트 실패 (무시): {e}")

    logger.info("\n" + "=" * 60)
    logger.info(f"{blog_label}시리즈 완료: {uploaded}/{len(episodes)}편 성공")
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
    def _run_all_blogs() -> None:
        for blog_cfg in get_blog_configs():
            run_once(blog_config=blog_cfg)

    schedule.every().day.at(time_str).do(_run_all_blogs)
    logger.info(f"스케줄 등록: 매일 {time_str} 전체 블로그 실행 (cron: {SCHEDULE_CRON})")
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
    parser.add_argument("--setup", action="store_true", help="AdSense 심사 필수 페이지 생성 (개인정보처리방침·블로그 소개)")
    parser.add_argument("--blog", type=str, default="", metavar="BLOG_ID",
                        help="특정 블로그 ID만 실행 (BLOGS_CONFIG의 id 값; 기본값: 모든 블로그)")
    parser.add_argument("--weekly-check", action="store_true",
                        help="주간 시스템 점검 및 학습 실행 (weekly_learning.py)")
    parser.add_argument("--auto-repair", action="store_true",
                        help="자동 진단·수리 실행 (auto_repair.py)")
    parser.add_argument("--dry", action="store_true",
                        help="--auto-repair 와 함께 사용: 진단만 하고 실제 수리는 하지 않음")
    parser.add_argument("--retry", action="store_true",
                        help="실패한 포스트 재시도 (post_registry의 failed/retry_queued 상태 포스트)")
    parser.add_argument("--retry-max", type=int, default=10, metavar="N",
                        help="한 번에 재시도할 최대 포스트 수 (기본값: 10)")
    parser.add_argument("--retry-age", type=int, default=7, metavar="DAYS",
                        help="재시도 대상 포스트 최대 보존 일수 (기본값: 7일)")
    args = parser.parse_args()

    keywords = None
    if args.keyword:
        keywords = [k.strip() for k in args.keyword.split(",") if k.strip()]

    if args.interactive:
        keywords = _prompt_keywords(keywords)

    if args.weekly_check:
        logger.info("=== 주간 학습 및 시스템 점검 모드 ===")
        from weekly_learning import run_weekly_check
        report = run_weekly_check()
        health = report["analysis"].get("health_score")
        issues = report.get("issues", [])
        logger.info(f"점검 완료 | 건강점수: {health} | 이슈: {len(issues)}건")
        return

    if args.retry:
        logger.info("=== 실패 포스트 재시도 모드 ===")
        all_blogs = get_blog_configs()
        if args.blog:
            target_blogs = [b for b in all_blogs if b.get("id") == args.blog] or all_blogs
        else:
            target_blogs = all_blogs
        if not _check_config():
            sys.exit(1)
        total = {"success": 0, "failed": 0, "skipped": 0}
        for blog_cfg in target_blogs:
            blog_label = f"[{blog_cfg.get('name', blog_cfg.get('id', ''))}] "
            logger.info(f"{blog_label}실패 포스트 재시도 시작")
            counts = retry_failed_posts(
                blog_config=blog_cfg,
                max_posts=args.retry_max,
                max_age_days=args.retry_age,
            )
            for k in total:
                total[k] += counts.get(k, 0)
        logger.info(
            f"전체 재시도 완료 — 성공: {total['success']} / 실패: {total['failed']} / 건너뜀: {total['skipped']}"
        )
        try:
            export_dashboard()
        except Exception as _e:
            logger.warning(f"대시보드 업데이트 실패 (무시): {_e}")
        return

    if args.auto_repair:
        dry = getattr(args, "dry", False)
        logger.info(f"=== 자동 수리 모드{'(dry-run)' if dry else ''} ===")
        from auto_repair import run_auto_repair
        report = run_auto_repair(dry_run=dry)
        logger.info(
            f"수리 완료 | 건강점수: {report['health_score']}/100 | "
            f"이슈: {report['issues_found']}개 | 수리: {report['repairs_applied']}개"
        )
        return

    if args.setup:
        logger.info("=== AdSense 셋업 모드: 필수 페이지 생성 + 자동 광고 테마 주입 ===")
        from page_creator import create_required_pages
        from blogger_uploader import inject_adsense_to_theme

        setup_blogs = get_blog_configs()
        if args.blog:
            filtered = [b for b in setup_blogs if b.get("id") == args.blog]
            setup_blogs = filtered if filtered else setup_blogs

        if not setup_blogs:
            logger.error("BLOGS_CONFIG에 블로그가 없습니다 — .env 또는 GitHub Secrets 확인")
            sys.exit(1)

        for blog_cfg in setup_blogs:
            blog_name = blog_cfg.get("name") or blog_cfg.get("id", "")
            logger.info(f"\n── {blog_name} 필수 페이지 생성 ──")
            # 블로그별 맞춤 페이지 생성 (theme 자동 감지)
            results = create_required_pages(blog_cfg)
            for page_key, url in results.items():
                if url:
                    logger.info(f"  ✅ {page_key}: {url}")
                else:
                    logger.error(f"  ❌ {page_key}: 생성 실패")
            # AdSense 자동 광고 스크립트를 블로그 테마에 주입
            logger.info(f"  AdSense 자동 광고 테마 주입 시도: {blog_name}")
            ok = inject_adsense_to_theme(blog_cfg)
            if ok:
                logger.info(f"  ✅ AdSense 자동 광고 활성화: {blog_name}")
            else:
                logger.warning(f"  ⚠️ 테마 주입 실패 — Blogger 관리자에서 수동으로 AdSense 연결 필요: {blog_name}")
        return

    # 블로그 목록 결정
    all_blogs = get_blog_configs()
    if args.blog:
        target_blogs = [b for b in all_blogs if b.get("id") == args.blog]
        if not target_blogs:
            logger.warning(f"블로그 ID '{args.blog}'를 BLOGS_CONFIG에서 찾을 수 없습니다.")
            logger.warning(f"사용 가능한 블로그: {[b.get('id') for b in all_blogs]} — 전체 블로그로 실행합니다.")
            target_blogs = all_blogs
    else:
        target_blogs = all_blogs

    if len(target_blogs) > 1:
        logger.info(f"다중 블로그 모드: {len(target_blogs)}개 블로그 순차 실행")
        for b in target_blogs:
            logger.info(f"  - [{b.get('id')}] {b.get('name', '')}")

    if args.series:
        if not keywords:
            logger.error("시리즈 모드는 --keyword 가 필수입니다 (예: --series --keyword '재테크 완전정복')")
            sys.exit(1)
        series_kw = keywords[0]
        series_count = max(2, min(getattr(args, "series_count", 4), 5))
        skip_blogger = args.test or args.review
        if not _check_config(skip_blogger=skip_blogger):
            sys.exit(1)
        for blog_cfg in target_blogs:
            if args.test:
                logger.info(f"[시리즈 테스트] '{series_kw}' {series_count}편 — 업로드 없이 생성만")
                run_series(series_kw, series_count, dry_run=True, blog_config=blog_cfg)
            elif args.review:
                logger.info(f"[시리즈 검토] '{series_kw}' {series_count}편 — pending에 저장")
                run_series(series_kw, series_count, review=True, blog_config=blog_cfg)
            else:
                run_series(series_kw, series_count, blog_config=blog_cfg)
        return

    if not _check_config(skip_blogger=(args.test or args.review)):
        sys.exit(1)

    if args.test:
        logger.info("테스트 모드 — 업로드 없이 글만 생성합니다")
        for blog_cfg in target_blogs:
            run_once(keywords=keywords, dry_run=True, blog_config=blog_cfg)
        return

    if args.review:
        logger.info("검토 모드 — pending_posts.json에 저장합니다")
        for blog_cfg in target_blogs:
            run_once(keywords=keywords, review=True, blog_config=blog_cfg)
        return

    if args.once or args.interactive or keywords:
        for blog_cfg in target_blogs:
            run_once(keywords=keywords, blog_config=blog_cfg)
    else:
        run_scheduled()


if __name__ == "__main__":
    main()

