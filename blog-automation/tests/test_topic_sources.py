"""주제별 공식 출처 대체 경로를 검사합니다.

2026-09-20 실측: 오래된 글 11편은 research_collector가 뉴스 자료를 하나도
못 찾았습니다(`실존 출처 못 찾음 — 가짜 URL 방지 위해 생략`). 안내형 주제라
최근 기사가 없는 탓입니다.

그 글들을 영영 출처 없이 두는 대신 주제의 **공식 기관 대표 페이지**를 답니다.
이건 지어내기와 다릅니다. 다르다는 것을 코드가 지키는지 보는 파일입니다.
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import enrich_posts as ep  # noqa: E402


# ── 목록 자체의 건전성 ────────────────────────────────────────────────────

def test_every_source_is_https_and_has_a_title():
    for topic in ep._load_topic_sources():
        for s in topic["sources"]:
            assert s["url"].startswith("https://"), s
            assert len(s["title"]) >= 4, s


def test_sources_are_institution_root_pages():
    """개별 게시물 URL은 금방 사라집니다 — 대표 페이지만 담습니다."""
    for topic in ep._load_topic_sources():
        for s in topic["sources"]:
            path = s["url"].split("://", 1)[1].split("/", 1)
            tail = path[1] if len(path) > 1 else ""
            assert len(tail.strip("/")) <= 1, f"게시물 URL로 보입니다: {s['url']}"


def test_no_duplicate_urls_within_a_topic():
    for topic in ep._load_topic_sources():
        urls = [s["url"] for s in topic["sources"]]
        assert len(urls) == len(set(urls)), topic["name"]


def test_file_records_when_it_was_verified():
    """언제 접속해 확인했는지 남아 있어야 다음 사람이 재확인할 수 있습니다."""
    path = os.path.join(os.path.dirname(_HERE), "topic_sources.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert data.get("verifiedAt")


# ── 주제 매칭 ─────────────────────────────────────────────────────────────

def test_matches_by_title_keyword():
    got = ep.curated_sources_for("자동차보험 다이렉트 가격 비교 및 가입 완벽 가이드 2026")
    assert got and any("knia" in s["url"] for s in got)


def test_stock_post_gets_dart_and_krx():
    got = ep.curated_sources_for("삼성전자 주가 분석: 전략적 투자 접근법")
    urls = " ".join(s["url"] for s in got)
    assert "dart.fss.or.kr" in urls and "krx.co.kr" in urls


def test_golf_post_matches():
    assert ep.curated_sources_for("해외 골프 여행 추천 5곳: 2026년 골퍼를 위한 완벽 코스 가이드")


def test_unrelated_title_gets_nothing():
    """아무 주제나 억지로 붙이면 관련 없는 링크가 달립니다."""
    assert ep.curated_sources_for("포핸즈 등장인물 분석과 배우 케미") == []


def test_limit_is_respected():
    got = ep.curated_sources_for("자동차보험 갱신 할인받는 방법", max_sources=2)
    assert len(got) <= 2


# ── 표기 — 인용한 자료인 척하지 않는다 ────────────────────────────────────

def test_curated_sources_are_labelled_as_official_not_cited():
    html = ep.build_sources_html(
        [dict(s, curated=True) for s in
         ep.curated_sources_for("자동차보험 갱신 할인받는 방법")])
    assert "공식 기관 자료" in html
    assert "본문에서 인용" not in html


def test_news_sources_get_no_official_note():
    """research_collector가 찾은 기사에는 그 문구가 붙으면 안 됩니다."""
    html = ep.build_sources_html(
        [{"title": "뉴스 기사", "url": "https://news.example.com/a"}])
    assert "공식 기관 자료" not in html


def test_mixed_sources_are_not_called_official():
    html = ep.build_sources_html([
        {"title": "뉴스 기사", "url": "https://news.example.com/a"},
        {"title": "금융감독원", "url": "https://www.fss.or.kr/", "curated": True},
    ])
    assert "공식 기관 자료" not in html


# ── 대체 경로가 우선순위를 뒤집지 않는지 ──────────────────────────────────

def test_news_wins_over_curated(monkeypatch):
    """뉴스 자료를 찾았으면 공식 자료로 대체하지 않습니다."""
    import types
    fake = types.SimpleNamespace(collect_research=lambda kw, max_materials=6: {
        "materials": [{"title": "실제 기사", "url": "https://news.example.com/1"}]})
    monkeypatch.setitem(sys.modules, "research_collector", fake)
    got = ep.collect_source_links("자동차보험", title="자동차보험 갱신 할인")
    assert [s["url"] for s in got] == ["https://news.example.com/1"]
    assert not got[0].get("curated")


def test_falls_back_when_research_returns_nothing(monkeypatch):
    import types
    fake = types.SimpleNamespace(
        collect_research=lambda kw, max_materials=6: {"materials": []})
    monkeypatch.setitem(sys.modules, "research_collector", fake)
    got = ep.collect_source_links("자동차보험", title="자동차보험 갱신 할인")
    assert got and all(s["curated"] for s in got)


def test_still_empty_when_topic_is_unknown(monkeypatch):
    """둘 다 없으면 빈 목록 — 호출부가 그 글을 건너뜁니다."""
    import types
    fake = types.SimpleNamespace(
        collect_research=lambda kw, max_materials=6: {"materials": []})
    monkeypatch.setitem(sys.modules, "research_collector", fake)
    assert ep.collect_source_links("포핸즈", title="포핸즈 등장인물 분석") == []
