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
        "건강": ["다이어트", "운동", "영양", "건강", "병원", "치료", "의료", "약", "혈당", "면역"],
        "기술": ["AI", "챗GPT", "코딩", "스마트폰", "앱", "IT", "자동화", "소프트웨어", "유튜브", "블로그"],
        "여행": ["여행", "호텔", "항공", "캠핑", "해외", "국내여행", "맛집"],
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
        "기술": 1.5, "교육": 1.3, "여행": 1.2, "쇼핑": 0.9,
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
        "blogId": cfg.get("id", "default"),
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
                "sources": r.get("sources", []),
                "labels": r.get("labels", []),
                "metaDescription": r.get("meta_description", ""),
                "blogId": cfg.get("id", "default"),
                "blogName": cfg.get("name", ""),
            }
            for r in results
        ],
    }
    history.insert(0, entry)
    history = history[:100]
    _save_history(history)
    logger.info(f"실행 이력 저장 완료 (총 {len(history)}개)")


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
    """GSC 캐시 데이터를 docs/data/gsc.json으로 내보냅니다."""
    try:
        from config import GSC_SITE_URL
        if not GSC_SITE_URL:
            return
        from gsc_fetcher import fetch_search_analytics, save_gsc_for_dashboard
        data = fetch_search_analytics(GSC_SITE_URL)
        if data:
            save_gsc_for_dashboard(data, docs_dir)
    except Exception as exc:
        logger.debug(f"GSC 내보내기 생략: {exc}")


def _export_social(docs_dir: str) -> None:
    """run_history.json 포스트에서 기본 SNS 콘텐츠 항목을 생성합니다."""
    dst = os.path.join(docs_dir, "social.json")
    try:
        history = _load_history()
        seen: set[str] = set()
        entries: list[dict] = []
        cat_tags: dict[str, list[str]] = {
            "금융": ["#재테크", "#주식투자", "#경제", "#투자", "#금융"],
            "부동산": ["#부동산", "#아파트", "#청약", "#부동산투자"],
            "건강": ["#건강", "#다이어트", "#운동", "#건강관리"],
            "기술": ["#IT", "#기술", "#AI", "#디지털"],
            "여행": ["#여행", "#국내여행", "#여행스타그램"],
            "교육": ["#공부", "#자기계발", "#교육", "#학습"],
            "쇼핑": ["#쇼핑", "#할인", "#리뷰"],
            "법률": ["#법률", "#생활법률", "#법"],
        }
        default_tags = ["#정보", "#블로그", "#일상"]

        for run in history:
            run_date = (run.get("runAt", "") or "")[:10]
            for post in run.get("posts", []):
                title = post.get("title", "")
                keyword = post.get("keyword", "")
                url = post.get("blogUrl", "")
                if not title or title in seen:
                    continue
                seen.add(title)
                cat = _categorize(keyword)
                tags = cat_tags.get(cat, default_tags)
                kw_slug = re.sub(r"[^가-힣a-zA-Z0-9]", "", keyword)
                caption = (
                    f"{title}\n\n💡 {keyword}에 대한 핵심 정보를 정리했습니다.\n\n"
                    + " ".join(tags)
                )
                entries.append({
                    "id": f"{run_date}_{kw_slug}_social",
                    "date": run_date,
                    "keyword": keyword,
                    "postTitle": title,
                    "postUrl": url,
                    "instagram": {
                        "caption": caption,
                        "hookLine": title[:50],
                        "hashtags": {
                            "popular": tags,
                            "medium": [f"#{kw_slug}"] if kw_slug else [],
                            "niche": [],
                        },
                        "bestPostingTimes": ["07:00", "12:00", "21:00"],
                        "storyHighlightTitle": keyword[:10],
                    },
                    "threads": None,
                    "tiktok": None,
                })

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
        run_blog_id = run.get("blogId", "default")
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
            post_id = run["date"] + "_" + re.sub(r"[^\w가-힣]", "_", title)[:60]
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
                "trendDirection": "rising",
                "factCheck": None,
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

    for name, data in [
        ("posts.json", posts),
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
            "blogId": cfg.get("id", r.get("blogId", "default")),
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
