"""라벨 정리와 글 목차 페이지.

2026-10-08: blog1 글 107편에 서로 다른 라벨이 402개 있었습니다. 글마다
5~7개씩, 대부분 한 번만 쓰인 라벨 — 카테고리가 아니라 키워드 나열입니다.
그리고 blog1 의 robots.txt 는 `Disallow: /search` 라서 Blogger 라벨 목록
(/search/label/...)은 구글이 아예 가져가지 않습니다. 그래서 구조를 보여주는
쪽은 라벨이 아니라 페이지(/p/....html)여야 합니다.
"""

import os
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import build_toc_page as toc  # noqa: E402
import normalize_labels as nl  # noqa: E402


# ── 카테고리 분류 ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("title,labels,expected", [
    ("포핸즈 결말 총평, 호불호 갈린 이유", ["포핸즈", "드라마리뷰"], "드라마리뷰"),
    ("신병4 6화 등장인물 정리", ["신병4", "군대드라마"], "드라마리뷰"),
    ("2026 추석특선영화 편성표 총정리", ["추석특선영화", "명절영화"], "영화리뷰"),
    ("면세점 할인 알뜰하게 이용하는 방법", ["면세점", "해외여행준비"], "해외여행"),
    ("유류할증료 아끼는 항공권 저렴하게 구매하는 방법", ["유류할증료"], "해외여행"),
    ("해외에서 사고 났을 때 대사관 신고 절차", ["영사콜센터"], "해외여행"),
    ("가을 강원도 여행 가볼만한 곳 추천 7선, 단풍 명소", ["가을여행", "단풍명소"], "국내여행"),
    ("가을 등산 코스 추천, 붐비지 않는 명산", ["등산코스"], "국내여행"),
])
def test_category_for_real_titles(title, labels, expected):
    assert nl.category_for(title, labels, "blog1") == expected


def test_unclassifiable_post_is_left_alone():
    """분류 신호가 없으면 None — 아무 카테고리에 억지로 넣지 않습니다."""
    assert nl.category_for("멜론 vs 지니 요금 비교", ["멜론"], "blog1") is None


def test_unknown_blog_returns_none():
    """카테고리를 정의하지 않은 블로그는 건드리지 않습니다."""
    assert nl.category_for("제주 여행 코스", ["제주"], "blog3") is None


def test_ascii_keyword_boundaries():
    """'ott'가 'ottawa' 안에서, 'ena'가 'arena' 안에서 걸려선 안 됩니다."""
    assert nl._hits({"ott"}, "ottawa 여행기") == 0
    assert nl._hits({"ott"}, "ott 추천 순위") == 1
    assert nl._hits({"ena"}, "arena 콘서트") == 0
    assert nl._hits({"ena"}, "ena 드라마 편성") == 1


# ── 라벨 개수 줄이기 ─────────────────────────────────────────────────────────

def test_keeps_category_plus_two_frequent_labels():
    labels = ["포핸즈", "포핸즈결말", "드라마추천", "송강", "ENA드라마"]
    keepable = {"포핸즈", "송강"}  # 2회 이상 쓰인 것
    got = nl.plan_labels("드라마리뷰", labels, keepable)
    assert got == ["드라마리뷰", "포핸즈", "송강"]
    assert len(got) <= nl.MAX_LABELS


def test_drops_labels_used_only_once():
    """한 번만 쓰인 라벨은 분류가 아니라 키워드입니다."""
    labels = ["포핸즈결말호불호", "2026드라마추천순위"]
    assert nl.plan_labels("드라마리뷰", labels, keepable=set()) == ["드라마리뷰"]


def test_category_is_never_duplicated():
    """원래 라벨에 카테고리 이름이 들어 있어도 두 번 붙지 않습니다."""
    got = nl.plan_labels("드라마리뷰", ["드라마리뷰", "포핸즈"], {"드라마리뷰", "포핸즈"})
    assert got == ["드라마리뷰", "포핸즈"]


def test_other_category_names_are_not_kept_as_detail_labels():
    """'영화리뷰'가 세부 라벨로 따라붙으면 글이 목차 두 곳에 나옵니다."""
    got = nl.plan_labels("드라마리뷰", ["영화리뷰", "포핸즈"], {"영화리뷰", "포핸즈"})
    assert "영화리뷰" not in got
    assert got == ["드라마리뷰", "포핸즈"]


