"""AdSense 정책 대응 기능 A1~A4 회귀 테스트.

A1 미달 글 draft 전환 / A2 제목 낚시 표현 사전 차단 /
A3 blog2 구주제 분류 / A4 저자 박스(E-E-A-T)

실행: cd blog-automation && python -m pytest tests/test_policy_features.py -v
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ──────────────────────────────────────────────────────────────────────────────
# A2 — 제목 정책 (title_policy)
# ──────────────────────────────────────────────────────────────────────────────

def test_check_title_detects_clickbait():
    from title_policy import check_title
    assert check_title("충격! 이것만 알면 대박")
    assert "충격" in check_title("충격 고백")


def test_check_title_clean_returns_empty():
    from title_policy import check_title
    assert check_title("부산 1박2일 혼자 여행 코스 정리") == []


def test_sanitize_title_removes_only_violating_terms():
    from title_policy import sanitize_title, check_title
    out = sanitize_title("충격! 부산 여행 실제 비용 공개합니다")
    assert "충격" not in out
    assert "부산 여행" in out
    assert check_title(out) == []


def test_sanitize_title_keeps_original_when_too_short():
    """제거 후 제목이 무의미해지면 원본 유지 — 빈 제목 발행 방지."""
    from title_policy import sanitize_title
    assert sanitize_title("헐 대박") == "헐 대박"


def test_title_escalation_note_mentions_terms():
    from title_policy import title_escalation_note
    note = title_escalation_note(["충격", "대박"])
    assert "제목 재작성 요청" in note and "충격" in note
    assert title_escalation_note([]) == ""


def test_audit_uses_same_clickbait_source_as_generator():
    """감사(사후)와 생성(사전)이 같은 기준을 쓰는지 — 기준 어긋남 방지."""
    import adsense_audit as aa
    from title_policy import CLICKBAIT_TERMS
    assert aa._CLICKBAIT is CLICKBAIT_TERMS


# ──────────────────────────────────────────────────────────────────────────────
# A1 — 글자수 미달 글 draft 전환
# ──────────────────────────────────────────────────────────────────────────────

def _short_post():
    return {"id": "p1", "title": "짧은 글", "url": "http://x",
            "content": "<p>내용</p><img src='a.jpg' alt='x'>", "labels": []}


def test_draft_short_reverts_when_enabled():
    import adsense_audit as aa
    list_resp = MagicMock(status_code=200)
    list_resp.json.return_value = {"items": [_short_post()]}

    with patch("blogger_uploader._get_access_token", return_value="tok"), \
         patch("requests.get", return_value=list_resp), \
         patch("requests.patch", return_value=MagicMock(status_code=200)), \
         patch("requests.post", return_value=MagicMock(status_code=200)) as mock_post, \
         patch("time.sleep"):
        result = aa.run_audit({"id": "blog2", "name": "T", "blog_id": "123"},
                              dry_run=False, draft_short=True)

    assert result["drafted"] == 1
    assert any("/revert" in str(c) for c in mock_post.call_args_list)


def test_draft_short_disabled_by_default():
    """기본 실행(주간 자동 포함)은 draft 전환하지 않음 — 의도치 않은 비공개 방지."""
    import adsense_audit as aa
    list_resp = MagicMock(status_code=200)
    list_resp.json.return_value = {"items": [_short_post()]}

    with patch("blogger_uploader._get_access_token", return_value="tok"), \
         patch("requests.get", return_value=list_resp), \
         patch("requests.patch", return_value=MagicMock(status_code=200)), \
         patch("requests.post") as mock_post, \
         patch("time.sleep"):
        result = aa.run_audit({"id": "blog2", "name": "T", "blog_id": "123"}, dry_run=False)

    assert result.get("drafted", 0) == 0
    assert not mock_post.called


def test_draft_short_dry_run_does_not_call_api():
    import adsense_audit as aa
    list_resp = MagicMock(status_code=200)
    list_resp.json.return_value = {"items": [_short_post()]}

    with patch("blogger_uploader._get_access_token", return_value="tok"), \
         patch("requests.get", return_value=list_resp), \
         patch("requests.post") as mock_post, \
         patch("time.sleep"):
        result = aa.run_audit({"id": "blog2", "name": "T", "blog_id": "123"},
                              dry_run=True, draft_short=True)

    assert result["drafted"] == 1      # 미리보기 집계는 됨
    assert not mock_post.called        # 실제 변경은 없음


# ──────────────────────────────────────────────────────────────────────────────
# A3 — blog2 구주제 분류
# ──────────────────────────────────────────────────────────────────────────────

def test_blog2_keeps_sports_content():
    """blog2는 스포츠가 현재 주제 — blog1 기준으로는 보관 대상이 되던 문제."""
    from migrate_offtopic import classify
    assert classify("KBO 야구 직관 준비물 정리", ["스포츠"], "blog2") == "keep"
    assert classify("손흥민 EPL 경기 결과 분석", [], "blog2") == "keep"


def test_blog1_does_not_keep_sports():
    from migrate_offtopic import classify
    assert classify("KBO 야구 직관 준비물 정리", ["스포츠"], "blog1") != "keep"


def test_blog2_still_migrates_finance_and_archives_it():
    from migrate_offtopic import classify
    assert classify("ETF 투자 수수료 비교", ["금융"], "blog2") == "migrate_blog3"
    assert classify("챗GPT 코딩 활용법", ["IT"], "blog2") == "archive"


def test_blog2_keeps_travel_and_drama():
    from migrate_offtopic import classify
    assert classify("제주 여행 맛집 추천", [], "blog2") == "keep"
    assert classify("넷플릭스 드라마 결말 리뷰", [], "blog2") == "keep"


# ──────────────────────────────────────────────────────────────────────────────
# A4 — 저자 박스 (E-E-A-T)
# ──────────────────────────────────────────────────────────────────────────────

def test_author_box_rendered_with_profile():
    import blogger_uploader as bu
    with patch("config.get_author_profile", return_value={"name": "마린파파", "bio": "여행을 조사합니다"}):
        html = bu._author_box({"id": "blog2", "topics": ["국내여행"]})
    assert "마린파파" in html and "여행을 조사합니다" in html


def test_author_box_falls_back_to_topics_when_no_bio():
    import blogger_uploader as bu
    with patch("config.get_author_profile", return_value={"name": "마린파파", "bio": ""}):
        html = bu._author_box({"id": "blog2", "topics": ["국내여행", "스포츠"]})
    assert "국내여행" in html and "스포츠" in html


def test_author_box_empty_without_name():
    """필명이 없으면 아무것도 넣지 않음 — 가짜 저자 정보 생성 방지."""
    import blogger_uploader as bu
    with patch("config.get_author_profile", return_value={}):
        assert bu._author_box({"id": "blog1"}) == ""


def test_author_box_escapes_html():
    import blogger_uploader as bu
    with patch("config.get_author_profile", return_value={"name": "<script>x</script>", "bio": "a & b"}):
        html = bu._author_box(None)
    assert "<script>" not in html
    assert "&amp;" in html


def test_full_content_includes_author_box():
    import blogger_uploader as bu
    with patch("config.get_author_profile", return_value={"name": "마린파파", "bio": "소개"}):
        html = bu._build_full_content(
            {"title": "제목", "content": "<p>본문</p><h2>섹션</h2>", "labels": ["여행"]},
            {"id": "blog1"},
        )
    assert "글쓴이 · 마린파파" in html
