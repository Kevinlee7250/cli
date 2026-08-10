"""성과 측정 복구 회귀 테스트 (2026-08-10 점검에서 발견).

Blogger 조회수가 항상 0이던 파싱 버그, URL 형식 차이로 GSC 매칭이
전멸하던 문제, 그리고 이런 상태를 조용히 넘기지 않기 위한 진단.

실행: cd blog-automation && python -m pytest tests/test_measurement_health.py -v
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ──────────────────────────────────────────────────────────────────────────────
# Blogger pageviews 파싱 — 요청 라벨과 응답 timeRange 형식이 다름
# ──────────────────────────────────────────────────────────────────────────────

def test_pageviews_parsed_when_response_uses_different_label():
    """요청은 30DAYS, 응답 timeRange는 THIRTY_DAYS — 이 불일치로 항상 0이었음."""
    import blog_analytics as ba
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"counts": [{"timeRange": "THIRTY_DAYS", "count": "1234"}]}
    with patch("requests.get", return_value=resp):
        result = ba.fetch_blogger_pageviews("blogid", "tok")
    assert result["total_30d"] == 1234


def test_pageviews_does_not_request_unsupported_1days():
    """1DAYS는 Blogger가 400을 내는 값 — 호출하면 안 됨."""
    import blog_analytics as ba
    ranges = []

    def fake_get(url, headers=None, params=None, timeout=None):
        ranges.append(params.get("range"))
        r = MagicMock(status_code=200)
        r.json.return_value = {"counts": [{"timeRange": "X", "count": 1}]}
        return r

    with patch("requests.get", side_effect=fake_get):
        ba.fetch_blogger_pageviews("blogid", "tok")
    assert "1DAYS" not in ranges
    assert set(ranges) == {"30DAYS", "7DAYS"}


def test_pageviews_zero_when_counts_empty():
    import blog_analytics as ba
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"counts": []}
    with patch("requests.get", return_value=resp):
        result = ba.fetch_blogger_pageviews("blogid", "tok")
    assert result["total_30d"] == 0


def test_pageviews_stops_on_403():
    import blog_analytics as ba
    with patch("requests.get", return_value=MagicMock(status_code=403, text="denied")) as m:
        result = ba.fetch_blogger_pageviews("blogid", "tok")
    assert result["total_30d"] == 0
    assert m.call_count == 1      # 권한 없으면 즉시 중단


# ──────────────────────────────────────────────────────────────────────────────
# URL 정규화 — 도메인 전환·www·슬래시 차이 흡수
# ──────────────────────────────────────────────────────────────────────────────

def test_normalize_url_absorbs_www_scheme_slash():
    from blog_analytics import _normalize_url
    a = _normalize_url("https://www.hoguwhat.com/2026/08/a.html")
    b = _normalize_url("http://hoguwhat.com/2026/08/a.html/")
    assert a == b == "hoguwhat.com/2026/08/a.html"


def test_normalize_url_handles_empty():
    from blog_analytics import _normalize_url
    assert _normalize_url("") == ""
    assert _normalize_url(None) == ""


def test_estimate_pageviews_matches_despite_url_format_difference():
    """GSC는 www 있는 URL, posts.json은 없는 URL이어도 매칭돼야 함."""
    from blog_analytics import estimate_post_pageviews
    gsc = {"https://www.hoguwhat.com/2026/08/a.html": {"clicks": 10}}
    views = estimate_post_pageviews(
        "http://hoguwhat.com/2026/08/a.html/", gsc,
        total_blog_views_30d=0, total_gsc_clicks=0, total_posts=1,
    )
    assert views == 150   # clicks 10 × 경험적 배율 15


def test_estimate_pageviews_exact_match_still_works():
    from blog_analytics import estimate_post_pageviews
    gsc = {"https://x.com/a": {"clicks": 2}}
    assert estimate_post_pageviews("https://x.com/a", gsc, 0, 0, 1) == 30


# ──────────────────────────────────────────────────────────────────────────────
# 측정 상태 진단 — 조용한 실패를 경보로
# ──────────────────────────────────────────────────────────────────────────────

def _write_summary(tmp_path, monkeypatch, data):
    import auto_repair as ar
    p = tmp_path / "analytics_summary.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(ar, "ANALYTICS_SUMMARY", str(p))
    return ar


def test_measurement_dead_is_critical(tmp_path, monkeypatch):
    ar = _write_summary(tmp_path, monkeypatch, {
        "totalPosts": 100,
        "dataSource": {"bloggerApi": False, "gscPageData": False},
    })
    issues = ar._diagnose_measurement_health()
    assert any(i["id"] == "measurement_dead" and i["level"] == "critical" for i in issues)


def test_gsc_url_mismatch_detected(tmp_path, monkeypatch):
    """GSC는 데이터를 주는데 매칭률이 바닥 — 도메인 전환 사고의 신호."""
    ar = _write_summary(tmp_path, monkeypatch, {
        "totalPosts": 100,
        "dataSource": {"bloggerApi": True, "gscPageData": True,
                       "gscUrlsSeen": 300, "gscMatchRate": 0.0, "postsWithoutUrl": 0},
    })
    issues = ar._diagnose_measurement_health()
    assert any(i["id"] == "gsc_url_mismatch" for i in issues)


def test_healthy_measurement_reports_nothing(tmp_path, monkeypatch):
    ar = _write_summary(tmp_path, monkeypatch, {
        "totalPosts": 100,
        "dataSource": {"bloggerApi": True, "gscPageData": True,
                       "gscUrlsSeen": 300, "gscMatchRate": 85.0, "postsWithoutUrl": 2},
    })
    assert ar._diagnose_measurement_health() == []


def test_missing_url_ratio_flagged(tmp_path, monkeypatch):
    ar = _write_summary(tmp_path, monkeypatch, {
        "totalPosts": 100,
        "dataSource": {"bloggerApi": True, "gscPageData": True,
                       "gscUrlsSeen": 300, "gscMatchRate": 85.0, "postsWithoutUrl": 30},
    })
    issues = ar._diagnose_measurement_health()
    assert any(i["id"] == "posts_missing_url" for i in issues)


def test_no_alert_before_first_analysis(tmp_path, monkeypatch):
    """분석을 아직 안 돌린 상태에서 경보를 내면 소음이 됨."""
    import auto_repair as ar
    monkeypatch.setattr(ar, "ANALYTICS_SUMMARY", str(tmp_path / "nope.json"))
    assert ar._diagnose_measurement_health() == []