def test_label_order_is_preserved():
    labels = ["송강", "포핸즈"]
    assert nl.plan_labels("드라마리뷰", labels, set(labels)) == ["드라마리뷰", "송강", "포핸즈"]


# ── 목차 묶기 ───────────────────────────────────────────────────────────────

ORDER = toc.CATEGORY_ORDER_BY_BLOG["blog1"]


def _post(title, labels, published="2026-10-01T00:00:00+09:00", url=None):
    return {"title": title, "labels": labels, "published": published,
            "url": url or f"https://example.test/{title}.html"}


def test_a_post_appears_in_exactly_one_group():
    """라벨이 둘이어도 한 군데만 — 중복 링크 더미가 되면 안 됩니다."""
    posts = [_post("겹치는 글", ["드라마리뷰", "영화리뷰"])]
    groups = toc.group_posts(posts, ORDER)
    assert sum(len(v) for v in groups.values()) == 1
    assert "드라마리뷰" in groups  # order 에서 앞선 쪽


def test_every_post_is_in_the_toc():
    """한 편도 빠지면 목차가 아닙니다."""
    posts = [
        _post("제주 여행", ["국내여행"]),
        _post("도쿄 여행", ["해외여행"]),
        _post("라벨 없는 글", []),
    ]
    groups = toc.group_posts(posts, ORDER)
    assert sum(len(v) for v in groups.values()) == len(posts)
    assert groups[toc.OTHER_LABEL][0]["title"] == "라벨 없는 글"


def test_empty_groups_are_dropped():
    groups = toc.group_posts([_post("제주 여행", ["국내여행"])], ORDER)
    assert list(groups) == ["국내여행"]


def test_newest_first_within_a_group():
    posts = [
        _post("오래된 글", ["국내여행"], "2026-01-01T00:00:00+09:00"),
        _post("새 글", ["국내여행"], "2026-10-01T00:00:00+09:00"),
    ]
    titles = [p["title"] for p in toc.group_posts(posts, ORDER)["국내여행"]]
    assert titles == ["새 글", "오래된 글"]


# ── 목차 HTML ───────────────────────────────────────────────────────────────

def test_rendered_toc_links_every_post():
    posts = [_post("제주 여행", ["국내여행"]), _post("도쿄 여행", ["해외여행"])]
    groups = toc.group_posts(posts, ORDER)
    out = toc.render_toc(groups, len(posts), "2026년 10월 08일")
    for p in posts:
        assert p["url"] in out
        assert p["title"] in out
    assert out.count("<li") == 2


def test_marker_is_present_so_the_page_can_be_found_again():
    out = toc.render_toc(toc.group_posts([_post("제주 여행", ["국내여행"])], ORDER), 1, "오늘")
    assert toc.MARKER in out
    assert toc.find_toc_page([{"title": "아무거나", "content": out}]) is not None


def test_titles_are_escaped():
    """제목에 < 나 & 가 있으면 페이지가 깨집니다."""
    posts = [_post("부모 & 자녀 <여행> 가이드", ["국내여행"])]
    out = toc.render_toc(toc.group_posts(posts, ORDER), 1, "오늘")
    assert "&amp;" in out and "&lt;여행&gt;" in out
    assert "<여행>" not in out


def test_date_formatting():
    assert toc._date("2026-10-07T01:48:43+09:00") == "2026.10.07"
    assert toc._date("") == ""


def test_toc_page_is_not_confused_with_other_pages():
    pages = [
        {"title": "개인정보처리방침", "content": "<p>...</p>"},
        {"title": "면책 조항", "content": "<p>...</p>"},
    ]
    assert toc.find_toc_page(pages) is None


# ── 두 스크립트가 같은 카테고리를 쓰는지 ─────────────────────────────────────

def test_both_scripts_agree_on_the_categories():
    """라벨 정리와 목차가 다른 이름을 쓰면 전부 '그 외'로 떨어집니다."""
    assert set(toc.CATEGORY_ORDER_BY_BLOG["blog1"]) == nl._CATEGORY_NAMES
