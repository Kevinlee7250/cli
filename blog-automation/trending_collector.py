"""
실시간 트렌드 키워드 수집 → docs/data/trending_keywords.json

실행:
  cd blog-automation && python trending_collector.py
  python trending_collector.py --output ../docs/data/trending_keywords.json
"""
import argparse
import json
import logging
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_BASE_DIR = os.path.dirname(__file__)
_DEFAULT_OUTPUT = os.path.join(_BASE_DIR, "..", "docs", "data", "trending_keywords.json")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

# ──────────────────────────────────────────────────────────────────────────────
# 실시간 검색 소스들
# ──────────────────────────────────────────────────────────────────────────────

_GOOGLE_TRENDS_URLS = [
    # 신규 Trending Now RSS (2025년부터 daily RSS 대체)
    "https://trends.google.com/trending/rss?geo=KR",
    # 구버전 daily RSS (폴백 — 일부 리전에서 아직 동작)
    "https://trends.google.com/trends/trendingsearches/daily/rss?geo=KR",
]


def _google_trends_realtime(count: int = 20) -> list[dict]:
    """구글 트렌드 코리아 실시간 검색어 수집 (RSS)."""
    for url in _GOOGLE_TRENDS_URLS:
        try:
            r = requests.get(url, headers=_HEADERS, timeout=12)
            if r.status_code != 200:
                logger.warning(f"Google Trends RSS 오류 ({url}): HTTP {r.status_code}")
                continue
            root = ET.fromstring(r.content)
            results = []
            for i, item in enumerate(root.iter("item")):
                if len(results) >= count:
                    break
                title_el = item.find("title")
                if title_el is None:
                    continue
                kw = re.sub(r"<[^>]+>", "", title_el.text or "").strip()
                if not kw:
                    continue
                # 네임스페이스에 상관없이 approx_traffic 태그 탐색
                traffic = ""
                for child in item:
                    if child.tag.endswith("approx_traffic"):
                        traffic = re.sub(r"<[^>]+>", "", child.text or "").strip()
                        break
                results.append({
                    "keyword": kw,
                    "rank": i + 1,
                    "traffic": traffic,
                    "source": "google_trends",
                })
            if results:
                logger.info(f"구글 트렌드: {len(results)}개 수집 ({url})")
                return results
        except Exception as e:
            logger.warning(f"Google Trends RSS 수집 실패 ({url}): {e}")
    return []


# 네이버 RSS(rss.naver.com)는 서비스 종료 → 언론사 직접 RSS로 대체 (실패해도 무해)
_NAVER_RSS_CATEGORIES = {
    "경제": "https://www.mk.co.kr/rss/30100041/",
    "IT과학": "https://www.mk.co.kr/rss/50700001/",
    "생활문화": "https://www.mk.co.kr/rss/50000001/",
    "경제일반": "https://www.hankyung.com/feed/economy",
    "IT": "https://www.hankyung.com/feed/it",
}

_NAVER_API_QUERIES = ["경제 재테크", "건강 의료", "IT AI 기술", "생활 소비", "부동산 청약"]


def _naver_rss_headlines(per_feed: int = 8) -> list[dict]:
    """네이버 뉴스 RSS 카테고리별 헤드라인 수집 (API 키 불필요)."""
    results = []
    seen = set()
    for cat, url in _NAVER_RSS_CATEGORIES.items():
        try:
            r = requests.get(url, headers=_HEADERS, timeout=10)
            if r.status_code != 200:
                continue
            root = ET.fromstring(r.content.decode("utf-8", errors="replace"))
            items = root.findall(".//item")
            for item in items[:per_feed]:
                title_el = item.find("title")
                if title_el is None:
                    continue
                title = re.sub(r"<[^>]+>", "", title_el.text or "").strip()
                title = re.sub(r"\s+", " ", title)
                if not title or title in seen:
                    continue
                seen.add(title)
                results.append({
                    "headline": title,
                    "category": cat,
                    "source": "naver_rss",
                })
        except Exception as e:
            logger.debug(f"Naver RSS ({cat}) 실패: {e}")
    logger.info(f"네이버 RSS 헤드라인: {len(results)}개 수집")
    return results


def _naver_api_news(
    client_id: str,
    client_secret: str,
    per_query: int = 8,
) -> list[dict]:
    """네이버 뉴스 검색 API (API 키 필요)."""
    if not client_id or not client_secret:
        return []
    results = []
    seen = set()
    for q in _NAVER_API_QUERIES:
        try:
            r = requests.get(
                "https://openapi.naver.com/v1/search/news.json",
                headers={
                    "X-Naver-Client-Id": client_id,
                    "X-Naver-Client-Secret": client_secret,
                },
                params={"query": q, "display": per_query, "sort": "date"},
                timeout=10,
            )
            if r.status_code != 200:
                logger.debug(f"Naver API 뉴스 오류 ({q}): HTTP {r.status_code}")
                continue
            for item in r.json().get("items", []):
                title = re.sub(r"<[^>]+>", "", item.get("title", "")).strip()
                title = re.sub(r"\s+", " ", title)
                if not title or title in seen:
                    continue
                seen.add(title)
                results.append({
                    "headline": title,
                    "category": "뉴스",
                    "query": q,
                    "source": "naver_api",
                })
        except Exception as e:
            logger.debug(f"Naver API 뉴스 ({q}) 실패: {e}")
    logger.info(f"네이버 API 뉴스: {len(results)}개 수집")
    return results


