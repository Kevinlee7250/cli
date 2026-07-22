"""도입부 후킹·카테고리별 체류 지침 분화 테스트.

실행: cd blog-automation && python -m pytest tests/test_content_hooks.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_detect_category_finance_by_blog_id():
    import content_generator as cg
    assert cg._detect_content_category("아무 키워드", "blog3") == "finance"


def test_detect_category_finance_by_keyword():
    import content_generator as cg
    assert cg._detect_content_category("ETF 월배당 포트폴리오", "") == "finance"


def test_detect_category_sports():
    import content_generator as cg
    assert cg._detect_content_category("손흥민 결승골 경기 결과", "") == "sports"


def test_detect_category_drama():
    import content_generator as cg
    assert cg._detect_content_category("SBS 드라마 김부장 리뷰", "") == "drama"


def test_detect_category_defaults_to_travel():
    import content_generator as cg
    assert cg._detect_content_category("부산 1박2일 혼자 여행", "") == "travel"


def test_engagement_block_uses_category_specific_hook():
    import content_generator as cg
    finance_block = cg._engagement_block("ETF 월배당 포트폴리오", "blog3")
    travel_block = cg._engagement_block("부산 1박2일 혼자 여행", "")
    assert "숫자·근거로 시작" in finance_block
    assert "상황·공감으로 시작" in travel_block
    assert finance_block != travel_block


def test_engagement_block_still_contains_common_rules():
    import content_generator as cg
    block = cg._engagement_block("아무 키워드", "")
    assert "낚시 금지" in block
    assert "모바일 가독성" in block
