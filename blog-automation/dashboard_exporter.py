"""
대시보드 데이터 내보내기 모듈
- 실행 이력을 logs/run_history.json에 누적 저장
- docs/data/ 폴더로 대시보드용 JSON 파일 내보내기
"""

import json
import logging
import os
import re
from datetime import datetime

logger = logging.getLogger(__name__)

HISTORY_FILE = os.path.join(os.path.dirname(__file__), "logs", "run_history.json")
DOCS_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "data")
PENDING_FILE = os.path.join(os.path.dirname(__file__), "..", "docs", "data", "pending_posts.json")


def _load_history() -> list[dict]:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_history(history: list[dict]) -> None:
    try:
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error(f"히스토리 저장 실패: {e}")


def _estimate_earnings(post_count: int, avg_cpc: float = 0.9) -> dict:
    """AdSense 수익 추정 (CTR 2.5%, 포스트당 80 페이지뷰/일 기준)."""
    daily_views = post_count * 80
    daily_clicks = daily_views * 0.025
    daily_rev = daily_clicks * avg_cpc
    return {
        "totalPosts": post_count,
        "estimatedDailyRevenue": round(daily_rev, 2),
        "estimatedMonthlyRevenue": round(daily_rev * 30, 2),
        "estimatedYearlyRevenue": round(daily_rev * 365, 2),
        "avgCPC": avg_cpc,
        "currency": "USD",
    }


def _categorize(keyword: str) -> str:
    cats = {
        "금융": ["주식", "코인", "ETF", "펀드", "재테크", "투자", "금리", "배당", "채권", "보험", "대출", "신용"],
        "부동산": ["아파트", "분양", "청약", "전세", "월세", "부동산", "재건축", "임대"],
        "건강": ["다이어트", "영양", "건강", "병원", "치료", "의료", "약", "혈당", "면역", "요가", "필라테스"],
        "기술": ["AI", "챗GPT", "코딩", "스마트폰", "앱", "IT", "자동화", "소프트웨어", "유튜브", "블로그"],
        "여행": ["여행", "호텔", "항공", "캠핑", "해외", "국내여행", "맛집", "관광", "코스", "숙소"],
        "스포츠": ["축구", "야구", "농구", "테니스", "골프", "k리그", "kbo", "nba", "선수", "경기",
                  "스포츠", "마라톤", "트레킹", "등산", "러닝", "수영", "자전거", "손흥민", "류현진"],
        "교육": ["영어", "자격증", "취업", "공부", "학습", "시험", "재취업"],
        "쇼핑": ["할인", "세일", "쿠폰", "구매", "패션", "가전"],
        "법률": ["법률", "소송", "변호사", "계약", "이혼", "상속", "교통사고"],
    }
    kw_lower = keyword.lower()
    for cat, words in cats.items():
        if any(w in kw_lower for w in words):
            return cat
    return "일반"


def _cpc_for_category(cat: str) -> float:
    return {
        "법률": 3.2, "부동산": 2.8, "금융": 2.5, "건강": 1.8,
        "기술": 1.5, "교육": 1.3, "여행": 1.2, "스포츠": 1.1, "쇼핑": 0.9,
    }.get(cat, 0.9)


