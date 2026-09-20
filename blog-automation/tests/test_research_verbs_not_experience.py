"""'정리해봤습니다'를 경험 주장으로 보지 않는지 검사합니다.

2026-09-20에 자동 발행된 글이 high로 잡혔습니다.

    "이 글에서는 2026년 가을 시즌 골프장 예약 타이밍과 라운딩 비용을
     항목별로 정리해봤습니다."

'정리해봤'의 '해봤'을 본 것인데, 이건 **글을 쓴 행위**이지 겪은 일이
아닙니다. 오히려 생성 프롬프트가 쓰라고 지시한 조사·정리형 문장입니다.

high는 본문 리라이팅과 비공개 판정을 부르는 등급이라 더 위험합니다 —
멀쩡한 새 글이 자동으로 고쳐지거나 내려갈 수 있었습니다.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from experience_audit import analyze_text  # noqa: E402
from title_policy import check_title  # noqa: E402

RESEARCH = [
    "이 글에서는 라운딩 비용을 항목별로 정리해봤습니다.",
    "공시 자료를 찾아봤습니다.",
    "요금제를 하나씩 비교해봤습니다.",
    "제도가 어떻게 바뀌는지 알아봤습니다.",
    "약관을 살펴봤습니다.",
    "수수료를 계산해봤습니다.",
    "관련 기사를 검색해봤습니다.",
    "조건을 따져봤습니다.",
]

EXPERIENCE = [
    "직접 써봤습니다.",
    "지난달에 다녀왔습니다.",
    "1년 살아봤습니다.",
    "저도 같은 일을 겪었습니다.",
    "매장에 가봤습니다.",
]


def test_research_verbs_are_not_experience_claims():
    for s in RESEARCH:
        assert analyze_text(s) == [], f"조사 동사를 경험으로 봤습니다: {s}"


def test_real_experience_claims_are_still_high():
    for s in EXPERIENCE:
        hits = analyze_text(s)
        assert hits, f"진짜 경험 주장을 놓쳤습니다: {s}"
        assert any(h["severity"] in ("high", "critical") for h in hits), (s, hits)


def test_the_actual_post_that_was_flagged():
    """9/20 자동 발행된 실제 문장."""
    s = ("이 글에서는 2026년 가을 시즌 골프장 예약 타이밍과 라운딩 비용을 "
         "항목별로 정리해봤습니다.")
    assert analyze_text(s) == [], analyze_text(s)


def test_title_policy_uses_the_same_rule():
    """생성 단계와 감사가 어긋나면 안 됩니다."""
    assert not check_title("가을 골프장 예약 타이밍과 비용 정리해봤습니다")
    assert check_title("신상 골프화 직접 써봤습니다")


def test_mixed_sentence_still_caught():
    """조사 동사가 섞여 있어도 진짜 경험 주장은 잡아야 합니다."""
    s = "요금제를 비교해봤고, 저는 3개월 써봤습니다."
    hits = analyze_text(s)
    assert any(h["severity"] in ("high", "critical") for h in hits), hits
