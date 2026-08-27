"""스케줄 감시가 실제로 전부를 보고 있는지 고정합니다.

점검에서 나온 것: 스케줄 워크플로 22개 중 8개만 등록돼 있는데 감시기는
`alerts: 0`을 보고하고 있었습니다. backup(Drive 백업)이나 gsc-indexing(색인)이
조용히 멈춰도 아무도 몰랐습니다.

"안 보고 있어서 0"과 "문제가 없어서 0"이 화면에서 같아 보이는 것이 문제의
핵심입니다. 그래서 커버리지를 테스트로 고정합니다.

반대 방향도 봅니다. 설정에 blog-run의 정오·저녁 슬롯이 있었지만 워크플로에는
해당 크론이 없었습니다 — 돌지 않는 스케줄을 감시하고 있던 셈입니다.
"""

import glob
import json
import os
import re

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_WF = os.path.join(_ROOT, ".github", "workflows")
_CFG = os.path.join(_ROOT, "docs", "data", "schedule_config.json")


def _scheduled_workflows():
    """제목이 한글이거나 blog-automation을 쓰는, cron이 있는 워크플로."""
    out = {}
    for path in sorted(glob.glob(os.path.join(_WF, "*.yml"))):
        text = open(path, encoding="utf-8").read()
        if not (re.search(r"^name:.*[가-힣]", text, re.M)
                or "blog-automation" in text):
            continue
        crons = re.findall(r"cron:\s*['\"]([^'\"]+)['\"]", text)
        if crons:
            out[os.path.basename(path)] = crons
    return out


def _config():
    return json.load(open(_CFG, encoding="utf-8"))


def test_every_scheduled_workflow_is_monitored():
    registered = {s["workflow"] for s in _config()["schedules"]}
    missing = sorted(set(_scheduled_workflows()) - registered)
    assert not missing, (
        "스케줄로 도는데 감시 설정에 없습니다 — 조용히 멈춰도 아무도 "
        f"모릅니다. schedule_config.json에 추가하세요: {missing}"
    )


def test_no_phantom_schedule_is_monitored():
    """설정이 실제 워크플로에 없는 크론을 가리키면 안 됩니다."""
    actual = _scheduled_workflows()
    phantom = []
    for s in _config()["schedules"]:
        wf, cron = s["workflow"], s.get("cron_utc", "")
        if cron not in actual.get(wf, []):
            phantom.append(f"{s['id']} → {wf} {cron!r}")
    assert not phantom, (
        "워크플로에 없는 크론을 감시하고 있습니다 — 돌 리 없는 실행을 "
        f"기다리게 됩니다: {phantom}"
    )


def test_registered_workflow_files_exist():
    names = {os.path.basename(p) for p in glob.glob(os.path.join(_WF, "*.yml"))}
    gone = sorted({s["workflow"] for s in _config()["schedules"]} - names)
    assert not gone, f"설정이 없는 워크플로 파일을 가리킵니다: {gone}"


def test_cron_count_matches_the_workflow():
    """크론이 여러 개인 워크플로는 그만큼 자주 돕니다 — 침묵 판정에 씁니다."""
    actual = _scheduled_workflows()
    wrong = []
    for s in _config()["schedules"]:
        want = len(actual.get(s["workflow"], []))
        if want and s.get("cron_count", 1) != want:
            wrong.append(f"{s['workflow']}: 설정 {s.get('cron_count')} ≠ 실제 {want}")
    assert not wrong, wrong


def test_check_is_not_vacuous():
    assert len(_scheduled_workflows()) >= 20
    assert len(_config()["schedules"]) >= 20
