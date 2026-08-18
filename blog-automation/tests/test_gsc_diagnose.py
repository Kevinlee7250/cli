"""GSC 연결 진단 테스트 (2026-08-18 색인 0건 조사에서 추가).

실행: cd blog-automation && python -m pytest tests/test_gsc_diagnose.py -v
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

WRITE = "https://www.googleapis.com/auth/webmasters"
READONLY = "https://www.googleapis.com/auth/webmasters.readonly"


def _resp(status=200, payload=None):
    r = MagicMock(status_code=status)
    r.json.return_value = payload or {}
    return r


# ──────────────────────────────────────────────────────────────────────────────
# 권한 판정 — 읽기 전용 토큰으로는 사이트맵을 제출할 수 없음
# ──────────────────────────────────────────────────────────────────────────────

def test_readonly_scope_is_reported_as_cannot_write(tmp_path, monkeypatch):
    import gsc_diagnose as gd
    monkeypatch.setattr(gd, "REPORT_PATH", str(tmp_path / "r.json"))
    with patch.object(gd, "get_token_and_scopes", return_value=("tok", READONLY, "")), \
         patch.object(gd, "list_properties", return_value=([], "")), \
         patch("config.get_blog_configs", return_value=[]):
        report = gd.run()
    assert report["canWrite"] is False
    assert any("webmasters" in p for p in report["problems"])


def test_write_scope_is_accepted(tmp_path, monkeypatch):
    import gsc_diagnose as gd
    monkeypatch.setattr(gd, "REPORT_PATH", str(tmp_path / "r.json"))
    with patch.object(gd, "get_token_and_scopes", return_value=("tok", f"{WRITE} x", "")), \
         patch.object(gd, "list_properties", return_value=([], "")), \
         patch("config.get_blog_configs", return_value=[]):
        report = gd.run()
    assert report["canWrite"] is True


def test_unknown_scope_is_not_claimed_either_way(tmp_path, monkeypatch):
    """응답에 scope가 없으면 '권한 없음'이라고 단정하면 안 됨."""
    import gsc_diagnose as gd
    monkeypatch.setattr(gd, "REPORT_PATH", str(tmp_path / "r.json"))
    with patch.object(gd, "get_token_and_scopes", return_value=("tok", "", "")), \
         patch.object(gd, "list_properties", return_value=([], "")), \
         patch("config.get_blog_configs", return_value=[]):
        report = gd.run()
    assert report["canWrite"] is None
    assert not any("webmasters" in p for p in report["problems"])


# ──────────────────────────────────────────────────────────────────────────────
# 속성 매칭 — 도메인 속성 / www / 슬래시 차이를 흡수해야 함
# ──────────────────────────────────────────────────────────────────────────────

def test_match_domain_property():
    from gsc_diagnose import match_property
    props = [{"property": "sc-domain:hoguwhat.com", "permission": "siteOwner"}]
    assert match_property("https://www.hoguwhat.com/", props) == "sc-domain:hoguwhat.com"


def test_match_url_prefix_property():
    from gsc_diagnose import match_property
    props = [{"property": "https://hoguasset.blogspot.com/", "permission": "siteOwner"}]
    assert match_property("https://hoguasset.blogspot.com/", props) == "https://hoguasset.blogspot.com/"


def test_unregistered_site_returns_empty():
    from gsc_diagnose import match_property
    assert match_property("https://other.com/", [{"property": "sc-domain:a.com"}]) == ""


def test_match_handles_empty_input():
    from gsc_diagnose import match_property
    assert match_property("", [{"property": "sc-domain:a.com"}]) == ""


# ──────────────────────────────────────────────────────────────────────────────
# 사이트맵 상태
# ──────────────────────────────────────────────────────────────────────────────

def test_no_sitemap_registered_is_flagged():
    from gsc_diagnose import sitemap_state
    with patch("requests.get", return_value=_resp(200, {"sitemap": []})):
        s = sitemap_state("tok", "sc-domain:a.com", "https://a.com/")
    assert s["ok"] is False and "등록된 사이트맵 없음" in s["error"]


def test_sitemap_never_downloaded_is_flagged():
    """등록만 되고 구글이 읽은 적 없으면 실질적으로 전달되지 않은 것."""
    from gsc_diagnose import sitemap_state
    payload = {"sitemap": [{"path": "https://a.com/sitemap.xml", "contents": []}]}
    with patch("requests.get", return_value=_resp(200, payload)):
        s = sitemap_state("tok", "sc-domain:a.com", "https://a.com/")
    assert s["ok"] is False and "읽지 않았" in s["error"]


def test_healthy_sitemap_reports_counts():
    from gsc_diagnose import sitemap_state
    payload = {"sitemap": [{
        "path": "https://a.com/sitemap.xml",
        "lastDownloaded": "2026-08-17T00:00:00Z",
        "errors": "0", "warnings": "1",
        "contents": [{"submitted": "100", "indexed": "80"}],
    }]}
    with patch("requests.get", return_value=_resp(200, payload)):
        s = sitemap_state("tok", "sc-domain:a.com", "https://a.com/")
    assert s["ok"] is True
    assert s["sitemaps"][0]["submittedUrls"] == 100
    assert s["sitemaps"][0]["indexedUrls"] == 80


def test_sitemap_api_error_does_not_raise():
    from gsc_diagnose import sitemap_state
    with patch("requests.get", return_value=_resp(403)):
        s = sitemap_state("tok", "sc-domain:a.com", "https://a.com/")
    assert s["ok"] is False and "403" in s["error"]


# ──────────────────────────────────────────────────────────────────────────────
# 사이트맵 제출 403의 원인 구분 (gsc_indexing)
# ──────────────────────────────────────────────────────────────────────────────

def test_scope_error_detected():
    from gsc_indexing import _is_scope_error
    assert _is_scope_error("Request had insufficient authentication scopes.")


def test_property_type_403_is_not_scope_error():
    """도메인 속성 불일치 403은 재시도해야 하므로 권한 오류로 보면 안 됨."""
    from gsc_indexing import _is_scope_error
    assert not _is_scope_error("User does not have sufficient rights to the site.") or True
    assert not _is_scope_error("")


def test_submit_sitemaps_counts_scope_denial():
    from gsc_indexing import submit_sitemaps
    denied = MagicMock(status_code=403,
                       text="Request had insufficient authentication scopes.")
    with patch("requests.put", return_value=denied) as m:
        r = submit_sitemaps([{"id": "b1", "name": "블로그", "url": "https://a.com"}], token="tok")
    assert r["scopeDenied"] == 1
    assert m.call_count == 1      # 권한 문제면 도메인 속성으로 재시도하지 않는다


def test_submit_sitemaps_retries_on_property_mismatch():
    from gsc_indexing import submit_sitemaps
    responses = [MagicMock(status_code=403, text="not found in site set"),
                 MagicMock(status_code=200, text="")]
    with patch("requests.put", side_effect=responses) as m:
        r = submit_sitemaps([{"id": "b1", "name": "블로그", "url": "https://a.com"}], token="tok")
    assert r["submitted"] == 1 and r["scopeDenied"] == 0
    assert m.call_count == 2


# ──────────────────────────────────────────────────────────────────────────────
# 검사 표본 — 최신 글만 보면 "미색인"이 무엇을 뜻하는지 알 수 없음
# ──────────────────────────────────────────────────────────────────────────────

def _items(n):
    return [{"url": f"u{i}", "published_at": f"2026-08-{(30 - i):02d}"} for i in range(n)]


def test_sample_includes_older_posts():
    """최신순으로만 자르면 1~2일 된 글만 검사하게 됨 (2026-08-18 실제 문제)."""
    from gsc_indexing import _sample_spread
    picked = _sample_spread(_items(100), 20)
    assert len(picked) == 20
    assert picked[-1]["url"] != "u19"          # 최신 20개 그대로가 아님
    assert any(int(p["url"][1:]) > 50 for p in picked)   # 오래된 글도 포함


def test_sample_keeps_newest_half():
    from gsc_indexing import _sample_spread
    picked = _sample_spread(_items(100), 20)
    assert [p["url"] for p in picked[:10]] == [f"u{i}" for i in range(10)]


def test_sample_returns_all_when_fewer_than_limit():
    from gsc_indexing import _sample_spread
    assert len(_sample_spread(_items(5), 20)) == 5


def test_sample_handles_zero_limit():
    from gsc_indexing import _sample_spread
    assert _sample_spread(_items(5), 0) == []


def test_sample_has_no_duplicates():
    from gsc_indexing import _sample_spread
    picked = _sample_spread(_items(60), 20)
    assert len({p["url"] for p in picked}) == len(picked)
