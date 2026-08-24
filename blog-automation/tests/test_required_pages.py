"""AdSense 필수 페이지 확인 — "모른다"와 "없다"를 섞지 않습니다.

page_creator가 페이지를 만들 수 있지만 그 진입점(main.py --setup)을 도는
워크플로가 없어, 페이지가 있는지 없는지 시스템 어디에도 기록되지 않았습니다.
심사에서 바로 걸리는 항목인데도요.

가장 위험한 오류는 자격증명 문제로 조회에 실패했을 때 "페이지 없음"으로
보고하는 것입니다. 멀쩡한 블로그를 고치라고 하게 됩니다. 반대로 한 블로그도
확인하지 못했는데 ok로 끝내는 것도 안 됩니다 — 사이트맵에서 "한 건도 못
보냈는데 실패 0이라 성공"으로 읽던 것과 같은 실수입니다.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import required_pages_check as rpc  # noqa: E402


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """블로그 목록·토큰·페이지 조회를 갈아 끼웁니다."""
    monkeypatch.setattr(rpc, "REPORT_PATH", str(tmp_path / "required_pages.json"))

    state = {"token": "tok", "pages": []}

    def _setup(blogs, token="tok", pages=None):
        state["token"] = token
        state["pages"] = pages if pages is not None else []
        monkeypatch.setattr("config.get_blog_configs", lambda: blogs)
        monkeypatch.setattr("page_creator._get_access_token", lambda cfg: state["token"])
        monkeypatch.setattr("page_creator._get_blog_id", lambda cfg: "b1")
        monkeypatch.setattr("page_creator._list_existing_pages",
                            lambda tok, bid: state["pages"])
    return _setup


_BLOG = [{"id": "blog1", "name": "테스트 블로그"}]
_ALL_PAGES = [{"title": "개인정보처리방침", "url": "u1"},
              {"title": "블로그 소개", "url": "u2"},
              {"title": "문의하기", "url": "u3"}]


def test_all_pages_present(wired):
    wired(_BLOG, pages=_ALL_PAGES)
    r = rpc.check()
    assert r["ok"] is True
    assert r["blogsWithMissing"] == 0 and r["unknown"] == 0


def test_missing_pages_are_listed(wired):
    wired(_BLOG, pages=[{"title": "개인정보처리방침", "url": "u1"}])
    r = rpc.check()
    assert r["ok"] is False
    assert r["blogsWithMissing"] == 1
    assert set(r["blogs"][0]["missing"]) == {"블로그 소개", "문의"}


def test_token_failure_is_unknown_not_missing(wired):
    """확인 못 한 것을 '없음'으로 보고하면 멀쩡한 블로그를 고치라고 하게 됩니다."""
    wired(_BLOG, token=None)
    r = rpc.check()
    assert r["unknown"] == 1
    assert r["blogsWithMissing"] == 0        # '없음'으로 세지 않습니다
    assert r["blogs"][0].get("error")
    assert r["blogs"][0]["missing"] == []


def test_nothing_checked_is_not_ok(wired):
    """한 블로그도 확인 못 했으면 ok가 아닙니다."""
    wired(_BLOG, token=None)
    assert rpc.check()["ok"] is False


def test_title_variants_are_accepted(wired):
    """사람이 손으로 만들었다면 제목이 조금 다를 수 있습니다."""
    wired(_BLOG, pages=[{"title": "개인정보 처리방침", "url": "u1"},
                        {"title": "About", "url": "u2"},
                        {"title": "연락처", "url": "u3"}])
    r = rpc.check()
    assert r["ok"] is True, f"별칭 매칭 실패: {r['blogs'][0]['missing']}"


def test_report_is_written(wired):
    import json
    wired(_BLOG, pages=_ALL_PAGES)
    rpc.check()
    with open(rpc.REPORT_PATH, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["ok"] is True and saved["checkedAt"]


def test_check_never_creates_pages(wired, monkeypatch):
    """이 모듈은 확인만 합니다 — 발행 중인 블로그를 건드리면 안 됩니다."""
    called = []
    monkeypatch.setattr("page_creator._create_or_update_page",
                        lambda *a, **k: called.append(a))
    wired(_BLOG, pages=[])
    rpc.check()
    assert not called, "확인 단계가 페이지를 만들었습니다"


def test_blog_filter(wired):
    blogs = [{"id": "blog1", "name": "A"}, {"id": "blog2", "name": "B"}]
    wired(blogs, pages=_ALL_PAGES)
    assert len(rpc.check("blog2")["blogs"]) == 1
