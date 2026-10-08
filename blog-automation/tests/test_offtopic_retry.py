"""구주제 이전의 429 처리 — 재시도와 '이어서 하기'.

2026-10-08: 금융 글 17편을 blog3로 옮기는 작업이 6편 성공 후 멈췄습니다.
Blogger API가 429 'Resource has been exhausted'를 돌려줬는데 재시도가
없어서 남은 11편이 전부 실패로 떨어졌습니다. 다행히 코드가
'blog3 발행 성공 → 그 다음 blog1 원본 draft 전환' 순서였기 때문에
실패한 글은 blog1에 공개 상태로 그대로 남았습니다. 이 순서가 바뀌면
한쪽에서 사라지고 다른 쪽에 없는 글이 생기므로 테스트로 묶어 둡니다.
"""

import os
import sys
import types

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import migrate_offtopic as mo  # noqa: E402

API = "https://example.invalid/blogger/v3"


class FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _no_sleeping(monkeypatch):
    """테스트가 재시도 대기 때문에 65초 걸리면 안 됩니다."""
    monkeypatch.setattr(mo.time, "sleep", lambda _s: None)


def _fake_requests(monkeypatch, responses):
    """requests.request 를 정해진 응답 목록으로 바꾸고 호출 기록을 돌려줍니다."""
    calls = []

    def _request(method, url, **kw):
        calls.append((method, url))
        return responses[min(len(calls) - 1, len(responses) - 1)]

    monkeypatch.setattr(mo.requests, "request", _request)
    return calls


# ── 재시도 ───────────────────────────────────────────────────────────────────

def test_retries_on_429_then_succeeds(monkeypatch):
    calls = _fake_requests(monkeypatch, [
        FakeResponse(429, text="Resource has been exhausted"),
        FakeResponse(200, {"url": "https://blog3.example/post.html"}),
    ])
    url, status = mo._create_on_blog3(API, "B3", {"title": "ETF", "content": "..."}, "tok")
    assert (url, status) == ("https://blog3.example/post.html", 200)
    assert len(calls) == 2, "한 번 더 시도했어야 합니다"


def test_gives_up_after_all_retries_and_reports_429(monkeypatch):
    calls = _fake_requests(monkeypatch, [FakeResponse(429, text="exhausted")])
    url, status = mo._create_on_blog3(API, "B3", {"title": "ETF", "content": "..."}, "tok")
    assert url == ""
    assert status == 429, "호출자가 할당량 소진을 알아야 멈출 수 있습니다"
    assert len(calls) == 1 + len(mo._RETRY_WAITS)


def test_does_not_retry_a_real_error(monkeypatch):
    """403·404 같은 건 다시 보내도 같은 답입니다."""
    calls = _fake_requests(monkeypatch, [FakeResponse(403, text="forbidden")])
    url, status = mo._create_on_blog3(API, "B3", {"title": "x", "content": "y"}, "tok")
    assert (url, status) == ("", 403)
    assert len(calls) == 1


def test_connection_error_is_retried(monkeypatch):
    state = {"n": 0}

    def _request(method, url, **kw):
        state["n"] += 1
        if state["n"] == 1:
            raise mo.requests.RequestException("연결 끊김")
        return FakeResponse(200, {"url": "https://blog3.example/ok.html"})

    monkeypatch.setattr(mo.requests, "request", _request)
    url, status = mo._create_on_blog3(API, "B3", {"title": "x", "content": "y"}, "tok")
    assert status == 200
    assert state["n"] == 2


def test_revert_also_retries(monkeypatch):
    calls = _fake_requests(monkeypatch, [FakeResponse(503), FakeResponse(200)])
    assert mo._revert_to_draft(API, "B1", "123", "tok") is True
    assert len(calls) == 2


def test_revert_failure_is_reported_not_swallowed(monkeypatch):
    _fake_requests(monkeypatch, [FakeResponse(429, text="exhausted")])
    assert mo._revert_to_draft(API, "B1", "123", "tok") is False


# ── 순서: 발행 성공이 먼저, 원본 비공개가 나중 ───────────────────────────────

def test_original_is_never_unpublished_before_the_copy_exists():
    """이 순서가 데이터 손실을 막았습니다.

    migrate 분기는 `new_url and _revert_to_draft(...)` 로 묶여 있어야 하고,
    파이썬의 and 는 왼쪽이 거짓이면 오른쪽을 평가하지 않습니다. 따라서
    blog3 발행이 실패하면 blog1 원본은 손대지 않습니다.
    2026-10-08에 11편이 이 덕분에 살아남았습니다.
    """
    import inspect
    src = inspect.getsource(mo.main)
    assert "if new_url and _revert_to_draft(" in src, (
        "발행 성공 확인 없이 원본을 비공개로 돌리면 글이 양쪽에서 사라집니다"
    )


# ── 할당량이 바닥나도 보관은 계속 ────────────────────────────────────────────

def test_archive_uses_a_different_endpoint_than_create():
    """보관은 revert, 이전은 posts 생성 — 할당량이 다릅니다.

    2026-10-08 실행에서 429가 쏟아지는 동안에도 보관 3편은 전부
    성공했습니다. 그래서 할당량이 바닥나도 보관은 멈추지 않습니다.
    """
    import inspect
    assert "/revert" in inspect.getsource(mo._revert_to_draft)
    assert "/posts/" in inspect.getsource(mo._create_on_blog3)
    main_src = inspect.getsource(mo.main)
    # 할당량 소진 시 건너뛰는 분기는 migrate 에만 걸려야 합니다.
    assert 'cat == "migrate_blog3" and quota_exhausted' in main_src


def test_quota_exhaustion_is_not_a_red_build():
    """할당량은 고장이 아니라 '나중에 이어서'입니다."""
    import inspect
    src = inspect.getsource(mo.main)
    assert "if quota_exhausted:" in src and "return 0" in src


def test_pace_is_slower_than_the_run_that_got_throttled():
    """1.5초 간격으로 돌렸다가 429를 맞았습니다."""
    assert mo._PACE_SECONDS >= 3
