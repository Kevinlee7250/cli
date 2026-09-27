# -*- coding: utf-8 -*-
"""수동 발행한 글이 post_registry에도 등록되는지 검증합니다.

2026-09-27까지 publish_pending은 Blogger에만 올리고 레지스트리에는 아무것도
남기지 않았습니다. 그래서 수동 발행 글은 블로그에는 멀쩡히 있는데 시스템에는
없는 글이 됐습니다 — 대시보드 집계, 내부링크, 색인 큐, 이미지 관리
(manage_post)가 전부 레지스트리로 글을 찾기 때문입니다.

지키는 것
  · 발행 성공 시 레지스트리에 등록된다
  · 등록 항목의 blogId가 레코드의 blogId와 같다 (기본 블로그로 새지 않는다)
  · docs/data 쪽도 같이 맞춰진다 (읽는 도구들이 보는 파일)
  · 등록이 실패해도 발행 결과를 뒤집지 않는다
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import post_manager  # noqa: E402
import publish_pending  # noqa: E402


_BLOG3 = {"id": "blog3", "name": "금융NEWS", "blog_id": "3612975334194190709"}

_POST = {
    "id": "20260927_x",
    "title": "테스트 글",
    "keyword": "테스트 키워드",
    "blogUrl": "https://hoguasset.blogspot.com/2026/09/x.html",
    "blogId": "blog3",
    "labels": ["금융"],
    "metaDescription": "설명",
    "contentLength": 3000,
    "contentCategory": "finance",
}


@pytest.fixture
def isolated_registry(tmp_path, monkeypatch):
    """레지스트리 두 파일을 임시 경로로 돌려, 실제 파일을 건드리지 않습니다."""
    logs = tmp_path / "logs" / "post_registry.json"
    docs = tmp_path / "docs" / "data" / "post_registry.json"
    logs.parent.mkdir(parents=True, exist_ok=True)
    docs.parent.mkdir(parents=True, exist_ok=True)
    logs.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(post_manager, "REGISTRY_FILE", str(logs))
    monkeypatch.setattr(post_manager, "DOCS_REGISTRY_FILE", str(docs))
    return logs, docs


def test_published_post_lands_in_registry(isolated_registry):
    logs, docs = isolated_registry

    assert publish_pending.register_in_registry(dict(_POST), _BLOG3) is True

    entries = json.loads(logs.read_text(encoding="utf-8"))
    assert len(entries) == 1
    assert entries[0]["title"] == "테스트 글"
    assert entries[0]["blogUrl"] == _POST["blogUrl"]
    assert entries[0]["status"] == "published"
    assert entries[0]["source"] == "manual"


def test_registry_entry_keeps_the_right_blog(isolated_registry):
    """blogId가 기본값('default')으로 새면 안 됩니다."""
    logs, _ = isolated_registry
    publish_pending.register_in_registry(dict(_POST), _BLOG3)

    entry = json.loads(logs.read_text(encoding="utf-8"))[0]
    assert entry["blogId"] == "blog3"
    assert entry["blogName"] == "금융NEWS"


def test_docs_copy_is_updated_too(isolated_registry):
    """읽는 도구들은 docs/data 쪽을 봅니다 — 여기까지 맞아야 글이 보입니다."""
    _, docs = isolated_registry
    publish_pending.register_in_registry(dict(_POST), _BLOG3)

    assert docs.exists(), "docs/data 레지스트리가 갱신되지 않았습니다"
    mirrored = json.loads(docs.read_text(encoding="utf-8"))
    assert [e["blogUrl"] for e in mirrored] == [_POST["blogUrl"]]


def test_registry_failure_does_not_raise(monkeypatch, isolated_registry):
    """등록이 깨져도 발행 자체는 이미 성공한 상태이므로 예외를 올리지 않습니다."""
    def boom(*a, **k):
        raise RuntimeError("디스크 없음")

    monkeypatch.setattr(post_manager, "register_post", boom)
    assert publish_pending.register_in_registry(dict(_POST), _BLOG3) is False


def test_mirror_writes_compact_json(isolated_registry):
    """대시보드가 받아 가는 파일이라 들여쓰기를 넣지 않습니다."""
    _, docs = isolated_registry
    publish_pending.register_in_registry(dict(_POST), _BLOG3)

    raw = docs.read_text(encoding="utf-8")
    assert "\n" not in raw.strip(), "docs/data 레지스트리에 들여쓰기가 들어갔습니다"
