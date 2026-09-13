"""비공개 전환 기준선(--unpublish-severity)이 동작하는지 검사합니다.

자동 재작성이 계속 반려되는 글은 고쳐지지 않은 채 공개로 남습니다.
2026-09-13 기준 high 9편이 그 상태였고, 기준선이 critical로 박혀 있어
도구로는 내릴 방법이 없었습니다.

기본값은 critical이라 기존 동작은 그대로여야 합니다 — 이것도 검사합니다.
"""
import os
import re
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from fix_experience_claims import _at_least  # noqa: E402

_WORKFLOW = os.path.join(
    os.path.dirname(os.path.dirname(_HERE)),
    ".github", "workflows", "fix-experience-claims.yml",
)


@pytest.mark.parametrize("sev,floor,expected", [
    ("critical", "critical", True),
    ("high", "critical", False),
    ("medium", "critical", False),
    ("critical", "high", True),
    ("high", "high", True),
    ("medium", "high", False),
    ("medium", "medium", True),
])
def test_severity_floor(sev, floor, expected):
    assert _at_least(sev, floor) is expected


def test_ok_is_never_unpublished():
    """'ok'는 어떤 기준선에서도 내려가면 안 됩니다."""
    for floor in ("critical", "high", "medium"):
        assert _at_least("ok", floor) is False


def test_unknown_floor_unpublishes_nothing():
    """오타 난 기준선이 전부 내리는 사고로 이어지면 안 됩니다."""
    assert _at_least("critical", "치명적") is False


def _workflow_text():
    with open(_WORKFLOW, encoding="utf-8") as f:
        return f.read()


def test_workflow_exposes_the_severity_input():
    """입력이 없으면 워크플로에서는 여전히 critical만 내릴 수 있습니다."""
    text = _workflow_text()
    assert "unpublish_severity:" in text
    assert re.search(r"unpublish_severity:.*?default:\s*'critical'", text, re.S)


def test_workflow_passes_the_input_to_both_flags():
    """--severity와 --unpublish-severity가 어긋나면 대상만 걸러지고 안 내려갑니다."""
    text = _workflow_text()
    assert "--unpublish-severity" in text
    assert '--severity "$SEV"' in text
    assert '--unpublish-severity "$SEV"' in text


def test_workflow_default_keeps_old_behaviour():
    assert "inputs.unpublish_severity || 'critical'" in _workflow_text()
