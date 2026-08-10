"""운영 알림 워치독 (alert_notifier) 테스트.

실행: cd blog-automation && python -m pytest tests/test_alert_notifier.py -v
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _runs_response(runs):
    r = MagicMock(status_code=200)
    r.json.return_value = {"workflow_runs": runs}
    return r


def _run(name="블로그 자동 발행", path=".github/workflows/blog-run.yml", rid=1):
    return {"id": rid, "name": name, "path": path,
            "created_at": "2026-08-10T00:00:00Z",
            "html_url": f"https://github.com/x/y/actions/runs/{rid}"}


# ──────────────────────────────────────────────────────────────────────────────
# 워크플로 실패 수집
# ──────────────────────────────────────────────────────────────────────────────

def test_fetch_failed_runs_returns_our_workflows():
    from alert_notifier import fetch_failed_runs
    with patch("requests.get", return_value=_runs_response([_run()])):
        out = fetch_failed_runs("o/r", "tok")
    assert len(out) == 1 and out[0]["id"] == 1


def test_fetch_failed_runs_ignores_npm_cli_fork_workflows():
    """포크에서 딸려온 npm/cli 워크플로 실패는 우리 문제가 아님."""
    from alert_notifier import fetch_failed_runs
    runs = [_run(path=".github/workflows/ci-release.yml", rid=1),
            _run(path=".github/workflows/codeql-analysis.yml", rid=2),
            _run(path=".github/workflows/blog-run.yml", rid=3)]
    with patch("requests.get", return_value=_runs_response(runs)):
        out = fetch_failed_runs("o/r", "tok")
    assert [r["id"] for r in out] == [3]


def test_fetch_failed_runs_without_token_returns_empty():
    from alert_notifier import fetch_failed_runs
    with patch("requests.get") as m:
        assert fetch_failed_runs("o/r", "") == []
    assert not m.called


def test_fetch_failed_runs_survives_api_error():
    """조회가 안 된다고 워치독이 죽으면 알림 자체가 사라짐."""
    from alert_notifier import fetch_failed_runs
    with patch("requests.get", return_value=MagicMock(status_code=403, text="nope")):
        assert fetch_failed_runs("o/r", "tok") == []


def test_fetch_failed_runs_survives_network_exception():
    import requests
    from alert_notifier import fetch_failed_runs
    with patch("requests.get", side_effect=requests.exceptions.Timeout()):
        assert fetch_failed_runs("o/r", "tok") == []


# ──────────────────────────────────────────────────────────────────────────────
# 시스템 상태 수집
# ──────────────────────────────────────────────────────────────────────────────

def _setup_data(tmp_path, monkeypatch, **files):
    import alert_notifier as an
    monkeypatch.setattr(an, "_DOCS_DATA", str(tmp_path))
    for name, data in files.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False),
                                               encoding="utf-8")
    return an


def test_low_health_score_alerts(tmp_path, monkeypatch):
    an = _setup_data(tmp_path, monkeypatch, repairs=[{"health_score": 40, "issues": []}])
    assert any("건강점수" in a["text"] for a in an.collect_system_alerts())


def test_healthy_score_does_not_alert(tmp_path, monkeypatch):
    an = _setup_data(tmp_path, monkeypatch, repairs=[{"health_score": 95, "issues": []}])
    assert an.collect_system_alerts() == []


def test_transient_auth_failure_is_not_alerted(tmp_path, monkeypatch):
    """429/5xx는 설정 문제가 아니므로 알리면 거짓 경보가 됨."""
    an = _setup_data(tmp_path, monkeypatch, auth_health={
        "checks": [{"name": "ads.txt", "ok": False, "transient": True, "error": "429"}]})
    assert an.collect_system_alerts() == []


def test_real_auth_failure_is_alerted(tmp_path, monkeypatch):
    an = _setup_data(tmp_path, monkeypatch, auth_health={
        "checks": [{"name": "Blogger", "ok": False, "error": "invalid_grant"}]})
    alerts = an.collect_system_alerts()
    assert len(alerts) == 1 and "invalid_grant" in alerts[0]["text"]


def test_measurement_dead_is_alerted(tmp_path, monkeypatch):
    an = _setup_data(tmp_path, monkeypatch, analytics_summary={
        "dataSource": {"bloggerApi": False, "gscPageData": False}})
    assert any(a["key"] == "measurement_dead" for a in an.collect_system_alerts())


def test_missing_reports_do_not_crash(tmp_path, monkeypatch):
    an = _setup_data(tmp_path, monkeypatch)
    assert an.collect_system_alerts() == []


# ──────────────────────────────────────────────────────────────────────────────
# 중복 억제 — 같은 문제로 매 실행마다 알리지 않아야 함
# ──────────────────────────────────────────────────────────────────────────────

def _isolate(tmp_path, monkeypatch):
    import alert_notifier as an
    monkeypatch.setattr(an, "_DOCS_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(an, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(an, "REPORT_PATH", str(tmp_path / "alerts.json"))
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    return an


def test_same_failure_is_not_notified_twice(tmp_path, monkeypatch):
    an = _isolate(tmp_path, monkeypatch)
    with patch("requests.get", return_value=_runs_response([_run()])):
        first = an.run()
        second = an.run()
    assert first["newFailedRuns"] == 1
    assert second["newFailedRuns"] == 0
    assert second["failedRuns"]        # 현황에는 계속 보임


def test_new_failure_after_seen_one_is_notified(tmp_path, monkeypatch):
    an = _isolate(tmp_path, monkeypatch)
    with patch("requests.get", return_value=_runs_response([_run(rid=1)])):
        an.run()
    with patch("requests.get", return_value=_runs_response([_run(rid=1), _run(rid=2)])):
        report = an.run()
    assert report["newFailedRuns"] == 1


def test_dry_run_does_not_record_state(tmp_path, monkeypatch):
    an = _isolate(tmp_path, monkeypatch)
    with patch("requests.get", return_value=_runs_response([_run()])):
        an.run(dry_run=True)
        again = an.run(dry_run=True)
    assert again["newFailedRuns"] == 1   # 기록하지 않았으므로 계속 새 건


def test_report_is_written_even_when_nothing_wrong(tmp_path, monkeypatch):
    an = _isolate(tmp_path, monkeypatch)
    with patch("requests.get", return_value=_runs_response([])):
        an.run()
    assert json.loads((tmp_path / "alerts.json").read_text(encoding="utf-8"))["failedRuns"] == []


# ──────────────────────────────────────────────────────────────────────────────
# 발송 / 종료코드
# ──────────────────────────────────────────────────────────────────────────────

def test_send_telegram_without_config_returns_false(monkeypatch):
    from alert_notifier import send_telegram
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert send_telegram("hi") is False


def test_send_telegram_failure_is_swallowed(monkeypatch):
    import requests
    from alert_notifier import send_telegram
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    with patch("requests.post", side_effect=requests.exceptions.Timeout()):
        assert send_telegram("hi") is False


def test_build_message_truncates_long_run_list():
    from alert_notifier import build_message
    runs = [{"name": "w", "url": f"u{i}"} for i in range(9)]
    msg = build_message(runs, [])
    assert "외 4건" in msg


def test_main_returns_zero_even_on_alerts(tmp_path, monkeypatch):
    """알림이 떴다고 워크플로가 빨개지면 알림 자체를 끄게 됨."""
    an = _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["alert_notifier.py", "--dry-run"])
    with patch("requests.get", return_value=_runs_response([_run()])):
        assert an.main() == 0


def test_old_report_without_transient_flag_is_still_filtered(tmp_path, monkeypatch):
    """transient 필드가 없던 시절 리포트도 429를 설정 오류로 알리면 안 됨."""
    an = _setup_data(tmp_path, monkeypatch, auth_health={
        "checks": [{"name": "ads_txt:A", "ok": False,
                    "error": "HTTP 429 — Blogger 설정 → 수익에서 맞춤 ads.txt를 켜세요"}]})
    assert an.collect_system_alerts() == []
