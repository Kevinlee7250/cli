"""
트렌드 키워드 수집 모듈
- Google Trends RSS (무료, 인증 불필요)
- Naver DataLab 인기 검색어 (API 키 있을 때)
- 폴백: 고정 키워드 목록 (중복 방지 로테이션)
"""

import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

_USED_KW_FILE = os.path.join(os.path.dirname(__file__), "logs", "used_keywords.json")

# 폴백 키워드 — 매번 다른 키워드가 선택되도록 충분히 많이 유지
_FALLBACK_KEYWORDS_KR = [
    "재테크 방법", "주식 투자 초보", "부동산 투자 전략", "다이어트 방법", "건강 관리 팁",
    "부업 아이디어", "자기계발 방법", "여행 추천지", "맛집 추천", "최신 IT 기기",
    "ETF 투자 방법", "청약 당첨 전략", "코인 투자 입문", "다이어트 식단", "운동 루틴",
    "자격증 추천", "영어 공부법", "재취업 준비", "노후 준비 방법", "보험 비교",
    "아파트 분양 정보", "전세 월세 비교", "대출 금리 비교", "신용카드 혜택", "절세 방법",
    "챗GPT 활용법", "AI 투자 도구", "스마트폰 추천", "유튜브 수익화", "블로그 수익화",
    "법률 상식", "이혼 절차", "상속세 계산", "교통사고 처리", "소비자 권리",
    "건강검진 추천", "영양제 효능", "혈당 관리법", "면역력 높이는 법", "수면의 질 높이기",
]

_FALLBACK_KEYWORDS_EN = [
    "passive income ideas", "investing for beginners", "weight loss tips", "remote work productivity",
    "best travel destinations", "healthy meal prep", "personal finance tips", "side hustle ideas",
    "tech gadgets review", "home workout routines", "credit card rewards", "tax saving strategies",
    "real estate investing", "crypto for beginners", "AI tools productivity", "freelancing tips",
    "retirement planning", "dividend investing", "budget travel hacks", "online courses worth it",
]


def _load_used_keywords() -> dict:
    """최근 사용된 키워드 목록을 로드합니다."""
    if os.path.exists(_USED_KW_FILE):
        try:
            with open(_USED_KW_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"keywords": []}


def _save_used_keywords(used: list[str]) -> None:
    """사용된 키워드 목록을 저장합니다 (최근 300개 유지)."""
    os.makedirs(os.path.dirname(_USED_KW_FILE), exist_ok=True)
    with open(_USED_KW_FILE, "w", encoding="utf-8") as f:
        json.dump({"keywords": used[-300:], "updatedAt": datetime.now().isoformat()}, f, ensure_ascii=False, indent=2)


def _google_trends_rss(country: str = "KR", count: int = 10) -> list[str]:
    """Google Trends 일간 트렌드 RSS에서 키워드를 수집합니다."""
    url = f"https://trends.google.com/trends/trendingsearches/daily/rss?geo={country.upper()}"
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

        logger.info(f"Google Trends {country}: {len(keywords)}개 키워드 수집")
        return keywords
    except Exception as e:
        logger.debug(f"Google Trends RSS 오류: {e}")
        return []


def _naver_datalab_keywords(client_id: str, client_secret: str, count: int = 10) -> list[str]:
    """Naver DataLab 검색어 트렌드 API (선택적)."""
    if not client_id or not client_secret:
        return []
    try:
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
            try:
                results = r.json().get("results", [])
            except ValueError:
                logger.debug("Naver DataLab API 응답이 JSON이 아님")
                return []
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
    트렌드 키워드를 수집합니다. 이미 사용된 키워드는 건너뜁니다.
    우선순위: Google Trends RSS → Naver DataLab → 고정 폴백 목록
    """
    used_data = _load_used_keywords()
    used_set = set(used_data.get("keywords", []))

    candidates: list[str] = []

    # 1순위: Google Trends RSS
    candidates = _google_trends_rss(country, count * 3)

    # 2순위: Naver DataLab
    if len(candidates) < count and naver_client_id:
        candidates += _naver_datalab_keywords(naver_client_id, naver_client_secret, count * 2)

    # 3순위: 고정 폴백 (미사용 키워드 우선)
    if len(candidates) < count:
        fallback = _FALLBACK_KEYWORDS_KR if language == "ko" else _FALLBACK_KEYWORDS_EN
        unused = [kw for kw in fallback if kw not in used_set]
        if not unused:
            unused = fallback  # 모두 사용했으면 전체 목록 재사용
            logger.info("폴백 키워드 전체 재사용 (사이클 완료)")
        else:
            logger.warning(f"외부 트렌드 API 실패 — 미사용 폴백 키워드 {len(unused)}개 사용")
        candidates += unused

    # 중복 제거 및 count 개 선택 (미사용 우선)
    seen: set[str] = set()
    result: list[str] = []

    # 미사용 키워드 우선
    for kw in candidates:
        kw = kw.strip()
        if kw and kw not in seen and kw not in used_set:
            seen.add(kw)
            result.append(kw)
        if len(result) >= count:
            break

    # 부족하면 이미 사용한 것도 포함
    if len(result) < count:
        for kw in candidates:
            kw = kw.strip()
            if kw and kw not in seen:
                seen.add(kw)
                result.append(kw)
            if len(result) >= count:
                break

    # 사용 이력 업데이트
    updated_used = used_data.get("keywords", []) + result
    _save_used_keywords(updated_used)

    logger.info(f"선택된 키워드 {len(result)}개: {result}")
    return result
