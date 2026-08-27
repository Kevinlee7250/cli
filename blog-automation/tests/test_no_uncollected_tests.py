"""CI가 돌리지 않는 테스트 파일이 생기지 않게 합니다.

blog-tests.yml은 `pytest tests/`만 돌립니다. 그런데 blog-automation/ 루트에
test_fix_unlicensed_images.py가 tests/ 쪽 사본과 거의 같은 내용으로 남아
있었고, 28건이 한 번도 실행되지 않았습니다. 실행해 보니 1건은 실패 상태로
방치돼 있었습니다 — 코드가 _fetch_best_image에서 _search_all_sources로
바뀌었는데, 안 도는 사본은 옛 함수를 patch한 채였습니다.

돌지 않는 테스트는 없는 테스트보다 나쁩니다. 파일 목록만 보면 "검사하고
있다"고 읽히기 때문입니다. 그래서 위치 자체를 고정합니다.

로컬 수동 점검 스크립트는 test_ 접두사를 쓰지 마세요 (manual_*.py).
"""

import glob
import os

_SRC = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


def test_no_test_files_outside_the_tests_dir():
    stray = [os.path.basename(p) for p in glob.glob(os.path.join(_SRC, "test_*.py"))]
    assert not stray, (
        "blog-automation/ 루트의 test_*.py는 CI(`pytest tests/`)가 수집하지 "
        "않습니다. tests/로 옮기거나, 수동 스크립트라면 manual_*.py로 "
        f"이름을 바꾸세요: {stray}"
    )


def test_check_is_not_vacuous():
    """tests/를 못 찾으면 위 검사는 아무것도 안 한 것입니다."""
    assert len(glob.glob(os.path.join(os.path.dirname(__file__), "test_*.py"))) >= 40
