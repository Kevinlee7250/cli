"""색인 요청 우선순위 큐 테스트.

GSC UI의 색인 요청은 하루 10건 정도가 한계라, 무엇을 먼저 넣느냐가
실제 결과를 가릅니다.

실행: cd blog-automation && python -m pytest tests/test_index_priority.py -v
"""

import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _date(days_ago):
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def _setup(tmp_path, monkeypatch, items, posts):
    import index_priority as ip
    monkeypatch.setattr(ip, "_DOCS_DATA", str(tmp_path))
    monkeypatch.setattr(ip, "REPORT_PATH", str(tmp_path / "index_priority.json"))
    (tmp_path / "index_status.json").write_text(
        json.dumps({"checked_at": "2026-08-18", "items": items}, ensure_ascii=False),
        encoding="utf-8")
    (tmp_path / "posts.json").write_text(json.dumps(posts, ensure_ascii=False),
                                         encoding="utf-8")
    return ip


def _item(url, coverage="Discovered - currently not indexed", verdict="not_indexed"):
    return {"url": url, "coverage": coverage, "verdict": verdict, "blog": "블로그"}


def _post(url, days_ago=30, words=3000, faq=3, impressions=0):
    return {"blogUrl": url, "title": f"글 {url}", "date": _date(days_ago),
            "wordCount": words, "faqCount": faq, "gscImpressions30d": impressions}


# ──────────────────────────────────────────────────────────────────────────────

def test_unknown_to_google_ranks_above_discovered():
    """구글이 존재조차 모르는 글이 가장 급함."""
    from index_priority import score_candidate
    unknown, _ = score_candidate(_item("a", "URL is unknown to Google"), _post("a"))
    discovered, _ = score_candidate(_item("b"), _post("b"))
    assert unknown > discovered


def test_search_demand_raises_priority():
    from index_priority import score_candidate
    with_demand, reasons = score_candidate(_item("a"), _post("a", impressions=120))
    without, _ = score_candidate(_item("b"), _post("b", impressions=0))
    assert with_demand > without
    assert any("수요" in r for r in reasons)


def test_thin_post_is_deprioritized():
    """분량 부족한 글을 먼저 넣으면 할당량만 낭비됨."""
    from index_priority import score_candidate
    thin, reasons = score_candidate(_item("a"), _post("a", words=1200, faq=0))
    full, _ = score_candidate(_item("b"), _post("b", words=3500, faq=5))
    assert thin < full
    assert any("분량 부족" in r for r in reasons)


def test_every_candidate_carries_reasons():
    from index_priority import score_candidate
    _, reasons = score_candidate(_item("a"), _post("a"))
    assert reasons and all(isinstance(r, str) for r in reasons)


# ──────────────────────────────────────────────────────────────────────────────

def test_indexed_posts_are_excluded(tmp_path, monkeypatch):
    ip = _setup(tmp_path, monkeypatch,
                [_item("a", verdict="indexed"), _item("b")],
                [_post("a"), _post("b")])
    r = ip.build_queue(10)
    assert r["skippedIndexed"] == 1
    assert [c["url"] for c in r["queue"]] == ["b"]


def test_freshly_published_posts_are_skipped(tmp_path, monkeypatch):
    """발행 직후엔 원래 시간이 걸림 — 할당량을 여기 쓰면 낭비."""
    ip = _setup(tmp_path, monkeypatch, [_item("a")], [_post("a", days_ago=0)])
    r = ip.build_queue(10)
    assert r["skippedTooFresh"] == 1 and r["queue"] == []


def test_queue_respects_daily_quota(tmp_path, monkeypatch):
    items = [_item(f"u{i}") for i in range(25)]
    posts = [_post(f"u{i}") for i in range(25)]
    ip = _setup(tmp_path, monkeypatch, items, posts)
    r = ip.build_queue(10)
    assert len(r["queue"]) == 10
    assert r["backlog"] == 15


def test_queue_is_sorted_by_score(tmp_path, monkeypatch):
    ip = _setup(tmp_path, monkeypatch,
                [_item("low"), _item("high", "URL is unknown to Google")],
                [_post("low", words=1000, faq=0), _post("high", impressions=50)])
    r = ip.build_queue(10)
    assert r["queue"][0]["url"] == "high"


def test_missing_index_report_does_not_crash(tmp_path, monkeypatch):
    import index_priority as ip
    monkeypatch.setattr(ip, "_DOCS_DATA", str(tmp_path))
    monkeypatch.setattr(ip, "REPORT_PATH", str(tmp_path / "r.json"))
    r = ip.build_queue(10)
    assert r["queue"] == [] and "색인 리포트 없음" in r.get("note", "")


def test_run_writes_report(tmp_path, monkeypatch):
    ip = _setup(tmp_path, monkeypatch, [_item("a")], [_post("a")])
    ip.run(10)
    saved = json.loads((tmp_path / "index_priority.json").read_text(encoding="utf-8"))
    assert saved["queue"][0]["url"] == "a"
