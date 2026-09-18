"""생성 프롬프트가 '경험을 지어내라'고 지시하지 않는지 검사합니다.

2026-09-12 AdSense 거절 이후 감사·정정 도구를 붙였지만, 생성 프롬프트는
한 글자도 건드리지 않았습니다. 그래서 9/14~9/16 신규 글에 "실관람 후기",
"세 번 다녀온 사람들의 결론" 같은 표현이 그대로 다시 나왔습니다.

원인은 프롬프트 자체였습니다. 시스템 프롬프트는 "하지 않은 경험을 한 것처럼
쓰지 않습니다"라고 하는데, 사용자 프롬프트는 여섯 군데서 "직접 겪은 상황으로
시작", "글쓴이만 아는 구체적 경험 포함"을 '필수'로 요구했습니다.
구체적인 요구가 이깁니다.

이 테스트는 그 문구들이 다시 들어오는 것을 막습니다.
"""
import os
import re
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

_GENERATOR = os.path.join(os.path.dirname(_HERE), "content_generator.py")


def _source() -> str:
    with open(_GENERATOR, encoding="utf-8") as f:
        return f.read()


#: 프롬프트에 있으면 안 되는 문구 — 모델에게 경험을 지어내라고 시키는 지시들.
BANNED = [
    ("직접 겪은 상황으로 시작", "도입부에서 경험을 지어내게 만듭니다"),
    ("글쓴이만 아는 구체적 경험", "AdSense 섹션이 거절 사유를 지시하던 문구입니다"),
    ("구체적 사례·수치·경험 반드시 포함", "섹션마다 경험을 요구합니다"),
    ("어떤 건 경험담", "섹션 유형으로 경험담을 제시합니다"),
    ("본 직후의 한 줄 감상", "보지 않은 방송을 본 것처럼 쓰게 만듭니다"),
    ("혹시 이런 경험 있으세요?", "경험 전제 화법을 유도합니다"),
    ("막상 해보니 달랐던 것", "체험 전제 각도를 제시합니다"),
    ("이건 진짜 저도 실수했어요", "H2 예시가 경험담입니다"),
]


@pytest.mark.parametrize("phrase,why", BANNED, ids=[b[0][:18] for b in BANNED])
def test_prompt_does_not_demand_fabricated_experience(phrase, why):
    src = _source()
    assert phrase not in src, (
        f"content_generator.py에 '{phrase}' 가 다시 들어왔습니다 — {why}.\n"
        f"생성 단계에서 경험을 지어내게 하면, 감사·정정 도구는 그걸 뒤에서 치우기만 합니다."
    )


def test_drama_block_is_informational():
    """드라마 회차 글이 '시청자'가 아니라 '정리하는 사람' 화자인지."""
    src = _source()
    assert "드라마 회차 정리 구조 (정보형" in src
    assert "화자는 시청자가 아니라" in src
    assert "편성·시청률" in src, "시청률 H2가 빠졌습니다 — 정보형의 핵심입니다"
    assert "조사기관명을 밝힐 것" in src
    assert "추정치를 만들어내지 말 것" in src, (
        "시청률을 지어내는 것은 경험을 지어내는 것보다 나쁩니다 — 숫자는 검증됩니다"
    )


def test_title_policy_covers_every_audit_rule():
    """제목 정책과 사후 감사의 기준이 어긋나지 않는지.

    title_policy.py 주석이 직접 경고하고 있습니다 —
    "두 곳이 어긋나면 생성은 통과시키고 감사만 지적하는 상태가 된다".
    실제로 '직접 비교·정리' 규칙이 감사에만 있어서 2026-09-15 글이 통과했습니다.
    """
    import experience_audit as ea
    import title_policy as tp

    title_rules = {p.pattern for p, _ in tp.EXPERIENCE_PATTERNS}
    missing = [label for pat, label in ea.MEDIUM_PATTERNS
               if pat.pattern not in title_rules]
    assert not missing, (
        f"감사에는 있고 제목 정책에는 없는 규칙: {missing}\n"
        f"생성은 통과시키고 감사만 지적하는 상태가 됩니다."
    )


def test_the_title_that_slipped_through_is_now_caught():
    """2026-09-15 발행된 실제 제목 — 이제는 걸려야 합니다."""
    from title_policy import check_title
    assert check_title("해외여행 환전 수수료 0% 만들기, 트래블카드 직접 비교 정리")
