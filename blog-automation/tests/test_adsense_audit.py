"""AdSense 승인 감사 (adsense_audit.py) 테스트.

실행: cd blog-automation && python -m pytest tests/test_adsense_audit.py -v
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _long_content(n_chars: int = 3000) -> str:
    return "<p>" + ("본문 내용입니다. " * (n_chars // 10)) + "</p>"


# ──────────────────────────────────────────────────────────────────────────────
# _plain_len / _is_ymyl
# ──────────────────────────────────────────────────────────────────────────────

def test_plain_len_strips_tags_and_scripts():
    from adsense_audit import _plain_len
    html = "<p>안녕 <script>alert(1)</script>하세요</p>"
    assert _plain_len(html) == len("안녕하세요")


def test_is_ymyl_detects_finance_keyword():
    from adsense_audit import _is_ymyl
    assert _is_ymyl("ETF 월배당 포트폴리오", []) is True


def test_is_ymyl_false_for_unrelated_topic():
    from adsense_audit import _is_ymyl
    assert _is_ymyl("부산 1박2일 여행 코스", ["여행"]) is False


# ──────────────────────────────────────────────────────────────────────────────
# audit_post — 8개 검사 항목 통합 검증
# ──────────────────────────────────────────────────────────────────────────────

def test_audit_post_flags_short_content():
    from adsense_audit import audit_post
    post = {"title": "짧은 글", "content": "<p>내용</p>", "labels": []}
    fixes, issues, _ = audit_post(post)
    assert any("글자수 부족" in i for i in issues)


def test_audit_post_flags_missing_faq_and_sources():
    from adsense_audit import audit_post
    post = {"title": "일반 글", "content": _long_content() + '<img src="a.jpg" alt="x">', "labels": []}
    fixes, issues, _ = audit_post(post)
    assert any("FAQ" in i for i in issues)
    assert any("출처" in i for i in issues)


def test_audit_post_flags_clickbait_title():
    from adsense_audit import audit_post
    post = {"title": "충격 대박 소식", "content": _long_content() + '<img src="a.jpg" alt="x">', "labels": []}
    _, issues, _ = audit_post(post)
    assert any("과장 표현" in i for i in issues)


def test_audit_post_inserts_thumbnail_when_no_image():
    from adsense_audit import audit_post
    fake_thumb = {"url": "data:image/svg+xml;base64,xx", "alt_text": "테스트 관련 이미지"}
    with patch("image_fetcher.generate_title_thumbnail", return_value=fake_thumb), \
         patch("image_fetcher._make_img_html", return_value='<img src="thumb.jpg" alt="테스트">'):
        post = {"title": "테스트", "content": _long_content(), "labels": []}
        fixes, issues, new_content = audit_post(post)
    assert any("썸네일" in f for f in fixes)
    assert "<img" in new_content


def test_audit_post_fills_empty_alt_when_image_exists():
    from adsense_audit import audit_post
    post = {"title": "테스트", "content": _long_content() + '<img src="a.jpg">', "labels": []}
    fixes, issues, new_content = audit_post(post)
    assert any("alt 텍스트" in f for f in fixes)
    assert 'alt="' in new_content


def test_audit_post_dedupes_duplicate_toc():
    from adsense_audit import audit_post
    toc = '<p>목차</p><ul><li>섹션1</li></ul>'
    post = {"title": "가이드", "content": toc + toc + _long_content() + '<img src="a.jpg" alt="x">', "labels": []}
    fixes, issues, new_content = audit_post(post)
    assert any("중복 목차 제거" in f for f in fixes)
    from fix_duplicate_toc import count_tocs
    assert count_tocs(new_content) == 1


def test_audit_post_adds_disclaimer_for_ymyl_without_one():
    from adsense_audit import audit_post
    post = {
        "title": "ETF 투자 전략",
        "content": _long_content() + '<img src="a.jpg" alt="x">',
        "labels": ["투자", "ETF"],
    }
    fixes, issues, new_content = audit_post(post)
    assert any("면책 문구" in f for f in fixes)
    assert "면책" in new_content or "전문가와 상담" in new_content


def test_audit_post_skips_disclaimer_when_already_present():
    from adsense_audit import audit_post
    content = _long_content() + '<img src="a.jpg" alt="x"><p>이 글은 참고용이며 투자 판단은 본인 책임입니다.</p>'
    post = {"title": "ETF 투자 전략", "content": content, "labels": ["투자"]}
    fixes, _, _ = audit_post(post)
    assert not any("면책 문구" in f for f in fixes)


def test_audit_post_clean_content_has_no_fixes_or_issues():
    from adsense_audit import audit_post
    content = (
        _long_content(4000) +
        '<img src="a.jpg" alt="설명 이미지">'
        '<h2>자주 묻는 질문</h2><h3>Q. 질문?</h3><p>답변</p>'
        '<h2>참고자료</h2><p>출처: 예시</p>'
    )
    post = {"title": "일반 정보 글", "content": content, "labels": []}
    fixes, issues, _ = audit_post(post)
    assert issues == []


# ──────────────────────────────────────────────────────────────────────────────
# run_audit — Blogger API 연동 (mock)
# ──────────────────────────────────────────────────────────────────────────────

def test_run_audit_dry_run_does_not_call_patch():
    from adsense_audit import run_audit
    cfg = {"id": "blog1", "name": "테스트블로그", "blog_id": "123"}

    list_resp = MagicMock(status_code=200)
    list_resp.json.return_value = {
        "items": [{"id": "p1", "title": "짧은 글", "content": "<p>내용</p>", "labels": [], "url": "http://x"}],
    }

    with patch("blogger_uploader._get_access_token", return_value="tok"), \
         patch("requests.get", return_value=list_resp) as mock_get, \
         patch("requests.patch") as mock_patch:
        result = run_audit(cfg, dry_run=True)

    assert mock_get.called
    assert not mock_patch.called
    assert result["scanned"] == 1


def test_run_audit_live_run_calls_patch_when_fixes_exist():
    from adsense_audit import run_audit
    cfg = {"id": "blog1", "name": "테스트블로그", "blog_id": "123"}

    list_resp = MagicMock(status_code=200)
    list_resp.json.return_value = {
        "items": [{
            "id": "p1", "title": "테스트", "url": "http://x", "labels": [],
            "content": "<p>목차</p><ul><li>a</li></ul><p>목차</p><ul><li>a</li></ul>" + _long_content(),
        }],
    }
    patch_resp = MagicMock(status_code=200)

    with patch("blogger_uploader._get_access_token", return_value="tok"), \
         patch("requests.get", return_value=list_resp), \
         patch("requests.patch", return_value=patch_resp) as mock_patch, \
         patch("time.sleep"):
        result = run_audit(cfg, dry_run=False)

    assert mock_patch.called
    assert result["fixed"] == 1


def test_run_audit_missing_token_skips_gracefully():
    from adsense_audit import run_audit
    cfg = {"id": "blog1", "name": "테스트", "blog_id": ""}
    with patch("blogger_uploader._get_access_token", return_value=None):
        result = run_audit(cfg, dry_run=True)
    assert result["scanned"] == 0
