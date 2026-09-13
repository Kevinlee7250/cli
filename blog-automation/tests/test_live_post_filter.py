"""관련 포스트 후보에서 이미 내려간 글을 빼는지 검사합니다.

posts.json은 자동화 '실행 이력'이라 글이 임시저장으로 내려간 것을 모릅니다.
2026-09-13 재편으로 409편이 내려갔고, 거르지 않으면 새로 발행하는 글이
내려간 글로 관련 포스트 링크를 겁니다.

거르는 것보다 무서운 건 잘못 거르는 것입니다 — 동기화가 반쪽만 된 파일로
멀쩡한 글을 링크에서 빼면 조용히 망가집니다. 그래서 '필터를 생략하는'
경우를 더 촘촘히 검사합니다.
"""
import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import related_posts  # noqa: E402


def _posts(n, start=0):
    return [{"blogUrl": f"https://b.com/p{i}.html", "title": f"글 {i}",
             "tags": ["여행"]} for i in range(start, start + n)]


@pytest.fixture
def data(tmp_path, monkeypatch):
    """posts.json / live_posts.json 을 임시 경로로 돌립니다."""
    posts_p = tmp_path / "posts.json"
    live_p = tmp_path / "live_posts.json"
    monkeypatch.setattr(related_posts, "POSTS_JSON", posts_p)
    monkeypatch.setattr(related_posts, "LIVE_POSTS_JSON", live_p)

    def write(posts=None, live=None):
        if posts is not None:
            posts_p.write_text(json.dumps(posts, ensure_ascii=False), encoding="utf-8")
        if live is not None:
            live_p.write_text(json.dumps({"urls": live}, ensure_ascii=False),
                              encoding="utf-8")
    return write


def test_unpublished_posts_are_dropped(data):
    posts = _posts(10)
    data(posts=posts, live=[p["blogUrl"] for p in posts[:6]])
    kept = related_posts._load_posts()
    assert len(kept) == 6
    assert {p["blogUrl"] for p in kept} == {p["blogUrl"] for p in posts[:6]}


def test_trailing_slash_still_matches(data):
    """Blogger 주소는 끝 슬래시가 붙었다 말았다 합니다."""
    posts = _posts(5)
    data(posts=posts, live=[p["blogUrl"] + "/" for p in posts])
    assert len(related_posts._load_posts()) == 5


def test_missing_live_file_keeps_everything(data):
    """파일이 없으면 예전처럼 동작해야 합니다 — 처음 배포될 때가 그렇습니다."""
    data(posts=_posts(10))
    assert len(related_posts._load_posts()) == 10


def test_broken_live_file_keeps_everything(data, tmp_path):
    data(posts=_posts(10))
    (tmp_path / "live_posts.json").write_text("{ 깨진 json", encoding="utf-8")
    assert len(related_posts._load_posts()) == 10


def test_empty_live_file_keeps_everything(data):
    data(posts=_posts(10), live=[])
    assert len(related_posts._load_posts()) == 10


def test_suspiciously_small_live_file_keeps_everything(data):
    """동기화가 반쪽만 됐을 때 멀쩡한 글을 링크에서 빼면 안 됩니다."""
    posts = _posts(100)
    data(posts=posts, live=[p["blogUrl"] for p in posts[:5]])   # 5%
    assert len(related_posts._load_posts()) == 100


def test_ratio_boundary_applies_the_filter(data):
    """기준선(20%) 위면 정상 동기화로 보고 거릅니다."""
    posts = _posts(100)
    data(posts=posts, live=[p["blogUrl"] for p in posts[:25]])  # 25%
    assert len(related_posts._load_posts()) == 25


def test_clusters_are_built_from_live_posts_only(data):
    posts = _posts(10)
    data(posts=posts, live=[p["blogUrl"] for p in posts[:6]])
    rep = related_posts.build_clusters()
    assert rep.get("total_posts") == 6


def test_sync_does_not_overwrite_on_partial_failure(tmp_path, monkeypatch):
    """한 블로그라도 조회에 실패하면 파일을 덮어쓰지 않아야 합니다."""
    import sync_live_posts as mod

    out = tmp_path / "live_posts.json"
    out.write_text(json.dumps({"count": 81, "urls": ["https://b.com/keep.html"]}),
                   encoding="utf-8")
    monkeypatch.setattr(mod, "LIVE_PATH", str(out))
    monkeypatch.setattr(mod, "sync",
                        lambda blog_filter="": {"by_blog": {"blog1": []},
                                                "failed": ["blog1"]})
    monkeypatch.setattr(sys, "argv", ["sync_live_posts.py"])

    assert mod.main() == 1
    kept = json.loads(out.read_text(encoding="utf-8"))
    assert kept["count"] == 81, "실패했는데 기존 목록을 덮어썼습니다"
