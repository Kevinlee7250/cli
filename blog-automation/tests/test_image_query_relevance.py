# -*- coding: utf-8 -*-
"""검색어와 무관한 이미지가 본문에 들어가지 않도록 고정합니다.

2026-09-27에 실제로 일어난 일입니다. 주택담보대출 글에 이미지를 자동
첨부했는데, AI가 검색어를 'LTV 주택담보대출 비율'로 잡았고 Wikimedia
Commons가 LTV를 항공기 제조사(Ling-Temco-Vought)로 해석해
'LTV A-7E Corsair II.jpg' — 미 해군 전투기 사진을 돌려줬습니다.
그대로 발행됐습니다.

Commons 전문 검색은 짧은 약어 하나만 겹쳐도 결과를 냅니다. 그래서
제목과 검색어가 '근거가 될 만한' 토큰을 하나라도 공유해야 통과시킵니다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import image_fetcher as imf  # noqa: E402


# ── 실제로 일어난 사고 ────────────────────────────────────────────────────

def test_the_fighter_jet_is_rejected():
    assert imf._title_matches_query(
        "File:LTV A-7E Corsair II.jpg", "LTV 주택담보대출 비율"
    ) is False


def test_acronym_only_query_trusts_nothing():
    """검색어가 약어뿐이면 어떤 결과도 근거가 없습니다."""
    assert imf._title_matches_query("File:LTV A-7E Corsair II.jpg", "LTV") is False
    assert imf._title_matches_query("File:DSR Motor Co truck.jpg", "DSR") is False
    assert imf._title_matches_query("File:Anything.jpg", "ETF") is False


# ── 통과해야 하는 것 ──────────────────────────────────────────────────────

def test_english_noun_query_matches():
    assert imf._title_matches_query(
        "File:Apartment building in Seoul.jpg", "apartment building seoul"
    ) is True


def test_case_does_not_matter():
    assert imf._title_matches_query("File:SEOUL Skyline.jpg", "seoul skyline") is True


def test_korean_token_matches_korean_title():
    assert imf._title_matches_query("File:서울 아파트 단지.jpg", "서울 아파트") is True


def test_partial_overlap_is_enough():
    """토큰 하나만 겹쳐도 통과 — 완전 일치를 요구하면 쓸 수 있는 결과가 없습니다."""
    assert imf._title_matches_query(
        "File:Bank counter in Tokyo.jpg", "bank counter customer"
    ) is True


# ── 토큰 판정 규칙 ────────────────────────────────────────────────────────

def test_short_english_tokens_are_not_evidence():
    """3자 이하 영문은 근거로 세지 않습니다 (약어 오매칭의 원인)."""
    toks = imf._meaningful_tokens("LTV DSR ETF loan")
    assert "ltv" not in toks
    assert "dsr" not in toks
    assert "etf" not in toks
    assert "loan" in toks


def test_korean_two_chars_are_evidence():
    """한글은 2자부터 뜻이 있습니다."""
    toks = imf._meaningful_tokens("서울 아파트 값")
    assert "서울" in toks
    assert "아파트" in toks
    assert "값" not in toks


def test_empty_query_matches_nothing():
    assert imf._title_matches_query("File:Anything.jpg", "") is False
    assert imf._meaningful_tokens("") == set()


# ── 필터가 실제 검색 경로에 걸려 있는지 ───────────────────────────────────

def test_irrelevant_results_are_dropped_before_fetching(monkeypatch):
    """무관한 제목만 나오면 imageinfo를 조회하지도 않고 빈 결과를 냅니다."""
    monkeypatch.setattr(
        imf, "_wikimedia_search_titles",
        lambda kw, n: ["File:LTV A-7E Corsair II.jpg", "File:LTV Aerospace logo.svg"],
    )

    fetched = []

    def no_fetch(*a, **k):
        fetched.append(a)
        raise AssertionError("무관한 제목인데 imageinfo를 조회했습니다")

    monkeypatch.setattr(imf.requests, "get", no_fetch)

    assert imf._wikimedia_images("LTV 주택담보대출 비율", 3) == []
    assert fetched == []
