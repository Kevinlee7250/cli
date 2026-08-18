"""Google 인증 설정 스크립트 테스트.

핵심은 "토큰은 받았지만 권한이 모자란" 경우를 그 자리에서 잡아내는 것입니다.
이걸 놓쳐서 사이트맵 제출이 몇 달간 403으로 실패했습니다.

실행: cd blog-automation && python -m pytest tests/test_setup_google_auth.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

WRITE = "https://www.googleapis.com/auth/webmasters"
READONLY = "https://www.googleapis.com/auth/webmasters.readonly"
BLOGGER = "https://www.googleapis.com/auth/blogger"
ADSENSE = "https://www.googleapis.com/auth/adsense.readonly"


def test_readonly_webmasters_is_rejected():
    """readonly는 webmasters를 부분 문자열로 포함 — 통과시키면 안 됨."""
    from setup_google_auth import verify_scopes
    missing = verify_scopes(f"{BLOGGER} {READONLY} {ADSENSE}")
    assert WRITE in missing


def test_all_scopes_present_passes():
    from setup_google_auth import verify_scopes
    assert verify_scopes(f"{BLOGGER} {WRITE} {ADSENSE}") == []


def test_partial_consent_reports_each_missing_scope():
    """사용자가 동의 화면에서 일부만 체크하면 빠진 항목을 전부 알려야 함."""
    from setup_google_auth import verify_scopes
    missing = verify_scopes(BLOGGER)
    assert set(missing) == {WRITE, ADSENSE}


def test_empty_scope_reports_all_missing():
    from setup_google_auth import verify_scopes
    assert len(verify_scopes("")) == 3


def test_scope_order_does_not_matter():
    from setup_google_auth import verify_scopes
    assert verify_scopes(f"{ADSENSE} {WRITE}  {BLOGGER}") == []


def test_every_scope_has_a_stated_purpose():
    """권한이 모자랄 때 '무엇이 망가지는지'를 말할 수 있어야 함."""
    from setup_google_auth import SCOPES, _SCOPE_PURPOSE
    assert all(s in _SCOPE_PURPOSE and _SCOPE_PURPOSE[s] for s in SCOPES)


def test_save_env_does_not_duplicate_and_is_ignored(tmp_path, monkeypatch):
    import setup_google_auth as sg
    env = tmp_path / ".env"
    env.write_text('OTHER="x"\nGOOGLE_REFRESH_TOKEN="old"\n', encoding="utf-8")
    monkeypatch.setattr(sg.os.path, "dirname", lambda _: str(tmp_path))

    sg.save_env("new-token")

    text = env.read_text(encoding="utf-8")
    assert text.count("GOOGLE_REFRESH_TOKEN=") == 1   # 옛 줄이 남으면 옛 토큰이 계속 쓰임
    assert "new-token" in text
    assert 'OTHER="x"' in text                        # 다른 설정은 보존


# ──────────────────────────────────────────────────────────────────────────────
# 자격증명 형식 검증 — 구글은 401 invalid_client만 주고 이유를 말해주지 않음
# ──────────────────────────────────────────────────────────────────────────────

VALID_ID = "123-abc.apps.googleusercontent.com"
VALID_SECRET = "GOCSPX-abcdef123456"


def test_valid_credentials_pass_through():
    from setup_google_auth import _validate_credentials
    assert _validate_credentials(VALID_ID, VALID_SECRET) == (VALID_ID, VALID_SECRET)


def test_quotes_from_cmd_set_are_stripped():
    """cmd의 set X="값" 은 따옴표까지 값에 넣어버림."""
    from setup_google_auth import _validate_credentials
    cid, sec = _validate_credentials(f'"{VALID_ID}"', f'"{VALID_SECRET}"')
    assert cid == VALID_ID and sec == VALID_SECRET


def test_placeholder_text_is_rejected():
    """안내문의 자리표시자를 그대로 넣은 경우 (실제로 발생)."""
    import pytest
    from setup_google_auth import _validate_credentials
    with pytest.raises(SystemExit):
        _validate_credentials("여기에_실제_클라이언트_ID", VALID_SECRET)


def test_wrong_id_suffix_is_rejected():
    import pytest
    from setup_google_auth import _validate_credentials
    with pytest.raises(SystemExit):
        _validate_credentials("123456", VALID_SECRET)


def test_old_style_secret_only_warns():
    """옛 형식 시크릿은 정상일 수 있으므로 경고만 하고 진행."""
    from setup_google_auth import _validate_credentials
    cid, sec = _validate_credentials(VALID_ID, "old-style-secret")
    assert cid == VALID_ID and sec == "old-style-secret"


def test_mask_never_reveals_whole_secret():
    from setup_google_auth import _mask
    masked = _mask(VALID_SECRET)
    assert VALID_SECRET not in masked and "…" in masked


def test_set_port_updates_redirect_uri():
    """콘솔에 등록된 URI와 한 글자라도 다르면 redirect_uri_mismatch가 남."""
    import setup_google_auth as sg
    original = sg.DEFAULT_PORT
    try:
        sg.set_port(9090)
        assert sg.REDIRECT_URI == "http://localhost:9090"
    finally:
        sg.set_port(original)


def test_default_redirect_uri_has_port():
    import setup_google_auth as sg
    assert sg.REDIRECT_URI == f"http://localhost:{sg.DEFAULT_PORT}"
