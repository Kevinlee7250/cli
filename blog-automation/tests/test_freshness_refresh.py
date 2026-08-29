"""데이터 신선도 패널의 새로고침·재수집.

왜
──
신선도 패널은 "이 파일이 며칠 된 것인지"만 보여 주고, 낡은 걸 발견해도
거기서 할 수 있는 일이 없었습니다(죽은 링크 39일). 화면에서 바로
다시 받고, 필요하면 그 파일을 만드는 워크플로를 돌릴 수 있어야 합니다.

여기서 지키는 것
────────────────
  1. 새로고침 버튼이 있고 실제로 함수를 부른다
  2. 재수집이 가리키는 워크플로가 저장소에 실제로 있고 수동 실행이 된다
  3. 발행 글을 고치는 워크플로에는 미리보기 입력을 반드시 넘긴다 —
     리포트를 갱신하려다 버튼 하나로 글이 고쳐지면 안 됩니다
"""

import os
import re

import pytest

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_HTML = os.path.join(_ROOT, "docs", "index.html")
_WF_DIR = os.path.join(_ROOT, ".github", "workflows")

#: 발행된 글을 실제로 고칠 수 있어 미리보기 입력이 필수인 워크플로.
#: fix-duplicate-images는 dry_run 기본값이 false라 빼먹으면 그대로 고칩니다.
_MUTATING = {
    "fix-dead-links.yml": "dry_run",
    "fix-duplicate-images.yml": "dry_run",
    "image-audit.yml": "apply",
    "pending-cleanup.yml": "apply",
}


def _html():
    with open(_HTML, encoding="utf-8") as f:
        return f.read()


def _wf_map():
    """FRESH_SOURCE_WF에서 {파일: (워크플로, 입력값 문자열)}을 뽑습니다."""
    m = re.search(r"const FRESH_SOURCE_WF = \{(.*?)\n\}", _html(), re.S)
    assert m, "FRESH_SOURCE_WF를 찾지 못했습니다"
    out = {}
    for line in m.group(1).split("\n"):
        hit = re.match(r"\s*'([^']+)':\s*\['([^']+)',\s*(\{.*?\}),", line)
        if hit:
            out[hit.group(1)] = (hit.group(2), hit.group(3))
    return out


def test_refresh_button_exists_and_is_wired():
    html = _html()
    assert 'id="freshness-refresh-btn"' in html
    assert 'onclick="freshnessRefresh()"' in html, "버튼이 아무것도 부르지 않습니다"
    assert "async function freshnessRefresh()" in html
    # 다시 받지 않으면 새로고침이 아닙니다
    assert re.search(r"function freshnessRefresh\(\)[\s\S]{0,600}loadAll\(true\)", html)


def test_recollect_button_is_rendered_not_just_defined():
    """정의만 있고 카드에 안 붙으면 화면에는 아무것도 안 뜹니다."""
    html = _html()
    assert "function freshnessRecollect(" in html
    assert html.count("freshnessRecollect('") >= 1, "재수집 버튼이 목록에 붙지 않았습니다"
    assert "FRESH_SOURCE_WF[r.name]" in html, "항목마다 생산 워크플로를 보지 않습니다"


def test_map_is_not_empty():
    assert len(_wf_map()) >= 15


@pytest.mark.parametrize("name", sorted(_wf_map()))
def test_every_mapped_workflow_exists_and_is_dispatchable(name):
    wf, _ = _wf_map()[name]
    path = os.path.join(_WF_DIR, wf)
    assert os.path.exists(path), f"{name}이 없는 워크플로 {wf}를 가리킵니다"
    with open(path, encoding="utf-8") as f:
        assert "workflow_dispatch" in f.read(), (
            f"{wf}는 수동 실행이 안 되므로 버튼을 눌러도 아무 일도 일어나지 않습니다"
        )


@pytest.mark.parametrize("name", sorted(_wf_map()))
def test_mutating_workflows_are_dispatched_in_preview_mode(name):
    """리포트를 갱신하려다 발행 글이 고쳐지면 안 됩니다."""
    wf, inputs = _wf_map()[name]
    key = _MUTATING.get(wf)
    if not key:
        return
    expected = "'true'" if key == "dry_run" else "'false'"
    assert f"{key}: {expected}" in inputs, (
        f"{name} → {wf} 실행에 {key} 입력이 빠졌습니다 — 워크플로 기본값이 "
        f"글을 고치는 쪽이면 버튼 한 번에 발행 글이 바뀝니다: {inputs}"
    )


def test_mapped_files_are_known_to_the_freshness_panel():
    """패널이 모르는 파일에 버튼을 달면 아무 데도 안 나옵니다."""
    html = _html()
    for name in _wf_map():
        assert f"'{name}':" in html.split("const FRESH_SOURCE_WF")[0], (
            f"{name}이 SOURCE_META에 없습니다"
        )
