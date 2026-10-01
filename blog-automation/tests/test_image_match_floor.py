# -*- coding: utf-8 -*-
"""일반적인 단어 하나로 구체적인 검색어가 통과하지 않도록 고정합니다.

2026-09-27에 실제로 일어난 일입니다. 'bank consultation desk documents'로
이미지를 찾았는데, 본문에 붙은 것은 벤치에 혼자 앉아 휴대폰 보는 여성
사진이었습니다. 태그에 'bank'가 하나 들어 있어서 1/4 = 0.25가 되고,
임계값 0.15를 넘겨 통과했습니다.

비율만 보면 흔한 단어 하나가 긴 구체적 쿼리를 통째로 통과시킵니다.
그래서 절대 개수 하한을 같이 둡니다 — 구체적으로 물었으면 구체적으로
맞아야 합니다.

alt 텍스트도 같이 봅니다. 검색어를 그대로 alt에 박으면 "무엇을 찾았는지"가
적힙니다. alt는 "무엇이 찍혀 있는지"를 적는 자리입니다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import image_fetcher as imf  # noqa: E402


# 실제 사고 — Pixabay가 돌려준 벤치 사진의 태그
BENCH = {"title": "women / one / wall / minimalism / bank / bench",
         "url": "https://cdn.pixabay.com/photo/2016/01/01/bench.jpg"}
BANK_DESK = {"title": "bank / desk / documents / counter",
             "url": "https://cdn.pixabay.com/photo/2017/02/02/bank-desk.jpg"}


# ── 개수 하한 ─────────────────────────────────────────────────────────────

def test_the_bench_photo_is_rejected():
    """단어 하나(bank)만 겹친 사진은 통과하면 안 됩니다."""
    q = "bank consultation desk documents"
    matched, total = imf._relevance_counts(BENCH, q)
    assert matched == 1 and total == 4
    # 비율로는 0.25라 옛 임계값(0.15)을 넘습니다 — 그게 사고의 원인이었습니다
    assert imf._score_title_relevance(BENCH, q) > imf._MIN_RELEVANCE
    assert imf._passes_relevance(BENCH, q, imf._MIN_RELEVANCE) is False


def test_a_real_match_passes():
    q = "bank consultation desk documents"
    assert imf._passes_relevance(BANK_DESK, q, imf._MIN_RELEVANCE) is True


def test_short_query_needs_only_one_match():
    """단어가 2개 이하면 하나만 맞아도 통과입니다 — 아니면 쓸 결과가 없습니다."""
    img = {"title": "apartment building", "url": "https://cdn.pixabay.com/a.jpg"}
    assert imf._passes_relevance(img, "apartment", imf._MIN_RELEVANCE) is True
    assert imf._passes_relevance(img, "apartment seoul", imf._MIN_RELEVANCE) is True


def test_three_word_query_needs_two_matches():
    img = {"title": "apartment / sky / cloud", "url": "https://cdn.pixabay.com/a.jpg"}
    assert imf._passes_relevance(img, "seoul apartment skyline", imf._MIN_RELEVANCE) is False
    img2 = {"title": "apartment / skyline / city", "url": "https://cdn.pixabay.com/a.jpg"}
    assert imf._passes_relevance(img2, "seoul apartment skyline", imf._MIN_RELEVANCE) is True


def test_zero_match_never_passes():
    img = {"title": "fighter jet / military", "url": "https://cdn.pixabay.com/j.jpg"}
    assert imf._passes_relevance(img, "bank desk documents", imf._MIN_RELEVANCE) is False
    assert imf._passes_relevance(img, "bank desk documents", 0.0) is False


def test_empty_query_passes_nothing():
    assert imf._passes_relevance(BANK_DESK, "", imf._MIN_RELEVANCE) is False


def test_floor_also_applies_to_the_zero_ratio_path():
    """폴백 경로(min_ratio=0.0)에도 같은 개수 하한이 걸려야 합니다.

    하한을 임계값에만 걸면 폴백으로 그대로 새어 나갑니다 — 벤치 사진이
    실제로 지나간 경로입니다.
    """
    assert imf._passes_relevance(BENCH, "bank consultation desk documents", 0.0) is False


def test_score_function_still_returns_a_ratio():
    """정렬에 쓰이므로 비율 자체는 그대로여야 합니다."""
    assert imf._score_title_relevance(BANK_DESK, "bank desk") == 1.0
    assert imf._score_title_relevance({"title": "", "url": ""}, "bank") == 0.0


# ── alt 텍스트 ────────────────────────────────────────────────────────────

def test_alt_describes_the_image_not_the_query():
    img = {"title": "apartment / colorful building / resident",
           "url": "https://cdn.pixabay.com/a.jpg"}
    alt = imf.alt_text_for(img, "seoul apartment complex skyline")
    assert "seoul" not in alt.lower(), "확인되지 않은 '서울'이 alt에 박혔습니다"
    assert "apartment" in alt


def test_alt_keeps_only_the_first_few_tags():
    img = {"title": "women / one / wall / minimalism / bank / bench / mono"}
    alt = imf.alt_text_for(img, "bank desk")
    assert alt.count(",") <= 2


def test_alt_falls_back_to_the_query_when_image_says_nothing():
    assert imf.alt_text_for({"title": "", "url": ""}, "bank desk") == "bank desk"


def test_alt_prefers_explicit_alt_text():
    img = {"alt_text": "직접 만든 제목 썸네일", "title": "무시될 제목"}
    assert imf.alt_text_for(img, "쿼리") == "직접 만든 제목 썸네일"


def test_alt_is_length_capped():
    img = {"title": "a" * 200}
    assert len(imf.alt_text_for(img, "q")) <= 50
