"""트렌드 선점 발행 테스트.

실행: cd blog-automation && python -m pytest tests/test_trend_preempt.py -v
"""

import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


_BLOGS = [
    {"id": "blog1", "name": "여행블로그", "topics": ["국내여행", "해외여행"], "naver_api_queries": []},
    {"id": "blog3", "name": "금융블로그", "topics": ["금융", "주식", "ETF"], "naver_api_queries": []},
]


def _write_trending(path, google=None, naver=None, high_cpc=None):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "collectedAt": "2026-07-22T00:00:00+00:00",
            "sources": {
                "googleTrends": google or [],
                "naverNews": naver or [],
                "highCPC": high_cpc or [],
            },
        }, f, ensure_ascii=False)


def test_multi_source_keyword_scores_higher(monkeypatch, tmp_path):
    import trend_preempt as tp

    trending_path = tmp_path / "trending_keywords.json"
    out_path = tmp_path / "trend_preempt.json"
    _write_trending(
        trending_path,
        google=[{"keyword": "ETF 투자 전략"}],
        naver=[{"keyword": "ETF 투자 전략"}],
    )
    monkeypatch.setattr(tp, "_TRENDING_FILE", str(trending_path))
    monkeypatch.setattr(tp, "_OUT_FILE", str(out_path))
    monkeypatch.setattr(tp, "_all_used_keywords", lambda: set())

    with patch("config.get_blog_configs", return_value=_BLOGS):
        result = tp.detect_candidates(min_score=1)

    assert result["candidates"]
    top = result["candidates"][0]
    assert top["keyword"] == "ETF 투자 전략"
    assert set(top["sources"]) == {"googleTrends", "naverNews"}
    assert top["blogId"] == "blog3"


def test_used_keyword_is_excluded(monkeypatch, tmp_path):
    import trend_preempt as tp

    trending_path = tmp_path / "trending_keywords.json"
    out_path = tmp_path / "trend_preempt.json"
    _write_trending(trending_path, naver=[{"keyword": "국내여행 숨은 명소"}])
    monkeypatch.setattr(tp, "_TRENDING_FILE", str(trending_path))
    monkeypatch.setattr(tp, "_OUT_FILE", str(out_path))
    monkeypatch.setattr(tp, "_all_used_keywords", lambda: {"국내여행 숨은 명소"})

    with patch("config.get_blog_configs", return_value=_BLOGS):
        result = tp.detect_candidates(min_score=1)

    assert result["candidates"] == []


def test_keyword_with_no_matching_blog_topic_is_excluded(monkeypatch, tmp_path):
    import trend_preempt as tp

    trending_path = tmp_path / "trending_keywords.json"
    out_path = tmp_path / "trend_preempt.json"
    _write_trending(trending_path, naver=[{"keyword": "완전히 무관한 화제"}])
    monkeypatch.setattr(tp, "_TRENDING_FILE", str(trending_path))
    monkeypatch.setattr(tp, "_OUT_FILE", str(out_path))
    monkeypatch.setattr(tp, "_all_used_keywords", lambda: set())

    with patch("config.get_blog_configs", return_value=_BLOGS):
        result = tp.detect_candidates(min_score=1)

    assert result["candidates"] == []


def test_min_score_threshold_filters_weak_signals(monkeypatch, tmp_path):
    import trend_preempt as tp

    trending_path = tmp_path / "trending_keywords.json"
    out_path = tmp_path / "trend_preempt.json"
    _write_trending(trending_path, naver=[{"keyword": "국내여행 축제"}])
    monkeypatch.setattr(tp, "_TRENDING_FILE", str(trending_path))
    monkeypatch.setattr(tp, "_OUT_FILE", str(out_path))
    monkeypatch.setattr(tp, "_all_used_keywords", lambda: set())

    with patch("config.get_blog_configs", return_value=_BLOGS):
        result = tp.detect_candidates(min_score=10)

    assert result["candidates"] == []
