"""
트렌드 키워드 수집 모듈
- Google Trends RSS (무료, 인증 불필요)
- Naver DataLab 인기 검색어 (API 키 있을 때)
- 폴백: 설정 파일의 고정 키워드 목록
"""

import logging
import os
import re
import xml.etree.ElementTree as ET

import requests

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

# 폴백 키워드 (외부 API 모두 실패 시 사용)
_FALLBACK_KEYWORDS_KR = [
    "재테크 방법",
    "주식 투자 초보",
    "부동산 투자 전략",
    "다이어트 방법",
    "건강 관리 팁",
    "부업 아이디어",
    "자기계발 방법",
    "여행 추천지",
    "맛집 추천",
    "최신 IT 기기",
]

_FALLBACK_KEYWORDS_EN = [
    "passive income ideas",
    "investing for beginners",
    "weight loss tips",
    "remote work productivity",
    "best travel destinations",
    "healthy meal prep",
    "personal finance tips",
    "side hustle ideas",
    "tech gadgets 2025",
    "home workout routines",
]


def _google_trends_rss(country: str = "KR", count: int = 10) -> list[str]:
    """Google Trends 일간 트렌드 RSS에서 키워드를 수집합니다."""
    geo = country.upper()
    url = f"https://trends.google.com/trends/trendingsearches/daily/rss?geo={geo}"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=12)
        if r.status_code != 200:
            logger.debug(f"Google Trends RSS 실패: HTTP {r.status_code}")
            return []

        root = ET.fromstring(r.content)
        keywords = []
        for item in root.findall(".//item"):
            title = item.findtext("title", "").strip()
            if title:
                keywords.append(title)
            if len(keywords) >= count:
                break

        logger.info(f"Google Trends {geo}: {len(keywords)}개 키워드 수집")
        return keywords
    except Exception as e:
        logger.debug(f"Google Trends RSS 오류: {e}")
        return []


def _naver_datalab_keywords(client_id: str, client_secret: str, count: int = 10) -> list[str]:
    """Naver DataLab 검색어 트렌드 API (선택적)."""
    if not client_id or not client_secret:
        return []
    try:
        from datetime import datetime, timedelta
        today = datetime.now().strftime("%Y-%m-%d")
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

        r = requests.post(
            "https://openapi.naver.com/v1/datalab/search",
            json={
                "startDate": week_ago,
                "endDate": today,
                "timeUnit": "date",
                "keywordGroups": [
                    {"groupName": "트렌드", "keywords": ["주식", "부동산", "재테크", "다이어트", "여행"]},
                ],
            },
            headers={
                "X-Naver-Client-Id": client_id,
                "X-Naver-Client-Secret": client_secret,
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        if r.status_code == 200:
            results = r.json().get("results", [])
            return [res.get("title", "") for res in results[:count] if res.get("title")]
    except Exception as e:
        logger.debug(f"Naver DataLab 오류: {e}")
    return []


def get_trending_keywords(
    country: str = "KR",
    language: str = "ko",
    count: int = 5,
    naver_client_id: str = "",
    naver_client_secret: str = "",
) -> list[str]:
    """
    트렌드 키워드를 수집합니다.
    우선순위: Google Trends RSS → Naver DataLab → 고정 폴백 목록
    """
    keywords: list[str] = []

    # 1순위: Google Trends RSS
    keywords = _google_trends_rss(country, count * 2)

    # 2순위: Naver DataLab (키 있을 때)
    if not keywords and naver_client_id:
        keywords = _naver_datalab_keywords(naver_client_id, naver_client_secret, count * 2)

    # 3순위: 고정 폴백
    if not keywords:
        fallback = _FALLBACK_KEYWORDS_KR if language == "ko" else _FALLBACK_KEYWORDS_EN
        logger.warning("외부 트렌드 API 실패 — 고정 키워드 목록 사용")
        keywords = fallback

    # 중복 제거 후 count 개 반환
    seen: set[str] = set()
    result: list[str] = []
    for kw in keywords:
        kw = kw.strip()
        if kw and kw not in seen:
            seen.add(kw)
            result.append(kw)
        if len(result) >= count:
            break

    return result
