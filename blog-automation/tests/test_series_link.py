"""시리즈 회차 ↔ 글 연결 — 제목이 아니라 id로 잇습니다.

지금까지 둘을 잇는 유일한 끈이 제목이었습니다. 그런데 final_editor가 생성
후 제목을 교정하므로(`post_data["title"] = new_title`) 그 순간 연결이
끊깁니다. 2026-08-24 점검에서 pending_review 41편 중 38편이 검토 대기·보관·
발행 목록·레지스트리 어디에서도 제목으로 찾히지 않았습니다.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import series_relink  # noqa: E402


def test_save_pending_posts_returns_assigned_ids(tmp_path, monkeypatch):
    """호출부가 id를 받아야 회차에 적어 둘 수 있습니다."""
    import dashboard_exporter as de
    import pending_store as ps
    monkeypatch.setattr(ps, "INDEX_FILE", str(tmp_path / "pending_posts.json"))
    monkeypatch.setattr(ps, "BODIES_FILE", str(tmp_path / "pending_bodies.json"))
    monkeypatch.setattr(ps, "ARCHIVE_FILE", str(tmp_path / "pending_archive.json"))

    ids = de.save_pending_posts(
        [{"title": "1편 제목", "content": "<p>본문</p>", "keyword": "테스트"},
         {"title": "2편 제목", "content": "<p>본문</p>", "keyword": "테스트"}],
        {"id": "blog1"})
    assert len(ids) == 2 and all(ids)
    saved = {r["id"] for r in ps.load()}
    assert set(ids) == saved


def test_skipped_posts_keep_their_slot(tmp_path, monkeypatch):
    """건너뛴 항목도 자리를 지켜야 호출부가 순서대로 짝지을 수 있습니다."""
    import dashboard_exporter as de
    import pending_store as ps
    monkeypatch.setattr(ps, "INDEX_FILE", str(tmp_path / "pending_posts.json"))
    monkeypatch.setattr(ps, "BODIES_FILE", str(tmp_path / "pending_bodies.json"))
    monkeypatch.setattr(ps, "ARCHIVE_FILE", str(tmp_path / "pending_archive.json"))

    ids = de.save_pending_posts(
        [{"title": "정상", "content": "<p>본문</p>"},
         {"title": "", "content": ""},                 # 건너뜀
         {"title": "정상2", "content": "<p>본문</p>"}],
        {"id": "blog1"})
    assert len(ids) == 3
    assert ids[0] and ids[1] == "" and ids[2]


def _series(tmp_path, episodes):
    path = tmp_path / "series.json"
    path.write_text(json.dumps([{"keyword": "테스트", "episodes": episodes}],
                               ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_relink_matches_by_exact_title(tmp_path, monkeypatch):
    monkeypatch.setattr(series_relink, "SERIES_FILE",
                        _series(tmp_path, [{"episode": 1, "title": "제목 A",
                                            "status": "pending_review"}]))
    monkeypatch.setattr(series_relink, "_candidates",
                        lambda: [{"id": "p1", "title": "제목 A"}])
    r = series_relink.relink(apply_changes=True)
    assert r["exact"] == 1 and r["lost"] == 0
    with open(series_relink.SERIES_FILE, encoding="utf-8") as f:
        assert json.load(f)[0]["episodes"][0]["post_id"] == "p1"


def test_relink_matches_by_prefix_when_title_was_edited(tmp_path, monkeypatch):
    """final_editor가 뒷부분을 고쳐도 앞부분으로 찾습니다.

    앞 14자까지가 같아야 합니다 — 제목 중간을 고쳤다면 못 찾습니다.
    그 한계 때문에 앞으로는 post_id로 잇습니다.
    """
    monkeypatch.setattr(series_relink, "SERIES_FILE",
                        _series(tmp_path, [{"episode": 1, "status": "pending_review",
                                            "title": "연준 금리 발표에 계좌가 흔들린 이유"}]))
    monkeypatch.setattr(series_relink, "_candidates", lambda: [
        {"id": "p9", "title": "연준 금리 발표에 계좌가 흔들린 이유와 대응 방법 총정리"}])
    r = series_relink.relink(apply_changes=True)
    assert r["prefix"] == 1


def test_prefix_match_fails_when_title_middle_changed(tmp_path, monkeypatch):
    """앞부분이 갈라지면 못 찾습니다 — 이 한계를 알고 쓰라고 고정해 둡니다."""
    monkeypatch.setattr(series_relink, "SERIES_FILE",
                        _series(tmp_path, [{"episode": 1, "status": "pending_review",
                                            "title": "연준 금리 발표에 계좌가 흔들린 이유"}]))
    monkeypatch.setattr(series_relink, "_candidates", lambda: [
        {"id": "p9", "title": "연준 금리 발표에 계좌가 흔들린 진짜 이유"}])
    r = series_relink.relink(apply_changes=True)
    assert r["prefix"] == 0 and r["lost"] == 1


def test_unfindable_episode_is_marked_lost_with_reason(tmp_path, monkeypatch):
    """열 수 없는 일감을 '검토 대기'로 남겨 두지 않습니다."""
    monkeypatch.setattr(series_relink, "SERIES_FILE",
                        _series(tmp_path, [{"episode": 1, "title": "사라진 글",
                                            "status": "pending_review"}]))
    monkeypatch.setattr(series_relink, "_candidates", lambda: [])
    series_relink.relink(apply_changes=True)
    with open(series_relink.SERIES_FILE, encoding="utf-8") as f:
        ep = json.load(f)[0]["episodes"][0]
    assert ep["status"] == series_relink.LOST_STATUS
    assert ep.get("lostReason"), "왜 lost인지 남겨야 나중에 다시 조사하지 않습니다"


def test_already_linked_episodes_are_left_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(series_relink, "SERIES_FILE",
                        _series(tmp_path, [{"episode": 1, "title": "X", "post_id": "keep",
                                            "status": "pending_review"}]))
    monkeypatch.setattr(series_relink, "_candidates",
                        lambda: [{"id": "other", "title": "X"}])
    r = series_relink.relink(apply_changes=True)
    assert r["alreadyLinked"] == 1
    with open(series_relink.SERIES_FILE, encoding="utf-8") as f:
        assert json.load(f)[0]["episodes"][0]["post_id"] == "keep"


def test_dry_run_changes_nothing(tmp_path, monkeypatch):
    path = _series(tmp_path, [{"episode": 1, "title": "사라진 글", "status": "pending_review"}])
    monkeypatch.setattr(series_relink, "SERIES_FILE", path)
    monkeypatch.setattr(series_relink, "_candidates", lambda: [])
    before = open(path, encoding="utf-8").read()
    series_relink.relink(apply_changes=False)
    assert open(path, encoding="utf-8").read() == before


# ──────────────────────────────────────────────────────────────────────────────
# 저장소의 실제 series.json
# ──────────────────────────────────────────────────────────────────────────────

def test_shipped_series_has_no_internal_refs():
    """회차 레코드에 파이썬 객체 참조가 새어 들어가면 안 됩니다."""
    path = os.path.join(os.path.dirname(__file__), "..", "..",
                        "docs", "data", "series.json")
    with open(path, encoding="utf-8") as f:
        series = json.load(f)
    for sr in series:
        for ep in sr.get("episodes", []):
            assert "_post_ref" not in ep, (
                "_post_ref는 저장 전에 사라져야 하는 임시 짝입니다"
            )
