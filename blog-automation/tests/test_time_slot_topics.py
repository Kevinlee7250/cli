"""스케줄 시간대별 주제 다양화 테스트.

07/12/19시(KST) 실행마다 아침=여행, 점심=스포츠, 저녁=드라마·연예를
우선 다루도록 하는 _current_time_slot()/_prioritize_by_time_slot() 검증.

실행: cd blog-automation && python -m pytest tests/test_time_slot_topics.py -v
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_current_time_slot_morning():
    from keyword_collector import _current_time_slot
    assert _current_time_slot(datetime(2026, 1, 1, 7, 0)) == "morning"
    assert _current_time_slot(datetime(2026, 1, 1, 10, 59)) == "morning"


def test_current_time_slot_noon():
    from keyword_collector import _current_time_slot
    assert _current_time_slot(datetime(2026, 1, 1, 12, 0)) == "noon"
    assert _current_time_slot(datetime(2026, 1, 1, 15, 59)) == "noon"


def test_current_time_slot_evening():
    from keyword_collector import _current_time_slot
    assert _current_time_slot(datetime(2026, 1, 1, 19, 0)) == "evening"
    assert _current_time_slot(datetime(2026, 1, 1, 23, 59)) == "evening"
    assert _current_time_slot(datetime(2026, 1, 1, 0, 0)) == "morning"


def test_prioritize_by_time_slot_morning_favors_travel():
    from keyword_collector import _prioritize_by_time_slot
    kws = ["ETF 월배당 포트폴리오", "부산 1박2일 혼자 여행", "손흥민 결승골 경기 결과"]
    result = _prioritize_by_time_slot(kws, "", "morning")
    assert result[0] == "부산 1박2일 혼자 여행"


def test_prioritize_by_time_slot_noon_favors_sports():
    from keyword_collector import _prioritize_by_time_slot
    kws = ["ETF 월배당 포트폴리오", "부산 1박2일 혼자 여행", "손흥민 결승골 경기 결과"]
    result = _prioritize_by_time_slot(kws, "", "noon")
    assert result[0] == "손흥민 결승골 경기 결과"


def test_prioritize_by_time_slot_evening_favors_drama():
    from keyword_collector import _prioritize_by_time_slot
    kws = ["ETF 월배당 포트폴리오", "SBS 드라마 김부장 리뷰", "손흥민 결승골 경기 결과"]
    result = _prioritize_by_time_slot(kws, "", "evening")
    assert result[0] == "SBS 드라마 김부장 리뷰"


def test_prioritize_preserves_order_within_same_rank():
    """같은 우선순위 안에서는 원래(트렌드) 순서가 유지되어야 함 (안정 정렬)."""
    from keyword_collector import _prioritize_by_time_slot
    kws = ["ETF 투자", "국내여행 축제", "해외여행 항공권"]
    result = _prioritize_by_time_slot(kws, "", "morning")
    assert result == ["국내여행 축제", "해외여행 항공권", "ETF 투자"]


def test_prioritize_no_slot_match_returns_unchanged_order():
    from keyword_collector import _prioritize_by_time_slot
    kws = ["a", "b", "c"]
    assert _prioritize_by_time_slot(kws, "", "unknown_slot") == kws


def test_get_trending_keywords_applies_time_slot_for_mixed_topic_blog(monkeypatch):
    """여행+스포츠+드라마가 섞인 블로그(blog2)는 시간대 우선순위가 실제로 반영되어야 함."""
    import keyword_collector as kc

    monkeypatch.setattr(kc, "_naver_realtime_news", lambda *a, **k: [])
    monkeypatch.setattr(kc, "_google_trends_rss", lambda *a, **k: [
        "ETF 월배당 포트폴리오", "부산 1박2일 혼자 여행", "손흥민 결승골 경기 결과", "SBS 드라마 김부장 리뷰",
    ])
    monkeypatch.setattr(kc, "_current_time_slot", lambda: "noon")
    monkeypatch.setattr(kc, "_load_used_keywords", lambda path: {})
    monkeypatch.setattr(kc, "_get_active_used_set", lambda data: set())
    monkeypatch.setattr(kc, "_load_recent_post_corpus", lambda blog_id="": [])
    monkeypatch.setattr(kc, "_load_other_blogs_recent_keywords", lambda blog_id, days=2: [])

    cfg = {"id": "blog2", "topics": ["국내여행", "해외여행", "스포츠", "드라마", "영화", "연예", "K-POP"]}
    result = kc.get_trending_keywords(country="KR", language="ko", count=3, blog_config=cfg)

    assert result, "결과가 비어있으면 안 됨"
    assert "손흥민 결승골 경기 결과" in result[:2], f"점심 시간대엔 스포츠 키워드가 상위에 와야 함: {result}"
