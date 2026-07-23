"""자가진단 자동 대조 봇 + 주간 운영 브리핑 테스트.

실행: cd blog-automation && python -m pytest tests/test_self_diagnosis_and_brief.py -v
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ──────────────────────────────────────────────────────────────────────────────
# incident_log.match_known — 자가진단 자동 대조
# ──────────────────────────────────────────────────────────────────────────────

def test_match_known_finds_overlapping_incident(monkeypatch, tmp_path):
    import incident_log as il

    log_path = tmp_path / "incident_log.json"
    monkeypatch.setattr(il, "_LOG_FILE", str(log_path))
    il.add_incident(
        title="GSC 도메인 속성 403",
        symptom="사이트맵 제출이 blog1에서만 403으로 실패",
        root_cause="URL-프리픽스 조회가 도메인 속성 GSC에 안 맞음",
        fix="_domain_property_for() 폴백 추가",
    )

    result = il.match_known("blog1 사이트맵 제출 403 실패")
    assert result is not None
    assert result["title"] == "GSC 도메인 속성 403"
    assert "폴백" in result["fix"]


def test_match_known_returns_none_when_no_overlap(monkeypatch, tmp_path):
    import incident_log as il

    log_path = tmp_path / "incident_log.json"
    monkeypatch.setattr(il, "_LOG_FILE", str(log_path))
    il.add_incident(
        title="GSC 도메인 속성 403",
        symptom="사이트맵 제출이 blog1에서만 403으로 실패",
        root_cause="URL-프리픽스 조회가 도메인 속성 GSC에 안 맞음",
        fix="폴백 추가",
    )

    assert il.match_known("전혀 관계없는 완전히 다른 메시지") is None


def test_match_known_empty_log_returns_none(monkeypatch, tmp_path):
    import incident_log as il
    monkeypatch.setattr(il, "_LOG_FILE", str(tmp_path / "missing.json"))
    assert il.match_known("아무 메시지") is None


# ──────────────────────────────────────────────────────────────────────────────
# weekly_brief.generate_brief — 주간 운영 브리핑 집계
# ──────────────────────────────────────────────────────────────────────────────

def _iso(dt):
    return dt.isoformat()


def test_weekly_brief_aggregates_recent_runs_only(monkeypatch, tmp_path):
    import weekly_brief as wb

    monkeypatch.setattr(wb, "_DOCS_DATA", str(tmp_path))
    monkeypatch.setattr(wb, "_OUT_FILE", str(tmp_path / "weekly_brief.json"))

    now = datetime.now(timezone.utc)
    recent = now - timedelta(days=2)
    old = now - timedelta(days=20)

    runs = [
        {"runAt": _iso(recent), "postsGenerated": 2, "bloggerUploaded": 2, "errors": 0,
         "blogId": "blog1", "blogName": "HOGU What?"},
        {"runAt": _iso(old), "postsGenerated": 5, "bloggerUploaded": 5, "errors": 0,
         "blogId": "blog1", "blogName": "HOGU What?"},
    ]
    with open(tmp_path / "runs.json", "w", encoding="utf-8") as f:
        json.dump(runs, f)
    with open(tmp_path / "repairs.json", "w", encoding="utf-8") as f:
        json.dump([], f)
    with open(tmp_path / "posts.json", "w", encoding="utf-8") as f:
        json.dump([], f)

    brief = wb.generate_brief()
    assert brief["metrics"]["posts_uploaded"] == 2
    assert brief["metrics"]["posts_generated"] == 2


def test_weekly_brief_flags_risk_when_auth_broken(monkeypatch, tmp_path):
    import weekly_brief as wb

    monkeypatch.setattr(wb, "_DOCS_DATA", str(tmp_path))
    monkeypatch.setattr(wb, "_OUT_FILE", str(tmp_path / "weekly_brief.json"))

    with open(tmp_path / "runs.json", "w", encoding="utf-8") as f:
        json.dump([], f)
    with open(tmp_path / "repairs.json", "w", encoding="utf-8") as f:
        json.dump([], f)
    with open(tmp_path / "posts.json", "w", encoding="utf-8") as f:
        json.dump([], f)
    with open(tmp_path / "auth_health.json", "w", encoding="utf-8") as f:
        json.dump({"all_ok": False}, f)

    brief = wb.generate_brief()
    assert any("인증" in r for r in brief["risks"])


def test_weekly_brief_counts_recurring_issues_from_known_incident_matches(monkeypatch, tmp_path):
    import weekly_brief as wb

    monkeypatch.setattr(wb, "_DOCS_DATA", str(tmp_path))
    monkeypatch.setattr(wb, "_OUT_FILE", str(tmp_path / "weekly_brief.json"))

    now = datetime.now(timezone.utc)
    repairs = [{
        "timestamp": _iso(now - timedelta(days=1)),
        "health_score": 80,
        "issues": [
            {"level": "warning", "message": "x", "known_incident": {"title": "과거 인시던트"}},
            {"level": "warning", "message": "y"},
        ],
    }]
    with open(tmp_path / "runs.json", "w", encoding="utf-8") as f:
        json.dump([], f)
    with open(tmp_path / "repairs.json", "w", encoding="utf-8") as f:
        json.dump(repairs, f)
    with open(tmp_path / "posts.json", "w", encoding="utf-8") as f:
        json.dump([], f)

    brief = wb.generate_brief()
    assert brief["metrics"]["recurring_issues_auto_matched"] == 1
    assert brief["metrics"]["avg_health_score"] == 80.0
