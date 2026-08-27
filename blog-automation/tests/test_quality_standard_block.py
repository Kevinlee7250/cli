"""품질 기준 블록이 모든 글 경로의 프롬프트에 실제로 들어가는지 고정합니다.

프롬프트는 조각을 이어 붙여 만들어집니다. 블록을 정의해 두고 조립 지점 한
군데에 배선을 빠뜨리면, 그 경로로 나가는 글에는 규칙이 적용되지 않습니다.
그런데 코드만 봐서는 티가 나지 않습니다 — 함수는 멀쩡히 존재하니까요.

그래서 함수 존재가 아니라 "완성된 프롬프트에 문구가 있는가"를 검사합니다.
일반 글 3종과 시리즈 글이 각각 다른 조립 지점을 지납니다.
"""

import pytest

import content_generator as cg

_BLOGS = ("blog1", "blog2", "blog3")
_KEYWORD = "전기요금 절약"


def _prompt(blog_id):
    return cg._build_prompt(_KEYWORD, "높음", {"id": blog_id, "language": "ko"})


def _series_prompt():
    return cg._build_series_prompt(
        _KEYWORD, "높음",
        {"title": "시리즈", "index": 1, "total": 3},
        {"id": "blog3", "language": "ko"},
    )


# ── 품질 기준이 모든 경로에 도달하는가 ───────────────────────────────────────

_REQUIRED = [
    ("검색 종결성", "다른 사이트를 다시 찾아야 하면 실패"),
    ("독자적 가치", "어디서나 나오는 정보의 재배열 금지"),
    ("출처 신뢰 서열", "자료가 어긋날 때의 판단 기준"),
    ("반드시 최신 자료로 확인할 항목", "가격·정책·법률 등"),
]


@pytest.mark.parametrize("blog_id", _BLOGS)
@pytest.mark.parametrize("phrase,why", _REQUIRED, ids=lambda x: x if isinstance(x, str) else "")
def test_quality_standard_reaches_every_blog(blog_id, phrase, why):
    assert phrase in _prompt(blog_id), f"{blog_id} 프롬프트에 없음 ({why})"


@pytest.mark.parametrize("phrase,why", _REQUIRED, ids=lambda x: x if isinstance(x, str) else "")
def test_quality_standard_reaches_series_posts(phrase, why):
    """시리즈 글은 조립 지점이 따로입니다 — 한쪽만 배선하기 쉽습니다."""
    assert phrase in _series_prompt(), f"시리즈 프롬프트에 없음 ({why})"


# ── 수치 날조 방지 ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("blog_id", _BLOGS)
def test_fabricated_search_volume_is_forbidden(blog_id):
    assert "검색량·조회수·순위 같은" in _prompt(blog_id)


# ── 키워드는 하한 신호이지 채워야 할 할당량이 아님 ───────────────────────────

@pytest.mark.parametrize("blog_id", _BLOGS)
def test_keyword_count_is_not_a_quota(blog_id):
    """10~14회는 남기되 기계적 충족은 금지 — 둘이 함께 있어야 의미가 삽니다."""
    p = _prompt(blog_id)
    assert "10~14회" in p, "키워드 노출 하한 신호가 사라졌습니다"
    assert ("억지로 넣지 말 것" in p) or ("억지 반복 금지" in p), (
        "횟수만 남고 억지 반복 금지가 빠지면 숫자를 채우려 어색한 문장이 늘어납니다"
    )


# ── 검사가 헛돌지 않는지 ─────────────────────────────────────────────────────

def test_prompts_are_substantial():
    for blog_id in _BLOGS:
        assert len(_prompt(blog_id)) > 5000
    assert len(_series_prompt()) > 3000
