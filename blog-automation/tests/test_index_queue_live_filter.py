"""색인 요청 큐가 이미 내려간 글을 빼는지 검사합니다.

2026-09-18 index_status.json 점검: 검사된 20건 중 7건이 9/13 재편으로
이미 비공개 전환된 글이었습니다. 색인 요청은 속성당 하루 10건뿐이라,
죽은 URL 7건은 그날 할당량의 대부분을 태운 셈입니다.

related_posts와 같은 원칙을 씁니다 — 목록을 못 믿겠으면 거르지 않습니다.
잘못 걸러서 멀쩡한 글이 큐에서 빠지는 쪽이 더 조용히 나쁩니다.
"""
import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import index_priority as ip  # noqa: E402


@pytest.fixture
def data(tmp_path, monkeypatch):
    """index_status / posts / live_posts 를 임시 경로로 돌립니다."""
    monkeypatch.setattr(ip, "_DOCS_DATA", str(tmp_path))
    monkeypatch.setattr(ip, "LIVE_POSTS_PATH", str(tmp_path / "live_posts.json"))
    monkeypatch.setattr(ip, "MIN_AGE_DAYS", 0)

    def write(urls, live=None):
        items = [{"url": u, "verdict": "not_indexed",
                  "coverage": "URL is unknown to Google",
                  "published_at": "2026-01-01"} for u in urls]
        (tmp_path / "index_status.json").write_text(
            json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")
        (tmp_path / "posts.json").write_text("[]", encoding="utf-8")
        if live is not None:
            (tmp_path / "live_posts.json").write_text(
                json.dumps({"urls": live}, ensure_ascii=False), encoding="utf-8")
    return write


def _urls(report):
    return [c["url"] for c in report["queue"]]


def test_unpublished_urls_are_dropped(data):
    data(["https://b.com/1.html", "https://b.com/2.html", "https://b.com/3.html",
          "https://b.com/4.html", "https://b.com/5.html"],
         live=["https://b.com/1.html", "https://b.com/2.html",
               "https://b.com/3.html", "https://b.com/4.html"])
    r = ip.build_queue()
    assert "https://b.com/5.html" not in _urls(r)
    assert r["skippedUnpublished"] == 1
    assert r["liveFilterApplied"] is True


def test_missing_live_file_does_not_empty_the_queue(data, tmp_path):
    """live_posts.json이 없으면 예전처럼 전부 후보입니다."""
    data(["https://b.com/1.html", "https://b.com/2.html"])
    r = ip.build_queue()
    assert len(r["queue"]) == 2
    assert r["liveFilterApplied"] is False
    assert r["skippedUnpublished"] == 0


def test_broken_live_file_does_not_empty_the_queue(data, tmp_path):
    data(["https://b.com/1.html"])
    (tmp_path / "live_posts.json").write_text("{ not json", encoding="utf-8")
    r = ip.build_queue()
    assert len(r["queue"]) == 1
    assert r["liveFilterApplied"] is False


def test_half_synced_live_file_is_not_trusted(data):
    """공개 목록이 검사 대상의 20% 미만만 덮으면 필터를 생략합니다.

    동기화가 반쯤 실패한 파일로 큐를 비우면, 색인이 안 되는 진짜 이유를
    영영 못 찾습니다.
    """
    urls = [f"https://b.com/{i}.html" for i in range(10)]
    data(urls, live=[urls[0]])            # 10건 중 1건 = 10%
    r = ip.build_queue()
    assert r["liveFilterApplied"] is False
    assert len(r["queue"]) == 10


def test_ratio_at_the_threshold_is_trusted(data):
    urls = [f"https://b.com/{i}.html" for i in range(10)]
    data(urls, live=urls[:2])             # 정확히 20%
    r = ip.build_queue()
    assert r["liveFilterApplied"] is True
    assert len(r["queue"]) == 2


def test_empty_live_list_is_treated_as_unknown(data):
    """공개 글 0건은 '전부 내렸다'가 아니라 '판정 불가'입니다."""
    data(["https://b.com/1.html"], live=[])
    r = ip.build_queue()
    assert r["liveFilterApplied"] is False
    assert len(r["queue"]) == 1


def test_already_indexed_urls_still_skipped(data, tmp_path):
    """기존 동작(색인된 글 제외)이 그대로인지."""
    data(["https://b.com/1.html"], live=["https://b.com/1.html"])
    items = json.loads((tmp_path / "index_status.json").read_text(encoding="utf-8"))
    items["items"][0]["verdict"] = "indexed"
    (tmp_path / "index_status.json").write_text(
        json.dumps(items, ensure_ascii=False), encoding="utf-8")
    r = ip.build_queue()
    assert r["queue"] == [] and r["skippedIndexed"] == 1