# ──────────────────────────────────────────────────────────────────────────────
# 고CPC 키워드 목록 (keyword_collector.py에서 동기화)
# ──────────────────────────────────────────────────────────────────────────────

def _load_high_cpc_keywords() -> list[dict]:
    """keyword_collector의 고CPC 풀에서 메타데이터 포함 목록 반환."""
    try:
        from keyword_collector import (
            _HIGH_CPC_KEYWORDS_BLOG1,
            _HIGH_CPC_KEYWORDS_BLOG2_IT_HCP,
            _HIGH_CPC_KEYWORDS_BLOG3_HCP,
        )
        pool = []
        _CPC_BLOG_META = {
            "blog1": {"label": "블로그1 (여행·생활)", "cpc_range": "$1.8~3.2"},
            "blog2": {"label": "블로그2 (IT·기술)", "cpc_range": "$1.5~3.2"},
            "blog3": {"label": "블로그3 (금융·법률)", "cpc_range": "$2.5~3.5"},
        }
        for kw in _HIGH_CPC_KEYWORDS_BLOG1:
            pool.append({"keyword": kw, "blog": "blog1", **_CPC_BLOG_META["blog1"], "source": "high_cpc"})
        for kw in _HIGH_CPC_KEYWORDS_BLOG2_IT_HCP:
            pool.append({"keyword": kw, "blog": "blog2", **_CPC_BLOG_META["blog2"], "source": "high_cpc"})
        for kw in _HIGH_CPC_KEYWORDS_BLOG3_HCP:
            pool.append({"keyword": kw, "blog": "blog3", **_CPC_BLOG_META["blog3"], "source": "high_cpc"})
        # 최근 사용된 것 제외
        used = _load_used_keywords()
        pool = [x for x in pool if x["keyword"] not in used]
        logger.info(f"고CPC 키워드: {len(pool)}개 (미사용)")
        return pool
    except Exception as e:
        logger.warning(f"고CPC 키워드 로드 실패: {e}")
        return []


def _load_used_keywords() -> set:
    """최근 30일 사용된 키워드 목록."""
    used = set()
    for fname in ["logs/used_keywords.json", "logs/used_keywords_blog2.json", "logs/used_keywords_blog3.json"]:
        fpath = os.path.join(_BASE_DIR, fname)
        if not os.path.exists(fpath):
            continue
        try:
            with open(fpath, encoding="utf-8") as f:
                data = json.load(f)
            entries = data.get("entries", [])
            for e in entries:
                used.add(e.get("keyword", ""))
        except Exception:
            pass
    return used


def _load_ai_recommended() -> list[dict]:
    """최신 학습 리포트에서 AI 추천 키워드 로드. 없으면 Claude로 직접 생성."""
    learning_path = os.path.join(_BASE_DIR, "..", "docs", "data", "learning.json")
    if os.path.exists(learning_path):
        try:
            with open(learning_path, encoding="utf-8") as f:
                data = json.load(f)
            latest = data[0] if data else {}
            kws = latest.get("analysis", {}).get("recommended_keywords", [])
            result = [{"keyword": kw, "source": "ai_recommended"} for kw in kws if kw]
            if result:
                logger.info(f"AI 추천 (학습 리포트): {len(result)}개")
                return result
        except Exception as e:
            logger.debug(f"AI 추천 키워드 로드 실패: {e}")
    # 학습 리포트가 비어있으면 Claude API로 직접 생성
    return _generate_ai_keywords()


