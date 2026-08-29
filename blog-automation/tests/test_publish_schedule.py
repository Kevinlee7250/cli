"""블로그별 발행 계획.

왜
──
발행량이 워크플로에 박혀 있어(연중일 % 3으로 당번 하나) 블로그마다 3일에
1편이었고, 바꾸려면 매번 워크플로를 고쳐야 했습니다. 이제 설정 파일이
원본입니다. 여기서 지키는 것은 세 가지입니다.

  1. 설정을 못 읽어도 발행이 조용히 멈추지 않는다
  2. 워크플로가 실제로 그 계획을 읽어 쓴다 (모듈만 있고 안 부르면 무의미)
  3. 수동 발행은 이 계획에 묶이지 않는다 — 급할 때 설정을 건드리지 않고
     바로 올릴 수 있어야 합니다
"""

import json
import os
import sys
from datetime import datetime

import pytest
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import publish_schedule as ps  # noqa: E402

_WF = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..",
                                    ".github", "workflows", "blog-run.yml"))
_CFG = os.path.normpath(os.path.join(os.path.dirname(__file__), "..",
                                     "publish_schedule.json"))


# ── 기본값과 방어 ────────────────────────────────────────────────────────────

def test_missing_file_still_publishes(tmp_path):
    """설정을 못 읽었다고 발행이 멈추면 초록불인데 글이 안 올라옵니다."""
    assert ps.load_schedule(str(tmp_path / "없는파일.json")) == {}
    assert ps.plan_for_today({}) == {"blog1": 1, "blog2": 1, "blog3": 1}


def test_broken_json_falls_back(tmp_path):
    bad = tmp_path / "publish_schedule.json"
    bad.write_text("{ 깨진 내용", encoding="utf-8")
    assert ps.load_schedule(str(bad)) == {}


def test_unknown_blog_gets_default():
    assert ps.entry_for("blog9", {"blogs": {}}) == ps.DEFAULT_ENTRY


def test_non_numeric_count_is_treated_as_one():
    e = ps.entry_for("blog1", {"blogs": {"blog1": {"postsPerDay": "많이"}}})
    assert e["postsPerDay"] == 1


@pytest.mark.parametrize("given,expected", [(-3, 0), (0, 0), (2, 2), (99, 5)])
def test_count_is_clamped(given, expected):
    e = ps.entry_for("blog1", {"blogs": {"blog1": {"postsPerDay": given}}})
    assert e["postsPerDay"] == expected


# ── 계획 계산 ────────────────────────────────────────────────────────────────

def test_disabled_blog_publishes_nothing():
    sched = {"blogs": {"blog2": {"enabled": False, "postsPerDay": 3}}}
    assert ps.posts_for_today("blog2", sched) == 0


def test_zero_count_is_the_same_as_off():
    sched = {"blogs": {"blog2": {"enabled": True, "postsPerDay": 0}}}
    assert ps.posts_for_today("blog2", sched) == 0


def test_weekday_filter_skips_other_days():
    sched = {"blogs": {"blog1": {"enabled": True, "postsPerDay": 2, "days": [0]}}}
    monday = datetime(2026, 8, 31, 7, 0, tzinfo=ps.KST)
    tuesday = datetime(2026, 9, 1, 7, 0, tzinfo=ps.KST)
    assert ps.posts_for_today("blog1", sched, monday) == 2
    assert ps.posts_for_today("blog1", sched, tuesday) == 0


def test_weekday_is_judged_in_kst():
    """크론이 UTC 22시라 UTC 요일로 보면 하루가 밀립니다."""
    sched = {"blogs": {"blog1": {"enabled": True, "postsPerDay": 1, "days": [0]}}}
    from datetime import timezone
    # UTC 일요일 22:00 = KST 월요일 07:00 — 발행일이어야 합니다
    run = datetime(2026, 8, 30, 22, 0, tzinfo=timezone.utc)
    assert ps.posts_for_today("blog1", sched, run) == 1


# ── 실제 설정값 ──────────────────────────────────────────────────────────────

def test_shipped_config_gives_every_blog_at_least_one_a_day():
    with open(_CFG, encoding="utf-8") as f:
        sched = json.load(f)
    plan = ps.plan_for_today(sched, datetime(2026, 8, 31, 7, 0, tzinfo=ps.KST))
    assert all(n >= 1 for n in plan.values()), plan


# ── 워크플로 연결 ────────────────────────────────────────────────────────────

def _wf():
    with open(_WF, encoding="utf-8") as f:
        return f.read()


def test_workflow_actually_runs_the_planner():
    """모듈만 있고 워크플로가 부르지 않으면 계획은 아무 효과가 없습니다."""
    assert "publish_schedule.py --github-output" in _wf()


def test_old_day_of_year_rotation_is_gone():
    # 주석에는 "예전에는 연중일 % 3이었다"는 설명이 남아도 됩니다 —
    # 실제로 도는 코드에 남아 있으면 계획과 둘 중 무엇이 이기는지 모릅니다.
    code = [ln for ln in _wf().split("\n") if not ln.lstrip().startswith("#")]
    text = "\n".join(code)
    assert "date -u +%j" not in text and "outputs.today" not in text, (
        "연중일 당번 로직이 남아 있으면 계획과 둘 중 무엇이 이기는지 알 수 없습니다"
    )


@pytest.mark.parametrize("blog", ps.BLOG_IDS)
def test_each_blog_job_reads_its_own_plan(blog):
    text = _wf()
    assert f"needs.rotation.outputs.{blog} != '0'" in text
    assert f"needs.rotation.outputs.{blog} ||" in text, (
        f"{blog}이 계획된 편수를 POSTS_PER_RUN으로 쓰지 않습니다"
    )


def test_manual_run_is_not_gated_by_the_plan():
    """급할 때 설정을 고치지 않고 바로 올릴 수 있어야 합니다."""
    wf = yaml.safe_load(_wf())
    for blog in ps.BLOG_IDS:
        cond = wf["jobs"][f"publish-{blog}"]["if"]
        assert f"github.event_name != 'schedule'" in cond, blog
        # 계획 게이트는 schedule 분기 안에만 있어야 합니다
        manual_part = cond.split("github.event_name != 'schedule'", 1)[1]
        assert "rotation.outputs" not in manual_part, (
            f"{blog}의 수동 실행 조건이 발행 계획에 묶여 있습니다"
        )


def test_dashboard_can_read_and_write_the_plan():
    html = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..",
                                         "docs", "index.html"))
    with open(html, encoding="utf-8") as f:
        text = f.read()
    assert "blog-automation/publish_schedule.json" in text, "대시보드가 원본 파일을 고치지 않습니다"
    assert "fetchData(base, 'publish_schedule.json'" in text, "대시보드가 현재 설정을 읽지 않습니다"
    # 정의만 하고 부르지 않으면 화면에는 아무것도 안 뜹니다
    assert text.count("renderPublishSchedule()") >= 2
    assert "savePublishSchedule(" in text