def log_run(
    keywords: list[str],
    results: list[dict],
    blogger_uploaded: int,
    errors: int,
    blog_config: dict | None = None,
    error_messages: list[str] | None = None,
) -> None:
    """실행 결과를 run_history.json에 기록합니다."""
    history = _load_history()

    total_images = sum(r.get("images_inserted", 0) for r in results)
    total_posts = len(results)
    total_words = sum(r.get("word_count", 0) for r in results)

    avg_cpc = 0.9
    if results:
        cpcs = [_cpc_for_category(_categorize(r.get("keyword", ""))) for r in results]
        avg_cpc = sum(cpcs) / len(cpcs)

    # 전체 누적 포스트 수 (이번 실행 + 이전 이력)
    total_cumulative = total_posts + sum(h.get("postsGenerated", 0) for h in history)

    cfg = blog_config or {}
    entry = {
        "runAt": datetime.now().isoformat(),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "keywords": keywords,
        "postsGenerated": total_posts,
        "bloggerUploaded": blogger_uploaded,
        "errors": errors,
        "errorMessages": (error_messages or [])[:20],
        "imagesInserted": total_images,
        "totalWords": total_words,
        "blogId": cfg.get("id", "blog1"),
        "blogName": cfg.get("name", ""),
        "platforms": {
            "blogger": blogger_uploaded,
        },
        "earnings": _estimate_earnings(total_cumulative, avg_cpc),
        "posts": [
            {
                "title": r.get("title", ""),
                "keyword": r.get("keyword", ""),
                "blogUrl": r.get("blogUrl", ""),
                "imagesInserted": r.get("images_inserted", 0),
                "wordCount": r.get("word_count", 0),
                "contentPreview": r.get("content_preview", ""),
                "faqCount": len(r.get("faq", [])),
                "faq": r.get("faq", []),
                "factCheck": r.get("fact_check"),
                "sources": r.get("sources", []),
                "labels": r.get("labels", []),
                "metaDescription": r.get("meta_description", ""),
                "adsenseCategory": _categorize(r.get("keyword", "")),
                "articleType": r.get("article_type", ""),
                "blogId": cfg.get("id", "blog1"),
                "blogName": cfg.get("name", ""),
                # 소셜 미디어 콘텐츠 (social_publisher.generate_social_content() 반환값)
                "socialContent": r.get("socialContent"),
                "socialPublished": {
                    "instagram": r.get("social_instagram"),
                    "threads":   r.get("social_threads"),
                    "tiktok":    r.get("social_tiktok"),
                },
            }
            for r in results
        ],
    }
    history.insert(0, entry)
    history = history[:100]
    _save_history(history)
    logger.info(f"실행 이력 저장 완료 (총 {len(history)}개)")


