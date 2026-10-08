"""업로드 시 붙는 라벨 — 키워드가 라벨이 되던 문제.

2026-10-08: blog1 글 107편에 서로 다른 라벨이 402개 쌓였고, 그 대부분이
한 번만 쓰인 것이었습니다. 원인은 blogger_uploader 에서 업로드할 때마다
`[keyword] + labels` 로 라벨을 만든 것이었습니다. 키워드는 '삼양해수욕장
검은모래해변 일몰 맨발걷기' 같은 문장이라, 그 글에만 붙는 라벨이 한 개씩
계속 생겼습니다. 카테고리가 아니라 키워드 나열이 된 이유입니다.

라벨을 한 번 정리해도 이걸 고치지 않으면 다음 글부터 다시 쌓입니다.
"""

import os
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from blogger_uploader import MAX_LABELS, _label_like, build_labels  # noqa: E402


# ── 이 사고를 그대로 ─────────────────────────────────────────────────────────

def test_the_keyword_sentence_never_becomes_a_label():
    """2026-10-08 삼양 글 발행에서 실제로 붙었던 라벨입니다."""
    got = build_labels("삼양해수욕장 검은모래해변 일몰 맨발걷기", ["국내여행", "제주"])
    assert got == ["국내여행", "제주"]
    assert all("삼양해수욕장 검은모래" not in lb for lb in got)


def test_caller_labels_are_not_pushed_out_by_the_keyword():
    """라벨을 제대로 넘긴 호출자의 분류가 밀려나면 안 됩니다."""
    got = build_labels("제주 가을 여행 코스 추천 총정리", ["국내여행"])
    assert got == ["국내여행"]


# ── 라벨이 하나도 없을 때만 키워드를 씁니다 ──────────────────────────────────

def test_short_keyword_is_used_when_there_are_no_labels():
    assert build_labels("국내여행", []) == ["국내여행"]
    assert build_labels("제주 여행", None) == ["제주 여행"]


def test_long_keyword_is_dropped_rather_than_becoming_a_junk_label():
    """라벨 없이 올라가는 게, 한 번 쓰고 마는 라벨이 생기는 것보다 낫습니다."""
    assert build_labels("2026년 제주도 가을 단풍 명소 추천 총정리 가이드", []) == []


def test_empty_keyword_and_no_labels_gives_nothing():
    assert build_labels("", []) == []
    assert build_labels(None, None) == []


# ── 정제 ────────────────────────────────────────────────────────────────────

def test_blank_and_duplicate_labels_are_removed():
    assert build_labels("", ["국내여행", "  ", "국내여행", "제주", ""]) == ["국내여행", "제주"]


def test_order_is_preserved():
    assert build_labels("", ["드라마리뷰", "포핸즈", "송강"]) == ["드라마리뷰", "포핸즈", "송강"]


def test_never_exceeds_the_blogger_limit():
    """Blogger API는 라벨이 5개를 넘으면 400을 돌려줍니다."""
    got = build_labels("", [f"라벨{i}" for i in range(12)])
    assert len(got) == MAX_LABELS == 5


def test_non_string_labels_are_skipped_not_stringified():
    """str(None)은 "None"입니다 — 걸러내지 않으면 'None' 라벨이 실제로 붙습니다."""
    assert build_labels("", ["국내여행", None, 123, ""]) == ["국내여행"]


# ── '분류처럼 생겼나' 판정 ───────────────────────────────────────────────────

@pytest.mark.parametrize("text,ok", [
    ("국내여행", True),
    ("드라마리뷰", True),
    ("제주 여행", True),
    ("삼양해수욕장", True),
    ("제주 가을 여행", False),          # 세 단어
    ("삼양해수욕장 검은모래해변 일몰 맨발걷기", False),
    ("2026년 제주도 가을 단풍 명소 추천", False),
    ("", False),
    ("   ", False),
])
def test_label_like(text, ok):
    assert _label_like(text) is ok


# ── 호출부가 실제로 이 함수를 쓰는지 ─────────────────────────────────────────

def test_both_upload_paths_go_through_build_labels():
    """새 글 업로드와 기존 글 수정 두 경로 모두 같은 규칙을 써야 합니다.

    한쪽만 고치면 수정할 때마다 키워드 라벨이 다시 붙습니다.
    """
    import inspect

    import blogger_uploader as bu

    for fn_name in ("upload_post", "update_post"):
        fn = getattr(bu, fn_name, None)
        assert fn is not None, f"{fn_name} 이 없습니다"
        src = inspect.getsource(fn)
        assert "build_labels(" in src, f"{fn_name} 이 build_labels 를 쓰지 않습니다"
        assert "[_clean_label(kw)]" not in src, (
            f"{fn_name} 에 키워드를 라벨 앞에 붙이던 코드가 남아 있습니다"
        )