def _generate_ai_keywords(count: int = 10) -> list[dict]:
    """Claude API로 시의성 있는 블로그 키워드를 직접 추천받습니다."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key or api_key.startswith("sk-ant-xxx"):
        return []
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        model = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")
        now_str = datetime.now().strftime("%Y년 %m월 %d일")
        used = _load_used_keywords()
        used_text = ", ".join(list(used)[:30]) if used else "없음"
        prompt = (
            f"오늘은 {now_str}입니다. 한국 블로그(재테크·건강·IT·생활정보·여행 카테고리)에 "
            f"올릴 AdSense 고수익 키워드 {count}개를 추천하세요.\n\n"
            "기준:\n"
            "1. 지금 계절·시기에 맞는 시의성 있는 주제 (검색 수요가 실제 있을 것)\n"
            "2. AdSense 안전 — 정치·갈등·선정적 주제 제외\n"
            "3. 경험/방법/비교/후기 각도로 풀 수 있는 구체적 키워드\n"
            f"4. 최근 사용한 키워드와 중복 금지: {used_text}\n\n"
            f'JSON 배열만 응답 (설명 없이): ["키워드1", ..., "키워드{count}"]'
        )
        msg = client.messages.create(
            model=model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
        s, e = raw.find("["), raw.rfind("]")
        if s != -1 and e > s:
            kws = json.loads(raw[s:e + 1])
            if isinstance(kws, list):
                result = [
                    {"keyword": str(k).strip(), "source": "ai_generated"}
                    for k in kws if str(k).strip()
                ][:count]
                logger.info(f"AI 추천 (Claude 생성): {len(result)}개")
                return result
    except Exception as e:
        logger.warning(f"Claude AI 키워드 생성 실패: {e}")
    return []


# ──────────────────────────────────────────────────────────────────────────────
# 헤드라인 → 블로그 키워드 변환 (Claude 없이 규칙 기반)
# ──────────────────────────────────────────────────────────────────────────────

_FLUFF_WORDS = {
    "속보", "단독", "종합", "정리", "확인", "발표", "예정", "관련", "대한",
    "위한", "통해", "따라", "따른", "위해", "이후", "이전", "현재", "오늘",
    "내일", "이번", "이달", "올해", "지난", "최근", "지금", "바로", "직접",
}

def _headline_to_keyword(headline: str, max_words: int = 6) -> str:
    """뉴스 헤드라인에서 블로그 키워드로 변환 (규칙 기반)."""
    # HTML 태그 제거
    text = re.sub(r"<[^>]+>", "", headline).strip()
    # 따옴표, 특수문자 정리
    text = re.sub(r"[「」『』【】\[\]""'']", " ", text)
    # 키워드로 불필요한 접미사 제거
    text = re.sub(r"\.\.\.$", "", text).strip()
    # 핵심 단어 추출
    words = re.findall(r"[가-힣]{2,}|[A-Za-z][A-Za-z0-9]{1,}|\d{4}", text)
    core = [w for w in words if w not in _FLUFF_WORDS][:max_words]
    return " ".join(core) if core else text[:30]


# ──────────────────────────────────────────────────────────────────────────────
# 메인 수집 함수
# ──────────────────────────────────────────────────────────────────────────────

def collect_trending(
    naver_client_id: str = "",
    naver_client_secret: str = "",
    output_path: str = _DEFAULT_OUTPUT,
) -> dict:
    """모든 소스에서 트렌드 키워드를 수집하고 JSON으로 저장합니다."""
    now = datetime.now(timezone.utc).isoformat()

    logger.info("=== 트렌드 키워드 수집 시작 ===")

    # 구글 트렌드 실시간 검색어
    google_trends = _google_trends_realtime(count=20)

    # 네이버 뉴스 RSS + API
    naver_rss = _naver_rss_headlines(per_feed=6)
    naver_api = _naver_api_news(naver_client_id, naver_client_secret, per_query=6)
    naver_news = naver_rss + naver_api

    # 뉴스 헤드라인 → 블로그 키워드 변환
    for item in naver_news:
        item["keyword"] = _headline_to_keyword(item["headline"])

    # 고CPC 미사용 키워드
    high_cpc = _load_high_cpc_keywords()

    # AI 추천 (학습 리포트에서)
    ai_recommended = _load_ai_recommended()

    result = {
        "collectedAt": now,
        "sources": {
            "googleTrends": google_trends,
            "naverNews": naver_news,
            "highCPC": high_cpc[:30],  # 최대 30개
            "aiRecommended": ai_recommended,
        },
        "stats": {
            "googleTrends": len(google_trends),
            "naverNews": len(naver_news),
            "highCPC": len(high_cpc),
            "aiRecommended": len(ai_recommended),
        },
    }

    # 저장
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    logger.info(
        f"=== 수집 완료 → {output_path} | "
        f"구글트렌드 {len(google_trends)}개, "
        f"네이버뉴스 {len(naver_news)}개, "
        f"고CPC {len(high_cpc)}개, "
        f"AI추천 {len(ai_recommended)}개 ==="
    )
    return result


def main():
    parser = argparse.ArgumentParser(description="실시간 트렌드 키워드 수집")
    parser.add_argument("--output", default=_DEFAULT_OUTPUT, help="출력 JSON 파일 경로")
    args = parser.parse_args()

    naver_id = os.getenv("NAVER_CLIENT_ID", "")
    naver_secret = os.getenv("NAVER_CLIENT_SECRET", "")

    collect_trending(
        naver_client_id=naver_id,
        naver_client_secret=naver_secret,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
