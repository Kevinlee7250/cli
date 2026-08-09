"""FAQ·출처 자동 보강 (enrich_posts.py) 테스트.

실행: cd blog-automation && python -m pytest tests/test_enrich_posts.py -v
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ──────────────────────────────────────────────────────────────────────────────
# 감지 규칙 — adsense_audit와 동일 기준
# ──────────────────────────────────────────────────────────────────────────────

def test_needs_faq_detection():
    from enrich_posts import needs_faq
    assert needs_faq("<p>본문</p>") is True
    assert needs_faq("<h2>자주 묻는 질문</h2><p>답</p>") is False
    assert needs_faq("<h2>FAQ</h2>") is False


def test_needs_sources_detection():
    from enrich_posts import needs_sources
    assert needs_sources("<p>본문</p>") is True
    assert needs_sources("<h2>참고자료</h2>") is False
    assert needs_sources("<p>출처: 한국은행</p>") is False


# ──────────────────────────────────────────────────────────────────────────────
# 섹션 렌더링·삽입 위치
# ──────────────────────────────────────────────────────────────────────────────

def test_build_faq_html_escapes_and_renders_cards():
    from enrich_posts import build_faq_html
    html = build_faq_html([{"q": "질문<script>?", "a": "답변입니다."}])
    assert "자주 묻는 질문" in html
    assert "&lt;script&gt;" in html          # XSS 이스케이프
    assert "background:#f8fafc" in html       # 기존 FAQ 카드와 동일 스타일


def test_build_faq_html_empty_items_returns_empty():
    from enrich_posts import build_faq_html
    assert build_faq_html([]) == ""


def test_build_sources_html_renders_links():
    from enrich_posts import build_sources_html
    html = build_sources_html([{"title": "기사 제목", "url": "https://news.example.com/a"}])
    assert "참고자료" in html
    assert 'href="https://news.example.com/a"' in html
    assert 'rel="noopener nofollow"' in html


def test_insert_before_tail_places_section_before_disclaimer():
    from enrich_posts import insert_before_tail
    disclaimer = '<div style="margin-top:2.5em;padding:16px 20px;background:#fffbeb">면책</div>'
    content = "<p>본문</p>" + disclaimer
    result = insert_before_tail(content, "<h2>자주 묻는 질문</h2>")
    assert result.index("자주 묻는 질문") < result.index("면책")


def test_insert_before_tail_appends_when_no_marker():
    from enrich_posts import insert_before_tail
    result = insert_before_tail("<p>본문</p>", "<h2>참고자료</h2>")
    assert result.endswith("<h2>참고자료</h2>")


# ──────────────────────────────────────────────────────────────────────────────
# FAQ 생성 — Claude 응답 파싱
# ──────────────────────────────────────────────────────────────────────────────

def test_generate_faq_items_parses_json_response():
    import enrich_posts as ep
    fake_response = '설명 텍스트 [{"q": "질문1?", "a": "답변1"}, {"q": "질문2?", "a": "답변2"}] 끝'
    with patch("anthropic.Anthropic"), \
         patch("config.claude_generate", return_value=fake_response):
        items = ep.generate_faq_items("제목", "<p>" + "본문 내용. " * 100 + "</p>")
    assert len(items) == 2
    assert items[0]["q"] == "질문1?"


def test_generate_faq_items_short_content_skipped():
    from enrich_posts import generate_faq_items
    # 300자 미만 본문은 근거 부족 — API 호출 없이 빈 목록
    assert generate_faq_items("제목", "<p>짧은 글</p>") == []


def test_generate_faq_items_bad_response_returns_empty():
    import enrich_posts as ep
    with patch("anthropic.Anthropic"), \
         patch("config.claude_generate", return_value="JSON 아님"):
        items = ep.generate_faq_items("제목", "<p>" + "본문. " * 100 + "</p>")
    assert items == []


# ──────────────────────────────────────────────────────────────────────────────
# 출처 수집 — 실존 URL만, 실패 시 생략
# ──────────────────────────────────────────────────────────────────────────────

def test_collect_source_links_uses_research_materials():
    import enrich_posts as ep
    fake_research = {"materials": [
        {"title": "기사1", "url": "https://n.example.com/1", "trusted": True},
        {"title": "기사2", "url": "https://n.example.com/2", "trusted": False},
        {"title": "", "url": "https://n.example.com/3"},          # 제목 없음 → 제외
    ]}
    with patch("research_collector.collect_research", return_value=fake_research):
        sources = ep.collect_source_links("테스트 키워드")
    assert len(sources) == 2
    assert sources[0]["url"] == "https://n.example.com/1"


def test_collect_source_links_failure_returns_empty():
    import enrich_posts as ep
    with patch("research_collector.collect_research", side_effect=Exception("네트워크")):
        assert ep.collect_source_links("키워드") == []


# ──────────────────────────────────────────────────────────────────────────────
# 파이프라인 — dry-run은 수정 없음 / 실제 실행은 PATCH
# ──────────────────────────────────────────────────────────────────────────────

def _blogger_list_response():
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"items": [
        {"id": "p1", "title": "FAQ 없는 글", "url": "http://x/1",
         "content": "<p>" + "본문. " * 100 + "</p><h2>참고자료</h2>"},
    ]}
    return resp


def test_enrich_blog_dry_run_no_patch():
    import enrich_posts as ep
    with patch("blogger_uploader._get_access_token", return_value="tok"), \
         patch("requests.get", return_value=_blogger_list_response()), \
         patch("requests.patch") as mock_patch:
        result = ep.enrich_blog({"id": "blog2", "name": "테스트", "blog_id": "123"},
                                dry_run=True, limit=5)
    assert not mock_patch.called
    assert result["enriched"] == 1
    assert result["posts"][0]["detail"][0].startswith("[dry-run]")


def test_enrich_blog_live_run_patches_content():
    import enrich_posts as ep
    patch_resp = MagicMock(status_code=200)
    with patch("blogger_uploader._get_access_token", return_value="tok"), \
         patch("requests.get", return_value=_blogger_list_response()), \
         patch("requests.patch", return_value=patch_resp) as mock_patch, \
         patch.object(ep, "generate_faq_items", return_value=[{"q": "질문?", "a": "답변"}]), \
         patch("time.sleep"):
        result = ep.enrich_blog({"id": "blog2", "name": "테스트", "blog_id": "123"},
                                dry_run=False, limit=5)
    assert mock_patch.called
    sent = mock_patch.call_args.kwargs["json"]["content"]
    assert "자주 묻는 질문" in sent
    # 이미 있는 참고자료 섹션은 건드리지 않음 (출처 추가 안 함)
    assert result["posts"][0]["faq_added"] is True
    assert result["posts"][0]["sources_added"] is False


def test_enrich_blog_skips_when_faq_generation_fails():
    import enrich_posts as ep
    with patch("blogger_uploader._get_access_token", return_value="tok"), \
         patch("requests.get", return_value=_blogger_list_response()), \
         patch("requests.patch") as mock_patch, \
         patch.object(ep, "generate_faq_items", return_value=[]), \
         patch("time.sleep"):
        result = ep.enrich_blog({"id": "blog2", "name": "테스트", "blog_id": "123"},
                                dry_run=False, limit=5)
    assert not mock_patch.called   # 생성 실패 → 원문 유지, PATCH 없음
    assert result["enriched"] == 0
