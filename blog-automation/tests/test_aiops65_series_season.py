"""AIOPS-65 ④ — 2026-11-27 blog-run #392에서 본 결함 두 가지를 고정합니다.

(가) blog1 자동 시리즈가 1·2편 생성 실패, 3편 검토 대기였는데 run_series가
     None을 돌려줘 집계에서 빠졌습니다. 결과가 "발행 시도 없음·실패 0"(idle)으로
     남아 실패 알림도 건너뛰었습니다.
(나) 11/11 빼빼로데이 시즌 예약 키워드가 11/27에 쓰여, 구매 전 안내("출시 초반에
     확인")가 담긴 글이 blog3에 발행됐습니다. 예약 큐에 만료 조건이 없었습니다.

이 파일은 테스트 중단 규칙(2026-11-25~) 기간에 작성만 했고 실행하지 않았습니다.
"""
import json
import os
import sys
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import keyword_collector as kc  # noqa: E402
import main  # noqa: E402
from dashboard_exporter import classify_run_outcome  # noqa: E402


# ── (가) 시리즈 결과가 실행 집계에 들어가야 합니다 ────────────────────────────

def _eps(*statuses):
    return [{"episode": i + 1, "status": s, "title": f"편{i + 1}"} for i, s in enumerate(statuses)]


def test_series_failures_reach_run_outcome():
    """2026-11-27 blog1 그대로: 생성 실패 2편 + 검토 대기 1편 → idle이 아니라 failed."""
    eps = _eps("failed", "failed", "pending_review")
    tally = main._series_run_tally(eps, [None, None, None])
    assert tally["attempted"] == 3
    assert tally["failed"] == 2 and tally["pending"] == 1 and tally["published"] == 0
    assert len(tally["errors"]) == 2
    outcome = classify_run_outcome(tally["attempted"], tally["published"], tally["pending"], tally["failed"])
    assert outcome == "failed"


def test_episodes_done_in_earlier_runs_are_not_recounted():
    """이전 실행에서 이미 done인 편이 오늘 '게시'로 다시 세어지면 안 됩니다."""
    eps = _eps("done", "done", "scheduled")
    tally = main._series_run_tally(eps, ["done", "pending_review", "scheduled"])
    # 2편은 pending_review → done 으로 이번에 바뀌었으므로 게시 1건
    assert tally == {"attempted": 1, "published": 1, "pending": 0, "failed": 0, "errors": []}


def test_policy_rejection_counts_as_failure_like_single_posts():
    tally = main._series_run_tally(_eps("rejected_policy"), [None])
    assert tally["failed"] == 1 and "애드센스" in tally["errors"][0]


# ── (나) 행사가 지난 시즌 예약 키워드는 쓰지 않습니다 ─────────────────────────

def test_pepero_day_keyword_expires_after_grace(monkeypatch):
    monkeypatch.delenv("SEASON_KEYWORD_EXPIRE_DAYS", raising=False)
    item = {"event_date": "2026-11-11"}
    assert not kc._season_expired(item, datetime(2026, 11, 14))   # 행사 후 3일까지 허용
    assert kc._season_expired(item, datetime(2026, 11, 15))
    assert kc._season_expired(item, datetime(2026, 11, 27))       # 실제 발행일


def test_missing_or_bad_event_date_never_expires():
    assert not kc._season_expired({}, datetime(2026, 11, 27))
    assert not kc._season_expired({"event_date": "미정"}, datetime(2026, 11, 27))


def test_loader_skips_past_events(tmp_path, monkeypatch):
    queue = {"queue": [
        {"keyword": "빼빼로데이 과자 선물세트 솔직 비교", "event": "빼빼로데이",
         "event_date": "2026-11-11", "scheduledFor": "2026-11-04", "blog_id": "", "consumed": False},
        {"keyword": "연말정산 간소화 미리보기", "event": "연말정산시즌",
         "event_date": "2027-01-15", "scheduledFor": "2026-11-20", "blog_id": "", "consumed": False},
    ]}
    path = tmp_path / "scheduled_keywords.json"
    path.write_text(json.dumps(queue, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(kc, "_SCHEDULED_KW_FILE", str(path))
    monkeypatch.delenv("SEASON_KEYWORD_EXPIRE_DAYS", raising=False)
    got = kc._load_scheduled_keywords(today=datetime(2026, 11, 27), blog_id="blog3")
    assert got == ["연말정산 간소화 미리보기"]
