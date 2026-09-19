"""감사가 '본문이 아닌 것'과 '경험 주장이 아닌 것'을 지적하지 않는지 검사합니다.

2026-09-19 전수 감사 실측:
  · 지적 42건 중 14건 — 본문은 멀쩡한데 관련 포스트 카드에 박힌
    다른 글 제목 때문에 걸림 (히트 68개 중 31개)
  · 본문 히트 37개 중 26개 — "상품설명서를 직접 확인하는 게 안전합니다"처럼
    독자에게 권하는 문장
  · high 1건 — "실제 여행자들이 ... 겪었는지를 자료 기준으로 정리했습니다"

과소 탐지만 위험한 게 아닙니다. 이 상태로 본문 리라이팅을 돌리면
멀쩡한 안내 문장을 고쳐 놓고 "정정했다"고 기록합니다.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from experience_audit import analyze_text, _strip_html, strip_chrome  # noqa: E402
from title_policy import check_title  # noqa: E402


# ── 부속 블록은 본문이 아니다 ─────────────────────────────────────────────

RELATED = (
    '<div class="rp-wrap"><h3>📖 관련 포스트</h3>'
    '<div class="rp-grid">'
    '<a href="https://b.com/x" class="rp-card">'
    '<span class="rp-ctit">해외에서 사고 났을 때 대사관 신고 직접 경험한 절차</span>'
    '<span class="rp-tags"><span class="rp-tag">#해외여행</span></span></a>'
    '</div></div>'
)
SERIES_NAV = (
    '<div style="background:#f0f4ff;border:1px solid #c5d3f7;padding:20px;">'
    '<p>📚 환헤지 ETF 직접 알아본 완전 정리 시리즈 2/3편</p>'
    '<div><a href="/label/x">📋 시리즈 전체 보기</a>'
    '<a href="/1">[1편] 포핸즈 첫인상 솔직 리뷰</a></div>'
    '</div>'
)
INBOUND = ('<p class="hogu-inbound-related">함께 읽으면 좋은 글: '
           '<a href="https://b.com/y">제주 렌터카 직접 써본 후기</a></p>')

BODY = "<p>환헤지 ETF의 비용 구조를 공시 자료로 정리했습니다.</p>"


def test_related_post_cards_are_not_audited():
    """관련 포스트에 박힌 다른 글 제목이 이 글의 지적이 되면 안 됩니다."""
    assert analyze_text(_strip_html(BODY + RELATED)) == []


def test_series_navigation_is_not_audited():
    assert analyze_text(_strip_html(BODY + SERIES_NAV)) == []


def test_inbound_link_line_is_not_audited():
    """역방향 링크 한 줄이 그 글을 오염시키면, 링크를 걸수록 감사가 나빠집니다."""
    assert analyze_text(_strip_html(BODY + INBOUND)) == []


def test_all_three_blocks_together():
    assert analyze_text(_strip_html(BODY + RELATED + SERIES_NAV + INBOUND)) == []


def test_body_text_survives_the_stripping():
    """부속 블록만 지우고 본문은 그대로 남아야 합니다."""
    text = _strip_html(BODY + RELATED + SERIES_NAV + INBOUND)
    assert "환헤지 ETF의 비용 구조" in text
    assert "관련 포스트" not in text
    assert "시리즈 전체 보기" not in text


def test_real_experience_claim_inside_body_still_caught():
    """부속 블록을 지운다고 본문의 진짜 경험 주장까지 놓치면 안 됩니다."""
    html = "<p>제가 직접 써본 후기를 정리했습니다.</p>" + RELATED
    assert analyze_text(_strip_html(html)), "본문 경험 주장을 놓쳤습니다"


def test_nested_cards_do_not_eat_the_rest_of_the_post():
    """중첩 div를 잘못 닫으면 본문 뒷부분이 통째로 사라집니다."""
    html = RELATED + "<p>이 문장은 관련 포스트 뒤에 있는 본문입니다.</p>"
    assert "관련 포스트 뒤에 있는 본문" in _strip_html(html)


def test_trailing_hashtags_are_dropped():
    text = _strip_html("<p>본문입니다.</p><p>#해외여행 #대사관신고 #영사콜센터</p>")
    assert "해외여행" not in text


def test_strip_chrome_leaves_plain_html_alone():
    assert strip_chrome(BODY) == BODY


# ── 권유 문장은 경험 주장이 아니다 ────────────────────────────────────────

ADVICE = [
    "다만 운용사마다 표기 방식이 다를 수 있어 상품 설명서를 직접 확인하는 게 안전합니다.",
    "상품설명서를 직접 확인하는 절차가 필요합니다.",
    "가입 전에 약관을 직접 확인하세요.",
    "수수료는 직접 계산해 보면 차이가 분명합니다.",
    "청구 전에 보장 항목을 직접 점검해야 합니다.",
]


def test_advice_sentences_are_not_experience_claims():
    for s in ADVICE:
        assert analyze_text(s) == [], f"권유 문장을 지적했습니다: {s}"


def test_writer_side_claims_are_still_caught():
    """글쓴이가 '했다'는 쪽은 그대로 잡아야 합니다."""
    assert check_title("해외여행 환전 수수료 0%, 트래블카드 직접 비교 정리")
    assert analyze_text("카드 세 종류를 직접 비교 정리했습니다.")


def test_third_person_research_framing_is_not_high():
    """9/19 감사에서 유일한 high였던 실제 문장 — 조사형입니다."""
    s = ("이 글에서는 경찰서 신고 서류를 어떻게 받아야 보험사가 인정하는지, "
         "실제 여행자들이 어디서 시행착오를 겪었는지를 자료 기준으로 정리했습니다.")
    assert analyze_text(s) == [], analyze_text(s)


CONNECTIVE_ADVICE = [
    "실제 투자 전 최신 재무제표와 배당 이력을 반드시 직접 확인하고 결정하시기 바랍니다.",
    "'복리의 마법'을 직접 체험하세요.",
    "이 자료는 최근 강수 패턴과 직접 비교하긴 어렵지만 참고할 만합니다.",
    "보험료를 직접 비교하고 불필요한 중간 수수료를 줄이는 방식입니다.",
    "자금 흐름 데이터를 직접 확인하고 본인의 투자 기간을 먼저 점검하는 것이 낫습니다.",
]


def test_connective_and_imperative_forms_are_not_claims_in_body():
    """'직접 ~하고/하긴/하세요'는 다음 동작으로 이어지는 연결형입니다."""
    for s in CONNECTIVE_ADVICE:
        assert analyze_text(s) == [], f"연결·권유형을 지적했습니다: {s}"


def test_the_same_tail_is_still_caught_in_a_title():
    """제목은 명사구라 같은 꼬리도 뜻이 다릅니다.

    "직접 확인하고 정리한 체크리스트"는 글쓴이가 했다는 말입니다 —
    본문 예외를 제목까지 적용하면 9/17 발행 제목을 놓칩니다.
    """
    assert check_title("패키지여행 계약서 환불 조항, 직접 확인하고 정리한 체크리스트")
    assert analyze_text("패키지여행 계약서 환불 조항, 직접 확인하고 정리한 체크리스트",
                        title_mode=True)


def test_generic_noun_phrase_is_not_a_review_claim():
    """'기대와 실제 경험 사이의 간극' — 후기 표방이 아닙니다."""
    assert analyze_text("예약 전에 확인해두면 기대와 실제 경험 사이의 간극을 줄일 수 있습니다.") == []


def test_community_reviews_are_research_framing():
    s = ("신청자들이 자주 겪는 배정 착오, 실제 사례로 보면 "
         "커뮤니티 후기들을 살펴보면 불만이 자주 올라옵니다.")
    assert analyze_text(s) == [], analyze_text(s)


def test_writer_completed_claim_in_body_still_caught():
    """본문 예외를 넓히다 진짜 주장을 놓치면 안 됩니다."""
    assert analyze_text("카드 세 종류를 직접 비교 정리했습니다.")
    assert analyze_text("다음 편에서는 세 번 다녀온 경험을 종합해 총평을 다룹니다.")


def test_first_person_experience_is_still_high():
    """조사형 표현을 추가했다고 1인칭 경험까지 통과시키면 안 됩니다."""
    hits = analyze_text("제가 직접 겪은 일을 그대로 적었습니다.")
    assert any(h["severity"] in ("high", "critical") for h in hits), hits
