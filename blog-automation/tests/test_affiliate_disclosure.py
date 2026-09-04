"""쿠팡 파트너스 고지 문구가 독자에게 실제로 전달되는가.

왜
──
표시광고법상 대가를 받은 추천은 소비자가 "쉽게 인식할 수 있는" 방법으로
알려야 합니다. 문구가 빠지거나 안 읽히면 법적 문제가 됩니다.

이전 상태
─────────
문구는 있었지만 두 가지가 어긋나 있었습니다.

  · 표준 문구와 달랐습니다
    "이 포스트는 … 제공받을 수 있습니다" (임의 완화)
    → "이 포스팅은 … 제공받습니다" (쿠팡 파트너스 표준)
  · font-size 10px · color #bbb 였습니다. 흰 배경에 옅은 회색 10px는
    있어도 읽히지 않아, 표시했다고 보기 어렵습니다.

여기서 지키는 것
────────────────
  1. 문구가 글자 그대로 들어간다
  2. 제휴 링크가 있으면 문구도 반드시 있다 (둘이 갈라지지 않는다)
  3. 읽을 수 있는 크기·색으로 나온다
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import coupang_affiliate as ca  # noqa: E402

_EXPECTED = ("이 포스팅은 쿠팡 파트너스 활동의 일환으로, "
             "이에 따른 일정액의 수수료를 제공받습니다.")

_LINKS = [{"name": "쿠팡", "url": "https://link.coupang.com/a/TEST",
           "keywords": [], "blogs": [], "active": True}]


def _render(monkeypatch, links=None, keyword="추석 선물세트"):
    monkeypatch.setattr(ca, "load_affiliate_links", lambda: links if links is not None else _LINKS)
    return ca.inject_affiliate_section("<p>본문</p>", keyword, {"id": "blog1"})


# ── 문구 자체 ───────────────────────────────────────────────────────────────

def test_disclosure_is_the_standard_wording():
    assert ca.DISCLOSURE == _EXPECTED, (
        "쿠팡 파트너스 표준 문구와 다릅니다 — 임의로 완화하면 안 됩니다"
    )


def test_disclosure_reaches_the_post(monkeypatch):
    out = _render(monkeypatch)
    assert _EXPECTED in out, "발행될 본문에 고지 문구가 없습니다"


# ── 링크와 문구가 갈라지지 않는가 ────────────────────────────────────────────

def test_a_link_never_appears_without_the_disclosure(monkeypatch):
    """링크만 나가고 고지가 빠지는 조합이 있으면 안 됩니다."""
    out = _render(monkeypatch)
    assert "link.coupang.com" in out
    assert _EXPECTED in out


def test_no_links_means_no_section_and_no_stray_notice(monkeypatch):
    """넣을 링크가 없으면 광고도 고지도 없어야 합니다 — 빈 고지는 오해를 줍니다."""
    out = _render(monkeypatch, links=[])
    assert out == "<p>본문</p>"
    assert _EXPECTED not in out


def test_unmatched_keyword_inserts_nothing(monkeypatch):
    only_travel = [{"name": "여행용품", "url": "https://link.coupang.com/a/T",
                    "keywords": ["여행"], "blogs": [], "active": True}]
    out = _render(monkeypatch, links=only_travel, keyword="주택담보대출 금리")
    assert "link.coupang.com" not in out
    assert _EXPECTED not in out


# ── 읽을 수 있는가 ──────────────────────────────────────────────────────────

def test_disclosure_is_actually_legible(monkeypatch):
    """10px·#bbb로 되돌아가면 표시했다고 보기 어렵습니다."""
    out = _render(monkeypatch)
    idx = out.index(_EXPECTED)
    style = out[max(0, idx - 260):idx]
    size = re.search(r"font-size:(\d+)px", style)
    assert size and int(size.group(1)) >= 12, f"고지 문구가 너무 작습니다: {style!r}"
    assert "#bbb" not in style, "옅은 회색이라 흰 배경에서 읽히지 않습니다"


def test_disclosure_sits_inside_the_same_ad_box(monkeypatch):
    """본문 저 아래 따로 떨어지면 광고와 연결해 인식하기 어렵습니다.

    처음에는 링크와 고지 사이의 글자 수로 쟀는데, 그 사이는 대부분 인라인
    CSS라 화면상의 거리와 무관했습니다(414자). 같은 광고 상자 안에 있는지를
    봐야 의미가 있습니다.
    """
    out = _render(monkeypatch)
    box = out[out.rindex("<div", 0, out.index("link.coupang.com")):]
    assert _EXPECTED in box, "고지가 광고 상자 밖에 있습니다"
    assert box.count("</div>") <= 2, "고지와 링크가 다른 블록으로 갈라졌습니다"


# ── 삽입 경로가 하나인지 ─────────────────────────────────────────────────────

def test_only_one_place_builds_the_section():
    """다른 곳에서 링크를 넣기 시작하면 고지 없는 광고가 생깁니다."""
    src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    hits = []
    for name in os.listdir(src_dir):
        if not name.endswith(".py") or name == "coupang_affiliate.py":
            continue
        with open(os.path.join(src_dir, name), encoding="utf-8") as f:
            if "link.coupang.com" in f.read():
                hits.append(name)
    assert not hits, f"쿠팡 링크를 직접 만드는 모듈이 있습니다: {hits}"
