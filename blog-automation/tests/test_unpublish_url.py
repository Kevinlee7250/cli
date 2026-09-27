# -*- coding: utf-8 -*-
"""URL 하나를 지목해 비공개로 내리는 도구의 안전 규칙을 고정합니다.

지키는 것
  · URL의 호스트로 올바른 블로그를 찾는다 (custom domain, blogspot 모두)
  · 모르는 호스트면 아무것도 하지 않는다
  · --apply 없이는 절대 내리지 않는다 (기본은 확인만)
  · 이미 draft인 글은 건드리지 않는다
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unpublish_url as uu  # noqa: E402


_CONFIGS = [
    {"id": "blog1", "name": "HOGU What?", "blog_id": "4782599180249292575",
     "gsc_site_url": "https://www.hoguwhat.com/"},
    {"id": "blog2", "name": "HOGU 여행,스포츠,연예", "blog_id": "8903166932049624994",
     "gsc_site_url": "https://hogugolfntraval.blogspot.com/"},
    {"id": "blog3", "name": "금융NEWS", "blog_id": "3612975334194190709",
     "gsc_site_url": "https://hoguasset.blogspot.com/"},
]


@pytest.fixture(autouse=True)
def fake_configs(monkeypatch):
    import config
    monkeypatch.setattr(config, "get_blog_configs", lambda: _CONFIGS)


def test_custom_domain_resolves():
    cfg = uu._blog_for_url("https://www.hoguwhat.com/2026/09/x.html")
    assert cfg["id"] == "blog1"


def test_www_and_bare_host_are_the_same_blog():
    a = uu._blog_for_url("https://hoguwhat.com/2026/09/x.html")
    b = uu._blog_for_url("https://www.hoguwhat.com/2026/09/x.html")
    assert a["id"] == b["id"] == "blog1"


def test_blogspot_host_resolves():
    assert uu._blog_for_url("https://hoguasset.blogspot.com/2026/07/y.html")["id"] == "blog3"


def test_unknown_host_resolves_to_nothing():
    """모르는 호스트는 None — 기본 블로그로 떨어뜨리지 않습니다."""
    assert uu._blog_for_url("https://example.com/a.html") is None
    assert uu._blog_for_url("not-a-url") is None


def test_www_prefix_strip_does_not_eat_other_hosts():
    """lstrip('www.')의 문자 집합 버그가 되살아나지 않도록 고정합니다."""
    monkey = [{"id": "x", "name": "X", "blog_id": "1",
               "gsc_site_url": "https://wow.example.com/"}]
    import config
    orig = config.get_blog_configs
    config.get_blog_configs = lambda: monkey
    try:
        assert uu._blog_for_url("https://wow.example.com/a.html")["id"] == "x"
    finally:
        config.get_blog_configs = orig


def test_dry_run_never_reverts(monkeypatch):
    """--apply가 없으면 revert를 호출하지 않습니다."""
    calls = []

    import blogger_uploader
    monkeypatch.setattr(blogger_uploader, "_get_access_token", lambda cfg=None: "tok")
    monkeypatch.setattr(uu, "_post_by_url",
                        lambda bid, url, tok: {"id": "77", "title": "t", "status": "LIVE"})
    monkeypatch.setattr(uu.requests, "post",
                        lambda *a, **k: calls.append(a) or _Resp(200))

    rc = uu.run("https://www.hoguwhat.com/2026/09/x.html", apply_changes=False)
    assert rc == 0
    assert calls == [], "확인만 해야 하는데 revert를 호출했습니다"


def test_apply_reverts_once(monkeypatch):
    calls = []

    import blogger_uploader
    monkeypatch.setattr(blogger_uploader, "_get_access_token", lambda cfg=None: "tok")
    monkeypatch.setattr(uu, "_post_by_url",
                        lambda bid, url, tok: {"id": "77", "title": "t", "status": "LIVE"})
    monkeypatch.setattr(uu.requests, "post",
                        lambda *a, **k: (calls.append(a[0]), _Resp(200))[1])

    rc = uu.run("https://www.hoguwhat.com/2026/09/x.html", apply_changes=True)
    assert rc == 0
    assert len(calls) == 1
    assert "/posts/77/revert" in calls[0]


def test_already_draft_is_left_alone(monkeypatch):
    calls = []

    import blogger_uploader
    monkeypatch.setattr(blogger_uploader, "_get_access_token", lambda cfg=None: "tok")
    monkeypatch.setattr(uu, "_post_by_url",
                        lambda bid, url, tok: {"id": "77", "title": "t", "status": "DRAFT"})
    monkeypatch.setattr(uu.requests, "post",
                        lambda *a, **k: calls.append(a) or _Resp(200))

    assert uu.run("https://www.hoguwhat.com/2026/09/x.html", apply_changes=True) == 0
    assert calls == []


def test_unknown_host_returns_error_code(monkeypatch):
    assert uu.run("https://example.com/a.html", apply_changes=True) == 1


class _Resp:
    def __init__(self, code):
        self.status_code = code
        self.text = ""

    def json(self):
        return {}
