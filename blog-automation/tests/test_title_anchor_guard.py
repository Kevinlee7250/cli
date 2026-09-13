"""제목 정정안이 원제목의 핵심 토큰을 잃지 않는지 검사합니다.

2026-09-13 dry-run에서 "안동 하회마을 혼자 여행하기 좋을까, 솔직 후기
완전 정리" 가 "동 하회마을 혼자 여행 정보 정리…" 로 제안됐습니다.
첫 글자가 사라졌는데 정책 검사는 통과했습니다 — "동 하회마을"도
경험 주장은 아니니까요. 그래서 별도 가드가 필요합니다.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fix_experience_titles import _anchor_loss, _tokens  # noqa: E402


def test_tokens_splits_on_punctuation():
    assert _tokens("대부도·선재도, 영흥도 (2026)") == [
        "대부도", "선재도", "영흥도", "2026",
    ]


def test_leading_word_truncation_is_rejected():
    """실제로 터진 사고 — 첫 글자가 깎인 경우."""
    loss = _anchor_loss(
        "안동 하회마을 혼자 여행하기 좋을까, 솔직 후기 완전 정리",
        "동 하회마을 혼자 여행 정보 정리, 장단점과 팁 총정리",
    )
    assert loss, "첫 주제어가 잘렸는데 통과시켰습니다"
    assert "안동" in loss and "동" in loss


def test_trailing_contraction_is_allowed():
    """뒤가 깎이는 것은 한국어에서 자연스러운 축약이라 통과해야 합니다."""
    assert _anchor_loss(
        "제주 여행하기 좋은 계절 직접 다녀온 후기",
        "제주 여행 좋은 계절 자료 조사 정리",
    ) == ""


def test_removing_a_whole_phrase_is_allowed():
    """경험 주장 표현을 통째로 빼는 것이 이 도구가 하는 일입니다."""
    assert _anchor_loss(
        "홍콩 싱가포르 항공권 시기별 가격 차이 직접 추적해봤더니",
        "홍콩 싱가포르 항공권 시기별 가격 차이 조사 정리",
    ) == ""


@pytest.mark.parametrize("old,new,keyword", [
    ("2026년 부동산 투자 전략 TOP 5 완벽 정리 (충격 수익률)",
     "부동산 투자 전략 자료 조사 정리 (예상 수익률 비교)", "2026년"),
    ("ETF 자동투자 6개월 수익률 현실",
     "자동투자 6개월 수익률 자료 정리", "ETF"),
    ("SK하이닉스 주가 전망 분석 5단계 가이드",
     "주가 전망 분석 5단계 가이드 정리", "SK하이닉스"),
])
def test_dropping_search_keywords_is_rejected(old, new, keyword):
    """연도·브랜드·지표가 빠지면 그 글로 오던 검색 유입이 끊깁니다."""
    loss = _anchor_loss(old, new)
    assert loss, f"{keyword}가 빠졌는데 통과시켰습니다"
    assert keyword in loss


def test_keeping_every_keyword_passes():
    assert _anchor_loss(
        "2026년 부동산 투자 전략 TOP 5 완벽 정리 (충격 수익률)",
        "2026년 부동산 투자 전략 TOP 5 자료 조사 정리 (예상 수익률 비교)",
    ) == ""


def test_empty_candidate_is_rejected():
    assert _anchor_loss("안동 하회마을 여행 정리", "") == "토큰 없음"


def test_propose_title_rejects_a_corrupted_claude_answer(monkeypatch):
    """가드가 propose_title에 실제로 연결돼 있는지 — 함수만 있고 안 부르면 소용없습니다."""
    import fix_experience_titles as mod

    corrupted = "동 하회마을 혼자 여행 정보 정리, 장단점과 팁 총정리"
    monkeypatch.setattr(mod, "_rewrite_with_claude", lambda *a, **k: corrupted)

    new, source = mod.propose_title(
        "안동 하회마을 혼자 여행하기 좋을까, 솔직 후기 완전 정리",
        ["경험 주장: 솔직 후기"],
    )
    assert new != corrupted, "훼손된 제안을 그대로 채택했습니다"
    assert source in ("rule", "")


def test_propose_title_accepts_a_clean_claude_answer(monkeypatch):
    import fix_experience_titles as mod

    good = "홍콩 싱가포르 항공권 시기별 가격 차이 조사 정리"
    monkeypatch.setattr(mod, "_rewrite_with_claude", lambda *a, **k: good)

    new, source = mod.propose_title(
        "홍콩 싱가포르 항공권 시기별 가격 차이 직접 추적해봤더니",
        ["경험 주장: 직접 ~해봤"],
    )
    assert (new, source) == (good, "claude")
