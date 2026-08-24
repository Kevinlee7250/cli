"""쪼개 놓은 데이터 파일이 워크플로 커밋 목록에 함께 들어 있는지 확인합니다.

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

#: 대표 파일 → 반드시 함께 커밋돼야 하는 짝. 한 덩어리를 쪼갠 것이므로
#: 따로 커밋되면 반쪽만 남습니다.
COMPANIONS = {
    "docs/data/pending_posts.json": ("docs/data/pending_bodies.json",
                                     "docs/data/pending_archive.json"),
    "docs/data/posts.json": ("docs/data/post_details.json",),
}


def _commit_lines(text: str, primary: str) -> list[str]:
    """git add 대상으로 해당 파일이 등장하는 줄만 고릅니다.

    설명·주석에 파일 이름이 나오는 것은 대상이 아닙니다.
    """
    lines = []
    for line in text.split("\n"):
        if primary not in line:
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
def test_split_files_are_committed_together(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    for primary, companions in COMPANIONS.items():
        for line in _commit_lines(text, primary):
            for companion in companions:
                assert companion in text, (
                    f"{os.path.basename(path)}가 {primary}를 커밋하면서 "
                    f"{companion}을 빠뜨렸습니다 — 쪼갠 반쪽이 유실됩니다.\n"
                    f"  {line.strip()}"
                )


@pytest.mark.parametrize("primary", sorted(COMPANIONS))
def test_check_is_not_vacuous(primary):
    """검사 자체가 헛돌지 않는지 — 대상이 0개면 위 테스트는 항상 통과합니다."""
    found = [p for p in _workflows()
             if _commit_lines(open(p, encoding="utf-8").read(), primary)]
    assert len(found) >= 5, f"{primary}를 커밋하는 워크플로가 {len(found)}개뿐입니다"
