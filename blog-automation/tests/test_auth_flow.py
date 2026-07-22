"""인증 관련 회귀 테스트 — 2026-07-22 6연쇄 장애에서 얻은 시나리오.

실행: cd blog-automation && python -m pytest tests/test_auth_flow.py -v
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ──────────────────────────────────────────────────────────────────────────────
# auth_health_check — invalid_grant / invalid_client / 성공 시나리오 구분
# ──────────────────────────────────────────────────────────────────────────────

def _set_google_env(monkeypatch, client_id="cid", client_secret="secret", refresh_token="rtok"):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", client_id)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", client_secret)
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", refresh_token)


def test_auth_health_ok_when_token_refresh_succeeds(monkeypatch):
    import auth_health_check as ahc
    _set_google_env(monkeypatch)
    resp = MagicMock(status_code=200)
    with patch("requests.post", return_value=resp):
        result = ahc.check_google_oauth()
    assert result["ok"] is True
    assert result["error"] is None


def test_auth_health_detects_invalid_grant(monkeypatch):
    """refresh_token 자체가 폐기/만료됐을 때 (실제로 겪은 시나리오)."""
    import auth_health_check as ahc
    _set_google_env(monkeypatch)
    resp = MagicMock(status_code=400)
    resp.json.return_value = {"error": "invalid_grant", "error_description": "Bad Request"}
    with patch("requests.post", return_value=resp):
        result = ahc.check_google_oauth()
    assert result["ok"] is False
    assert "invalid_grant" in result["error"]


def test_auth_health_detects_invalid_client(monkeypatch):
    """client_secret이 Secret에 저장된 값과 다를 때 (실제로 겪은 시나리오)."""
    import auth_health_check as ahc
    _set_google_env(monkeypatch)
    resp = MagicMock(status_code=401)
    resp.json.return_value = {"error": "invalid_client", "error_description": "The provided client secret is invalid."}
    with patch("requests.post", return_value=resp):
        result = ahc.check_google_oauth()
    assert result["ok"] is False
    assert "invalid_client" in result["error"]


def test_auth_health_reports_missing_env(monkeypatch):
    monkeypatch.delenv("GOOGLE_REFRESH_TOKEN", raising=False)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    import auth_health_check as ahc
    result = ahc.check_google_oauth()
    assert result["ok"] is False


# ──────────────────────────────────────────────────────────────────────────────
# GSC 도메인 속성(sc-domain:) 폴백 — 커스텀 도메인 403 우회
# ──────────────────────────────────────────────────────────────────────────────

def test_gsc_domain_property_fallback_on_403():
    """URL-프리픽스 조회가 403이면 sc-domain: 형식으로 자동 재시도한다."""
    import blog_analytics as ba

    calls = []

    def fake_post(url, json, headers, timeout):
        calls.append(url)
        resp = MagicMock()
        if "sc-domain" in url:
            resp.status_code = 200
            resp.json.return_value = {"rows": [{"keys": ["https://www.hoguwhat.com/x"],
                                                   "clicks": 1, "impressions": 10, "ctr": 0.1, "position": 3.0}]}
        else:
            resp.status_code = 403
        return resp

    with patch("requests.post", side_effect=fake_post):
        result = ba.fetch_gsc_page_data("https://www.hoguwhat.com/", "token")

    assert len(calls) == 2, "URL-프리픽스 실패 후 도메인 속성으로 재시도해야 함"
    assert "sc-domain%3Ahoguwhat.com" in calls[1]
    assert "https://www.hoguwhat.com/x" in result


def test_gsc_domain_property_not_retried_when_first_call_succeeds():
    """이미 정상 응답이면 불필요한 재시도를 하지 않는다 (blog2/blog3 case)."""
    import blog_analytics as ba

    calls = []

    def fake_post(url, json, headers, timeout):
        calls.append(url)
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"rows": []}
        return resp

    with patch("requests.post", side_effect=fake_post):
        ba.fetch_gsc_page_data("https://hogugolfntraval.blogspot.com/", "token")

    assert len(calls) == 1


# ──────────────────────────────────────────────────────────────────────────────
# 등급 삭제 측정 게이트 — "측정 불가"를 "저성과"로 착각해 삭제하는 것 방지
# ──────────────────────────────────────────────────────────────────────────────

def test_delete_gate_blocks_when_no_real_signal(monkeypatch, tmp_path):
    """2026-07-22 근접 사고 재현: bloggerApi/gscPageData 둘 다 false면 삭제 거부."""
    import delete_low_grade_posts as dlg

    summary_path = tmp_path / "analytics_summary.json"
    summary_path.write_text('{"dataSource": {"bloggerApi": false, "gscPageData": false}}', encoding="utf-8")
    monkeypatch.setattr(dlg, "_ANALYTICS_SUMMARY", str(summary_path))

    msg = dlg._measurement_gate_blocked()
    assert msg is not None
    assert "측정" in msg


def test_delete_gate_passes_when_real_signal_present(monkeypatch, tmp_path):
    import delete_low_grade_posts as dlg

    summary_path = tmp_path / "analytics_summary.json"
    summary_path.write_text('{"dataSource": {"bloggerApi": false, "gscPageData": true}}', encoding="utf-8")
    monkeypatch.setattr(dlg, "_ANALYTICS_SUMMARY", str(summary_path))

    assert dlg._measurement_gate_blocked() is None


def test_delete_gate_blocks_when_no_analytics_file(monkeypatch, tmp_path):
    import delete_low_grade_posts as dlg
    monkeypatch.setattr(dlg, "_ANALYTICS_SUMMARY", str(tmp_path / "missing.json"))
    assert dlg._measurement_gate_blocked() is not None


def test_delete_gate_bypassed_with_force(monkeypatch, tmp_path):
    """--force가 명시되면 게이트 체크 자체를 건너뛴다 (scan_and_delete 진입부만 검증)."""
    import delete_low_grade_posts as dlg

    summary_path = tmp_path / "analytics_summary.json"
    summary_path.write_text('{"dataSource": {"bloggerApi": false, "gscPageData": false}}', encoding="utf-8")
    monkeypatch.setattr(dlg, "_ANALYTICS_SUMMARY", str(summary_path))
    monkeypatch.setattr(dlg, "_load", lambda path, default: [] if "posts.json" in path else default)

    from unittest.mock import patch
    with patch("config.get_blog_configs", return_value=[]):
        report = dlg.scan_and_delete({"B", "C"}, "", dry_run=False, force=True)
    assert not report.get("gated"), "force=True인데 측정 게이트에 막힘"


def test_gsc_indexing_sitemap_submit_domain_fallback():
    """sitemap 제출 API도 동일한 폴백을 타야 한다."""
    import gsc_indexing as gi

    calls = []

    def fake_put(url, headers, timeout):
        calls.append(url)
        resp = MagicMock()
        resp.status_code = 200 if "sc-domain" in url else 403
        resp.text = ""
        return resp

    with patch("requests.put", side_effect=fake_put):
        result = gi.submit_sitemaps(
            [{"id": "blog1", "name": "HOGU What?", "gsc_site_url": "https://www.hoguwhat.com/"}],
            token="token",
        )

    assert result == {"submitted": 1, "failed": 0}
    assert any("sc-domain" in c for c in calls)
