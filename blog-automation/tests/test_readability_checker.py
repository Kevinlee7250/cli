"""읽기 난이도 자동 검사 테스트.

실행: cd blog-automation && python -m pytest tests/test_readability_checker.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_short_simple_sentences_pass():
    from readability_checker import assess_readability
    html = "<p>오늘은 날씨가 좋습니다. 산책을 다녀왔습니다. 기분이 상쾌합니다.</p>"
    result = assess_readability(html, "travel")
    assert result["ok"] is True
    assert result["issues"] == []


def test_jargon_without_explanation_flagged():
    from readability_checker import assess_readability
    html = "<p>" + (
        "레버리지와 파생상품을 활용한 스프레드 전략은 변동성지수가 상승할 때 "
        "배당수익률을 함께 고려해야 합니다. "
    ) * 3 + "</p>"
    result = assess_readability(html, "finance")
    assert result["ok"] is False
    assert any("전문용어" in i for i in result["issues"])
    assert "레버리지" in result["jargonTerms"]


def test_jargon_with_explanation_marker_passes():
    from readability_checker import assess_readability
    html = (
        "<p>레버리지는 쉽게 말해 빌린 돈으로 투자 규모를 키우는 것입니다. "
        "이렇게 하면 수익도 커지지만 손실도 커집니다.</p>"
    )
    result = assess_readability(html, "finance")
    assert result["ok"] is True


def test_long_sentences_flagged():
    from readability_checker import assess_readability
    long_sentence = "그" + "리고 " * 60 + "결론적으로 이 상품은 좋습니다."
    html = f"<p>{long_sentence}</p>"
    result = assess_readability(html, "")
    assert result["ok"] is False
    assert any("문장" in i for i in result["issues"])


def test_empty_content_is_ok_by_default():
    from readability_checker import assess_readability
    result = assess_readability("<p></p>", "finance")
    assert result["ok"] is True


def test_escalation_note_empty_when_ok():
    from readability_checker import assess_readability, readability_escalation_note
    ok_result = assess_readability("<p>짧고 쉬운 문장입니다.</p>", "")
    assert readability_escalation_note(ok_result) == ""
    assert readability_escalation_note(None) == ""


def test_escalation_note_contains_issues_when_not_ok():
    from readability_checker import assess_readability, readability_escalation_note
    html = "<p>" + (
        "레버리지와 파생상품을 활용한 스프레드 전략은 변동성지수가 상승할 때 "
        "배당수익률을 함께 고려해야 합니다. "
    ) * 3 + "</p>"
    bad_result = assess_readability(html, "finance")
    note = readability_escalation_note(bad_result)
    assert "재작성 요청" in note
    assert "전문용어" in note
