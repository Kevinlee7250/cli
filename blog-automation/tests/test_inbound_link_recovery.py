"""고아 페이지에 인바운드 링크가 실제로 생기는지 검사합니다.

2026-09-19 실측: 고아 21건을 처리했는데 링크는 2건만 생겼습니다.
  · 16건 — 후보가 0건 (기준이 너무 빡빡)
  ·  3건 — 후보는 찾았지만 본문에 쓸 앵커가 없어 실패
  ·  2건 — 성공
같은 날 측정한 고아 비율은 blog1 19.4% / blog2 58.3% / blog3 53.7%였고,
색인 검사한 공개 글 13건 중 12건이 인바운드 0이었습니다.

이 파일은 "완화했다"가 아니라 "완화해도 무관한 링크는 안 만든다"를
같이 지킵니다 — 관련성 0점짜리 링크는 고아를 없애는 게 아니라
스팸 신호를 만듭니다.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import inbound_linker as il  # noqa: E402


def _cand(url, title, published, tags=None, inbound=0):
    return {"url": url, "title": title, "published": published,
            "tags": tags or [], "keyword": title, "inbound": inbound}


# ── 후보 선정 완화 ────────────────────────────────────────────────────────

def test_strict_tier_is_preferred_when_it_finds_something():
    """1단계로 찾히면 완화 단계는 쓰지 않습니다."""
    orphan = _cand("https://b.com/o.html", "제주 렌터카 보험 정리",
                   "2026-09-10", ["제주", "렌터카"])
    strong = _cand("https://b.com/a.html", "제주 렌터카 예약 요령",
                   "2026-09-01", ["제주", "렌터카"])
    weak = _cand("https://b.com/b.html", "부산 맛집", "2026-09-02", [])
    got = il.find_link_targets(orphan, [strong, weak], set())
    assert [c["url"] for c in got] == [strong["url"]]


def test_title_word_overlap_rescues_untagged_posts():
    """태그가 하나도 안 겹쳐도 제목 낱말이 겹치면 후보가 됩니다.

    '일본 기준금리 인상' / '한국은행 기준금리 동결' 처럼 공백 단위
    비교로는 놓치는 조합이 실제로 많았습니다.
    """
    orphan = _cand("https://b.com/o.html",
                   "일본 기준금리 1.25% 인상, 31년 만에 최고치", "2026-09-10")
    cand = _cand("https://b.com/a.html", "한국은행 기준금리 동결 배경", "2026-09-01")
    got = il.find_link_targets(orphan, [cand], set())
    assert [c["url"] for c in got] == [cand["url"]]


def test_common_words_alone_are_not_relevance():
    """'정리·방법·2026' 만 겹치는 글은 후보가 아닙니다."""
    orphan = _cand("https://b.com/o.html", "2026 청약 제도 정리", "2026-09-10")
    cand = _cand("https://b.com/a.html", "2026 등산 코스 정리", "2026-09-01")
    assert il.find_link_targets(orphan, [cand], set()) == []


def test_publish_order_is_relaxed_only_as_last_resort():
    """더 먼저 나온 글이 없으면 발행 순서 제약을 풉니다.

    가장 오래된 고아는 이 제약 때문에 후보가 영원히 0건이었습니다.
    """
    orphan = _cand("https://b.com/o.html", "제주 렌터카 보험 정리",
                   "2026-01-01", ["제주", "렌터카"])
    newer = _cand("https://b.com/a.html", "제주 렌터카 예약 요령",
                  "2026-09-01", ["제주", "렌터카"])
    assert il.find_link_targets(orphan, [newer], set(), relax=False) == []
    got = il.find_link_targets(orphan, [newer], set())
    assert [c["url"] for c in got] == [newer["url"]]


def test_already_linked_sources_stay_excluded_in_every_tier():
    """완화해도 멱등성은 깨지지 않습니다."""
    orphan = _cand("https://b.com/o.html", "제주 렌터카 보험 정리",
                   "2026-01-01", ["제주"])
    src = _cand("https://b.com/a.html", "제주 렌터카 예약 요령",
                "2026-09-01", ["제주"])
    assert il.find_link_targets(orphan, [src], {src["url"]}) == []


def test_orphan_is_never_linked_to_itself():
    orphan = _cand("https://b.com/o.html", "제주 렌터카 보험 정리",
                   "2026-01-01", ["제주"])
    assert il.find_link_targets(orphan, [orphan], set()) == []


# ── 앵커를 못 찾았을 때의 마지막 수단 ──────────────────────────────────────

def test_related_line_is_appended_when_no_anchor_fits():
    orphan = {"url": "https://b.com/o.html", "title": "제주 렌터카 보험 정리"}
    html = "<p>전혀 관계없는 문장입니다.</p>"
    out, ok = il.append_related_link(orphan, html)
    assert ok
    assert html in out, "기존 본문을 건드리면 안 됩니다"
    assert 'href="https://b.com/o.html"' in out
    assert il.FALLBACK_ANCHOR_LABEL in out


def test_append_is_idempotent():
    """같은 글을 두 번 돌려도 링크가 두 개 생기지 않습니다."""
    orphan = {"url": "https://b.com/o.html", "title": "제주 렌터카 보험 정리"}
    out, ok = il.append_related_link(orphan, "<p>본문</p>")
    assert ok
    out2, ok2 = il.append_related_link(orphan, out)
    assert not ok2 and out2 == out


def test_existing_body_link_blocks_the_append():
    """본문이 이미 그 글을 가리키면 덧붙이지 않습니다."""
    orphan = {"url": "https://b.com/o.html", "title": "제주 렌터카 보험 정리"}
    html = '<p>자세한 내용은 <a href="https://b.com/o.html">여기</a></p>'
    _, ok = il.append_related_link(orphan, html)
    assert not ok


def test_source_post_does_not_become_a_link_list():
    """한 글에 이 방식으로 붙는 줄은 상한이 있습니다."""
    html = "<p>본문</p>"
    for i in range(il.MAX_FALLBACK_PER_SOURCE):
        html, ok = il.append_related_link(
            {"url": f"https://b.com/{i}.html", "title": f"글 {i}"}, html)
        assert ok
    _, ok = il.append_related_link(
        {"url": "https://b.com/over.html", "title": "한 개 더"}, html)
    assert not ok, "상한을 넘으면 본문 끝이 링크 목록이 됩니다"


def test_title_is_escaped():
    """제목에 들어간 꺾쇠가 HTML을 깨뜨리지 않습니다."""
    orphan = {"url": "https://b.com/o.html", "title": '<script>x</script>'}
    out, ok = il.append_related_link(orphan, "<p>본문</p>")
    assert ok and "<script>" not in out.split("<p class=")[-1]


def test_build_anchor_falls_back_instead_of_giving_up():
    """본문 앵커가 없으면 포기하지 않고 관련 글 줄을 씁니다."""
    orphan = {"url": "https://b.com/o.html", "title": "제주 렌터카 보험 정리",
              "keyword": "제주 렌터카 보험", "tags": ["제주"]}
    out, ok, anchor = il.build_anchor_html(orphan, "<p>관계없는 문장.</p>")
    assert ok and anchor == il.FALLBACK_ANCHOR_LABEL
    assert "https://b.com/o.html" in out


def test_empty_orphan_is_ignored():
    """URL이나 제목이 없으면 아무것도 붙이지 않습니다."""
    assert il.append_related_link({"url": "", "title": "제목"}, "<p>a</p>")[1] is False
    assert il.append_related_link({"url": "https://b.com/o.html", "title": ""},
                                  "<p>a</p>")[1] is False
