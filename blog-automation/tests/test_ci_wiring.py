"""테스트 워크플로가 실제로 이 코드를 검사하는지 확인합니다.

blog-tests.yml은 오래전부터 있었지만 PR #26에는 한 번도 붙지 않았습니다.
이유가 셋이었고, 셋 다 "초록불인데 아무것도 검사하지 않는" 유형입니다.

  1) pull_request 트리거가 없어 PR에는 아예 안 돌았습니다.
  2) paths가 '.py'만 걸어 두어, 워크플로 커밋 목록·대시보드 계약·스위치
     라벨을 지키는 검사들이 정작 그 파일이 바뀔 때 돌지 않았습니다.
  3) checkout에 ref가 박혀 있어, PR에서 돌더라도 PR의 코드가 아니라 작업
     브랜치를 받아 검사했습니다 — 검사한 적 없는데 통과로 보이는 쪽이
     검사가 없는 것보다 나쁩니다.

세 가지가 되돌아가지 않게 고정합니다.
"""

import os

import pytest
import yaml

_WF = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..",
                                    ".github", "workflows", "blog-tests.yml"))


@pytest.fixture(scope="module")
def wf():
    with open(_WF, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _triggers(wf):
    # PyYAML은 따옴표 없는 on: 을 불리언 True로 읽습니다
    return wf.get("on") or wf.get(True) or {}


def test_tests_run_on_pull_requests(wf):
    assert "pull_request" in _triggers(wf), (
        "PR에 테스트가 붙지 않으면 리뷰 시점에 아무것도 검증되지 않습니다"
    )


@pytest.mark.parametrize("path", ["blog-automation/**",
                                  ".github/workflows/*.yml",
                                  "docs/index.html"])
def test_paths_cover_what_the_tests_check(wf, path):
    """테스트가 검사하는 대상이 바뀔 때 테스트가 돌아야 합니다."""
    for event in ("pull_request", "push"):
        paths = _triggers(wf).get(event, {}).get("paths", [])
        assert path in paths, f"{event} 트리거의 paths에 {path}가 없습니다"


def test_checkout_does_not_pin_a_branch(wf):
    """PR의 코드를 검사해야 합니다 — 고정 ref는 엉뚱한 코드에 초록불을 줍니다."""
    for step in wf["jobs"]["pytest"]["steps"]:
        if str(step.get("uses", "")).startswith("actions/checkout"):
            assert "ref" not in (step.get("with") or {}), (
                "checkout에 ref가 박혀 있으면 PR이 아니라 그 브랜치를 검사합니다"
            )


def test_collection_count_is_guarded(wf):
    """pytest는 '0개 수집'으로도 성공할 수 있습니다."""
    text = open(_WF, encoding="utf-8").read()
    assert "--collect-only" in text, "테스트 수집 개수 확인 단계가 없습니다"
