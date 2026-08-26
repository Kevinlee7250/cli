"""게시글 이미지 검증·수정 테스트 (2026-08-21).

발행된 글의 이미지를 교체·삭제하는 도구입니다. 오판 하나가 멀쩡한
이미지를 지우므로, "판단이 안 서면 유지" 원칙을 테스트로 고정합니다.

실행: cd blog-automation && python -m pytest tests/test_image_audit.py -v
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import image_audit  # noqa: E402

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
    # 파일명이 읽히는 단어여야 "무관"을 말할 수 있습니다. 숫자·해시 파일명은
    # 정보가 없다는 뜻이라 1.0(유지)이 됩니다 — test_hashed_cdn_url_… 참고
    assert relevance_score({"url": "https://a/seoul-subway-map.jpg", "alt": ""},
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
    content = "<p>" + "가" * 2000 + "</p>" + FIG.format(url="https://a/seoul-subway-map.jpg", alt="")
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
    original = FIG.format(url="https://a/seoul-subway-map.jpg", alt="")
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


# ── data URI 썸네일 회귀 (2026-08-21 첫 실행에서 227건 오판) ──────────────────
# 이 시스템의 썸네일은 <img src="data:image/svg+xml;base64,..."> 로 본문에
# 박혀 있습니다. 파일이 아니라 본문 자체라 죽을 수가 없는데, 초기 구현이
# startswith("http")만 봐서 전부 broken으로 잡았습니다.

_DATA_SVG = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0i"


def test_data_uri_image_is_alive():
    alive, why = image_audit.check_alive(_DATA_SVG)
    assert alive is True
    assert why == ""


def test_non_image_data_uri_is_broken():
    alive, _ = image_audit.check_alive("data:text/html;base64,PGh0bWw+")
    assert alive is False


def test_data_uri_is_always_relevant():
    assert image_audit.relevance_score({"url": _DATA_SVG, "alt": ""}, "전혀 다른 제목") == 1.0


def test_data_uri_terms_do_not_include_base64_blob():
    terms = image_audit._image_terms({"url": _DATA_SVG, "alt": "썸네일"})
    assert "PHN2ZyB4bWxucz0i" not in terms
    assert terms == "썸네일"


def test_insufficient_is_not_fixed_by_default():
    post = {"content": "<p>본문</p>", "title": "제목"}
    audit = {"issues": [{"type": "insufficient", "detail": "이미지 2장 (권장 3장)"}]}
    _, actions = image_audit.fix_post(post, audit)
    assert actions == []


def test_insufficient_is_fixed_when_opted_in(monkeypatch):
    monkeypatch.setattr(image_audit, "attach_image",
                        lambda c, t, k="": (c + "<img>", True, "테스트 첨부"))
    post = {"content": "<p>본문</p>", "title": "제목"}
    audit = {"issues": [{"type": "insufficient", "detail": ""}]}
    _, actions = image_audit.fix_post(
        post, audit, image_audit.DEFAULT_FIX_KINDS + ("insufficient",))
    assert any("첨부" in a for a in actions)


# ── 정보 없는 CDN 해시 URL (2026-08-21 suspect 15건이 전부 이 경우) ──────────
# 점수 0.0은 "무관"이 아니라 "대조할 정보 없음"입니다. --ai를 돌려도 Claude가
# 보는 건 같은 해시뿐이라, 근거 없이 무관으로 확정되면 안 됩니다.

def test_hashed_cdn_url_without_alt_is_not_suspect():
    img = {"url": "https://pixabay.com/get/ga5f45e80d7217b99888f565ea03eb3ca7c1f7b11.jpg",
           "alt": ""}
    assert image_audit.relevance_score(img, "카드사 여행 혜택 비교") == 1.0


def test_alt_text_still_drives_the_score():
    img = {"url": "https://pixabay.com/get/ga5f45e80d7217b99888f565ea03eb3ca7c1f7b11.jpg",
           "alt": "고양이 사진"}
    assert image_audit.relevance_score(img, "카드사 여행 혜택 비교") < 1.0


def test_readable_filename_still_drives_the_score():
    img = {"url": "https://example.com/photos/travel-card-benefits.jpg", "alt": ""}
    assert image_audit.relevance_score(img, "카드사 travel 혜택 비교") > 0.0


def test_is_informative_rejects_pure_hash():
    assert image_audit._is_informative("ga5f45e80d7217b99888f565ea03eb3ca") is False
    assert image_audit._is_informative("여행 카드") is True


# ── 한국어 조사·복합어 대조 (2026-08-21 suspect 오탐) ────────────────────────
# 대조 근거를 화면에 찍어 보고서야 드러난 문제입니다. _core_terms가 "비교로"의
# 조사를 못 떼고, "카드사"가 alt의 "카드"와 매칭되지 않아 관련 있는 이미지가
# 0.0을 받았습니다.

_CARD_TITLE = "카드사 여행 혜택 비교로 항공권·호캉스 카드 고르는 법"


def test_korean_particle_does_not_block_match():
    assert image_audit._term_hits("비교로", "카드 비교 정리") is True


def test_compound_noun_matches_its_stem():
    assert image_audit._term_hits("카드사", "신용 카드 이미지") is True


def test_stem_must_stay_at_least_two_chars():
    # "여행"에서 한 자를 떼면 "여" 하나만 남으므로 그런 매칭은 하지 않습니다
    assert image_audit._term_hits("여행", "여수 밤바다") is False


def test_related_korean_alt_escapes_suspect_threshold():
    img = {"url": "https://pixabay.com/get/ga5f45e80d_1280.jpg",
           "alt": "해외 결제 시 발생하는 카드 수수료 구조를 보여주는 영수증과 카드"}
    assert image_audit.relevance_score(img, _CARD_TITLE) >= image_audit.RELEVANCE_SUSPECT


def test_english_alt_against_korean_title_stays_suspect():
    """언어가 다르면 부분 문자열로는 판단할 수 없습니다 — AI 판정 대상입니다."""
    img = {"url": "https://pixabay.com/get/gb029af834b_1280.jpg",
           "alt": "checklist document signing"}
    assert image_audit.relevance_score(img, _CARD_TITLE) < image_audit.RELEVANCE_SUSPECT


# ── 블로그 선택 (대시보드에서 전체/개별을 고를 수 있게 된 뒤) ────────────────

def _blog(bid, name):
    return {"id": bid, "name": name, "blog_id": "1", "url": ""}


def test_unknown_blog_filter_raises_instead_of_auditing_everything():
    """폴백으로 전체를 도는 건 --apply와 만나면 사고입니다."""
    import pytest
    blogs = [_blog("blog1", "A"), _blog("blog2", "B")]
    with patch("config.get_blog_configs", return_value=blogs), \
         patch("blogger_uploader._get_access_token", return_value="t"), \
         patch("fix_unlicensed_images._iter_posts", return_value=[]):
        with pytest.raises(ValueError) as e:
            image_audit.run(blog_filter="blog9")
    assert "blog9" in str(e.value) and "blog1" in str(e.value)


def test_blog_filter_limits_scope_and_is_recorded():
    blogs = [_blog("blog1", "A"), _blog("blog2", "B")]
    with patch("config.get_blog_configs", return_value=blogs), \
         patch("blogger_uploader._get_access_token", return_value="t"), \
         patch("fix_unlicensed_images._iter_posts", return_value=[]), \
         patch("image_audit._save"):
        report = image_audit.run(blog_filter="blog2")
    assert report["blogFilter"] == "blog2"
    assert report["blogsAudited"] == ["B"]


def test_empty_filter_means_all_blogs():
    blogs = [_blog("blog1", "A"), _blog("blog2", "B")]
    with patch("config.get_blog_configs", return_value=blogs), \
         patch("blogger_uploader._get_access_token", return_value="t"), \
         patch("fix_unlicensed_images._iter_posts", return_value=[]), \
         patch("image_audit._save"):
        report = image_audit.run(blog_filter="")
    assert report["blogFilter"] == "" and report["blogsAudited"] == ["A", "B"]


# ── limit = "손댈 글 수" (스캔 상한 아님) ────────────────────────────────────
# 예전 limit은 스캔 상한이었습니다. 목록은 최신 글부터 오고 attach_insufficient는
# 한 번에 한 장만 붙이므로, --limit 20을 반복하면 맨 앞 20편만 계속 채워지고
# 뒤쪽 글에는 영원히 닿지 못했습니다. 그래서 "고칠 대상 글" 기준으로 셉니다.

def _post(pid, content, title="제목"):
    return {"id": str(pid), "title": title, "content": content, "url": ""}


_NO_IMG = "<p>" + ("가" * 300) + "</p>"          # 이미지 0장 → missing
_OK = ('<p>' + ('가' * 100) + '</p>'
       '<img src="https://a/x.jpg" alt="제목 관련 사진 설명"/>')


def _run(posts, **kw):
    with patch("config.get_blog_configs", return_value=[_blog("blog1", "A")]), \
         patch("blogger_uploader._get_access_token", return_value="t"), \
         patch("fix_unlicensed_images._iter_posts", return_value=posts), \
         patch("image_audit.check_alive", return_value=(True, "")), \
         patch("image_audit._save"):
        return image_audit.run(**kw)


def test_limit_counts_targets_not_scanned_posts():
    """앞쪽에 멀쩡한 글이 아무리 많아도 상한을 소모하지 않아야 합니다."""
    posts = [_post(i, _OK) for i in range(30)] + [_post(90 + i, _NO_IMG) for i in range(5)]
    report = _run(posts, limit=2)
    assert report["targeted"] == 2
    # 멀쩡한 글 30편을 지나쳐 대상 2편을 찾을 때까지 스캔했습니다
    assert report["scanned"] > 2
    assert report["stoppedAtLimit"] is True


def test_limit_zero_processes_every_target():
    posts = [_post(i, _NO_IMG) for i in range(5)]
    report = _run(posts, limit=0)
    assert report["targeted"] == 5 and report["stoppedAtLimit"] is False


def test_scan_limit_still_caps_the_scan():
    posts = [_post(i, _NO_IMG) for i in range(10)]
    report = _run(posts, scan_limit=3)
    assert report["scanned"] == 3


def test_unfixable_issue_does_not_consume_the_limit():
    """--ai 없이 suspect만 있는 글은 손댈 수 없으니 예산을 쓰면 안 됩니다."""
    suspect = ('<p>' + ('가' * 100) + '</p>'
               '<img src="https://a/x.jpg" alt="unrelated english words here"/>')
    posts = [_post(1, suspect), _post(2, _NO_IMG)]
    report = _run(posts, limit=1)
    assert report["issueCounts"].get("suspect")      # 문제로는 잡혔고
    assert report["targeted"] == 1                   # 대상은 missing 글 하나뿐


# ── alt·캡션 설명 수정 ───────────────────────────────────────────────────────
# 발행된 글에 alt 없는 <img>와 "사진" 한 단어짜리 캡션이 남아 있었습니다.
# 화면 낭독기에도 검색엔진에도 쓸모가 없고, 이미지를 건드리지 않고 고칠 수
# 있는 문제라 검사·수정 대상에 넣었습니다.

_FIG_SRC = ('<figure><img src="{url}"{alt}/>'
            '<figcaption>{cap}<br>이미지 출처: Pixabay</figcaption></figure>')


def test_missing_alt_is_flagged():
    assert "없음" in image_audit.alt_problem({"url": "https://a/x.jpg", "alt": ""}, "제목")


def test_too_short_alt_is_flagged():
    assert image_audit.alt_problem({"url": "https://a/x.jpg", "alt": "사진"}, "제목")


def test_descriptive_alt_is_left_alone():
    img = {"url": "https://a/x.jpg", "alt": "K-POP 컴백 무대 사진"}
    assert image_audit.alt_problem(img, "2026 K-POP 컴백 정보 확인법") == ""


def test_compose_alt_keeps_hyphenated_words():
    """부제 자르기가 'K-POP'을 'K'로 만들면 안 됩니다."""
    assert "K-POP" in image_audit.compose_alt("2026 K-POP 컴백 정보 확인법")


def test_compose_alt_drops_subtitle_after_dash():
    alt = image_audit.compose_alt("당뇨 초기 증상 7가지 — 2026년 완벽 정리")
    assert "2026년 완벽 정리" not in alt and "당뇨" in alt


def test_alt_is_added_when_attribute_absent():
    """_replace_image는 alt 속성이 있을 때만 씁니다 — 없으면 넣어야 합니다."""
    content = _FIG_SRC.format(url="https://a/x.jpg", alt="", cap="사진")
    out, done = image_audit.fix_alt(content, "https://a/x.jpg", "당뇨 초기 증상 자가진단")
    assert done and 'alt="당뇨 초기 증상 자가진단 관련 이미지"' in out


def test_caption_description_changes_but_source_is_kept():
    content = _FIG_SRC.format(url="https://a/x.jpg", alt=' alt="사진"', cap="사진")
    out, _ = image_audit.fix_alt(content, "https://a/x.jpg", "당뇨 초기 증상")
    assert "이미지 출처: Pixabay" in out          # 출처는 보존
    assert "<figcaption>당뇨 초기 증상 관련 이미지<br>" in out


def test_other_images_are_untouched():
    content = (_FIG_SRC.format(url="https://a/x.jpg", alt="", cap="사진")
               + _FIG_SRC.format(url="https://a/keep.jpg", alt=' alt="그대로"', cap="그대로"))
    out, _ = image_audit.fix_alt(content, "https://a/x.jpg", "제목입니다")
    assert 'alt="그대로"' in out and "<figcaption>그대로<br>" in out


def test_weak_alt_is_audited_and_fixed():
    content = "<p>" + "가" * 1500 + "</p>" + _FIG_SRC.format(
        url="https://a/diabetes-check.jpg", alt="", cap="사진")
    with patch("requests.head", return_value=_resp()):
        a = image_audit.audit_post({"title": "당뇨 초기 증상 자가진단", "content": content})
    assert any(i["type"] == "weak_alt" for i in a["issues"])

    post = {"title": "당뇨 초기 증상 자가진단", "content": content}
    out, actions = image_audit.fix_post(post, a)
    assert any("alt 재작성" in x for x in actions)


def test_alt_fix_never_removes_the_image():
    content = _FIG_SRC.format(url="https://a/x.jpg", alt="", cap="사진")
    out, _ = image_audit.fix_alt(content, "https://a/x.jpg", "제목입니다")
    assert 'src="https://a/x.jpg"' in out
