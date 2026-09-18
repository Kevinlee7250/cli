"""비공개 모드에서 severity_filter가 '이 등급 이상'으로 동작하는지 검사합니다.

2026-09-18: `unpublish_severity=high` 로 돌렸더니 high 6편만 잡히고
critical 1편("통영 여행 2박3일 실제 경비 공개")이 빠졌습니다.

워크플로가 --severity와 --unpublish-severity에 같은 값을 넘기는데,
--severity가 '정확히 그 등급'으로 동작해서 더 심각한 글이 제외됐습니다.
가장 심각한 글이 남는, 정확히 반대 방향의 사고입니다.
"""
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import fix_experience_claims as mod  # noqa: E402


def _kept(sev, severity_filter, unpublish_critical):
    """run()의 필터 분기와 같은 판정."""
    if severity_filter:
        if unpublish_critical:
            return mod._at_least(sev, severity_filter)
        return sev == severity_filter
    return True


def test_critical_is_included_when_unpublishing_high():
    """이번에 빠졌던 바로 그 경우."""
    assert _kept("critical", "high", unpublish_critical=True), (
        "high 이상을 내리는데 critical이 빠졌습니다"
    )
    assert _kept("high", "high", unpublish_critical=True)
    assert not _kept("medium", "high", unpublish_critical=True)


def test_rewrite_mode_keeps_exact_match():
    """본문 리라이팅(bodies)은 기존대로 '정확히 그 등급'이어야 합니다.

    여기까지 '이상'으로 바꾸면 medium만 고치려던 실행이 critical 글의
    본문까지 건드립니다.
    """
    assert _kept("medium", "medium", unpublish_critical=False)
    assert not _kept("critical", "medium", unpublish_critical=False)
    assert not _kept("high", "medium", unpublish_critical=False)


def test_no_filter_means_everything():
    for sev in ("critical", "high", "medium"):
        assert _kept(sev, "", unpublish_critical=True)
        assert _kept(sev, "", unpublish_critical=False)


def test_source_uses_the_floor_in_unpublish_mode():
    """분기가 실제로 run() 안에 배선돼 있는지."""
    with open(os.path.join(os.path.dirname(_HERE), "fix_experience_claims.py"),
              encoding="utf-8") as f:
        src = f.read()
    assert "if unpublish_critical:" in src
    assert "_at_least(sev, severity_filter)" in src
