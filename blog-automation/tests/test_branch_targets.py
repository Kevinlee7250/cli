"""워크플로가 기본 브랜치 하나만 바라보는지 확인합니다.

왜
──
이 저장소는 오랫동안 두 브랜치로 나뉘어 돌았습니다. 워크플로 파일과 스케줄
정의는 기본 브랜치(latest)에서 읽히는데, 체크아웃·푸시·트리거 필터는 작업
브랜치를 가리켰습니다. 그래서 같은 워크플로가 "어느 쪽 코드를 실행하고
어디에 결과를 쓰는가"가 갈렸고, 2026-08-25 하루에만 이런 일이 났습니다.

  · 수동 실행(ref=latest)이 배포를 못 부름 → 발행 글 25장이 404
  · 코드를 고쳐 머지해도 실행에는 반영 안 됨 → 브랜치 왕복 PR 6건
  · 워크플로가 기본 브랜치에 없어 dispatch가 404

두 브랜치를 오가는 동기화가 필요 없어지도록 latest 하나로 모았습니다.
되돌아가면 위 증상이 그대로 재발하므로 여기서 지킵니다.
"""

import glob
import os
import re

import pytest

_WF = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..",
                                    ".github", "workflows"))
_OLD = "claude/blog-automation-system-KAbtE"


def _files():
    return sorted(glob.glob(os.path.join(_WF, "*.yml")))


@pytest.mark.parametrize("path", _files(), ids=os.path.basename)
def test_no_workflow_targets_the_old_branch(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    hits = [ln.strip() for ln in text.split("\n") if _OLD in ln]
    assert not hits, (
        f"{os.path.basename(path)}가 아직 작업 브랜치를 가리킵니다 — "
        f"기본 브랜치에서 읽히는 정의와 어긋나 조용히 빗나갑니다:\n  "
        + "\n  ".join(hits)
    )


def test_check_is_not_vacuous():
    """검사 대상이 실제로 존재하는지 — 워크플로가 0개면 위 검사는 무의미합니다."""
    assert len(_files()) >= 30


@pytest.mark.parametrize("path", _files(), ids=os.path.basename)
def test_checkout_and_push_agree(path):
    """체크아웃한 브랜치와 푸시 대상이 어긋나면 결과가 엉뚱한 곳에 쌓입니다."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    # 같은 줄에 값이 있는 것만 봅니다 — "ref:" 다음 줄이 입력 이름 선언인
    # 경우(npm/cli 원본 워크플로)를 브랜치로 오인하지 않기 위해서입니다.
    refs = set(re.findall(r"ref:[ \t]+(\S+)", text))
    pushes = set(re.findall(r"git push origin (?:HEAD:)?(\S+)", text))
    # 표현식(${{ ... }})과 셸 변수는 실행 시점에 정해지므로 대상이 아닙니다
    concrete = {x.strip('"\'') for x in refs | pushes}
    concrete = {x for x in concrete if "$" not in x and "{" not in x}
    assert concrete <= {"latest"}, (
        f"{os.path.basename(path)}가 latest 외의 브랜치를 씁니다: {sorted(concrete)}"
    )
