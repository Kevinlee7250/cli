"""글 목록 순회 구현이 다시 갈라지지 않게 고정합니다.

_iter_posts는 네 모듈에 복사돼 있었습니다. 2026-08-25에 "목록이 조용히 잘려
'다 처리했다'를 알 수 없던 문제"를 고쳤는데, 사본이 넷이라 수정이
fix_unlicensed_images 한 곳에만 들어갔습니다. 나머지 셋은 그대로 버그를 안고
돌았고, 코드만 봐서는 티가 나지 않았습니다 — 함수는 넷 다 멀쩡히 있으니까요.

같은 일을 하는 코드가 여러 벌 있으면 고침이 전파되지 않습니다. 그래서 사본이
아니라 "공용 모듈을 쓰는가"를 검사합니다.
"""

import ast
import glob
import os

import pytest

import blogger_posts

_SRC = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

# 발행 글을 일괄로 훑는 도구들 — 전부 같은 순회 구현을 써야 합니다
_TOOLS = ["fix_dead_links.py", "fix_duplicate_images.py",
          "fix_duplicate_toc.py", "fix_unlicensed_images.py"]


def _iter_posts_body(filename):
    path = os.path.join(_SRC, filename)
    src = open(path, encoding="utf-8").read()
    for node in ast.parse(src).body:
        if isinstance(node, ast.FunctionDef) and node.name == "_iter_posts":
            return ast.get_source_segment(src, node)
    return None


@pytest.mark.parametrize("filename", _TOOLS)
def test_tools_delegate_instead_of_copying(filename):
    body = _iter_posts_body(filename)
    assert body is not None, f"{filename}에 _iter_posts가 없습니다"
    assert "iter_posts(" in body, f"{filename}이 공용 구현을 쓰지 않습니다"
    # 사본이면 요청을 직접 보냅니다
    assert "requests.get" not in body, (
        f"{filename}이 자체 사본을 들고 있습니다. 공용 blogger_posts.iter_posts를 "
        "쓰세요 — 사본이 있으면 여기 고친 것이 저기에 전파되지 않습니다"
    )


@pytest.mark.parametrize("filename", _TOOLS)
def test_no_silent_truncation_in_tools(filename):
    """비200에 로그만 남기고 return하는 옛 형태가 되살아나지 않게."""
    body = _iter_posts_body(filename)
    assert "status_code" not in body, (
        f"{filename}이 응답 코드를 직접 다룹니다 — 조용한 절단이 되돌아온 신호입니다"
    )


# ── 공용 구현 자체의 동작 ────────────────────────────────────────────────────

class _Resp:
    def __init__(self, code, payload=None, text=""):
        self.status_code, self._p, self.text = code, payload or {}, text

    def json(self):
        return self._p


def test_listing_failure_raises_instead_of_ending_quietly(monkeypatch):
    """이게 핵심입니다 — 조용히 끝나면 부분 결과가 전체로 보고됩니다."""
    monkeypatch.setattr(blogger_posts.time, "sleep", lambda *_: None)
    monkeypatch.setattr(blogger_posts.requests, "get", lambda *a, **k: _Resp(429, text="rate"))
    with pytest.raises(blogger_posts.ListingTruncated):
        list(blogger_posts.iter_posts("b", "t"))


def test_transient_failure_is_retried(monkeypatch):
    calls = {"n": 0}

    def fake_get(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Resp(503)
        return _Resp(200, {"items": [{"id": "1"}]})

    monkeypatch.setattr(blogger_posts.time, "sleep", lambda *_: None)
    monkeypatch.setattr(blogger_posts.requests, "get", fake_get)
    assert [p["id"] for p in blogger_posts.iter_posts("b", "t")] == ["1"]
    assert calls["n"] == 2, "일시적 실패는 재시도해야 합니다"


def test_pagination_follows_every_page(monkeypatch):
    pages = [
        _Resp(200, {"items": [{"id": "1"}], "nextPageToken": "p2"}),
        _Resp(200, {"items": [{"id": "2"}]}),
    ]
    monkeypatch.setattr(blogger_posts.requests, "get", lambda *a, **k: pages.pop(0))
    assert [p["id"] for p in blogger_posts.iter_posts("b", "t")] == ["1", "2"]


def test_error_message_says_how_far_it_got(monkeypatch):
    """몇 편까지 봤는지 알아야 부분 결과인지 판단할 수 있습니다."""
    pages = [_Resp(200, {"items": [{"id": "1"}], "nextPageToken": "p2"})] + [_Resp(500)] * 5
    monkeypatch.setattr(blogger_posts.time, "sleep", lambda *_: None)
    monkeypatch.setattr(blogger_posts.requests, "get", lambda *a, **k: pages.pop(0))
    with pytest.raises(blogger_posts.ListingTruncated) as e:
        list(blogger_posts.iter_posts("b", "t"))
    assert "1편까지" in str(e.value)


def test_reexport_keeps_old_import_path_working():
    """image_audit·mirror_existing_images가 이 경로로 import합니다."""
    import fix_unlicensed_images as fx
    assert fx.ListingTruncated is blogger_posts.ListingTruncated
