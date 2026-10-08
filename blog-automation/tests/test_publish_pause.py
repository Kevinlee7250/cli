"""발행 정지 스위치가 '모든' 발행 경로를 막는지 확인합니다.

2026-10-08: 애드센스가 같은 사유로 두 번째 거절했고(색인 0건·노출 0회),
발행을 멈추기로 했습니다. 그런데 publish_schedule.json 은 blog-run.yml 만
막고 있었고, series-schedule.yml 이 쓰는 process_scheduled_series() 는
그 파일을 아예 보지 않아서 매일 계속 발행하는 상태였습니다.
'정면만 잠그고 옆문은 열어둔' 경우라 여기에 고정해 둡니다.
"""

import json
import os
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

SCHEDULE_PATH = os.path.join(BASE_DIR, "publish_schedule.json")
BLOG_IDS = ("blog1", "blog2", "blog3")


def _schedule() -> dict:
    with open(SCHEDULE_PATH, encoding="utf-8") as f:
        return json.load(f)


# ── 현재 저장소 상태 ─────────────────────────────────────────────────────────

def test_all_blogs_are_currently_paused():
    """지금은 세 블로그 모두 멈춰 있어야 합니다.

    다시 켤 때는 이 테스트를 함께 고치게 되므로, 실수로 켜지는 일이 없습니다.
    """
    blogs = _schedule()["blogs"]
    for blog_id in BLOG_IDS:
        assert blogs[blog_id]["enabled"] is False, (
            f"{blog_id} 가 켜져 있습니다 — 2026-10-08 이후 발행은 멈춘 상태입니다"
        )


def test_pause_reason_is_recorded():
    """왜 멈췄는지가 파일에 남아 있어야 합니다."""
    assert _schedule().get("_stopped"), "멈춘 이유가 적혀 있지 않습니다"


def test_posts_for_today_is_zero_while_paused():
    from publish_schedule import posts_for_today
    for blog_id in BLOG_IDS:
        assert posts_for_today(blog_id) == 0


# ── 옆문: 예약 시리즈 ────────────────────────────────────────────────────────

def test_scheduled_series_is_paused_too():
    """예약 시리즈도 같은 스위치를 봐야 합니다."""
    from main import _series_publishing_paused
    for blog_id in BLOG_IDS:
        assert _series_publishing_paused(blog_id) is True


def test_series_without_blog_id_never_publishes():
    """blog_id 가 없는 계획은 발행하지 않습니다 (어느 블로그인지 모름)."""
    from main import _series_publishing_paused
    assert _series_publishing_paused("") is True
    assert _series_publishing_paused(None) is True


def _stub_schedule(monkeypatch, posts_for_today):
    """publish_schedule 모듈을 가짜로 바꿉니다 (monkeypatch가 원복해 줍니다)."""
    import types
    stub = types.ModuleType("publish_schedule")
    stub.posts_for_today = posts_for_today
    monkeypatch.setitem(sys.modules, "publish_schedule", stub)


def test_series_is_paused_when_schedule_cannot_be_read(monkeypatch):
    """스케줄을 못 읽으면 '발행해도 된다'가 아니라 '발행하지 않는다'."""
    import main

    def _boom(_blog_id):
        raise OSError("스케줄 파일을 읽을 수 없습니다")

    _stub_schedule(monkeypatch, _boom)
    assert main._series_publishing_paused("blog1") is True


def test_series_resumes_when_switch_is_on(monkeypatch):
    """스위치를 켜면 다시 발행됩니다 — 영구 차단이 아니어야 합니다."""
    import main

    _stub_schedule(monkeypatch, lambda _blog_id: 1)
    assert main._series_publishing_paused("blog1") is False


# ── 발행하는 워크플로가 모두 스위치를 거치는지 ───────────────────────────────

PUBLISHING_WORKFLOWS = {
    # 워크플로 파일 → 그 워크플로가 스위치를 거치는 근거가 되는 문자열
    "blog-run.yml": "publish_schedule.py",
    "series-schedule.yml": "--process-scheduled-series",
}


@pytest.mark.parametrize("filename,marker", sorted(PUBLISHING_WORKFLOWS.items()))
def test_publishing_workflow_goes_through_the_switch(filename, marker):
    """발행하는 스케줄 워크플로는 스위치를 보는 경로만 써야 합니다.

    blog-run.yml 은 publish_schedule.py 로 오늘 편수를 뽑고,
    series-schedule.yml 은 _series_publishing_paused 를 통과하는
    --process-scheduled-series 만 호출합니다.
    """
    path = os.path.join(os.path.dirname(BASE_DIR), ".github", "workflows", filename)
    if not os.path.exists(path):
        pytest.skip(f"{filename} 이 없습니다")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert marker in text, f"{filename} 이 {marker} 를 쓰지 않습니다"


# ── schedule 인자를 생략해도 파일을 읽는지 ───────────────────────────────────

def test_entry_for_reads_the_file_when_schedule_is_omitted():
    """2026-10-08: entry_for(blog_id) 가 파일을 읽지 않고 DEFAULT_ENTRY
    (켜짐·1편/일)로 떨어져서, enabled=false 를 적어도 스위치가 안 내려갔습니다.
    '스위치를 내렸는데 발행이 계속되는' 사고라 여기에 고정합니다."""
    from publish_schedule import entry_for
    on_file = _schedule()["blogs"]["blog1"]["enabled"]
    assert entry_for("blog1")["enabled"] is bool(on_file)


def test_explicit_schedule_still_wins():
    """명시적으로 넘긴 설정은 그대로 쓰입니다 (대시보드 내보내기 경로)."""
    from publish_schedule import entry_for, posts_for_today
    sched = {"blogs": {"blog1": {"enabled": True, "postsPerDay": 3, "days": "daily"}}}
    assert entry_for("blog1", sched)["postsPerDay"] == 3
    assert posts_for_today("blog1", sched) == 3


def test_unreadable_file_still_falls_back_to_default(monkeypatch):
    """파일을 못 읽는 경우의 기존 동작(기본값 1편/일)은 유지합니다."""
    import publish_schedule
    monkeypatch.setattr(publish_schedule, "load_schedule", lambda *a, **k: {})
    assert publish_schedule.entry_for("blog1") == dict(publish_schedule.DEFAULT_ENTRY)
