"""트렌드 선점 발행 — 정규 스케줄(하루 3회) 사이에 뜨는 급상승 키워드를 감지해
가장 먼저 다뤄야 할 블로그에 배정합니다.

키워드 자체 수집(trending_collector.py)이나 콘텐츠 생성(main.py)을 대체하지
않습니다. 이미 있는 두 시스템 사이의 빈틈 — "지금 뜨는 키워드를 다음 정규
실행(최대 8시간 후)까지 기다리지 않고 바로 글을 써서 선점할 가치가 있는가?"
를 판단하는 신호 계층입니다.

동작:
  1. trending_keywords.json(구글 트렌드 + 네이버 뉴스)에서 후보를 모읍니다.
  2. 이미 사용된 키워드(블로그별 30일 이내)는 제외합니다.
  3. 여러 소스에 동시에 뜬 키워드에 가산점을 줘 "진짜 급상승"만 남깁니다.
  4. blogs.json의 topics/naver_api_queries와 토큰 겹침으로 가장 잘 맞는
     블로그를 배정합니다.
  5. 점수 상위 후보를 docs/data/trend_preempt.json에 저장 — 대시보드에서
     "지금 선점 발행" 버튼으로 blog-run.yml을 즉시 dispatch할 수 있습니다.

Usage:
  python trend_preempt.py                 # 감지만 (기본)
  python trend_preempt.py --min-score 5    # 임계값 조정
"""

import argparse
import json
import logging
import os
import re
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_BASE_DIR = os.path.dirname(__file__)
_DOCS_DATA = os.path.join(_BASE_DIR, "..", "docs", "data")
_TRENDING_FILE = os.path.join(_DOCS_DATA, "trending_keywords.json")
_OUT_FILE = os.path.join(_DOCS_DATA, "trend_preempt.json")

_DEFAULT_MIN_SCORE = 4
_STOPWORDS = {"속보", "단독", "종합", "영상", "포토"}


def _load(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _save(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z0-9]+|[가-힣]+", (text or "").lower())
    return {w for w in words if len(w) > 1 and w not in _STOPWORDS}


def _all_used_keywords() -> set[str]:
    """3개 블로그 전체의 최근 사용 키워드를 합쳐 하나의 제외 집합으로 만듭니다."""
    from keyword_collector import _get_used_kw_file, _load_used_keywords, _get_active_used_set
    from config import get_blog_configs

    used: set[str] = set()
    blog_ids = [b.get("id", "") for b in get_blog_configs()] or [""]
    for blog_id in blog_ids:
        used_file = _get_used_kw_file(blog_id)
        used_data = _load_used_keywords(used_file)
        used |= _get_active_used_set(used_data)
    return used


def _best_blog_match(keyword_tokens: set[str], blogs: list[dict]) -> dict | None:
    best, best_overlap = None, 0
    for b in blogs:
        topic_text = " ".join(b.get("topics", []) + b.get("naver_api_queries", []))
        overlap = len(keyword_tokens & _tokenize(topic_text))
        if overlap > best_overlap:
            best, best_overlap = b, overlap
    if best and best_overlap > 0:
        return {"blogId": best.get("id", ""), "blogName": best.get("name", ""), "topicOverlap": best_overlap}
    return None


def detect_candidates(min_score: int = _DEFAULT_MIN_SCORE) -> dict:
    from config import get_blog_configs

    trending = _load(_TRENDING_FILE, {})
    sources = trending.get("sources", {})
    google_trends = sources.get("googleTrends", [])
    naver_news = sources.get("naverNews", [])
    high_cpc = sources.get("highCPC", [])

    # 키워드별로 등장한 소스 집계 (같은 키워드가 여러 소스에 뜨면 급상승 신뢰도↑)
    appearances: dict[str, dict] = {}

    def _register(items: list[dict], source_name: str, key_field: str):
        for item in items:
            kw = (item.get(key_field) or item.get("keyword") or "").strip()
            if not kw:
                continue
            entry = appearances.setdefault(kw, {"keyword": kw, "sources": set()})
            entry["sources"].add(source_name)

    _register(google_trends, "googleTrends", "keyword")
    _register(naver_news, "naverNews", "keyword")
    _register(high_cpc, "highCPC", "keyword")

    used = _all_used_keywords()
    blogs = get_blog_configs()

    candidates = []
    for kw, entry in appearances.items():
        if kw in used:
            continue
        tokens = _tokenize(kw)
        if not tokens:
            continue

        source_count = len(entry["sources"])
        score = source_count * 3  # 다중 소스 확인 = 가장 강한 신호

        match = _best_blog_match(tokens, blogs)
        if not match:
            continue  # 어떤 블로그 주제와도 안 맞으면 배정 불가 → 제외
        score += min(match["topicOverlap"], 3)

        if score < min_score:
            continue

        candidates.append({
            "keyword": kw,
            "score": score,
            "sources": sorted(entry["sources"]),
            "blogId": match["blogId"],
            "blogName": match["blogName"],
        })

    candidates.sort(key=lambda c: -c["score"])

    result = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "trendingCollectedAt": trending.get("collectedAt"),
        "minScore": min_score,
        "candidates": candidates[:15],
    }
    _save(_OUT_FILE, result)

    logger.info(f"[TrendPreempt] 후보 {len(candidates)}개 (임계값 {min_score} 이상)")
    for c in candidates[:5]:
        logger.info(f"  🔥 [{c['score']}점] {c['keyword']} → {c['blogName']} (소스: {', '.join(c['sources'])})")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="트렌드 선점 발행 후보 감지")
    parser.add_argument("--min-score", type=int, default=_DEFAULT_MIN_SCORE)
    args = parser.parse_args()
    detect_candidates(min_score=args.min_score)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
