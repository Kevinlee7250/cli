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


def _load_history() -> list[dict]:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_history(history: list[dict]) -> None:
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def _estimate_earnings(post_count: int, avg_cpc: float = 0.9) -> dict:
    """AdSense 수익 추정 (CTR 2.5%, 페이지뷰 100/일 기준)."""
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
        "금융": ["주식", "코인", "ETF", "펀드", "재테크", "투자", "금리", "배당", "채권"],
        "부동산": ["아파트", "분양", "청약", "전세", "월세", "부동산", "재건축"],
        "건강": ["다이어트", "운동", "영양", "건강", "병원", "치료", "의료", "약"],
        "기술": ["AI", "챗GPT", "코딩", "스마트폰", "앱", "IT", "자동화", "소프트웨어"],
        "여행": ["여행", "호텔", "항공", "캠핑", "해외", "국내여행"],
        "교육": ["영어", "자격증", "취업", "공부", "학습", "시험"],
        "쇼핑": ["할인", "세일", "쿠폰", "구매", "패션", "가전"],
        "법률": ["법률", "소송", "변호사", "계약", "이혼", "상속"],
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


def _word_count(html: str) -> int:
    text = re.sub(r"<[^>]+>", "", html)
    return len(re.sub(r"\s+", "", text))


def log_run(
    keywords: list[str],
    results: list[dict],
    blogger_uploaded: int,
    errors: int,
) -> None:
    """실행 결과를 run_history.json에 기록합니다."""
    history = _load_history()

    total_images = sum(r.get("images_inserted", 0) for r in results)
    total_posts = len(results)

    # 평균 CPC 계산
    avg_cpc = 0.9
    if results:
        cpcs = [_cpc_for_category(_categorize(r.get("keyword", ""))) for r in results]
        avg_cpc = sum(cpcs) / len(cpcs)

    entry = {
        "runAt": datetime.now().isoformat(),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "keywords": keywords,
        "postsGenerated": total_posts,
        "bloggerUploaded": blogger_uploaded,
        "errors": errors,
        "imagesInserted": total_images,
        "platforms": {
            "blogger": blogger_uploaded,
        },
        "earnings": _estimate_earnings(total_posts + len(history) * 2, avg_cpc),
        "posts": [
            {
                "title": r.get("title", ""),
                "keyword": r.get("keyword", ""),
                "blogUrl": r.get("blogUrl", ""),
                "imagesInserted": r.get("images_inserted", 0),
                "faqCount": len(r.get("faq", [])),
                "labels": r.get("labels", []),
            }
            for r in results
        ],
    }
    history.insert(0, entry)
    history = history[:100]  # 최대 100개 보관
    _save_history(history)
    logger.info(f"실행 이력 저장 완료 (총 {len(history)}개)")


def export_dashboard() -> None:
    """대시보드용 JSON을 docs/data/에 내보냅니다."""
    os.makedirs(DOCS_DATA_DIR, exist_ok=True)
    history = _load_history()

    # posts.json 생성
    posts = []
    seen_titles: set[str] = set()
    for run in history:
        for p in run.get("posts", []):
            title = p.get("title", "")
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)
            kw = p.get("keyword", "")
            cat = _categorize(kw)
            post_id = run["date"] + "_" + re.sub(r"[^\w가-힣]", "_", title)[:60]
            posts.append({
                "id": post_id,
                "title": title,
                "keyword": kw,
                "date": run["date"],
                "wordCount": 3000,
                "faqCount": p.get("faqCount", 0),
                "imagesInserted": p.get("imagesInserted", 0),
                "hasToc": True,
                "adSlots": 6,
                "adsenseCategory": cat,
                "estimatedCPC": _cpc_for_category(cat),
                "trendDirection": "rising",
                "factCheck": None,
                "tags": p.get("labels", [])[:7],
                "blogUrl": p.get("blogUrl", ""),
                "metaDescription": "",
                "contentPreview": "",
                "faq": [],
            })
    posts.sort(key=lambda x: x["date"], reverse=True)

    # runs.json 생성
    runs_export = []
    for run in history:
        runs_export.append({
            "runAt": run["runAt"],
            "date": run["date"],
            "keywords": run["keywords"],
            "postsGenerated": run["postsGenerated"],
            "bloggerUploaded": run.get("bloggerUploaded", 0),
            "imagesInserted": run.get("imagesInserted", 0),
            "errors": run["errors"],
            "platforms": run.get("platforms", {}),
            "earnings": run.get("earnings", {}),
        })

    # analytics.json
    total_revenue = sum(r.get("earnings", {}).get("estimatedDailyRevenue", 0) for r in history)
    last_earnings = history[0].get("earnings", {}) if history else {}
    analytics = {
        "estimatedDailyRevenue": last_earnings.get("estimatedDailyRevenue", 0),
        "estimatedMonthlyRevenue": last_earnings.get("estimatedMonthlyRevenue", 0),
        "estimatedYearlyRevenue": last_earnings.get("estimatedYearlyRevenue", 0),
        "avgCPC": last_earnings.get("avgCPC", 0.9),
        "totalCumulativeRevenue": round(total_revenue, 2),
        "runCount": len(history),
    }

    # meta.json
    blogger_total = sum(r.get("bloggerUploaded", 0) for r in history)
    meta = {
        "exportedAt": datetime.now().isoformat(),
        "totalPosts": len(posts),
        "totalRuns": len(history),
        "lastRunAt": history[0]["runAt"] if history else None,
        "lastKeywords": history[0]["keywords"] if history else [],
        "bloggerTotal": blogger_total,
        "totalRevenue": round(total_revenue, 2),
        "systemVersion": "Python 3.11",
        "repoUrl": "https://github.com/kevinlee7250/cli",
        "actionsUrl": "https://github.com/kevinlee7250/cli/actions",
        "blogUrl": "https://hoguwhat1.blogspot.com/",
    }

    # 파일 저장
    for name, data in [
        ("posts.json", posts),
        ("runs.json", runs_export),
        ("analytics.json", analytics),
        ("meta.json", meta),
    ]:
        path = os.path.join(DOCS_DATA_DIR, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info(f"대시보드 데이터 내보내기 완료 → {DOCS_DATA_DIR}")
    logger.info(f"  포스트: {len(posts)}개 / 실행 이력: {len(runs_export)}개")
