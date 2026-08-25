import requests
import xml.etree.ElementTree as ET
import json
import random
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

GOOGLE_TRENDS_RSS = {
    "KR": "https://trends.google.com/trends/trendingsearches/daily/rss?geo=KR",
    "US": "https://trends.google.com/trends/trendingsearches/daily/rss?geo=US",
    "JP": "https://trends.google.com/trends/trendingsearches/daily/rss?geo=JP",
}

NAVER_DATALAB_URL = "https://datalab.naver.com/keyword/realtimeList.naver?where=main"


def fetch_google_trends(country: str = "KR") -> list[dict]:
    """Google Trends RSS에서 인기 검색어를 가져옵니다."""
    url = GOOGLE_TRENDS_RSS.get(country, GOOGLE_TRENDS_RSS["KR"])
    headers = {"User-Agent": "Mozilla/5.0 (compatible; BlogBot/1.0)"}

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        ns = {"ht": "https://trends.google.com/trends/trendingsearches/daily"}

        topics = []
        for item in root.findall(".//item"):
            title_el = item.find("title")
            traffic_el = item.find("ht:approx_traffic", ns)
            if title_el is not None:
                topics.append({
                    "keyword": title_el.text.strip(),
                    "traffic": traffic_el.text.strip() if traffic_el is not None else "N/A",
                    "source": "google_trends",
                })
        logger.info(f"Google Trends에서 {len(topics)}개 키워드 수집")
        return topics
    except Exception as e:
        logger.warning(f"Google Trends 수집 실패: {e}")
        return []


def fetch_fallback_topics(country: str = "KR") -> list[dict]:
    """트렌드 API 실패 시 사용하는 폴백 키워드 목록."""
    fallback_kr = [
        "재테크 방법", "다이어트 식단", "AI 활용법", "부업 아이디어",
        "주식 투자 초보", "영어 공부법", "건강 관리 팁", "여행 추천지",
        "맛집 추천", "스마트폰 활용팁",
    ]
    fallback_us = [
        "make money online", "weight loss tips", "AI tools 2025",
        "side hustle ideas", "stock market beginners", "travel hacks",
        "healthy recipes", "productivity tips",
    ]
    topics = fallback_kr if country == "KR" else fallback_us
    random.shuffle(topics)
    return [{"keyword": t, "traffic": "N/A", "source": "fallback"} for t in topics[:5]]


def get_trending_topics(country: str = "KR", limit: int = 5) -> list[dict]:
    """트렌드 키워드를 수집하고 반환합니다."""
    topics = fetch_google_trends(country)
    if not topics:
        logger.warning("Google Trends 결과 없음, 폴백 키워드 사용")
        topics = fetch_fallback_topics(country)

    # 중복 제거 후 상위 limit개 반환
    seen = set()
    unique = []
    for t in topics:
        if t["keyword"] not in seen:
            seen.add(t["keyword"])
            unique.append(t)
        if len(unique) >= limit:
            break
    return unique


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    topics = get_trending_topics("KR")
    for t in topics:
        print(f"[{t['source']}] {t['keyword']} ({t['traffic']})")
