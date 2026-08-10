"""검토 대기 글 정리·재검증 (pending_manager) 테스트.

실행: cd blog-automation && python -m pytest tests/test_pending_manager.py -v
"""

import json
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _entry(status="pending", days_ago=0, content="본문" * 100, **kw):
    e = {
        "id": kw.pop("id", f"p{days_ago}{status}"),
        "title": kw.pop("title", "글 제목"),
        "status": status,
        "savedAt": (datetime.now() - timedelta(days=days_ago)).isoformat(),
        "content": content,
        "wordCount": 3000,
    }
    e.update(kw)
    return e


# ──────────────────────────────────────────────────────────────────────────────
# prune — 끝난 건의 본문만 제거 (기록은 유지)
# ──────────────────────────────────────────────────────────────────────────────

def test_prune_removes_content_of_terminal_entries():
    from pending_manager import prune_terminal
    entries = [_entry("published", 10), _entry("expired", 40)]
    assert prune_terminal(entries) == 2
    assert all(e["content"] == "" for e in entries)
    assert all(e["contentBytes"] > 0 for e in entries)   # 원래 크기는 기록


def test_prune_keeps_pending_content():
    """대기 중인 글의 본문은 절대 지우면 안 됨 — 발행에 필요."""
    from pending_manager import prune_terminal
    entries = [_entry("pending", 100)]
    assert prune_terminal(entries) == 0
    assert entries[0]["content"]


def test_prune_keeps_recently_finished_content():
    """방금 끝난 건은 되돌릴 여지가 있으므로 유예 기간을 둠."""
    from pending_manager import prune_terminal
    entries = [_entry("published", 0)]
    assert prune_terminal(entries, keep_days=3) == 0
    assert entries[0]["content"]


def test_prune_is_idempotent():
    from pending_manager import prune_terminal
    entries = [_entry("published", 10)]
    prune_terminal(entries)
    assert prune_terminal(entries) == 0   # 두 번째 실행에선 할 일 없음


# ──────────────────────────────────────────────────────────────────────────────
# revalidate — 검증 불가와 실제 미달을 구분
# ──────────────────────────────────────────────────────────────────────────────

_UNVALIDATED = {
    "score": 65, "recommendation": "review",
    "checks": {"a": {"note": "검증 생략 (API 오류)"}},
    "warnings": ["AdSense 검증이 API 오류로 생략됐습니다."],
    "issues": [],
}


def test_revalidate_marks_api_error_as_unvalidated_not_failed():
    """검증기가 평가조차 못 한 걸 '미달'로 집계하면 리포트가 거짓말을 함."""
    from pending_manager import revalidate_pending
    entries = [_entry("pending", 5)]
    with patch("adsense_validator.validate_adsense", return_value=_UNVALIDATED):
        r = revalidate_pending(entries)
    assert r["unvalidated"] == 1 and r["failed"] == 0
    assert "콘텐츠 문제 아님" in entries[0]["revalidateReason"]


def test_revalidate_passes_high_score():
    from pending_manager import revalidate_pending
    entries = [_entry("pending", 5)]
    good = {"score": 90, "recommendation": "upload", "checks": {"a": {"note": "ok"}},
            "warnings": [], "issues": []}
    with patch("adsense_validator.validate_adsense", return_value=good):
        r = revalidate_pending(entries)
    assert r["passed"] == 1
    assert entries[0]["revalidated"] is True


def test_revalidate_fails_low_score_with_reason():
    from pending_manager import revalidate_pending
    entries = [_entry("pending", 5)]
    bad = {"score": 40, "recommendation": "review", "checks": {"a": {"note": "ok"}},
           "warnings": [], "issues": ["분량 부족"]}
    with patch("adsense_validator.validate_adsense", return_value=bad):
        r = revalidate_pending(entries)
    assert r["failed"] == 1 and r["unvalidated"] == 0
    assert entries[0]["revalidateReason"] == "분량 부족"


def test_revalidate_skips_entries_without_content():
    from pending_manager import revalidate_pending
    entries = [_entry("pending", 5, content="")]
    with patch("adsense_validator.validate_adsense") as m:
        r = revalidate_pending(entries)
    assert r["checked"] == 0 and not m.called


def test_revalidate_respects_limit():
    from pending_manager import revalidate_pending
    entries = [_entry("pending", 5, id=f"x{i}") for i in range(10)]
    with patch("adsense_validator.validate_adsense", return_value=_UNVALIDATED):
        r = revalidate_pending(entries, limit=3)
    assert r["checked"] == 3


# ──────────────────────────────────────────────────────────────────────────────
# expire
# ──────────────────────────────────────────────────────────────────────────────

def test_expire_old_pending_only():
    from pending_manager import expire_old
    entries = [_entry("pending", 40), _entry("pending", 5), _entry("published", 90)]
    assert expire_old(entries, days=30) == 1
    assert entries[0]["status"] == "expired"
    assert entries[1]["status"] == "pending"
    assert entries[2]["status"] == "published"


def test_expire_skips_revalidated_passers():
    """재검증을 통과한 글은 발행 대상 — 만료시키면 안 됨."""
    from pending_manager import expire_old
    entries = [_entry("pending", 90, revalidated=True)]
    assert expire_old(entries, days=30) == 0
    assert entries[0]["status"] == "pending"


# ──────────────────────────────────────────────────────────────────────────────
# run — 기본은 리포트만, --apply에서만 파일 변경
# ──────────────────────────────────────────────────────────────────────────────

def test_run_without_apply_does_not_write_pending(tmp_path, monkeypatch):
    import pending_manager as pm
    pending_file = tmp_path / "pending.json"
    original = [_entry("published", 30)]
    pending_file.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(pm, "PENDING_FILE", str(pending_file))
    monkeypatch.setattr(pm, "REPORT_PATH", str(tmp_path / "report.json"))

    with patch("adsense_validator.validate_adsense", return_value=_UNVALIDATED):
        report = pm.run(apply_changes=False, expire_days=30, revalidate_limit=0)

    assert json.loads(pending_file.read_text(encoding="utf-8"))[0]["content"]  # 그대로
    assert report["pruned"] == 1        # 리포트에는 예정 건수가 나옴


def test_run_with_apply_writes_changes(tmp_path, monkeypatch):
    import pending_manager as pm
    pending_file = tmp_path / "pending.json"
    pending_file.write_text(json.dumps([_entry("published", 30)], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(pm, "PENDING_FILE", str(pending_file))
    monkeypatch.setattr(pm, "REPORT_PATH", str(tmp_path / "report.json"))

    with patch("adsense_validator.validate_adsense", return_value=_UNVALIDATED):
        pm.run(apply_changes=True, expire_days=30, revalidate_limit=0)

    assert json.loads(pending_file.read_text(encoding="utf-8"))[0]["content"] == ""


def test_run_reports_ready_to_publish(tmp_path, monkeypatch):
    import pending_manager as pm
    pending_file = tmp_path / "pending.json"
    pending_file.write_text(json.dumps([_entry("pending", 5)], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(pm, "PENDING_FILE", str(pending_file))
    monkeypatch.setattr(pm, "REPORT_PATH", str(tmp_path / "report.json"))

    good = {"score": 95, "recommendation": "upload", "checks": {"a": {"note": "ok"}},
            "warnings": [], "issues": []}
    with patch("adsense_validator.validate_adsense", return_value=good):
        report = pm.run(apply_changes=False, expire_days=30, revalidate_limit=0)

    assert len(report["readyToPublish"]) == 1
    assert report["readyToPublish"][0]["score"] == 95
