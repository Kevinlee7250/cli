"""본문 리라이팅이 자동 생성 블록을 건드리지 않는지 검사합니다.

관련 포스트 카드와 시리즈 내비게이션에는 '다른 글의 제목'이 그대로 박혀
있습니다. 그걸 문단으로 보고 고치면, 내비게이션 문구를 바꿔 놓고
"본문을 정정했다"고 기록하게 됩니다.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from fix_experience_claims import find_bad_paragraphs  # noqa: E402

SERIES_NAV = (
    '<div style="background:#f0f4ff;border:1px solid #c5d3f7;padding:20px;">'
    '<p>📚 포핸즈 첫인상 솔직 리뷰 시리즈 2/3편</p>'
    '</div>'
)
INBOUND = ('<p class="hogu-inbound-related">함께 읽으면 좋은 글: '
           '<a href="https://b.com/y">제주 렌터카 직접 써본 후기</a></p>')
RELATED = (
    '<div class="rp-wrap"><h3>📖 관련 포스트</h3><div class="rp-grid">'
    '<p>대사관 신고 직접 경험한 절차</p></div></div>'
)
GOOD = "<p>공시 자료를 기준으로 비용 구조를 정리했습니다.</p>"
BAD = "<p>제가 직접 써본 후기를 그대로 적었습니다.</p>"


def test_series_nav_paragraph_is_not_a_target():
    assert find_bad_paragraphs(GOOD + SERIES_NAV) == []


def test_inbound_link_paragraph_is_not_a_target():
    assert find_bad_paragraphs(GOOD + INBOUND) == []


def test_related_card_paragraph_is_not_a_target():
    assert find_bad_paragraphs(GOOD + RELATED) == []


def test_real_body_paragraph_is_still_a_target():
    found = find_bad_paragraphs(BAD + SERIES_NAV + INBOUND + RELATED)
    assert len(found) == 1
    assert "제가 직접 써본" in found[0][0]


def test_plain_post_behaviour_unchanged():
    assert find_bad_paragraphs(GOOD) == []
    assert len(find_bad_paragraphs(BAD)) == 1
