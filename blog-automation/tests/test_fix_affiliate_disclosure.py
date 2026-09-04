"""발행된 글의 옛 고지 문구 교체.

왜
──
문구를 표준으로 바꾸고 읽히게 키운 것은 앞으로 쓰는 글에만 적용됩니다.
이미 나간 글에는 옛 문구("이 포스트는 … 제공받을 수 있습니다")가 10px
회색으로 남아 있습니다.

여기서 지키는 것
────────────────
  1. 옛 문구를 찾아 현재 기준으로 바꾼다 (표현이 조금 달라도 잡는다)
  2. 링크는 건드리지 않는다
  3. 손대면 안 되는 글은 손대지 않는다 — 쿠팡 링크가 없는 글, 이미 최신인
     글, 그리고 링크만 있고 고지가 없는 글(어디에 넣을지는 사람이 정해야
     하므로 지어내 붙이지 않는다)
  4. 교체 결과가 coupang_affiliate가 새로 만드는 것과 같은 모양이다 —
     다르면 고친 글과 새 글의 고지가 갈라집니다
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import coupang_affiliate as ca  # noqa: E402
import fix_affiliate_disclosure as fx  # noqa: E402

_OLD = (
    '<p style="font-size:10px;color:#bbb;margin:14px 0 0;line-height:1.5">'
    '이 포스트는 쿠팡 파트너스 활동의 일환으로, '
    '이에 따른 일정액의 수수료를 제공받을 수 있습니다.</p>'
)
_LINK = ('<a href="https://link.coupang.com/a/TEST" rel="nofollow sponsored '
         'noopener">🛒 쿠팡</a>')


def _post(*parts):
    return "<p>본문</p>" + "".join(parts)


# ── 교체 결과가 새 글과 같은 모양인가 ────────────────────────────────────────

def test_replacement_matches_what_new_posts_get(monkeypatch):
    """고친 글과 새 글의 고지가 갈라지면 안 됩니다."""
    monkeypatch.setattr(ca, "load_affiliate_links", lambda: [
        {"name": "쿠팡", "url": "https://link.coupang.com/a/T",
         "keywords": [], "blogs": [], "active": True}])
    fresh = ca.inject_affiliate_section("<p>본문</p>", "키워드", {"id": "blog1"})
    assert fx.DISCLOSURE_HTML in fresh, (
        "교체용 HTML이 coupang_affiliate가 만드는 것과 다릅니다"
    )


def test_replacement_uses_the_standard_wording():
    assert ca.DISCLOSURE in fx.DISCLOSURE_HTML


# ── 고쳐야 하는 글 ──────────────────────────────────────────────────────────

def test_old_notice_is_detected_and_replaced():
    html = _post(_LINK, _OLD)
    assert fx.needs_fix(html)
    out = fx.replace_disclosure(html)
    assert ca.DISCLOSURE in out
    assert "제공받을 수 있습니다" not in out
    assert "#bbb" not in out


def test_link_is_left_alone():
    out = fx.replace_disclosure(_post(_LINK, _OLD))
    assert "https://link.coupang.com/a/TEST" in out
    assert 'rel="nofollow sponsored noopener"' in out


def test_wording_variants_are_caught():
    """표현이 조금 달라도 잡아야 합니다 — 옛 글마다 문구가 미묘하게 다릅니다."""
    for body in (
        "이 포스트는 쿠팡 파트너스 활동의 일환으로, 수수료를 제공받습니다.",
        "본 포스팅은 쿠팡파트너스 활동을 통해 일정액의 수수료를 지급받습니다.",
        "이 글은 쿠팡 파트너스 활동의 일부로서 수수료를 받을 수 있습니다.",
    ):
        html = _post(_LINK, f'<p style="font-size:10px">{body}</p>')
        assert fx.needs_fix(html), f"못 잡음: {body}"
        assert ca.DISCLOSURE in fx.replace_disclosure(html)


# ── 손대면 안 되는 글 ───────────────────────────────────────────────────────

def test_post_without_a_coupang_link_is_untouched():
    html = _post('<p>이 글에는 광고가 없습니다.</p>')
    assert not fx.needs_fix(html)
    assert fx.replace_disclosure(html) == html


def test_already_current_post_is_untouched():
    html = _post(_LINK, fx.DISCLOSURE_HTML)
    assert not fx.needs_fix(html), "이미 최신인 글을 또 고치려 합니다"


def test_link_without_any_notice_is_not_invented():
    """어디에 넣을지는 사람이 정해야 합니다 — 임의로 붙이면 엉뚱한 자리에 갑니다."""
    html = _post(_LINK)
    assert not fx.needs_fix(html)
    assert fx.replace_disclosure(html) == html


def test_replacement_does_not_eat_neighbouring_paragraphs():
    """<p>를 욕심내 매칭하면 앞뒤 문단까지 삼킵니다."""
    html = _post("<p>앞 문단입니다.</p>", _LINK, _OLD, "<p>뒤 문단입니다.</p>")
    out = fx.replace_disclosure(html)
    assert "앞 문단입니다." in out
    assert "뒤 문단입니다." in out
    assert out.count("<p") == html.count("<p")
