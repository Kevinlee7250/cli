"""게시글 이미지 검증·수정 테스트 (2026-08-21).

발행된 글의 이미지를 교체·삭제하는 도구입니다. 오판 하나가 멀쩡한
이미지를 지우므로, "판단이 안 서면 유지" 원칙을 테스트로 고정합니다.

실행: cd blog-automation && python -m pytest tests/test_image_audit.py -v
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

FIG = ('<figure><img src="{url}" alt="{alt}"/>'
       '<figcaption>설명</figcaption></figure>')


def _resp(status=200, ctype="image/jpeg"):
    return MagicMock(status_code=status, headers={"Content-Type": ctype})


# ──────────────────────────────────────────────────────────────────────────────
# 첨부 여부
# ──────────────────────────────────────────────────────────────────────────────

def test_extract_images_reads_url_and_alt():
    from image_audit import extract_images
    imgs = extract_images(FIG.format(url="https://a/1.jpg", alt="골프장"))
    assert imgs == [{"url": "https://a/1.jpg", "alt": "골프장"}]


def test_extract_ignores_img_without_src():
    from image_audit import extract_images
    assert extract_images('<img alt="없음"/>') == []


def test_needed_count_scales_with_length():
    from image_audit import needed_image_count
    assert needed_image_count("가" * 6000) == 2
    assert needed_image_count("가" * 500) == 1        # 짧아도 최소 1장
    assert needed_image_count("") == 0


def test_post_without_images_is_flagged_missing():
    from image_audit import audit_post
    a = audit_post({"title": "글", "content": "<p>" + "가" * 3000 + "</p>"})
    assert [i["type"] for i in a["issues"]] == ["missing"]


def test_post_with_too_few_images_is_flagged():
    from image_audit import audit_post
    content = "<p>" + "가" * 8000 + "</p>" + FIG.format(url="https://a/1.jpg", alt="글")
    with patch("requests.head", return_value=_resp()):
        a = audit_post({"title": "글", "content": content})
    assert any(i["type"] == "insufficient" for i in a["issues"])


# ──────────────────────────────────────────────────────────────────────────────
# 링크 생존 — 판단이 안 서면 유지
# ──────────────────────────────────────────────────────────────────────────────

def test_404_is_broken():
    from image_audit import check_alive
    with patch("requests.head", return_value=_resp(404)):
        alive, why = check_alive("https://a/x.jpg")
    assert alive is False and "404" in why


def test_non_image_content_type_is_broken():
    from image_audit import check_alive
    with patch("requests.head", return_value=_resp(200, "text/html")):
        alive, _ = check_alive("https://a/x.jpg")
    assert alive is False


def test_network_error_keeps_image():
    """일시 오류로 멀쩡한 이미지를 지우면 안 됩니다."""
    import requests as rq
    from image_audit import check_alive
    with patch("requests.head", side_effect=rq.exceptions.Timeout()):
        alive, why = check_alive("https://a/x.jpg")
    assert alive is True and "확인 불가" in why


def test_server_error_keeps_image():
    from image_audit import check_alive
    with patch("requests.head", return_value=_resp(503)):
        alive, _ = check_alive("https://a/x.jpg")
    assert alive is True


def test_head_not_allowed_falls_back_to_get():
    from image_audit import check_alive
    with patch("requests.head", return_value=_resp(405)), \
         patch("requests.get", return_value=_resp(200)) as g:
        alive, _ = check_alive("https://a/x.jpg")
    assert alive is True and g.called


# ──────────────────────────────────────────────────────────────────────────────
# 관련성
# ──────────────────────────────────────────────────────────────────────────────

def test_matching_filename_scores_high():
    from image_audit import relevance_score
    s = relevance_score({"url": "https://a/golf-autumn.jpg", "alt": "골프장 단풍"},
                        "가을 단풍 골프장 추천")
    assert s > 0


def test_unrelated_image_scores_zero():
    from image_audit import relevance_score
    assert relevance_score({"url": "https://a/12345.jpg", "alt": ""},
                           "가을 단풍 골프장 추천") == 0.0


def test_ai_generated_image_is_always_relevant():
    """그 글을 위해 만든 이미지이므로 무관일 수 없습니다."""
    from image_audit import relevance_score
    assert relevance_score({"url": "https://x/ai_generated/a.png"}, "아무 제목") == 1.0
    assert relevance_score({"url": "https://x/a.png", "source": "ai_generated"}, "제목") == 1.0


def test_no_comparable_terms_keeps_image():
    from image_audit import relevance_score
    assert relevance_score({"url": "https://a/x.jpg", "alt": ""}, "") == 1.0


def test_low_relevance_is_suspect_not_irrelevant_without_ai():
    """AI 판정 없이 '무관'으로 확정하면 오삭제가 납니다."""
    from image_audit import audit_post
    content = "<p>" + "가" * 2000 + "</p>" + FIG.format(url="https://a/9999.jpg", alt="")
    with patch("requests.head", return_value=_resp()):
        a = audit_post({"title": "가을 단풍 골프장 추천", "content": content}, use_ai=False)
    types = [i["type"] for i in a["issues"]]
    assert "suspect" in types and "irrelevant" not in types


def test_ai_failure_keeps_image():
    from image_audit import judge_with_ai
    with patch("anthropic.Anthropic", side_effect=RuntimeError("boom")):
        related, reason = judge_with_ai({"url": "https://a/x.jpg"}, "제목", "본문")
    assert related is True


# ──────────────────────────────────────────────────────────────────────────────
# 수정 — 교체 우선, 대체 없을 때만 삭제
# ──────────────────────────────────────────────────────────────────────────────

def test_broken_image_is_replaced_when_alternative_found():
    from image_audit import fix_post
    post = {"title": "골프", "content": FIG.format(url="https://a/dead.jpg", alt="x")}
    audit = {"issues": [{"type": "broken", "url": "https://a/dead.jpg"}]}
    new = {"url": "https://cdn.pixabay.com/new.jpg", "source": "pixabay", "alt_text": "골프"}
    with patch("fix_unlicensed_images._find_safe_replacement", return_value=new):
        content, actions = fix_post(post, audit)
    assert "new.jpg" in content and any("교체" in a for a in actions)


def test_broken_image_is_removed_when_no_alternative():
    from image_audit import fix_post
    post = {"title": "골프", "content": FIG.format(url="https://a/dead.jpg", alt="x")}
    audit = {"issues": [{"type": "broken", "url": "https://a/dead.jpg"}]}
    with patch("fix_unlicensed_images._find_safe_replacement", return_value=None):
        content, actions = fix_post(post, audit)
    assert "dead.jpg" not in content and any("삭제" in a for a in actions)


def test_suspect_is_never_touched():
    """확정 판정 전에는 손대지 않습니다."""
    from image_audit import fix_post
    original = FIG.format(url="https://a/9999.jpg", alt="")
    post = {"title": "골프", "content": original}
    audit = {"issues": [{"type": "suspect", "url": "https://a/9999.jpg"}]}
    content, actions = fix_post(post, audit)
    assert content == original and actions == []


def test_missing_image_gets_attached():
    from image_audit import fix_post
    post = {"title": "골프", "content": "<p>본문</p>"}
    audit = {"issues": [{"type": "missing"}]}
    new = {"url": "https://cdn.pixabay.com/x.jpg", "source": "pixabay", "alt_text": "골프"}
    with patch("fix_unlicensed_images._find_safe_replacement", return_value=new), \
         patch("image_fetcher.inject_images_into_content",
               return_value='<p>본문</p><img src="https://cdn.pixabay.com/x.jpg"/>'):
        content, actions = fix_post(post, audit)
    assert "x.jpg" in content and any("첨부" in a for a in actions)


def test_attach_failure_is_reported_not_silent():
    from image_audit import attach_image
    with patch("fix_unlicensed_images._find_safe_replacement", return_value=None):
        content, ok, why = attach_image("<p>본문</p>", "제목")
    assert ok is False and why and content == "<p>본문</p>"


def test_no_issues_means_no_changes():
    from image_audit import fix_post
    post = {"title": "골프", "content": "<p>본문</p>"}
    content, actions = fix_post(post, {"issues": []})
    assert content == "<p>본문</p>" and actions == []
