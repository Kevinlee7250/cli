"""GSC 검색분석 수집의 도메인 속성 폴백 테스트 (2026-08-20).

커스텀 도메인(blog1 www.hoguwhat.com)이 gsc.json에서 통째로 빠져 있었습니다.
blog_analytics·gsc_indexing에는 sc-domain 폴백이 있는데 gsc_fetcher에만
없어서, 403을 받고 그대로 포기했기 때문입니다.

실행: cd blog-automation && python -m pytest tests/test_gsc_fetcher_domain.py -v
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

SITE = "https://www.hoguwhat.com/"


def _resp(status, rows=None):
    r = MagicMock(status_code=status, text="")
    r.json.return_value = {"rows": rows or []}
    return r


def _no_cache(monkeypatch):
    import gsc_fetcher as gf
    monkeypatch.setattr(gf, "_load_cache", lambda *_: None)
    monkeypatch.setattr(gf, "_save_cache", lambda *a, **k: None)
    monkeypatch.setattr(gf, "_get_access_token", lambda: "tok")
    return gf


# ──────────────────────────────────────────────────────────────────────────────

def test_domain_property_conversion():
    from gsc_fetcher import _domain_property_for
    assert _domain_property_for(SITE) == "sc-domain:hoguwhat.com"
    assert _domain_property_for("https://a.blogspot.com/") == "sc-domain:a.blogspot.com"


def test_domain_property_handles_empty():
    from gsc_fetcher import _domain_property_for
    assert _domain_property_for("") == ""


def test_403_retries_with_domain_property(monkeypatch):
    """URL-프리픽스가 403이면 sc-domain으로 다시 물어야 함."""
    gf = _no_cache(monkeypatch)
    calls = []

    def fake_post(url, **kw):
        calls.append(url)
        return _resp(200, [{"keys": ["여행"], "clicks": 3, "impressions": 100,
                            "ctr": 0.03, "position": 8.1}]) if "sc-domain" in url else _resp(403)

    with patch("requests.post", side_effect=fake_post):
        result = gf.fetch_search_analytics(SITE)

    assert result is not None
    assert result["total_rows"] == 1
    assert len(calls) == 2 and "sc-domain" in calls[1]


def test_success_on_first_try_does_not_retry(monkeypatch):
    gf = _no_cache(monkeypatch)
    with patch("requests.post", return_value=_resp(200)) as m:
        assert gf.fetch_search_analytics(SITE) is not None
    assert m.call_count == 1


def test_both_forms_403_returns_none_with_clear_log(monkeypatch, caplog):
    gf = _no_cache(monkeypatch)
    with patch("requests.post", return_value=_resp(403)):
        assert gf.fetch_search_analytics(SITE) is None
    assert "속성 유형" in caplog.text


def test_network_error_returns_none(monkeypatch):
    import requests as rq
    gf = _no_cache(monkeypatch)
    with patch("requests.post", side_effect=rq.exceptions.Timeout()):
        assert gf.fetch_search_analytics(SITE) is None


def test_no_site_url_returns_none(monkeypatch):
    gf = _no_cache(monkeypatch)
    assert gf.fetch_search_analytics("") is None
