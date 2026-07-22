"""FAQ 배치 최적화 테스트 — 본문 중간에 FAQ 카드 1개를 추가 배치하는 기능.

실행: cd blog-automation && python -m pytest tests/test_faq_placement.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _sample_html(h2_count: int = 5) -> str:
    sections = "".join(f"<h2>섹션{i}</h2><p>내용{i}</p>\n" for i in range(1, h2_count + 1))
    return f"""<article>
{sections}<h2>자주 묻는 질문</h2>
<h3>Q1. 질문1인가요?</h3><p>답변1입니다.</p>
<h3>Q2. 질문2인가요?</h3><p>답변2입니다.</p>
</article>"""


def test_mid_article_faq_inserted_when_enough_sections():
    import content_generator as cg
    styled = cg._faq_to_cards(_sample_html(5))
    result = cg._inject_mid_article_faq(styled)

    # 본문 중간에 재유입 유도 문구 + 카드가 삽입됨
    assert "잠깐, 이것도 궁금하지 않으세요?" in result
    # 끝의 FAQ 섹션은 그대로(카드 2개) 유지됨
    assert result.count("답변1입니다.") == 2
    assert result.count("답변2입니다.") == 1


def test_mid_article_faq_placed_before_middle_section():
    import content_generator as cg
    styled = cg._faq_to_cards(_sample_html(5))
    result = cg._inject_mid_article_faq(styled)

    teaser_pos = result.index("잠깐, 이것도 궁금하지 않으세요?")
    sec2_pos = result.index("<h2>섹션2</h2>")
    sec3_pos = result.index("<h2>섹션3</h2>")
    # 5개 섹션 중 중간(인덱스 2, "섹션3") 바로 앞에 삽입되어야 함
    assert sec2_pos < teaser_pos < sec3_pos


def test_no_injection_when_too_few_sections():
    import content_generator as cg
    styled = cg._faq_to_cards(_sample_html(2))
    result = cg._inject_mid_article_faq(styled)
    assert "잠깐, 이것도 궁금하지 않으세요?" not in result


def test_no_faq_no_change():
    import content_generator as cg
    html = "<article><h2>섹션1</h2><p>내용</p><h2>섹션2</h2><p>내용</p></article>"
    assert cg._inject_mid_article_faq(html) == html


def test_apply_design_calls_mid_faq_injection(monkeypatch):
    import content_generator as cg
    called = {}
    orig = cg._inject_mid_article_faq

    def spy(html):
        called["ran"] = True
        return orig(html)

    monkeypatch.setattr(cg, "_inject_mid_article_faq", spy)
    cg._apply_design(_sample_html(5), keyword="테스트", article_type="analysis")
    assert called.get("ran") is True
