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
    # 2026-09-19 — 답변이 검증(validate_faq_items)을 통과해야 하므로
    # 실제와 비슷한 길이로 씁니다. "답변1" 같은 한 마디는 이제 버려집니다.
    import enrich_posts as ep
    fake_response = (
        '설명 텍스트 ['
        '{"q": "언제 신고하나요?", "a": "본문에 정리한 대로 기간 안에 신고하면 됩니다."},'
        '{"q": "어디서 확인하나요?", "a": "본문에서 안내한 공식 채널에서 확인할 수 있습니다."}'
        '] 끝')
    with patch("anthropic.Anthropic"), \
         patch("config.claude_generate", return_value=fake_response):
        items = ep.generate_faq_items("제목", "<p>" + "본문 내용. " * 100 + "</p>")
    assert len(items) == 2
    assert items[0]["q"] == "언제 신고하나요?"


def test_generate_faq_items_drops_fabricated_numbers():
    """Claude가 규칙을 어기고 본문에 없는 수치를 넣으면 그 항목만 버립니다."""
    import enrich_posts as ep
    fake_response = (
        '[{"q": "기준이 얼마인가요?", "a": "공시가격 9억원을 넘으면 대상이 됩니다."},'
        '{"q": "어디서 확인하나요?", "a": "본문에서 안내한 공식 채널에서 확인할 수 있습니다."}]')
    with patch("anthropic.Anthropic"), \
         patch("config.claude_generate", return_value=fake_response):
        items = ep.generate_faq_items("제목", "<p>" + "본문 내용. " * 100 + "</p>")
    assert [it["q"] for it in items] == ["어디서 확인하나요?"]


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


# ──────────────────────────────────────────────────────────────────────────────
# FAQ 검증 — 2026-09-19 추가
# ──────────────────────────────────────────────────────────────────────────────
#
# generate_faq_items의 프롬프트는 처음부터 "본문에 없는 수치·사실 생성 금지"라고
# 적고 있었지만, 지켜졌는지 확인하는 코드가 없었습니다. AdSense 거절 사유가
# 정확히 "지어낸 내용"이었으므로, 부탁만 하고 넘어갈 수 없습니다.

_BODY = ("종합부동산세는 공시가격 12억원을 넘는 1주택자에게 부과됩니다. "
         "신고 기간은 12월이며, 절차는 크게 2단계로 나뉩니다.")


def test_faq_with_number_absent_from_body_is_rejected():
    from enrich_posts import validate_faq_items
    items = [{"q": "기준 금액이 얼마인가요?",
              "a": "공시가격 9억원을 넘으면 대상이 됩니다. 미리 확인해 두면 좋습니다."}]
    assert validate_faq_items(items, _BODY) == [], "본문에 없는 9억원을 통과시켰습니다"


def test_faq_supported_by_body_is_kept():
    from enrich_posts import validate_faq_items
    items = [{"q": "기준 금액이 얼마인가요?",
              "a": "공시가격 12억원을 넘는 1주택자가 대상입니다. 신고는 12월에 합니다."}]
    assert len(validate_faq_items(items, _BODY)) == 1


def test_structural_numbers_do_not_trigger_rejection():
    """'2단계' 같은 글의 구성 표현까지 막으면 아무것도 못 씁니다."""
    from enrich_posts import validate_faq_items
    items = [{"q": "절차가 어떻게 되나요?",
              "a": "크게 2단계입니다. 공시가격을 확인한 뒤 12월에 신고하면 됩니다."}]
    assert len(validate_faq_items(items, _BODY)) == 1


def test_faq_claiming_experience_is_rejected():
    """조사·정리형 글의 FAQ가 경험을 주장하면 거절 사유가 그대로 돌아옵니다."""
    from enrich_posts import validate_faq_items
    items = [{"q": "신고가 어렵나요?",
              "a": "제가 직접 신고해본 후기로는 어렵지 않았습니다. 홈택스에서 가능합니다."}]
    assert validate_faq_items(items, _BODY) == []


def test_too_short_items_are_rejected():
    from enrich_posts import validate_faq_items
    assert validate_faq_items([{"q": "왜?", "a": "네."}], _BODY) == []


def test_malformed_items_do_not_crash():
    from enrich_posts import validate_faq_items
    assert validate_faq_items("배열이 아님", _BODY) == []
    assert validate_faq_items([None, 7, {"q": "", "a": ""}], _BODY) == []


def test_unsupported_numbers_lists_the_offenders():
    from enrich_posts import unsupported_numbers
    assert unsupported_numbers("9억원과 3%가 기준입니다.", _BODY)
    assert unsupported_numbers("12억원이 기준입니다.", _BODY) == []


# ── FAQ 근거가 되는 본문 — 부속 블록은 빼고 넘긴다 ────────────────────────

def test_related_post_cards_are_not_used_as_faq_source():
    """관련 포스트 카드에는 다른 글의 제목·요약이 박혀 있습니다.

    그대로 넘기면 이 글에 없는 내용을 근거로 FAQ가 만들어집니다.
    """
    from enrich_posts import _plain_text
    html = ('<p>환헤지 ETF의 비용 구조를 공시 자료로 정리했습니다.</p>'
            '<div class="rp-wrap"><h3>📖 관련 포스트</h3><div class="rp-grid">'
            '<a href="https://b/x" class="rp-card">'
            '<span class="rp-ctit">대사관 신고 직접 경험한 절차</span></a>'
            '</div></div>')
    text = _plain_text(html)
    assert "환헤지 ETF의 비용 구조" in text
    assert "대사관" not in text, "다른 글의 제목이 FAQ 근거로 넘어갑니다"