def _load_analytics_summary() -> dict:
    """docs/data/analytics_summary.json에서 Blogger 실제 조회수 데이터를 로드합니다."""
    summary_path = os.path.join(DOCS_DATA_DIR, "analytics_summary.json")
    if os.path.exists(summary_path):
        try:
            with open(summary_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _export_repairs(docs_dir: str) -> None:
    """auto_repair.py 가 생성한 repair_history.json 을 docs/data/ 로 복사합니다."""
    src = os.path.join(os.path.dirname(__file__), "logs", "repair_history.json")
    dst = os.path.join(docs_dir, "repairs.json")
    try:
        if os.path.exists(src):
            with open(src, encoding="utf-8") as f:
                data = json.load(f)
            with open(dst, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"  수리 이력: {len(data)}건 내보내기 완료")
        else:
            with open(dst, "w", encoding="utf-8") as f:
                json.dump([], f)
    except Exception as exc:
        logger.debug(f"수리 데이터 내보내기 생략: {exc}")


def _export_learning(docs_dir: str) -> None:
    """weekly_learning.py 가 생성한 learning.json 을 docs/data/ 로 복사합니다."""
    src = os.path.join(os.path.dirname(__file__), "logs", "learning.json")
    dst = os.path.join(docs_dir, "learning.json")
    try:
        if os.path.exists(src):
            with open(src, encoding="utf-8") as f:
                data = json.load(f)
            with open(dst, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"  학습 이력: {len(data)}주 내보내기 완료")
        else:
            with open(dst, "w", encoding="utf-8") as f:
                json.dump([], f)
    except Exception as exc:
        logger.debug(f"학습 데이터 내보내기 생략: {exc}")


def _export_gsc(docs_dir: str) -> None:
    """GSC 데이터를 docs/data/gsc.json으로 내보냅니다.
    최상위 필드는 첫 번째 블로그(기존 대시보드 호환), 'sites'에 블로그별 데이터."""
    try:
        from config import GSC_SITE_URL, get_blog_configs
        from gsc_fetcher import fetch_search_analytics, save_gsc_for_dashboard

        # 블로그별 GSC 사이트 (중복 제거, 순서 유지)
        targets: list[tuple[str, str]] = []  # (blog_id, site_url)
        seen: set[str] = set()
        for b in get_blog_configs():
            u = (b.get("gsc_site_url") or "").strip()
            if u and u not in seen:
                seen.add(u)
                targets.append((b.get("id", ""), u))
        if not targets and GSC_SITE_URL:
            targets = [("blog1", GSC_SITE_URL)]
        if not targets:
            return

        sites: dict[str, dict] = {}
        for blog_id, site_url in targets:
            data = fetch_search_analytics(site_url)
            if data:
                sites[blog_id] = data
        if not sites:
            return

        # 기존 대시보드 호환: 첫 블로그 데이터를 최상위에 + sites 키 추가
        primary = next(iter(sites.values()))
        merged = {**primary, "sites": sites}
        save_gsc_for_dashboard(merged, docs_dir)
    except Exception as exc:
        logger.debug(f"GSC 내보내기 생략: {exc}")


_CAT_TAGS: dict[str, list[str]] = {
    "금융":  ["#재테크", "#주식투자", "#ETF", "#투자", "#경제", "#금융", "#돈관리", "#자산관리", "#주식", "#코인"],
    "부동산": ["#부동산", "#아파트", "#청약", "#부동산투자", "#전세", "#내집마련"],
    "건강":  ["#건강", "#다이어트", "#운동", "#건강관리", "#헬스", "#영양"],
    "기술":  ["#IT", "#기술", "#AI", "#디지털", "#챗GPT", "#인공지능"],
    "여행":  ["#여행", "#국내여행", "#여행스타그램", "#해외여행", "#여행추천", "#맛집"],
    "스포츠": ["#스포츠", "#축구", "#야구", "#운동", "#스포츠뉴스"],
    "교육":  ["#공부", "#자기계발", "#교육", "#학습", "#자격증", "#취업"],
    "쇼핑":  ["#쇼핑", "#할인", "#리뷰", "#추천", "#가성비"],
    "법률":  ["#법률", "#생활법률", "#법", "#법률정보"],
}
_DEFAULT_TAGS = ["#정보", "#블로그", "#일상", "#꿀팁", "#유용한정보"]


def _export_social(docs_dir: str) -> None:
    """run_history.json에서 SNS 콘텐츠를 추출해 social.json으로 내보냅니다.

    우선순위:
    1. 포스트에 socialContent 필드가 있으면 그대로 사용 (Claude API 생성본)
    2. 없으면 키워드·카테고리 기반 기본 템플릿으로 생성
    """
    dst = os.path.join(docs_dir, "social.json")
    try:
        history = _load_history()
        seen: set[str] = set()
        entries: list[dict] = []

        for run in history:
            run_date = (run.get("runAt", "") or "")[:10]
            for post in run.get("posts", []):
                title   = post.get("title", "")
                keyword = post.get("keyword", "")
                url     = post.get("blogUrl", "")
                if not title or title in seen:
                    continue
                seen.add(title)
                cat     = _categorize(keyword)
                kw_slug = re.sub(r"[^가-힣a-zA-Z0-9]", "", keyword)

                sc = post.get("socialContent")  # Claude API 생성본 있으면 우선 사용
                if sc and isinstance(sc, dict) and sc.get("instagram"):
                    ig_data = sc.get("instagram", {})
                    th_data = sc.get("threads")
                    tt_data = sc.get("tiktok")
                else:
                    # 기본 템플릿 생성
                    tags    = _CAT_TAGS.get(cat, _DEFAULT_TAGS)
                    caption = (
                        f"{title}\n\n💡 {keyword}에 대한 핵심 정보를 정리했습니다.\n\n저장 필수 🔖\n\n"
                        + " ".join(tags)
                    )
                    ig_data = {
                        "caption": caption,
                        "hookLine": title[:60],
                        "hashtags": {
                            "popular": tags,
                            "medium":  [f"#{kw_slug}"] if kw_slug else [],
                            "niche":   [],
                        },
                        "bestPostingTimes": ["07:00", "12:00", "21:00"],
                        "storyHighlightTitle": keyword[:5],
                    }
                    th_data = {
                        "posts": [
                            {"order": 1, "label": "1/5", "content": f"📌 {keyword} — 꼭 알아야 할 핵심 정보"},
                            {"order": 2, "label": "2/5", "content": f"📊 오늘 포스팅 주제: {title}"},
                            {"order": 3, "label": "3/5", "content": "🔍 자세한 내용은 블로그에서 확인하세요."},
                            {"order": 4, "label": "4/5", "content": f"💡 {keyword} 관련 궁금한 점 있으신가요?"},
                            {"order": 5, "label": "5/5", "content": f"🔗 전체 글: {url or '[블로그 URL]'}\n\n여러분의 생각은? 댓글로 알려주세요 💬"},
                        ],
                        "hashtags": [t if t.startswith("#") else f"#{t}" for t in (tags[:5] if tags else _DEFAULT_TAGS[:5])],
                        "engagementQuestion": f"{keyword}에 대해 어떻게 생각하시나요?",
                        "bestPostingTimes": ["08:00", "19:00"],
                    }
                    tt_data = {
                        "title": f"{keyword} 핵심 정리 60초",
                        "thumbnailText": keyword[:20],
                        "scenes": [
                            {"time": "0-3초",   "text": f"⚡ {keyword} 모르면 손해!",   "direction": "화면 클로즈업", "sound": "알림음"},
                            {"time": "3-15초",  "text": "이걸 모르는 분들이 많아요",     "direction": "정면 촬영",    "sound": "배경음악"},
                            {"time": "15-35초", "text": "핵심 내용 3가지",               "direction": "텍스트 슬라이드","sound": "배경음악"},
                            {"time": "35-50초", "text": f"{keyword} 이렇게 활용하세요",  "direction": "인포그래픽",   "sound": "배경음악"},
                            {"time": "50-60초", "text": f"더 자세히 → 링크 클릭! {url or ''}", "direction": "CTA 화면", "sound": "효과음"},
                        ],
                        "fullScript": f"{keyword}에 대한 핵심 정보입니다. 자세한 내용은 블로그 링크를 확인하세요.",
                        "commentBait": f"{keyword} 관련 경험 있으신 분? 댓글로 공유해주세요!",
                        "hashtags": ["#fyp", "#foryou", "#정보", "#꿀팁"] + (tags[:3] if tags else []),
                        "backgroundMusic": {"genre": "팝", "mood": "경쾌한"},
                        "bestPostingTimes": ["07:00", "20:00", "23:00"],
                    }

                # 게시 결과 (있을 경우)
                published = post.get("socialPublished", {}) or {}

                entries.append({
                    "id": f"{run_date}_{kw_slug}_social",
                    "date": run_date,
                    "keyword": keyword,
                    "postTitle": title,
                    "postUrl": url,
                    "instagram": ig_data,
                    "threads":   th_data,
                    "tiktok":    tt_data,
                    "published": published,
                })

        # 최신순 정렬, 최대 50개
        entries.sort(key=lambda e: e.get("date", ""), reverse=True)
        entries = entries[:50]

        with open(dst, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
        logger.info(f"  SNS 데이터: {len(entries)}개 내보내기 완료")
    except Exception as exc:
        logger.debug(f"SNS 데이터 내보내기 생략: {exc}")


def _export_series(docs_dir: str) -> None:
    """시리즈 기획 데이터를 docs/data/series.json으로 내보냅니다."""
    series_src = os.path.join(os.path.dirname(__file__), "logs", "series.json")
    series_dst = os.path.join(docs_dir, "series.json")
    try:
        if os.path.exists(series_src):
            with open(series_src, encoding="utf-8") as f:
                series_list = json.load(f)
        else:
            series_list = []
        export = [
            {
                "series_id": s.get("series_id", ""),
                "series_title": s.get("series_title", ""),
                "series_label": s.get("series_label", ""),
                "series_description": s.get("series_description", ""),
                "keyword": s.get("keyword", ""),
                "total_episodes": s.get("total_episodes", 0),
                "created_at": s.get("created_at", ""),
                "status": s.get("status", "planned"),
                "episodes": [
                    {
                        "episode": ep.get("episode"),
                        "title": ep.get("title", ""),
                        "focus": ep.get("focus", ""),
                        "status": ep.get("status", "pending"),
                        "blogger_url": ep.get("blogger_url"),
                    }
                    for ep in s.get("episodes", [])
                ],
            }
            for s in series_list
        ]
        with open(series_dst, "w", encoding="utf-8") as f:
            json.dump(export, f, ensure_ascii=False, indent=2)
        logger.info(f"  시리즈: {len(export)}개 내보내기 완료")
    except Exception as exc:
        logger.warning(f"시리즈 데이터 내보내기 실패 (무시): {exc}")


def export_dashboard() -> None:
    """대시보드용 JSON을 docs/data/에 내보냅니다."""
    os.makedirs(DOCS_DATA_DIR, exist_ok=True)
    history = _load_history()

    # posts.json 생성
    posts = []
    seen_titles: set[str] = set()
    blog_stats: dict[str, dict] = {}
    for run in history:
        run_blog_id = run.get("blogId", "blog1")
        run_blog_name = run.get("blogName", "")
        if run_blog_id not in blog_stats:
            blog_stats[run_blog_id] = {
                "id": run_blog_id, "name": run_blog_name,
                "postCount": 0, "runCount": 0,
                "lastRunAt": run.get("runAt", ""),
            }
        blog_stats[run_blog_id]["runCount"] += 1
        if run.get("runAt", "") > blog_stats[run_blog_id].get("lastRunAt", ""):
            blog_stats[run_blog_id]["lastRunAt"] = run.get("runAt", "")
        if run_blog_name and not blog_stats[run_blog_id]["name"]:
            blog_stats[run_blog_id]["name"] = run_blog_name

        for p in run.get("posts", []):
            title = p.get("title", "")
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)
            kw = p.get("keyword", "")
            cat = _categorize(kw)
            # 60자 잘림으로 다른 제목이 같은 id가 되는 충돌 방지 — 전체 제목 해시 접미사
            import hashlib
            _h = hashlib.md5(title.encode()).hexdigest()[:6]
            post_id = run["date"] + "_" + re.sub(r"[^\w가-힣]", "_", title)[:60] + "_" + _h
            blog_stats[run_blog_id]["postCount"] += 1
            posts.append({
                "id": post_id,
                "title": title,
                "keyword": kw,
                "date": run["date"],
                "wordCount": p.get("wordCount", 0),
                "faqCount": p.get("faqCount", 0),
                "imagesInserted": p.get("imagesInserted", 0),
                "hasToc": True,
                "adSlots": 4,
                "adsenseCategory": cat,
                "estimatedCPC": _cpc_for_category(cat),
                "articleType": p.get("articleType", ""),
                "trendDirection": "rising",
                "factCheck": p.get("factCheck"),
                "tags": p.get("labels", [])[:7],
                "blogUrl": p.get("blogUrl", ""),
                "metaDescription": p.get("metaDescription", ""),
                "contentPreview": p.get("contentPreview", ""),
                "faq": p.get("faq", []),
                "sources": p.get("sources", []),
                "blogId": p.get("blogId", run_blog_id),
                "blogName": p.get("blogName", run_blog_name),
            })
    posts.sort(key=lambda x: x["date"], reverse=True)

    # runs.json 생성
    runs_export = [
        {
            "runAt": run["runAt"],
            "date": run["date"],
            "keywords": run["keywords"],
            "postsGenerated": run["postsGenerated"],
            "bloggerUploaded": run.get("bloggerUploaded", 0),
            "imagesInserted": run.get("imagesInserted", 0),
            "totalWords": run.get("totalWords", 0),
            "errors": run["errors"],
            "blogId": run.get("blogId", "blog1"),
            "blogName": run.get("blogName", ""),
            "platforms": run.get("platforms", {}),
            "earnings": run.get("earnings", {}),
        }
        for run in history
    ]

    # analytics.json — 최신 실행의 누적 수익 추정치 사용 (모든 포스트 기반)
    last_earnings = history[0].get("earnings", {}) if history else {}
    analytics = {
        "estimatedDailyRevenue": last_earnings.get("estimatedDailyRevenue", 0),
        "estimatedMonthlyRevenue": last_earnings.get("estimatedMonthlyRevenue", 0),
        "estimatedYearlyRevenue": last_earnings.get("estimatedYearlyRevenue", 0),
        "avgCPC": last_earnings.get("avgCPC", 0.9),
        "runCount": len(history),
        "totalWords": sum(r.get("totalWords", 0) for r in history),
    }

    # meta.json — totalRevenue는 현재 누적 포스트 기준 연 예상 수익
    blogger_total = sum(r.get("bloggerUploaded", 0) for r in history)
    total_revenue = last_earnings.get("estimatedYearlyRevenue", 0)
    meta = {
        "exportedAt": datetime.now().isoformat(),
        "totalPosts": len(posts),
        "totalRuns": len(history),
        "lastRunAt": history[0].get("runAt") if history else None,
        "lastKeywords": history[0].get("keywords", []) if history else [],
        "bloggerTotal": blogger_total,
        "totalRevenue": round(total_revenue, 2),
        "systemVersion": "Python 3.11 v2.0",
        "repoUrl": "https://github.com/kevinlee7250/cli",
        "actionsUrl": "https://github.com/kevinlee7250/cli/actions",
        "blogUrl": "https://hoguwhat1.blogspot.com/",
    }

    blogs_export = sorted(blog_stats.values(), key=lambda b: b.get("lastRunAt", ""), reverse=True)

    # Blogger 실제 조회수 데이터를 blogs_export에 병합
    analytics_summary = _load_analytics_summary()
    if analytics_summary and blogs_export:
        pv30 = analytics_summary.get("bloggerPageviews30d", 0)
        pv7 = analytics_summary.get("bloggerPageviews7d", 0)
        pv1 = analytics_summary.get("bloggerPageviews1d", 0)
        updated_at = analytics_summary.get("generatedAt", "")
        for blog in blogs_export:
            blog["pageviews30d"] = pv30
            blog["pageviews7d"] = pv7
            blog["pageviews1d"] = pv1
            blog["analyticsUpdatedAt"] = updated_at

    # posts.json 비대화 방지 — 최근 POSTS_EXPORT_LIMIT개만 유지하고
    # 나머지는 posts_archive.json에 누적 (대시보드가 백그라운드에서 병합 로드)
    POSTS_EXPORT_LIMIT = 300
    posts_recent = posts[:POSTS_EXPORT_LIMIT]
    posts_overflow = posts[POSTS_EXPORT_LIMIT:]
    if posts_overflow:
        archive_path = os.path.join(DOCS_DATA_DIR, "posts_archive.json")
        try:
            archive = []
            if os.path.exists(archive_path):
                with open(archive_path, encoding="utf-8") as f:
                    archive = json.load(f)
            seen_ids = {p.get("id") for p in archive}
            new_items = [p for p in posts_overflow if p.get("id") not in seen_ids]
            if new_items:
                archive = new_items + archive
                with open(archive_path, "w", encoding="utf-8") as f:
                    json.dump(archive, f, ensure_ascii=False, indent=2)
                logger.info(f"  아카이브: {len(new_items)}개 이동 (총 {len(archive)}개)")
        except Exception as _ae:
            logger.warning(f"posts_archive.json 저장 실패 — posts.json에 전체 유지: {_ae}")
            posts_recent = posts

    for name, data in [
        ("posts.json", posts_recent),
        ("runs.json", runs_export),
        ("analytics.json", analytics),
        ("meta.json", meta),
        ("blogs.json", blogs_export),
    ]:
        path = os.path.join(DOCS_DATA_DIR, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    _export_series(DOCS_DATA_DIR)
    _export_social(DOCS_DATA_DIR)
    _export_gsc(DOCS_DATA_DIR)
    _export_learning(DOCS_DATA_DIR)
    _export_repairs(DOCS_DATA_DIR)

    # 포스트 레지스트리 내보내기 (post_manager)
    try:
        from post_manager import export_for_dashboard as _pm_export
        _pm_export(DOCS_DATA_DIR)
    except Exception as _pme:
        logger.debug(f"포스트 레지스트리 내보내기 생략: {_pme}")

    logger.info(f"대시보드 데이터 내보내기 완료 → {DOCS_DATA_DIR}")
    logger.info(f"  포스트: {len(posts)}개 / 실행 이력: {len(runs_export)}개 / 블로그: {len(blogs_export)}개")


def save_pending_posts(results: list[dict], blog_config: dict | None = None) -> None:
    """생성된 포스트를 검토 대기 목록으로 저장합니다 (Blogger 업로드 없이)."""
    pending: list[dict] = []
    if os.path.exists(PENDING_FILE):
        try:
            with open(PENDING_FILE, encoding="utf-8") as f:
                pending = json.load(f)
        except (json.JSONDecodeError, OSError):
            pending = []

    cfg = blog_config or {}
    initial_pending_len = len(pending)
    now = datetime.now()
    for idx, r in enumerate(results):
        title = r.get("title", "")
        content = r.get("content", "")
        if not title or not content:
            logger.warning(f"포스트 #{idx+1} 제목 또는 본문 비어있음 — 건너뜀 (title={repr(title[:30])})")
            continue
        safe_kw = re.sub(r"[^\w가-힣]", "_", r.get("keyword", ""))[:20]
        uid = f"{now.strftime('%Y%m%d%H%M%S')}_{idx:02d}_{safe_kw}"
        pending.append({
            "id": uid,
            "savedAt": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "keyword": r.get("keyword", ""),
            "title": title,
            "content": content,
            "labels": r.get("labels", []),
            "wordCount": r.get("word_count", 0),
            "imagesInserted": r.get("images_inserted", 0),
            "faq": r.get("faq", []),
            "metaDescription": r.get("meta_description", ""),
            "sources": r.get("sources", []),
            "status": "pending",
            "blogId": cfg.get("id", r.get("blogId", "blog1")),
            "blogName": cfg.get("name", r.get("blogName", "")),
        })
        logger.info(f"  검토 대기 저장: {title[:60]} ({len(content)}자 HTML)")

    try:
        os.makedirs(os.path.dirname(PENDING_FILE), exist_ok=True)
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(pending, f, ensure_ascii=False, indent=2)
        logger.info(f"검토 대기 포스트 저장 완료: {len(pending) - initial_pending_len}개 추가 (총 {len(pending)}개)")
    except OSError as e:
        logger.error(f"검토 대기 파일 저장 실패: {e}")
