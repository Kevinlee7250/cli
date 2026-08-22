"""검토 대기 파일 3종이 워크플로 커밋 목록에 함께 들어 있는지 확인합니다.

pending_posts.json만 커밋하고 pending_bodies.json을 빠뜨리면, 러너가 쓴 본문이
버려지고 다음 실행의 load()가 본문 없는 목록을 읽습니다. 워크플로는 초록으로
끝나고 글만 조용히 사라집니다 — verify_report.json이 39번 실행 내내 저장되지
않던 것과 같은 유형입니다. 사람이 매번 세 경로를 같이 적기를 기대하는 대신
여기서 잡습니다.
"""

import glob
import os

import pytest

_WF_DIR = os.path.join(os.path.dirname(__file__), "..", "..", ".github", "workflows")

COMPANIONS = ("docs/data/pending_bodies.json", "docs/data/pending_archive.json")


def _commit_lines(text: str) -> list[str]:
    """git add 대상으로 pending_posts.json이 등장하는 줄만 고릅니다.

    설명·주석에 파일 이름이 나오는 것은 대상이 아닙니다.
    """
    lines = []
    for line in text.split("\n"):
        if "docs/data/pending_posts.json" not in line:
            continue
        stripped = line.strip()
        if stripped.startswith("#") or "description:" in stripped:
            continue
        if "git add" in stripped or stripped.startswith("docs/data"):
            lines.append(line)
    return lines


def _workflows():
    return sorted(glob.glob(os.path.join(_WF_DIR, "*.yml")))


@pytest.mark.parametrize("path", _workflows(), ids=os.path.basename)
def test_pending_companions_are_committed_too(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    for line in _commit_lines(text):
        for companion in COMPANIONS:
            assert companion in text, (
                f"{os.path.basename(path)}가 pending_posts.json을 커밋하면서 "
                f"{companion}을 빠뜨렸습니다 — 본문이 유실됩니다.\n  {line.strip()}"
            )


def test_at_least_one_workflow_commits_pending():
    """검사 자체가 헛돌지 않는지 — 대상이 0개면 위 테스트는 항상 통과합니다."""
    found = [p for p in _workflows()
             if _commit_lines(open(p, encoding="utf-8").read())]
    assert len(found) >= 5, f"pending을 커밋하는 워크플로가 {len(found)}개뿐입니다"
