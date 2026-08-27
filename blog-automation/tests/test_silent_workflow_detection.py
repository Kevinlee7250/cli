"""트리거가 끊긴 워크플로를 잡습니다.

detect_consecutive_failures는 "실패했다"만 봅니다. 실행이 아예 없으면
completed가 threshold보다 적어 그대로 continue로 넘어가므로, 트리거가
끊긴 워크플로는 조용해질수록 건강해 보입니다.

실제로 그 사고가 있었습니다 — blog-verify가 38회 연속 실패한 뒤 아예
트리거되지 않았고, 실패가 멎자 화면이 조용해져 12일 뒤에야 발견됐습니다.
"""

import schedule_manager as sm


def _wf(cron, runs, *, count=1, enabled=True):
    return {"x.yml": {"cron_utc": cron, "cron_count": count, "enabled": enabled,
                      "category": "test", "recent_runs": runs}}


_RUN = {"run_id": 1, "status": "completed", "conclusion": "success"}


# ── 주기 계산 ────────────────────────────────────────────────────────────────

def test_daily_cron_is_24h():
    assert sm.expected_interval_hours("0 22 * * *") == 24.0


def test_weekly_cron_is_a_week():
    assert sm.expected_interval_hours("0 0 * * 1") == 24.0 * 7


def test_step_cron_uses_its_step():
    assert sm.expected_interval_hours("20 */6 * * *") == 6.0


def test_multiple_daily_crons_shorten_the_interval():
    """collect-keywords는 하루 8번 돕니다 — 3시간마다."""
    assert sm.expected_interval_hours("0 17 * * *", 8) == 3.0


def test_unparseable_cron_returns_zero():
    assert sm.expected_interval_hours("nonsense") == 0.0
    assert sm.expected_interval_hours("") == 0.0


# ── 침묵 판정 ────────────────────────────────────────────────────────────────

def test_daily_workflow_with_no_runs_is_silent():
    """이게 핵심입니다 — 연속 실패 감지가 놓치던 자리."""
    silent = sm.detect_silent_workflows(_wf("0 22 * * *", []))
    assert len(silent) == 1
    assert silent[0]["workflow"] == "x.yml"


def test_the_old_detector_would_have_missed_it():
    """같은 입력을 연속 실패 감지에 주면 아무것도 안 나옵니다."""
    runs = _wf("0 22 * * *", [])
    assert sm.detect_consecutive_failures(runs) == []
    assert sm.detect_silent_workflows(runs)


def test_workflow_that_ran_is_not_silent():
    assert sm.detect_silent_workflows(_wf("0 22 * * *", [_RUN])) == []


def test_weekly_workflow_is_not_flagged_daily():
    """수집 창(25시간)보다 드물게 도는 것은 실행이 없는 게 정상입니다."""
    assert sm.detect_silent_workflows(_wf("0 0 * * 1", [])) == []


def test_disabled_workflow_is_skipped():
    assert sm.detect_silent_workflows(_wf("0 22 * * *", [], enabled=False)) == []


def test_unknown_cadence_is_not_guessed():
    """주기를 모르면 판정하지 않습니다 — 오탐이 침묵보다 나은 건 아닙니다."""
    assert sm.detect_silent_workflows(_wf("", [])) == []


def test_grace_keeps_a_slightly_late_run_from_alerting():
    """GitHub 스케줄은 자주 밀립니다. 여유가 없으면 매일 오탐이 납니다."""
    # 12시간마다(하루 2번) → deadline 24h ≤ 창 25h → 판정 대상
    assert sm.detect_silent_workflows(_wf("0 1 * * *", [], count=2))
    # 같은 주기에 실행이 하나라도 있으면 정상
    assert sm.detect_silent_workflows(_wf("0 1 * * *", [_RUN], count=2)) == []
