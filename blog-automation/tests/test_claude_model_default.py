"""CLAUDE_MODEL이 빈 문자열일 때 기본 모델로 떨어지는지 확인합니다.

워크플로가 `CLAUDE_MODEL="${{ secrets.CLAUDE_MODEL }}"` 형태로 .env를 쓰는데
시크릿이 없으면 빈 값이 들어갑니다. os.getenv의 기본값은 이때 적용되지 않아
API가 400 "model: String should have at least 1 character"로 거절했습니다.
2026-08-22 댓글 자동화 전 건이 이 이유로 실패했습니다.
"""

import importlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _reload_config(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    else:
        monkeypatch.setenv("CLAUDE_MODEL", value)
    # load_dotenv()가 실제 .env로 덮어쓰지 않도록 무력화
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    import config
    return importlib.reload(config)


def test_empty_env_falls_back(monkeypatch):
    cfg = _reload_config(monkeypatch, "")
    assert cfg.CLAUDE_MODEL == "claude-sonnet-5"


def test_unset_env_falls_back(monkeypatch):
    cfg = _reload_config(monkeypatch, None)
    assert cfg.CLAUDE_MODEL == "claude-sonnet-5"


def test_explicit_env_wins(monkeypatch):
    cfg = _reload_config(monkeypatch, "claude-opus-4-8")
    assert cfg.CLAUDE_MODEL == "claude-opus-4-8"


def test_blank_model_kwarg_is_replaced(monkeypatch):
    """호출부가 model=""를 넘겨도 SDK에 빈 모델이 가지 않아야 합니다."""
    cfg = _reload_config(monkeypatch, "")
    seen = {}

    class _Stream:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            return _Msg()

    class _Msg:
        content = []

    class _Messages:
        def stream(self, **kwargs):
            seen.update(kwargs)
            return _Stream()

    class _Client:
        messages = _Messages()

    cfg.claude_generate(_Client(), model="", max_tokens=10,
                        messages=[{"role": "user", "content": "hi"}])
    assert seen["model"] == "claude-sonnet-5"
