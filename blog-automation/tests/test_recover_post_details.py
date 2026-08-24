"""실행 이력에서 글 상세(FAQ·출처) 복구."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from recover_post_details import find_recoverable, index_history  # noqa: E402


def _hist_post(title, keyword, faq=1, sources=1):
    return {"title": title, "keyword": keyword,
            "faq": [{"q": f"q{i}", "a": f"a{i}"} for i in range(faq)],
            "sources": [{"url": f"http://e/{i}"} for i in range(sources)]}


def test_recovers_post_missing_details():
    posts = [{"id": "p1", "title": "글", "keyword": "키워드", "faqCount": 2, "sourceCount": 1}]
    history = [{"posts": [_hist_post("글", "키워드", faq=2, sources=1)]}]
    got = find_recoverable(posts, {}, history)
    assert len(got) == 1
    assert got[0]["id"] == "p1"
    assert len(got[0]["faq"]) == 2
    assert len(got[0]["sources"]) == 1


def test_skips_posts_that_already_have_details():
    posts = [{"id": "p1", "title": "글", "keyword": "키워드", "faqCount": 2}]
    history = [{"posts": [_hist_post("글", "키워드")]}]
    assert find_recoverable(posts, {"p1": {"faq": [], "sources": []}}, history) == []


def test_skips_posts_that_never_had_details():
    """원래 FAQ·출처가 없던 글은 유실이 아닙니다."""
    posts = [{"id": "p1", "title": "글", "keyword": "키워드", "faqCount": 0, "sourceCount": 0}]
    history = [{"posts": [_hist_post("글", "키워드")]}]
    assert find_recoverable(posts, {}, history) == []


def test_title_alone_is_not_enough():
    """제목만 맞고 키워드가 다르면 다른 글입니다 — 섞이면 안 됩니다."""
    posts = [{"id": "p1", "title": "같은 제목", "keyword": "키워드A", "faqCount": 1}]
    history = [{"posts": [_hist_post("같은 제목", "키워드B")]}]
    assert find_recoverable(posts, {}, history) == []


def test_missing_from_history_is_reported_as_unrecoverable():
    posts = [{"id": "p1", "title": "글", "keyword": "키워드", "faqCount": 1}]
    assert find_recoverable(posts, {}, []) == []


def test_index_keeps_newest_when_duplicated():
    """실행 이력은 최신이 앞이므로 먼저 만난 것을 남깁니다."""
    history = [
        {"posts": [_hist_post("글", "키워드", faq=3)]},   # 최신
        {"posts": [_hist_post("글", "키워드", faq=1)]},   # 예전
    ]
    idx = index_history(history)
    assert len(idx[("글", "키워드")]["faq"]) == 3


def test_empty_inputs():
    assert find_recoverable([], {}, []) == []


def test_history_entry_without_posts_is_ignored():
    posts = [{"id": "p1", "title": "글", "keyword": "키워드", "faqCount": 1}]
    history = [{"runAt": "2026-08-22T00:00:00"}, {"posts": None}]
    assert find_recoverable(posts, {}, history) == []


def test_no_gap_remains_in_the_repository():
    """지금 저장소 상태 — 배지와 내용이 어긋나는 글이 없어야 합니다."""
    import json
    base = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "data")
    with open(os.path.join(base, "posts.json"), encoding="utf-8") as f:
        posts = json.load(f)
    with open(os.path.join(base, "post_details.json"), encoding="utf-8") as f:
        details = json.load(f)
    gaps = [p["title"] for p in posts
            if p.get("id") and p["id"] not in details
            and (p.get("faqCount") or p.get("sourceCount"))]
    assert not gaps, f"상세가 유실된 글: {gaps}"
