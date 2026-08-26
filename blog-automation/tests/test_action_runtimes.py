"""우리 워크플로가 Node 20으로 도는 액션을 쓰지 않는지 고정합니다.

GitHub이 Node 20 지원을 종료하면서, 지금은 러너가 Node 24로 강제 실행하고
경고만 남깁니다 — 즉 지금은 초록이지만 언젠가 조용히 멈춥니다. 그래서
"경고"를 검사 대상으로 끌어올립니다.

npm/cli 상류에서 온 워크플로는 대상이 아닙니다. 우리가 관리하지 않고,
상류와 diff를 만들면 머지가 어려워집니다.
"""

import glob
import os
import re

import pytest

_WF = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..",
                                    ".github", "workflows"))

# 액션 이름 → 그 액션이 Node 24로 도는 최소 메이저. 새로 쓰는 액션이 있으면
# 여기에 추가하세요. 목록에 없는 액션은 검사하지 않습니다.
_MIN_MAJOR = {
    "actions/checkout": 5,
    "actions/setup-python": 6,
    "actions/upload-artifact": 7,
    # Pages 3종은 서로 짝을 이뤄 돕니다. 한쪽만 올리면 배포가 깨질 수
    # 있어 셋을 함께 올렸고, 그래서 함께 고정합니다.
    "actions/configure-pages": 6,
    "actions/deploy-pages": 5,
}


def _ours():
    """제목이 한글인 워크플로 = 우리가 추가한 것."""
    out = []
    for p in sorted(glob.glob(os.path.join(_WF, "*.yml"))):
        with open(p, encoding="utf-8") as f:
            for ln in f:
                if ln.startswith("name:"):
                    if any("가" <= c <= "힣" for c in ln):
                        out.append(p)
                    break
    return out


@pytest.mark.parametrize("path", _ours(), ids=os.path.basename)
def test_no_node20_actions(path):
    name = os.path.basename(path)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    stale = []
    for action, minimum in _MIN_MAJOR.items():
        for major in re.findall(rf"{re.escape(action)}@v(\d+)", text):
            if int(major) < minimum:
                stale.append(f"{action}@v{major} (v{minimum} 이상 필요)")
    assert not stale, (
        f"{name}가 Node 20 액션을 씁니다 — 지금은 경고뿐이지만 지원이 끊기면 "
        f"멈춥니다:\n  " + "\n  ".join(stale)
    )


def test_check_is_not_vacuous():
    """우리 워크플로를 못 찾으면 위 검사는 아무것도 안 한 것입니다."""
    assert len(_ours()) >= 35
