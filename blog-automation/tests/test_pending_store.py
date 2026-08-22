"""검토 대기 저장소 — 목록/본문/보관 분리."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pending_store  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(pending_store, "INDEX_FILE", str(tmp_path / "pending_posts.json"))
    monkeypatch.setattr(pending_store, "BODIES_FILE", str(tmp_path / "pending_bodies.json"))
    monkeypatch.setattr(pending_store, "ARCHIVE_FILE", str(tmp_path / "pending_archive.json"))
    return pending_store


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_body_moves_out_of_index(store):
    store.save([{"id": "a1", "title": "글", "status": "pending",
                 "content": "<p>본문입니다</p>"}])
    index = _read(store.INDEX_FILE)
    assert "content" not in index[0], "본문이 목록에 남으면 분리한 의미가 없습니다"
    assert index[0]["contentLength"] == len("<p>본문입니다</p>")
    assert index[0]["excerpt"] == "본문입니다"
    assert _read(store.BODIES_FILE) == {"a1": "<p>본문입니다</p>"}


def test_load_reattaches_body(store):
    store.save([{"id": "a1", "status": "pending", "content": "<p>x</p>"}])
    assert store.load()[0]["content"] == "<p>x</p>"


def test_terminal_records_go_to_archive(store):
    store.save([
        {"id": "a1", "status": "pending", "content": "<p>대기</p>"},
        {"id": "a2", "status": "published", "content": "<p>발행됨</p>"},
        {"id": "a3", "status": "expired", "content": "<p>만료</p>"},
    ])
    assert [r["id"] for r in _read(store.INDEX_FILE)] == ["a1"]
    assert sorted(r["id"] for r in _read(store.ARCHIVE_FILE)) == ["a2", "a3"]
    # 본문은 보관 기록 것도 그대로 둡니다 — 언제 버릴지는 pending_manager가
    # 정합니다. 저장소가 함께 판단하면 규칙이 두 곳에 살게 됩니다.
    assert set(_read(store.BODIES_FILE)) == {"a1", "a2", "a3"}


def test_load_returns_everything_it_will_save(store):
    """읽은 범위와 쓰는 범위가 같아야 합니다.

    load가 목록만 주면, 그걸 그대로 save할 때 보관본이 통째로 지워집니다.
    """
    store.save([{"id": "a1", "status": "pending", "content": "x"},
                {"id": "a2", "status": "published", "content": "y"}])
    records = store.load()
    assert sorted(r["id"] for r in records) == ["a1", "a2"]

    store.save(records)          # 읽은 그대로 다시 저장해도
    assert sorted(r["id"] for r in store.load()) == ["a1", "a2"]   # 아무것도 잃지 않음


def test_save_load_roundtrip_keeps_fields(store):
    original = {"id": "a1", "status": "pending", "title": "제목", "keyword": "키워드",
                "faq": [{"q": "질문", "a": "답"}], "sources": ["출처"],
                "wordCount": 1234, "content": "<p>본문</p>"}
    store.save([original])
    got = store.load()[0]
    for k, v in original.items():
        assert got[k] == v, f"{k} 손실"


def test_migrate_from_legacy_single_file(store, tmp_path):
    """옛 형식(본문이 목록에 있는) 파일을 그대로 두고 migrate만 돌려도 됩니다."""
    legacy = [{"id": "a1", "status": "pending", "content": "<p>대기</p>"},
              {"id": "a2", "status": "expired", "content": "<p>만료</p>"}]
    with open(store.INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(legacy, f, ensure_ascii=False)
    result = store.migrate()
    assert result == {"records": 2, "index": 1, "archive": 1, "bodies": 2}
    # 두 번 돌려도 같은 결과 (멱등)
    assert store.migrate()["index"] == 1


def test_missing_files_are_not_an_error(store):
    assert store.load() == []
    assert store.load_bodies() == {}


def test_excerpt_strips_tags():
    assert pending_store.excerpt("<h2>제목</h2><p>본문  줄</p>") == "제목 본문 줄"
    assert pending_store.excerpt("") == ""
    assert len(pending_store.excerpt("가" * 500)) == pending_store.EXCERPT_LEN
