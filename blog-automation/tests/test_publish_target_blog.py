# -*- coding: utf-8 -*-
"""검토 대기 글이 자기 blogId의 블로그로 올라가는지 검증합니다.

2026-09-27에 겪은 사고를 고정합니다. publish_pending이 upload_post를
blog_config 없이 호출해서, blogId가 blog3인 금융 글이 기본값(blog1)으로
올라갔습니다. 대기 글이 거의 다 blog1이라 오래 드러나지 않았습니다.

여기서 지키는 것은 두 가지입니다.
  · 레코드의 blogId에 맞는 설정이 upload_post로 전달된다
  · 설정을 못 찾으면 기본 블로그로 올리지 않고 실패로 남긴다
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import publish_pending  # noqa: E402


_CONFIGS = [
    {"id": "blog1", "name": "HOGU What?", "blog_id": "1111"},
    {"id": "blog2", "name": "HOGU 여행,스포츠,연예", "blog_id": "2222"},
    {"id": "blog3", "name": "금융NEWS", "blog_id": "3612975334194190709"},
]


@pytest.fixture
def fake_configs(monkeypatch):
    import config
    monkeypatch.setattr(config, "get_blog_configs", lambda: _CONFIGS)
    return _CONFIGS


def test_blog_config_for_resolves_each_blog(fake_configs):
    assert publish_pending.blog_config_for("blog3")["blog_id"] == "3612975334194190709"
    assert publish_pending.blog_config_for("blog2")["name"] == "HOGU 여행,스포츠,연예"


def test_blog_config_for_unknown_id_returns_none(fake_configs):
    """모르는 id는 None — 기본 블로그로 떨어뜨리지 않습니다."""
    assert publish_pending.blog_config_for("blog9") is None
    assert publish_pending.blog_config_for("") is None


def test_upload_receives_the_records_blog_config(monkeypatch, fake_configs):
    """blogId가 blog3면 blog3 설정이 upload_post에 전달되어야 합니다."""
    seen = {}

    import blogger_uploader

    def fake_upload(post_data, blog_config=None):
        seen["blog_config"] = blog_config
        return {"url": "https://hoguasset.blogspot.com/2026/09/x.html"}

    monkeypatch.setattr(blogger_uploader, "upload_post", fake_upload)

    result, _ = publish_pending.upload_with_log_capture(
        {"title": "t", "content": "c"},
        publish_pending.blog_config_for("blog3"),
    )

    assert result is not None
    assert seen["blog_config"] is not None, "blog_config가 전달되지 않았습니다 (2026-09-27 사고 재발)"
    assert seen["blog_config"]["id"] == "blog3"
    assert seen["blog_config"]["blog_id"] == "3612975334194190709"


def test_upload_without_config_still_allowed_for_legacy_records(monkeypatch, fake_configs):
    """blogId가 아예 없는 옛 레코드는 기존처럼 기본 블로그로 갑니다.

    옛 글을 갑자기 실패시키지 않기 위한 것이며, blogId가 '있는데 못 찾는'
    경우와는 다릅니다 (그쪽은 main에서 실패 처리됩니다).
    """
    seen = {}
    import blogger_uploader
    monkeypatch.setattr(
        blogger_uploader, "upload_post",
        lambda post_data, blog_config=None: seen.setdefault("cfg", blog_config) or {"url": "u"},
    )

    publish_pending.upload_with_log_capture({"title": "t", "content": "c"}, None)
    assert seen["cfg"] is None
