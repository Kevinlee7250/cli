"""B4 검색 스니펫 최적화 / B5 키워드 검색의도 분류 테스트.

실행: cd blog-automation && python -m pytest tests/test_b4_b5.py -v
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ──────────────────────────────────────────────────────────────────────────────
# B5 — 검색의도 분류
# ──────────────────────────────────────────────────────────────────────────────

def test_detect_intent_comparison():
    from search_intent import detect_intent
    assert detect_intent("ETF vs 펀드 차이") == "comparison"
    assert detect_intent("부산 제주 여행 비교") == "comparison"


def test_detect_intent_transactional():
    from search_intent import detect_intent
    assert detect_intent("부산 여행 비용 얼마") == "transactional"
    assert detect_intent("항공권 예약 최저가") == "transactional"


def test_detect_intent_experience():
    from search_intent import detect_intent
    assert detect_intent("부산 여행 후기") == "experience"
    assert detect_intent("ETF 1년 투자 해봤다") == "experience"


def test_detect_intent_howto():
    from search_intent import detect_intent
    assert detect_intent("ISA 계좌 개설 방법") == "howto"
    assert detect_intent("연말정산 하는 법") == "howto"


def test_detect_intent_defaults_to_informational():
    from search_intent import detect_intent
    assert detect_intent("2026 하반기 코스피 전망") == "informational"
    assert detect_intent("") == "informational"


def test_comparison_wins_over_experience_when_both_present():
    """비교 의도가 더 구체적 — 표가 없으면 독자 목적이 미달성됨."""
    from search_intent import detect_intent
    assert detect_intent("ETF 수수료 비교 후기") == "comparison"


def test_intent_prompt_block_has_intent_specific_requirements():
    from search_intent import intent_prompt_block
    comparison = intent_prompt_block("ETF vs 펀드 비교")
    howto = intent_prompt_block("ISA 개설 방법")
    assert "<table>" in comparison          # 비교형엔 표 필수
    assert "단계" in howto                   # 방법형엔 절차 필수
    assert comparison != howto


def test_intent_prompt_block_experience_forbids_fabrication():
    """후기형이라고 없는 경험을 지어내면 안 됨 — 기존 경험 규칙과 충돌 방지."""
    from search_intent import intent_prompt_block
    block = intent_prompt_block("부산 여행 후기")
    assert "지어내지" in block


def test_build_prompt_includes_intent_directives():
    import content_generator as cg
    prompt = cg._build_prompt("ETF vs 펀드 비교", "N/A", {"id": "blog3", "topics": ["금융"]})
    assert "비교형" in prompt and "<table>" in prompt


# ──────────────────────────────────────────────────────────────────────────────
# B4 — 검색 스니펫 요약 박스
# ──────────────────────────────────────────────────────────────────────────────

def test_build_summary_box_renders_items():
    from snippet_optimizer import build_summary_box
    html = build_summary_box(["첫 번째 핵심 답변입니다", "두 번째 답변입니다"])
    assert "📌 핵심 요약" in html
    assert "첫 번째 핵심 답변입니다" in html


def test_build_summary_box_empty_returns_empty():
    from snippet_optimizer import build_summary_box
    assert build_summary_box([]) == ""
    assert build_summary_box(["", "  "]) == ""


def test_build_summary_box_escapes_html():
    from snippet_optimizer import build_summary_box
    assert "<script>" not in build_summary_box(["<script>alert(1)</script> 내용입니다"])


def test_build_summary_box_caps_item_count():
    from snippet_optimizer import build_summary_box
    html = build_summary_box([f"항목 번호 {i} 입니다" for i in range(10)])
    assert html.count("<li") == 3


def test_ensure_summary_box_uses_model_summary():
    from snippet_optimizer import ensure_summary_box
    post = {"content": "<p>도입부입니다.</p><h2>본문</h2>",
            "summary": ["부산 2인 총비용은 약 25만원이었습니다"]}
    assert ensure_summary_box(post) is True
    assert "25만원" in post["content"]


def test_ensure_summary_box_inserted_after_intro_paragraph():
    """제목 바로 밑이면 도입부 후킹이 잘리고, 너무 뒤면 스니펫에서 밀림."""
    from snippet_optimizer import ensure_summary_box
    post = {"content": "<p>도입부 문장입니다.</p><h2>첫 섹션</h2><p>내용</p>",
            "summary": ["핵심 답변입니다"]}
    ensure_summary_box(post)
    c = post["content"]
    assert c.index("도입부 문장입니다") < c.index("핵심 답변입니다") < c.index("첫 섹션")


def test_ensure_summary_box_skips_when_already_present():
    from snippet_optimizer import ensure_summary_box, build_summary_box
    existing = build_summary_box(["이미 있는 요약 문장입니다"])
    post = {"content": f"<p>도입부</p>{existing}", "summary": ["새 요약 문장입니다"]}
    assert ensure_summary_box(post) is False
    assert "새 요약 문장입니다" not in post["content"]


def test_ensure_summary_box_falls_back_to_meta_description():
    """모델이 summary를 안 줘도 이미 글에 있는 문장으로 만들어 넣음."""
    from snippet_optimizer import ensure_summary_box
    post = {
        "content": "<p>도입부입니다.</p>",
        "meta_description": "부산 1박2일 총비용은 25만원이었습니다. 숙소가 가장 큰 비중이었습니다.",
    }
    assert ensure_summary_box(post) is True
    assert "25만원" in post["content"]


def test_ensure_summary_box_no_op_when_nothing_usable():
    """만들 문장이 없으면 빈 박스를 넣지 않음."""
    from snippet_optimizer import ensure_summary_box
    post = {"content": "<p>짧음</p>", "meta_description": ""}
    assert ensure_summary_box(post) is False
    assert "핵심 요약" not in post["content"]


def test_ensure_summary_box_handles_empty_content():
    from snippet_optimizer import ensure_summary_box
    post = {"content": "", "summary": ["요약 문장입니다"]}
    assert ensure_summary_box(post) is False


def test_snippet_prompt_block_forbids_preview_phrasing():
    from snippet_optimizer import snippet_prompt_block
    block = snippet_prompt_block()
    assert "summary" in block
    assert "알아봅니다" in block          # 나쁜 예로 명시돼 있어야 함
