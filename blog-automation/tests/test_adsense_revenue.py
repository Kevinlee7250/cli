"""실제 AdSense 수익 연동 (adsense_revenue) 테스트.

실행: cd blog-automation && python -m pytest tests/test_adsense_revenue.py -v
"""

import json
import os
import sys
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _report(rows, headers=("DOMAIN_NAME", "ESTIMATED_EARNINGS", "PAGE_VIEWS",
                           "IMPRESSIONS", "CLICKS", "PAGE_VIEWS_RPM")):
    return {
        "headers": [{"name": h} for h in headers],
        "rows": [{"cells": [{"value": str(v)} for v in r]} for r in rows],
    }


# ──────────────────────────────────────────────────────────────────────────────
# 리포트 파싱
# ──────────────────────────────────────────────────────────────────────────────

def test_parse_report_extracts_earnings_and_rpm():
    from adsense_revenue import parse_report
    out = parse_report(_report([["hoguwhat.com", "12.34", "5000", "9000", "40", "2.47"]]))
    assert out["hoguwhat.com"]["earnings"] == 12.34
    assert out["hoguwhat.com"]["pageViews"] == 5000
    assert out["hoguwhat.com"]["rpm"] == 2.47


def test_parse_report_computes_rpm_when_missing():
    """PAGE_VIEWS_RPM을 안 주는 응답도 있어 직접 계산해야 함."""
    from adsense_revenue import parse_report
    r = _report([["a.com", "10", "5000", "9000", "40"]],
                headers=("DOMAIN_NAME", "ESTIMATED_EARNINGS", "PAGE_VIEWS",
                         "IMPRESSIONS", "CLICKS"))
    assert parse_report(r)["a.com"]["rpm"] == 2.0


def test_parse_report_uses_header_names_not_positions():
    """헤더 순서가 요청 순서와 달라도 값이 뒤바뀌면 안 됨."""
    from adsense_revenue import parse_report
    r = _report([["5000", "hoguwhat.com", "12.34"]],
                headers=("PAGE_VIEWS", "DOMAIN_NAME", "ESTIMATED_EARNINGS"))
    assert parse_report(r)["hoguwhat.com"]["earnings"] == 12.34


def test_parse_report_handles_empty():
    from adsense_revenue import parse_report
    assert parse_report({}) == {}
    assert parse_report({"headers": [], "rows": []}) == {}


# ──────────────────────────────────────────────────────────────────────────────
# 권한 부족 — 조용히 실패하고 추정치로 계속 가야 함
# ──────────────────────────────────────────────────────────────────────────────

def test_token_without_adsense_scope_is_rejected_with_guidance(monkeypatch):
    from adsense_revenue import get_access_token
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "rt")
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"access_token": "at",
                              "scope": "https://www.googleapis.com/auth/blogger"}
    with patch("requests.post", return_value=resp):
        token, err = get_access_token()
    assert token == ""
    assert "adsense.readonly" in err and "get_refresh_token" in err


def test_token_with_adsense_scope_succeeds(monkeypatch):
    from adsense_revenue import get_access_token
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "rt")
    resp = MagicMock(status_code=200)
    resp.json.return_value = {
        "access_token": "at",
        "scope": "https://www.googleapis.com/auth/blogger "
                 "https://www.googleapis.com/auth/adsense.readonly"}
    with patch("requests.post", return_value=resp):
        token, err = get_access_token()
    assert token == "at" and err == ""


def test_403_gives_actionable_message():
    from adsense_revenue import list_accounts
    with patch("requests.get", return_value=MagicMock(status_code=403, text="denied")):
        accounts, err = list_accounts("tok")
    assert accounts == [] and "adsense.readonly" in err


def test_run_without_permission_does_not_raise(tmp_path, monkeypatch):
    """수익 연동이 안 된다고 분석 파이프라인이 멈추면 안 됨."""
    import adsense_revenue as ar
    monkeypatch.setattr(ar, "REPORT_PATH", str(tmp_path / "rev.json"))
    monkeypatch.setattr(ar, "RPM_FILE", str(tmp_path / "rpm.json"))
    monkeypatch.delenv("GOOGLE_REFRESH_TOKEN", raising=False)
    result = ar.run()
    assert result["available"] is False and result["error"]
    assert not os.path.exists(str(tmp_path / "rpm.json"))   # 잘못된 RPM을 남기지 않음


def test_main_returns_zero_without_permission(monkeypatch, tmp_path):
    import adsense_revenue as ar
    monkeypatch.setattr(ar, "REPORT_PATH", str(tmp_path / "rev.json"))
    monkeypatch.setattr(sys, "argv", ["adsense_revenue.py", "--dry-run"])
    monkeypatch.delenv("GOOGLE_REFRESH_TOKEN", raising=False)
    assert ar.main() == 0


# ──────────────────────────────────────────────────────────────────────────────
# 실측 RPM 사용
# ──────────────────────────────────────────────────────────────────────────────

def _write_rpm(tmp_path, monkeypatch, updated, by_domain):
    import adsense_revenue as ar
    p = tmp_path / "rpm.json"
    p.write_text(json.dumps({"updatedAt": updated, "byDomain": by_domain}), encoding="utf-8")
    monkeypatch.setattr(ar, "RPM_FILE", str(p))
    return ar


def test_load_real_rpm_returns_fresh_values(tmp_path, monkeypatch):
    ar = _write_rpm(tmp_path, monkeypatch, date.today().isoformat(), {"a.com": 2.5})
    assert ar.load_real_rpm() == {"a.com": 2.5}


def test_load_real_rpm_ignores_stale_data(tmp_path, monkeypatch):
    """오래된 RPM으로 수익을 계산하면 실측이라는 이름의 거짓말이 됨."""
    old = (date.today() - timedelta(days=90)).isoformat()
    ar = _write_rpm(tmp_path, monkeypatch, old, {"a.com": 2.5})
    assert ar.load_real_rpm() == {}


def test_load_real_rpm_missing_file(tmp_path, monkeypatch):
    import adsense_revenue as ar
    monkeypatch.setattr(ar, "RPM_FILE", str(tmp_path / "nope.json"))
    assert ar.load_real_rpm() == {}


def test_revenue_from_rpm():
    from adsense_revenue import revenue_from_rpm
    assert revenue_from_rpm(5000, 2.0) == 10.0
    assert revenue_from_rpm(0, 2.0) == 0.0
    assert revenue_from_rpm(5000, 0) == 0.0


# ──────────────────────────────────────────────────────────────────────────────
# blog_analytics 연동
# ──────────────────────────────────────────────────────────────────────────────

def test_calculate_revenue_prefers_real_rpm():
    from blog_analytics import calculate_revenue
    r = calculate_revenue(10000, "금융", cpc=2.5, real_rpm=1.0)
    assert r["estimated30d"] == 10.0
    assert r["revenueSource"] == "adsense"


def test_calculate_revenue_falls_back_to_estimate():
    from blog_analytics import calculate_revenue
    r = calculate_revenue(10000, "금융", cpc=2.5)
    assert r["revenueSource"] == "estimate"
    assert r["cpc"] == 2.5


def test_domain_of_strips_www_and_scheme():
    from blog_analytics import _domain_of
    assert _domain_of("https://www.hoguwhat.com/2026/08/a.html") == "hoguwhat.com"
    assert _domain_of("http://a.blogspot.com/x") == "a.blogspot.com"
    assert _domain_of("") == ""
