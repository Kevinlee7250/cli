"""blog1 주제 개편 분류기 — 실제로 틀렸던 입력을 고정합니다.

2026-10-08: 애드센스 2차 거절 뒤 blog1을 '여행·드라마·연예'로 좁히기로 하고
migrate-offtopic 을 미리보기로 돌렸더니 50편 중 7편이 review(수동 판단)로
빠졌습니다. 7편 다 읽어보면 분명한 글이었고, 분류기 쪽 문제였습니다.
그 과정에서 짧은 영문 키워드가 다른 단어 안에서 걸리는 것도 발견했습니다.
"""

import os
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from migrate_offtopic import _count_hits, classify  # noqa: E402


# ── 2026-10-08 미리보기에서 review 로 빠졌던 7편 ─────────────────────────────

REVIEWED_2026_10_08 = [
    # 면세점은 여행 글입니다 — _KEEP_KW 에 없어서 빠졌습니다.
    ("면세점 할인 알뜰하게 이용하는 방법, 한도까지 완벽 정리", "keep"),
    # 보험은 금융입니다 — _FINANCE_KW 에 '보험'이 없었습니다.
    ("자동차보험 신규가입 최저가 비교, 처음이라 헷갈렸던 것들 정리", "migrate_blog3"),
    ("자동차보험 다이렉트 2026 최저가 비교 완벽 가이드", "migrate_blog3"),
    # 수혜주·종목도 금융입니다.
    ("젠슨황 수혜주 완벽 정리 2026 | 국내외 핵심 종목 비교 & 선택 기준", "migrate_blog3"),
    # 스포츠는 blog1 주제가 아닙니다 (blog2 주제).
    ("2026 월드컵 축구 완벽 가이드: 일정·중계·관람 꿀팁 총정리", "archive"),
    # 건강 — 애드센스가 가장 엄격하게 보는 분야입니다.
    ("당뇨 초기 증상 자가진단 방법 7가지 — 2026년 완벽 정리", "archive"),
    # 패션.
    ("2026년 여름 옷 완벽 가이드: 스타일·소재·코디 꿀팁 12가지", "archive"),
]


@pytest.mark.parametrize("title,expected", REVIEWED_2026_10_08)
def test_previously_unclassified_posts_now_land(title, expected):
    assert classify(title, [], "blog1") == expected


# ── 명절은 주제가 아니라 수식어 ──────────────────────────────────────────────

def test_holiday_word_does_not_decide_the_topic():
    """'추석특선영화'는 영화 글입니다.

    '추석'·'명절'을 보관 키워드로 넣었더니 2점이 되어, '영화' 1점을 눌러
    영화 글이 보관으로 분류됐습니다. 무엇에 관한 글인지는 옆 단어가 정합니다.
    """
    assert classify("2026 추석특선영화 편성표 총정리 후기 및 확인법 가이드",
                    ["추석특선영화", "추석편성표", "명절영화"], "blog1") == "keep"


def test_holiday_shopping_is_still_archived():
    assert classify("2026 추석 선물세트 백화점 3사 직접 비교 후기 총정리",
                    ["추석선물세트", "백화점선물세트"], "blog1") == "archive"


# ── 부분 일치 오탐 ───────────────────────────────────────────────────────────

def test_isa_does_not_match_inside_visa():
    """'isa'(금융)가 'visa'(비자 — 여행) 안에서 걸리고 있었습니다."""
    assert classify("일본 visa 발급 절차 총정리", ["visa", "여권"], "blog1") == "keep"


def test_subscription_word_does_not_match_reading():
    """'독서'가 '구독서비스비교' 안에서 걸려 음원 구독 글을 보관으로 보냈습니다.

    이제는 어느 쪽 신호도 없어 review 로 남습니다 — 실제로 애매한 글이라
    수동 판단이 맞습니다.
    """
    got = classify("멜론 vs 지니 vs 유튜브뮤직 요금 비교, 3개월 직접 써본 후기",
                   ["멜론", "음원스트리밍요금비교", "구독서비스비교"], "blog1")
    assert got == "review"


@pytest.mark.parametrize("hay,word,should_hit", [
    ("일본 visa 발급", "isa", False),
    ("isa계좌 세금혜택", "isa", True),
    ("isa 계좌 만들기", "isa", True),
    ("airport lounge mail", "ai", False),
    ("ai 글쓰기 도구", "ai", True),
    ("page title 수정", "it", False),
    ("it 기기 추천", "it", True),
    ("k-pop 콘서트", "k-pop", True),
])
def test_ascii_keywords_respect_word_boundaries(hay, word, should_hit):
    assert _count_hits({word}, hay) == (1 if should_hit else 0)


def test_korean_keywords_still_match_inside_compounds():
    """한글은 조사·복합어가 붙으므로 부분 일치를 유지해야 합니다."""
    assert _count_hits({"여행"}, "해외여행자보험 비교") == 1
    assert _count_hits({"드라마"}, "드라마추천2026") == 1


# ── 유지 우선 규칙이 살아 있는지 ─────────────────────────────────────────────

@pytest.mark.parametrize("title", [
    "해외여행자보험 비교 가이드",
    "유럽 여행 환전 방법",
    "제주 렌터카 보험 선택",
])
def test_travel_posts_do_not_leak_into_finance(title):
    """'보험'·'환전'이 들어가도 여행 글은 blog1에 남아야 합니다."""
    assert classify(title, [], "blog1") == "keep"


@pytest.mark.parametrize("title", [
    "2026 월드컵 축구 완벽 가이드: 일정·중계·관람 꿀팁 총정리",
    "KBO 포스트시즌 관람 가이드",
    "골프 입문 클럽 추천",
])
def test_sports_stays_on_blog2(title):
    """스포츠를 blog1 보관 키워드에 넣었지만 blog2에서는 현재 주제입니다."""
    assert classify(title, [], "blog2") == "keep"


# ── 전체 재분류에서 review 가 거의 남지 않는지 ───────────────────────────────

def test_registry_leaves_almost_nothing_for_manual_review():
    """실제 blog1 글 전체를 다시 분류했을 때 수동 판단이 많이 남으면 안 됩니다.

    키워드를 넓히기 전에는 review 가 7건이었습니다(미리보기 50편 기준).
    분류기를 조였으니 과도하게 막는지도 같이 봅니다 — 유지가 대부분이어야
    정상입니다(blog1 글은 대부분 여행·드라마입니다).
    """
    import json
    path = os.path.join(BASE_DIR, "..", "docs", "data", "post_registry.json")
    if not os.path.exists(path):
        pytest.skip("post_registry.json 이 없습니다")
    with open(path, encoding="utf-8") as f:
        posts = json.load(f)
    b1 = [p for p in posts if p.get("blogId") == "blog1"]
    if len(b1) < 20:
        pytest.skip(f"blog1 글이 {len(b1)}건뿐입니다")
    results = [classify(p.get("title", ""), p.get("labels") or [], "blog1") for p in b1]
    review = results.count("review")
    keep = results.count("keep")
    assert review <= max(3, len(b1) // 50), f"review 가 {review}건 남았습니다"
    assert keep >= len(b1) * 0.7, f"유지가 {keep}/{len(b1)} 뿐입니다 — 너무 많이 걸러냅니다"
