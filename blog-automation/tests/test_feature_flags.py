"""기능 on/off 스위치."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import feature_flags  # noqa: E402


def _write(tmp_path, data):
    p = tmp_path / "flags.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


def test_false_disables(tmp_path, monkeypatch):
    monkeypatch.delenv("FEATURE_COMMENT_AUTOMATION", raising=False)
    path = _write(tmp_path, {"comment_automation": False})
    assert feature_flags.is_enabled("comment_automation", path) is False


def test_true_enables(tmp_path, monkeypatch):
    monkeypatch.delenv("FEATURE_COMMENT_AUTOMATION", raising=False)
    path = _write(tmp_path, {"comment_automation": True})
    assert feature_flags.is_enabled("comment_automation", path) is True


def test_unknown_flag_defaults_on(tmp_path, monkeypatch):
    monkeypatch.delenv("FEATURE_SOMETHING_NEW", raising=False)
    path = _write(tmp_path, {})
    assert feature_flags.is_enabled("something_new", path) is True


def test_missing_file_defaults_on(monkeypatch):
    monkeypatch.delenv("FEATURE_ANYTHING", raising=False)
    assert feature_flags.is_enabled("anything", "/nonexistent/flags.json") is True


def test_env_overrides_file(tmp_path, monkeypatch):
    path = _write(tmp_path, {"comment_automation": False})
    monkeypatch.setenv("FEATURE_COMMENT_AUTOMATION", "true")
    assert feature_flags.is_enabled("comment_automation", path) is True
    monkeypatch.setenv("FEATURE_COMMENT_AUTOMATION", "off")
    assert feature_flags.is_enabled("comment_automation", path) is False


def test_require_returns_flag(tmp_path, monkeypatch, caplog):
    import logging
    caplog.set_level(logging.INFO, logger=feature_flags.logger.name)
    monkeypatch.delenv("FEATURE_COMMENT_AUTOMATION", raising=False)
    path = _write(tmp_path, {"comment_automation": False})
    assert feature_flags.require("comment_automation", path) is False
    assert "꺼져 있어" in caplog.text


def test_shipped_file_is_valid_and_comments_are_off():
    """지금 저장소 상태 — 댓글 기능은 꺼져 있어야 합니다."""
    flags = feature_flags.load_flags()
    assert flags.get("comment_automation") is False
