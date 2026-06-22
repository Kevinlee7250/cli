"""Google Search Console API 연동 — 실제 검색 노출/클릭 데이터 수집"""

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

GSC_API_BASE = "https://searchconsole.googleapis.com/webmasters/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CACHE_FILE = os.path.join(os.path.dirname(__file__), "logs", "gsc_cache.json")
CACHE_TTL_HOURS = 24


# ─────────────────────────────────────────────
# OAuth
# ─────────────────────────────────────────────

def _get_access_token() -> str | None:
    try:
        from config import BLOGGER_CLIENT_ID, BLOGGER_CLIENT_SECRET, BLOGGER_REFRESH_TOKEN
        if not BLOGGER_CLIENT_ID or not BLOGGER_REFRESH_TOKEN:
            return None
        resp = requests.post(TOKEN_URL, data={
            "client_id": BLOGGER_CLIENT_ID,
            "client_secret": BLOGGER_CLIENT_SECRET,
            "refresh_token": BLOGGER_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        }, timeout=15)
        if resp.status_code == 200:
            return resp.json().get("access_token")
        logger.warning(f"GSC 토큰 발급 실패: {resp.status_code}")
        return None
    except Exception as e:
        logger.debug(f"GSC 토큰 오류: {e}")
        return None


# ─────────────────────────────────────────────
# 캐시
# ─────────────────────────────────────────────

def _load_cache() -> dict | None:
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        fetched = datetime.fromisoformat(data.get("fetched_at", "2000-01-01"))
        if (datetime.now() - fetched).total_seconds() < CACHE_TTL_HOURS * 3600:
            logger.debug(f"GSC 캐시 사용 (만료까지 {CACHE_TTL_HOURS - (datetime.now() - fetched).seconds // 3600}h)")
            return data
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        pass
    return None


def _save_cache(data: dict) -> None:
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────
# API 호출
# ─────────────────────────────────────────────

def fetch_search_analytics(site_url: str, days: int = 30, row_limit: int = 100) -> dict | None:
    """
    Search Console API로 검색 분석 데이터를 가져옵니다.
    24시간 캐시를 사용하며, GSC_SITE_URL 미설정 시 None 반환.
    """
    if not site_url:
        logger.debug("GSC_SITE_URL 미설정 — GSC 연동 생략")
        return None

    cached = _load_cache()
    if cached and cached.get("site_url") == site_url:
        return cached

    token = _get_access_token()
    if not token:
        return None

    # GSC는 최신 데이터가 3일 지연
    end_date = datetime.now() - timedelta(days=3)
    start_date = end_date - timedelta(days=days)

    payload = {
        "startDate": start_date.strftime("%Y-%m-%d"),
        "endDate": end_date.strftime("%Y-%m-%d"),
        "dimensions": ["query"],
        "rowLimit": row_limit,
        "orderBy": [{"fieldName": "clicks", "sortOrder": "DESCENDING"}],
    }

    encoded_url = requests.utils.quote(site_url, safe="")
    url = f"{GSC_API_BASE}/sites/{encoded_url}/searchAnalytics/query"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
    except requests.exceptions.RequestException as e:
        logger.warning(f"GSC API 요청 오류: {e}")
        return None

    if resp.status_code == 403:
        logger.warning("GSC 권한 없음 — 사이트가 Search Console에 등록됐는지 확인하세요")
        return None
    if resp.status_code != 200:
        logger.warning(f"GSC API 오류: {resp.status_code} {resp.text[:200]}")
        return None

    try:
        rows = resp.json().get("rows", [])
    except Exception as e:
        logger.warning(f"GSC 응답 파싱 오류: {e}")
        return None

    top_queries = [
        {
            "query": row.get("keys", [""])[0],
            "clicks": int(row.get("clicks", 0)),
            "impressions": int(row.get("impressions", 0)),
            "ctr": round(row.get("ctr", 0) * 100, 2),
            "position": round(row.get("position", 0), 1),
        }
        for row in rows
    ]

    # 카테고리별 집계
    from dashboard_exporter import _categorize
    cat_stats: dict[str, dict] = defaultdict(lambda: {"clicks": 0, "impressions": 0, "queries": []})
    for q in top_queries:
        cat = _categorize(q["query"])
        cat_stats[cat]["clicks"] += q["clicks"]
        cat_stats[cat]["impressions"] += q["impressions"]
        cat_stats[cat]["queries"].append(q["query"])

    category_performance: dict[str, dict] = {}
    for cat, stats in cat_stats.items():
        imp = stats["impressions"]
        clicks = stats["clicks"]
        category_performance[cat] = {
            "clicks": clicks,
            "impressions": imp,
            "ctr": round(clicks / imp * 100, 2) if imp > 0 else 0.0,
            "top_queries": stats["queries"][:5],
        }

    result = {
        "site_url": site_url,
        "top_queries": top_queries[:50],
        "category_performance": category_performance,
        "date_range": {
            "start": start_date.strftime("%Y-%m-%d"),
            "end": end_date.strftime("%Y-%m-%d"),
            "days": days,
        },
        "fetched_at": datetime.now().isoformat(),
        "total_rows": len(rows),
    }

    _save_cache(result)
    logger.info(f"GSC 데이터 수집 완료: {len(rows)}개 쿼리 / {len(category_performance)}개 카테고리")
    return result


# ─────────────────────────────────────────────
# 키워드 수집기용 인터페이스
# ─────────────────────────────────────────────

def get_high_performing_categories(site_url: str, days: int = 30) -> list[str]:
    """클릭 수 기준 상위 카테고리 목록을 반환합니다. GSC 미설정 시 빈 목록."""
    data = fetch_search_analytics(site_url, days=days)
    if not data:
        return []
    sorted_cats = sorted(
        data["category_performance"].items(),
        key=lambda x: x[1]["clicks"],
        reverse=True,
    )
    cats = [cat for cat, stats in sorted_cats if stats["clicks"] > 0]
    logger.info(f"GSC 고성과 카테고리 순위: {cats}")
    return cats


def get_gsc_suggested_keywords(site_url: str, count: int = 10) -> list[str]:
    """GSC 상위 쿼리에서 아직 다루지 않은 롱테일 키워드를 추출합니다."""
    data = fetch_search_analytics(site_url, days=60, row_limit=200)
    if not data:
        return []

    # 노출은 높지만 CTR이 낮은 쿼리 → 개선 여지 있음 (4~20위권)
    candidates = [
        q["query"] for q in data["top_queries"]
        if q["impressions"] > 10 and q["position"] > 3 and q["ctr"] < 5.0
    ]
    return candidates[:count]


def save_gsc_for_dashboard(data: dict, docs_dir: str) -> None:
    """GSC 데이터를 docs/data/gsc.json으로 저장합니다."""
    os.makedirs(docs_dir, exist_ok=True)
    path = os.path.join(docs_dir, "gsc.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"GSC 대시보드 데이터 저장: {path}")
