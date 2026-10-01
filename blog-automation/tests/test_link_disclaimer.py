# -*- coding: utf-8 -*-
"""면책 조항 링크를 다른 필수 페이지에 넣는 도구의 안전 규칙을 고정합니다.

면책 조항 페이지는 만들어져 있는데 상단 메뉴 가젯에는 올라가지 않는
블로그가 있습니다. Blogger API로는 레이아웃을 건드릴 수 없어서, 이미
메뉴에 있는 페이지들에서 면책 조항으로 이어 둡니다.

지키는 것
  · --apply 없이는 아무것도 고치지 않는다
  · 면책 조항 페이지가 없으면 아무것도 하지 않는다
  · 이미 넣은 페이지는 두 번 넣지 않는다 (몇 번 돌려도 같음)
  · 기존 본문을 덮지 않고 뒤에 붙이기만 한다
  · 면책 조항 페이지 자신에는 넣지 않는다
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import link_disclaimer as ld  # noqa: E402


CFG = {"id": "blog2", "name": "HOGU 여행,스포츠,연예", "blog_id": "8903166932049624994"}

PAGES = [
    {"id": "1", "title": "개인정보처리방침", "content": "<p>개인정보 본문</p>",
     "url": "https://x.blogspot.com/p/privacy.html"},
    {"id": "2", "title": "블로그 소개", "content": "<p>소개 본문</p>",
     "url": "https://x.blogspot.com/p/about.html"},
    {"id": "3", "title": "문의하기", "content": "<p>문의 본문</p>",
     "url": "https://x.blogspot.com/p/contact.html"},
    {"id": "4", "title": "면책 조항", "content": "<p>면책 본문</p>",
     "url": "https://x.blogspot.com/p/disclaimer.html"},
]


class _Resp:
    def __init__(self, code, payload=None):
        self.status_code = code
        self._p = payload or {}
        self.text = ""

    def json(self):
        return self._p


@pytest.fixture
def api(monkeypatch):
    """Blogger API를 가짜로 바꾸고, PUT으로 간 내용을 모읍니다."""
    puts = []

    import blogger_uploader
    monkeypatch.setattr(blogger_uploader, "_get_access_token", lambda cfg=None: "tok")
    monkeypatch.setattr(ld.requests, "get",
                        lambda *a, **k: _Resp(200, {"items": PAGES}))

    def fake_put(url, json=None, **k):
        puts.append((url, json))
        return _Resp(200, {})

    monkeypatch.setattr(ld.requests, "put", fake_put)
    return puts


# ── 기본은 확인만 ─────────────────────────────────────────────────────────

def test_dry_run_changes_nothing(api):
    assert ld.run_for_blog(CFG, apply_changes=False) == 0
    assert api == [], "확인만 해야 하는데 페이지를 고쳤습니다"


# ── 실제 반영 ─────────────────────────────────────────────────────────────

def test_apply_updates_the_three_menu_pages(api):
    assert ld.run_for_blog(CFG, apply_changes=True) == 0
    assert len(api) == 3, f"3개 페이지를 고쳐야 하는데 {len(api)}개"
    ids = sorted(u.rsplit("/", 1)[-1] for u, _ in api)
    assert ids == ["1", "2", "3"]


def test_disclaimer_page_itself_is_not_touched(api):
    ld.run_for_blog(CFG, apply_changes=True)
    ids = [u.rsplit("/", 1)[-1] for u, _ in api]
    assert "4" not in ids, "면책 조항 페이지 자신에 링크를 넣었습니다"


def test_existing_content_is_kept(api):
    ld.run_for_blog(CFG, apply_changes=True)
    for url, payload in api:
        pid = url.rsplit("/", 1)[-1]
        original = next(p["content"] for p in PAGES if p["id"] == pid)
        assert payload["content"].startswith(original), "기존 본문이 사라졌습니다"


def test_the_link_points_at_the_disclaimer(api):
    ld.run_for_blog(CFG, apply_changes=True)
    for _, payload in api:
        assert "https://x.blogspot.com/p/disclaimer.html" in payload["content"]
        assert "면책 조항" in payload["content"]


def test_title_is_preserved(api):
    ld.run_for_blog(CFG, apply_changes=True)
    titles = sorted(p["title"] for _, p in api)
    assert titles == ["개인정보처리방침", "문의하기", "블로그 소개"]


# ── 두 번 돌려도 같음 ─────────────────────────────────────────────────────

def test_already_linked_pages_are_skipped(monkeypatch):
    linked = [dict(p, content=p["content"] + f'<p class="{ld.MARKER}">x</p>')
              for p in PAGES]
    puts = []
    import blogger_uploader
    monkeypatch.setattr(blogger_uploader, "_get_access_token", lambda cfg=None: "tok")
    monkeypatch.setattr(ld.requests, "get",
                        lambda *a, **k: _Resp(200, {"items": linked}))
    monkeypatch.setattr(ld.requests, "put",
                        lambda *a, **k: puts.append(a) or _Resp(200, {}))

    assert ld.run_for_blog(CFG, apply_changes=True) == 0
    assert puts == [], "이미 링크가 있는데 또 넣었습니다"


# ── 면책 조항이 없을 때 ───────────────────────────────────────────────────

def test_nothing_happens_without_a_disclaimer_page(monkeypatch):
    puts = []
    import blogger_uploader
    monkeypatch.setattr(blogger_uploader, "_get_access_token", lambda cfg=None: "tok")
    monkeypatch.setattr(
        ld.requests, "get",
        lambda *a, **k: _Resp(200, {"items": [p for p in PAGES if p["id"] != "4"]}))
    monkeypatch.setattr(ld.requests, "put",
                        lambda *a, **k: puts.append(a) or _Resp(200, {}))

    assert ld.run_for_blog(CFG, apply_changes=True) == 1
    assert puts == []


def test_api_failure_does_not_write(monkeypatch):
    puts = []
    import blogger_uploader
    monkeypatch.setattr(blogger_uploader, "_get_access_token", lambda cfg=None: "tok")
    monkeypatch.setattr(ld.requests, "get", lambda *a, **k: _Resp(500))
    monkeypatch.setattr(ld.requests, "put",
                        lambda *a, **k: puts.append(a) or _Resp(200, {}))

    assert ld.run_for_blog(CFG, apply_changes=True) == 1
    assert puts == []
