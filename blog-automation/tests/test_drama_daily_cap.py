"""드라마 회차 글이 하루 한 편씩, 방영 스케줄을 따라가는지 검사합니다.

2026-09-16에 HOGU What?에 포핸즈 글 3편이 하루에 올라갔습니다
(결말 총평 / 등장인물 분석 / 갈라 디너 첫인상). 하루치로는 양산형으로 읽히고,
9/13 재편 때 대량으로 내린 유형이 그대로 다시 쌓입니다.

원인은 두 가지였습니다.
  1) 이미 방영된 회차는 전부 status="pending"이라 한 실행에서 통째로 발행
  2) 하루 상한이 없어 실행이 두 번 돌면 두 편이 나감
"""
import os
import sys
from datetime import date, timedelta
from unittest.mock import patch

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import series_planner as sp  # noqa: E402


def _plan(count=4, latest=6, start=1):
    """방영 정보 조회를 막고 기획만 돌립니다 (네트워크·API 없음)."""
    info = {"latest_aired_episode": latest, "air_schedule": "토,일",
            "total_episodes": 16, "platform": "tvN", "confidence": "high"}
    with patch.object(sp, "fetch_drama_broadcast_info", return_value=info):
        return sp.plan_drama_episode_series("포핸즈", count=count, start_episode=start)


def test_aired_backlog_is_spread_one_per_day():
    """이미 방영된 4회차가 같은 날 발행 대상이 되면 안 됩니다."""
    plan = _plan(count=4, latest=6)
    aired = [e for e in plan["episodes"] if e["drama_episode"] <= 6]
    assert len(aired) == 4

    dates = [e.get("scheduled_date") for e in aired]
    assert len(set(dates)) == 4, f"같은 날짜에 몰렸습니다: {dates}"

    today = date.today()
    assert dates[0] == today.isoformat(), "첫 편은 오늘 나가야 합니다"
    for i, d in enumerate(dates):
        assert d == (today + timedelta(days=i)).isoformat()


def test_only_one_episode_is_due_today():
    """오늘 생성 대상은 정확히 한 편."""
    plan = _plan(count=6, latest=6)
    today = date.today().isoformat()
    due = [e for e in plan["episodes"]
           if e.get("status") != "done"
           and (e.get("scheduled_date") or today) <= today]
    assert len(due) == 1, f"오늘 대상이 {len(due)}편입니다"


def test_unaired_episodes_still_follow_the_broadcast_schedule():
    """미방영 회차는 기존대로 방영 익일 — 이 규칙을 깨면 안 됩니다."""
    plan = _plan(count=4, latest=2)
    unaired = [e for e in plan["episodes"] if e["drama_episode"] > 2]
    assert unaired, "미방영 회차가 잡히지 않았습니다"
    for e in unaired:
        assert e["status"] == "scheduled"
        if e.get("air_date") and e.get("scheduled_date"):
            air = date.fromisoformat(e["air_date"])
            sched = date.fromisoformat(e["scheduled_date"])
            assert sched == air + timedelta(days=1), "방영 익일이 아닙니다"


def test_series_description_makes_no_viewing_claim():
    """'직접 시청한 … 솔직 리뷰' — 코드가 만들던 경험 주장입니다."""
    from title_policy import check_title

    plan = _plan(count=2, latest=6)
    desc = plan["series_description"]
    assert "직접 시청" not in desc
    assert not check_title(desc), f"시리즈 설명이 정책 위반입니다: {desc}"


def test_episode_titles_are_informational():
    plan = _plan(count=2, latest=6)
    for e in plan["episodes"]:
        assert "시청률" in e["focus"], "편성·시청률이 focus에서 빠졌습니다"
        assert "연기 평가" not in e["focus"], "글쓴이 감상을 요구하고 있습니다"


def test_main_enforces_a_daily_cap():
    """기획이 날짜를 나눠도, 하루에 실행이 두 번 돌면 막을 것이 필요합니다."""
    with open(os.path.join(os.path.dirname(_HERE), "main.py"), encoding="utf-8") as f:
        src = f.read()
    assert 'series_plan.get("type") == "drama_episode_review"' in src
    assert "published_today >= 1" in src, "하루 1편 상한이 없습니다"
    assert 'ep["published_date"] = today_str' in src, (
        "발행일을 기록하지 않으면 다음 실행이 상한을 판정할 수 없습니다"
    )
