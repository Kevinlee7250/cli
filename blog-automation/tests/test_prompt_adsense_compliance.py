"""글쓰기 프롬프트가 애드센스 '가치 있는 인벤토리' 기준에 어긋나지 않는가.

왜
──
애드센스가 같은 사유('가치가 별로 없는 콘텐츠')로 두 번 거절했습니다.
프롬프트를 점검해 보니 셋 다 애드센스 섹션은 갖추고 있었는데, 정작
거절 사유를 키우는 지시가 세 군데 있었습니다.

  1. 없는 경험을 꾸미게 했다
     "H2: 자료·후기를 비교해본 관점 — 개인 경험처럼 구체적으로 작성"
     author_profile의 경험이 비어 있으니 모델은 지어낼 수밖에 없습니다.
     이건 E-E-A-T를 올리는 게 아니라 허위 표시입니다. 바로 아랫줄에
     "경험 정보 부족 시 …로 정리"라는 올바른 지시가 있어 모순이었습니다.

  2. blog1만 고정 7단 골격이었다
     글마다 같은 소제목 7개가 반복됐습니다. 구글이 인용하는 정책 문구는
     "little to no value … without adding value"이고 실무에서는 이
     판정을 templated page로 부릅니다. 272편 전부 같은 구조·중위
     3,197자·FAQ 270/272는 그 지문에 해당합니다.

  3. 분량 규칙이 늘려쓰기를 강제했다
     프롬프트는 섹션마다 500자를 요구하고(일부 경로는 4,500자·7섹션),
     품질 블록은 "분량을 위한 반복이 없는가"를 권고했습니다. 집행되는
     쪽이 이깁니다. 게다가 "Google AdSense 정책상 4000자 미만은 thin
     content"는 구글이 공표한 적 없는 수치였습니다.

여기서 지키는 것
────────────────
  1. 경험을 꾸미라고 지시하지 않는다
  2. 고정 골격을 강요하지 않는다
  3. 섹션별 글자 수 하한이 없다 — 게시 기준(2,500자)과 어긋나지 않는다
  4. 없는 정책을 근거로 들지 않는다
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "content_generator.py")

with open(_SRC, encoding="utf-8") as _f:
    SOURCE = _f.read()

#: 글을 쓰는 프롬프트를 만드는 함수들 — 하나만 고치면 다른 경로로 새어
#: 나가므로 전부 봅니다. 실제로 시리즈 프롬프트 두 개가 4,500자·7섹션을
#: 따로 요구하고 있었습니다.
PROMPT_BUILDERS = (
    "_build_blog1_prompt",
    "_build_blog2_prompt",
    "_build_blog3_prompt",
    "_build_prompt",
    "_build_series_prompt_general",
    "_build_series_prompt_finance",
)


def _body(name: str) -> str:
    """함수 하나의 소스 본문."""
    start = SOURCE.index(f"def {name}(")
    rest = SOURCE[start + 1:]
    nxt = rest.find("\ndef ")
    return rest[:nxt] if nxt != -1 else rest


def _flat(text: str) -> str:
    """공백·줄바꿈을 하나로 눌러 비교합니다.

    프롬프트 문장은 줄바꿈으로 감싸여 있어("확인할\\n   부분") 글자 그대로
    찾으면 빗나갑니다.
    """
    return re.sub(r"\s+", " ", text)


def test_every_prompt_builder_is_covered():
    """함수 이름이 바뀌면 이 테스트가 조용히 아무것도 안 보게 됩니다."""
    for name in PROMPT_BUILDERS:
        assert f"def {name}(" in SOURCE, f"{name} 가 없습니다 — 목록을 갱신하세요"


# ── 1. 경험을 꾸미라고 하지 않는가 ──────────────────────────────────────────

_FABRICATION = (
    "개인 경험처럼",
    "경험한 것처럼",
    "직접 해본 것처럼",
    "다녀온 것처럼",
    "써본 것처럼",
)


@pytest.mark.parametrize("name", PROMPT_BUILDERS)
def test_prompt_does_not_ask_to_fake_experience(name):
    body = _body(name)
    for phrase in _FABRICATION:
        assert phrase not in body, (
            f"{name} 가 없는 경험을 꾸미라고 지시합니다: '{phrase}' — "
            f"E-E-A-T가 아니라 허위 표시가 됩니다"
        )


def test_blog1_says_not_to_invent_experience():
    """빼는 것으로 끝나지 않고, 하지 말라고 적혀 있어야 합니다."""
    body = _flat(_body("_build_blog1_prompt"))
    assert "경험은 지어내지 마세요" in body
    assert "실제 적용 시 확인할 부분" in body, (
        "경험이 없을 때 어떻게 쓰라는 대안이 없으면 모델이 알아서 지어냅니다"
    )


# ── 2. 고정 골격을 강요하지 않는가 ──────────────────────────────────────────

def test_blog1_structure_is_not_a_fixed_skeleton():
    """blog1만 H2 7개가 글마다 똑같았습니다."""
    body = _body("_build_blog1_prompt")
    fixed = re.findall(r"^H2: (?!마무리)(.+)$", body, re.MULTILINE)
    assert len(fixed) <= 1, (
        f"고정 소제목이 {len(fixed)}개 박혀 있습니다 {fixed} — "
        f"글마다 같은 구조가 반복되면 templated page로 읽힙니다"
    )
    assert "H2 섹션 (5~7개" in body, "유연한 섹션 지시가 없습니다"


@pytest.mark.parametrize("name", PROMPT_BUILDERS)
def test_prompt_does_not_demand_an_identical_shape(name):
    body = _body(name)
    assert "H2 섹션 7개 이상" not in body, (
        f"{name} 가 섹션 7개를 못박습니다 — 글마다 같은 틀이 됩니다"
    )


# ── 3. 섹션별 글자 수 하한이 없는가 ─────────────────────────────────────────

@pytest.mark.parametrize("name", PROMPT_BUILDERS)
def test_no_per_section_length_floor(name):
    """섹션마다 하한이 있으면 할 말이 없어도 채웁니다."""
    body = _body(name)
    hits = re.findall(r"각 ?(?:H2 )?섹션[^\n]*?(\d{3,4})자 이상", body)
    hits += re.findall(r"\(각 ?(\d{3,4})자 이상", body)
    assert not hits, (
        f"{name} 에 섹션별 글자 수 하한이 남아 있습니다: {hits}자 — "
        f"분량을 채우려 늘린 문단이 '가치 없는 콘텐츠' 판정을 키웁니다"
    )


@pytest.mark.parametrize("name", PROMPT_BUILDERS)
def test_length_floor_matches_the_publish_gate(name):
    """프롬프트가 요구하는 분량과 실제 게시 기준이 달랐습니다.

    main.py 는 2,500자에서 막는데 프롬프트는 4,500자를 요구했습니다.
    """
    body = _body(name)
    assert "4500" not in body and "4,500" not in body, (
        f"{name} 가 4,500자를 요구합니다 — 게시 기준은 2,500자입니다"
    )


def test_the_publish_gate_is_still_2500():
    """하한을 낮춘 것이 아니라 하나로 맞춘 것입니다 — 게이트는 그대로."""
    with open(os.path.join(os.path.dirname(_SRC), "main.py"), encoding="utf-8") as f:
        main_src = f.read()
    assert "word_count < 2500" in main_src, (
        "thin content 게이트가 사라졌습니다 — 이건 유지해야 합니다"
    )


# ── 4. 없는 정책을 근거로 들지 않는가 ───────────────────────────────────────

def test_no_invented_character_threshold_policy():
    """구글은 글자 수 기준을 공표하지 않습니다.

    "Google AdSense 정책상 4000자 미만은 thin content" 라고 적혀 있었는데,
    출처가 없는 수치입니다. 틀린 근거로 규칙을 강제하면 그 규칙이 왜
    있는지 아무도 다시 묻지 않게 됩니다.
    """
    bad = re.findall(r"(?:AdSense|애드센스) 정책상[^\n]*?\d{3,4}자", SOURCE)
    assert not bad, f"구글이 공표하지 않은 글자 수 기준을 정책으로 인용합니다: {bad}"


# ── 지켜져야 하는 것이 사라지지 않았는가 ────────────────────────────────────

@pytest.mark.parametrize("name", ("_build_blog1_prompt", "_build_blog2_prompt",
                                  "_build_blog3_prompt"))
def test_adsense_section_still_exists(name):
    body = _body(name)
    assert "AdSense 정책 준수" in body
    assert "원본성" in body


@pytest.mark.parametrize("name", ("_build_blog1_prompt", "_build_blog2_prompt",
                                  "_build_blog3_prompt"))
def test_ad_placeholder_ban_still_exists(name):
    """광고 자리·클릭 유도 문구 삽입 금지는 프로그램 정책의 핵심입니다."""
    body = _body(name)
    assert "광고" in body and ("클릭 유도" in body or "클릭하세요" in body), (
        f"{name} 에서 클릭 유도 금지 지시가 사라졌습니다"
    )
