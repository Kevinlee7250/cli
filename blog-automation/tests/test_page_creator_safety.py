"""필수 페이지 생성이 사람이 써 둔 페이지를 덮어쓰지 않는지 검사합니다.

`_create_or_update_page`는 같은 제목이 있으면 PUT으로 갈아 끼웁니다.
2026-09-19 기준 blog1에는 이미 면책 조항이 있었고, 그 내용이 무엇인지
이쪽은 알 방법이 없습니다. 자동 생성본으로 덮으면 되돌릴 수 없습니다.
"""
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import page_creator as pc  # noqa: E402

_CFG = {"id": "blog1", "name": "HOGU What?", "url": "https://www.hoguwhat.com",
        "blog_id": "b1"}


@pytest.fixture
def wired(monkeypatch):
    written = []

    def _setup(pages):
        monkeypatch.setattr(pc, "_get_access_token", lambda cfg=None: "tok")
        monkeypatch.setattr(pc, "_get_blog_id", lambda cfg=None: "b1")
        monkeypatch.setattr(pc, "_list_existing_pages", lambda tok, bid: pages)

        def fake_write(token, blog_id, title, content, existing):
            written.append(title)
            return {"url": f"https://b/{title}"}
        monkeypatch.setattr(pc, "_create_or_update_page", fake_write)
        return written
    return _setup


def test_existing_pages_are_not_touched(wired):
    written = wired([{"title": "개인정보처리방침", "url": "u1"},
                     {"title": "블로그 소개", "url": "u2"},
                     {"title": "면책 조항", "url": "u3"}])
    pc.create_required_pages(_CFG)
    assert written == [], f"이미 있는 페이지를 덮어썼습니다: {written}"


def test_only_the_missing_page_is_created(wired):
    written = wired([{"title": "개인정보처리방침", "url": "u1"},
                     {"title": "블로그 소개", "url": "u2"}])
    r = pc.create_required_pages(_CFG)
    assert written == ["면책 조항"]
    assert r["privacy_policy"] == "u1"      # 건너뛴 것도 기존 URL을 돌려줍니다
    assert r["about"] == "u2"
    assert r["disclaimer"]


def test_title_variants_count_as_existing(wired):
    """사람이 '면책조항'(붙여쓰기)으로 만들었어도 있는 것으로 봅니다."""
    written = wired([{"title": "개인정보 처리방침", "url": "u1"},
                     {"title": "About", "url": "u2"},
                     {"title": "면책조항", "url": "u3"}])
    pc.create_required_pages(_CFG)
    assert written == []


def test_overwrite_is_opt_in(wired):
    written = wired([{"title": "면책 조항", "url": "u3"}])
    pc.create_required_pages(_CFG, only_missing=False)
    assert "면책 조항" in written


def test_dry_run_writes_nothing(wired):
    written = wired([])
    pc.create_required_pages(_CFG, dry_run=True)
    assert written == []


def test_token_failure_does_not_write(wired, monkeypatch):
    written = wired([])
    monkeypatch.setattr(pc, "_get_access_token", lambda cfg=None: None)
    r = pc.create_required_pages(_CFG)
    assert written == [] and all(v is None for v in r.values())


# ── 면책 조항 내용 ────────────────────────────────────────────────────────

def test_finance_disclaimer_covers_investment_risk():
    """금융 블로그(YMYL)는 투자 권유가 아님을 분명히 해야 합니다."""
    html = pc.build_disclaimer_html("https://x.com", "금융NEWS", "finance")
    assert "투자 권유" in html
    assert "원금 손실" in html
    assert "세무" in html


def test_lifestyle_disclaimer_covers_changing_info():
    html = pc.build_disclaimer_html("https://x.com", "여행 블로그", "lifestyle")
    assert "공식 안내" in html
    assert "의학적 조언이 아" in html


def test_every_disclaimer_states_how_posts_are_written():
    """'지어낸 경험을 쓰지 않는다'는 거절 사유에 대한 직접적인 답입니다."""
    for theme in ("finance", "lifestyle", "general"):
        html = pc.build_disclaimer_html("https://x.com", "블로그", theme)
        assert "직접 경험하지 않은 일을 경험한 것처럼 쓰지 않으며" in html
        assert "AdSense" in html
        assert "저작권" in html


def test_disclaimer_is_detected_as_required_page():
    """만든 페이지를 확인 스크립트가 알아보는지 — 두 곳이 어긋나면 안 됩니다."""
    from required_pages_check import REQUIRED, _find
    label, aliases = REQUIRED["disclaimer"]
    assert _find([{"title": "면책 조항", "url": "u"}], aliases)
    assert _find([{"title": "Disclaimer", "url": "u"}], aliases)
