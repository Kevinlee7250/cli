"""저자 경험 자료 — 자료 없이 1인칭만 허용되는 상태를 막습니다.

프롬프트는 경험이 매칭되면 "아래는 글쓴이의 실제 경험 자료입니다" 라고 선언하고
1인칭 표현을 허용합니다. 그런데 summary·detail이 비어 있으면 그 선언 아래에
아무것도 못 넣은 채 허가만 나갑니다 — 가짜 체험담을 막으려던 장치가 거꾸로
뚫립니다. author_profile.json이 템플릿만 든 채 오래 방치돼 있었으므로 실제로
일어날 수 있었던 상태입니다.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import content_generator as cg  # noqa: E402


def _profile(monkeypatch, experiences):
    monkeypatch.setattr("config.get_author_profile",
                        lambda: {"name": "테스트", "experiences": experiences})


def test_entry_without_summary_does_not_match(monkeypatch):
    """자료가 없으면 매칭되지 않아야 합니다 — 이게 이 테스트의 핵심입니다."""
    _profile(monkeypatch, [{"topics": ["ETF"], "blogs": ["blog3"],
                            "summary": "", "detail": ""}])
    assert cg._match_experience("ETF 투자전략 비교", "blog3") is None


def test_entry_with_summary_matches(monkeypatch):
    _profile(monkeypatch, [{"topics": ["ETF"], "blogs": ["blog3"],
                            "summary": "2023년부터 적립식 ETF 운용", "detail": ""}])
    exp = cg._match_experience("ETF 투자전략 비교", "blog3")
    assert exp and exp["summary"]


def test_whitespace_only_summary_is_empty(monkeypatch):
    _profile(monkeypatch, [{"topics": ["ETF"], "blogs": ["blog3"],
                            "summary": "   \n  ", "detail": ""}])
    assert cg._match_experience("ETF 투자전략", "blog3") is None


def test_template_topics_are_ignored(monkeypatch):
    """'예: '로 시작하는 토픽은 템플릿 예시입니다."""
    _profile(monkeypatch, [{"topics": ["예: ISA 계좌"], "blogs": ["blog3"],
                            "summary": "실제로 채워진 요약", "detail": ""}])
    assert cg._match_experience("ISA 계좌 개설 방법", "blog3") is None


def test_blog_filter_is_respected(monkeypatch):
    _profile(monkeypatch, [{"topics": ["골프"], "blogs": ["blog2"],
                            "summary": "주말 라운딩", "detail": ""}])
    assert cg._match_experience("가을 골프 라운딩", "blog2") is not None
    assert cg._match_experience("가을 골프 라운딩", "blog1") is None


def test_topics_match_whole_words_not_substrings():
    """'골프'는 '골프장'과 매칭되지 않습니다 — 토픽을 적을 때 알아야 하는 성질."""
    import config as _cfg
    _orig = _cfg.get_author_profile
    _cfg.get_author_profile = lambda: {"experiences": [
        {"topics": ["골프"], "blogs": [], "summary": "라운딩", "detail": ""}]}
    try:
        assert cg._match_experience("골프 라운딩 후기", "") is not None
        assert cg._match_experience("가을 단풍 골프장 추천", "") is None
    finally:
        _cfg.get_author_profile = _orig


def test_prompt_permits_first_person_only_with_material(monkeypatch):
    """매칭될 때만 1인칭 허용 문구가 나가는지 — 프롬프트 수준에서 확인."""
    _profile(monkeypatch, [{"topics": ["ETF"], "blogs": ["blog3"],
                            "summary": "2023년부터 적립식 ETF 운용", "detail": ""}])
    allowed = cg._experience_style_block("ETF 비교", "blog3")
    assert "1인칭 경험 표현 허용" in allowed
    assert "2023년부터 적립식 ETF 운용" in allowed

    _profile(monkeypatch, [{"topics": ["ETF"], "blogs": ["blog3"],
                            "summary": "", "detail": ""}])
    blocked = cg._experience_style_block("ETF 비교", "blog3")
    assert "가짜 체험담 금지" in blocked
    assert "1인칭 경험 표현 허용" not in blocked


# ──────────────────────────────────────────────────────────────────────────────
# 저장소에 실제로 들어 있는 파일
# ──────────────────────────────────────────────────────────────────────────────

def _shipped():
    path = os.path.join(os.path.dirname(__file__), "..", "author_profile.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_shipped_profile_has_no_template_topics():
    """템플릿 예시가 남아 있으면 채운 것처럼 보이지만 아무 효과가 없습니다."""
    for exp in _shipped().get("experiences", []):
        for topic in exp.get("topics", []):
            assert not str(topic).strip().startswith("예:"), (
                f"템플릿 예시가 남아 있습니다: {topic}"
            )


def test_shipped_profile_entries_are_well_formed():
    for exp in _shipped().get("experiences", []):
        assert exp.get("topics"), "topics가 비어 있으면 아무 키워드와도 매칭되지 않습니다"
        assert isinstance(exp.get("blogs"), list)
        assert "summary" in exp and "detail" in exp


def test_shipped_profile_carries_no_sensitive_data():
    """공개 저장소입니다 — 연락처·주민번호 형태가 들어가면 잡습니다."""
    import re
    raw = json.dumps(_shipped(), ensure_ascii=False)
    assert not re.search(r"01[016-9]-?\d{3,4}-?\d{4}", raw), "전화번호로 보이는 값"
    assert not re.search(r"\d{6}-[1-4]\d{6}", raw), "주민등록번호로 보이는 값"
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", raw), "이메일로 보이는 값"


@pytest.mark.parametrize("field", ["summary", "detail"])
def test_unfilled_entries_stay_inert(field):
    """아직 안 채운 항목은 매칭되지 않으므로 글에 영향을 주지 않습니다."""
    for exp in _shipped().get("experiences", []):
        if not str(exp.get("summary", "")).strip():
            assert not str(exp.get("detail", "")).strip() or field == "detail", (
                "summary 없이 detail만 있으면 자료가 글에 안 실립니다"
            )
