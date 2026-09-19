"""역방향 내부 링크 테스트 (2026-08-21).

발행된 글을 수정하는 도구라 규칙이 어긋나면 되돌리기가 번거롭습니다.
선택 규칙과 삽입 안전성을 고정합니다.

실행: cd blog-automation && python -m pytest tests/test_inbound_linker.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _cand(url, title="글", tags=None, published="2026-07-01", inbound=0):
    return {"url": url, "title": title, "tags": tags or [], "keyword": title,
            "published": published, "inbound": inbound}


def _orphan(title="가을 단풍 골프장 추천", tags=None, published="2026-08-20"):
    return {"url": "https://a.com/new", "title": title, "keyword": title,
            "tags": tags or ["골프", "가을"], "published": published}


# ──────────────────────────────────────────────────────────────────────────────
# 출처 글 선택 규칙
# ──────────────────────────────────────────────────────────────────────────────

def test_older_posts_are_preferred_as_sources():
    """나중 글이 앞 글을 링크하는 건 부자연스러움 — 먼저 쓰인 글만 출처."""
    from inbound_linker import find_link_targets
    older = _cand("https://a.com/old", "골프 가을 라운딩", ["골프", "가을"], "2026-07-01")
    newer = _cand("https://a.com/newer", "골프 가을 라운딩", ["골프", "가을"], "2026-08-25")
    picked = find_link_targets(_orphan(), [older, newer], set())
    assert [p["url"] for p in picked] == ["https://a.com/old"]


def test_unrelated_posts_are_not_linked():
    """억지 링크는 안 하느니만 못합니다."""
    from inbound_linker import find_link_targets
    unrelated = _cand("https://a.com/x", "ETF 세금 정리", ["금융", "ETF"])
    assert find_link_targets(_orphan(), [unrelated], set()) == []


def test_already_linking_sources_are_skipped():
    """멱등성 — 같은 링크를 두 번 넣으면 안 됨."""
    from inbound_linker import find_link_targets
    c = _cand("https://a.com/old", "골프 가을 라운딩", ["골프", "가을"])
    assert find_link_targets(_orphan(), [c], {"https://a.com/old"}) == []


def test_self_is_never_a_source():
    from inbound_linker import find_link_targets
    me = _cand("https://a.com/new", "가을 단풍 골프장 추천", ["골프", "가을"])
    assert find_link_targets(_orphan(), [me], set()) == []


def test_more_linked_source_wins_on_tie():
    """관련성이 같으면 구글이 이미 아는 글을 골라 크롤 경로를 잇습니다."""
    from inbound_linker import find_link_targets
    weak = _cand("https://a.com/weak", "골프 가을 라운딩", ["골프", "가을"], inbound=0)
    strong = _cand("https://a.com/strong", "골프 가을 라운딩", ["골프", "가을"], inbound=12)
    picked = find_link_targets(_orphan(), [weak, strong], set(), per_orphan=1)
    assert picked[0]["url"] == "https://a.com/strong"


def test_per_orphan_limit_respected():
    """고아 하나에 링크를 많이 달면 부자연스럽고 스팸처럼 보입니다."""
    from inbound_linker import find_link_targets
    cands = [_cand(f"https://a.com/{i}", "골프 가을 라운딩", ["골프", "가을"])
             for i in range(10)]
    assert len(find_link_targets(_orphan(), cands, set(), per_orphan=2)) == 2


# ──────────────────────────────────────────────────────────────────────────────
# 삽입 안전성 — internal_linker의 검증된 로직을 재사용하는지 확인
# ──────────────────────────────────────────────────────────────────────────────

def test_link_inserted_into_body_text():
    from inbound_linker import build_anchor_html
    html = "<p>가을 단풍 골프장 추천 코스를 정리했습니다.</p>"
    updated, ok, anchor = build_anchor_html(_orphan(), html)
    assert ok and '<a href="https://a.com/new"' in updated and anchor


# 2026-09-19 — 아래 네 건은 원래 "삽입 실패(ok=False)"를 기대했습니다.
# 그때는 그게 안전의 증거였지만, 실측해 보니 그 상태로 고아가 그대로
# 남았습니다(후보를 찾은 5건 중 3건이 앵커를 못 찾아 실패). 이제는
# 글 끝에 관련 글 한 줄을 붙이므로, 지켜야 할 것은 "삽입하지 않는다"가
# 아니라 "기존 본문을 한 글자도 건드리지 않는다"입니다.

def test_link_not_inserted_into_heading():
    """제목 안에 링크를 넣으면 문서 구조가 망가집니다."""
    from inbound_linker import build_anchor_html
    html = "<h2>가을 단풍 골프장 추천</h2><p>본문에는 다른 내용.</p>"
    updated, ok, _ = build_anchor_html(_orphan(), html)
    assert ok, "이제는 마지막 수단으로 관련 글 줄을 붙입니다"
    assert updated.startswith(html), "기존 본문이 변형됐습니다"
    assert "https://a.com/new" not in updated.split("</h2>")[0]


def test_link_not_nested_inside_existing_anchor():
    from inbound_linker import build_anchor_html
    html = '<p><a href="https://other.com">가을 단풍 골프장 추천</a></p>'
    updated, ok, _ = build_anchor_html(_orphan(), html)
    assert ok
    assert updated.startswith(html), "기존 앵커 안에 링크가 들어갔습니다"


def test_orphan_gets_a_link_even_without_a_matching_phrase():
    """본문에 쓸 표현이 없어도 고아를 그대로 두지는 않습니다.

    문장을 지어내는 게 아니라, 글 끝에 관련 글 한 줄을 붙입니다.
    """
    from inbound_linker import build_anchor_html, FALLBACK_ANCHOR_LABEL
    html = "<p>전혀 관계없는 내용입니다.</p>"
    updated, ok, anchor = build_anchor_html(_orphan(), html)
    assert ok and anchor == FALLBACK_ANCHOR_LABEL
    assert updated.startswith(html)
    assert "https://a.com/new" in updated


def test_original_html_is_never_rewritten():
    from inbound_linker import build_anchor_html
    html = "<h1>가을 단풍 골프장 추천</h1>"
    updated, ok, _ = build_anchor_html(_orphan(), html)
    assert ok and updated.startswith(html)


def test_nothing_is_added_when_the_link_already_exists():
    """이미 그 글을 가리키고 있으면 아무것도 하지 않습니다 (멱등)."""
    from inbound_linker import build_anchor_html
    html = '<p>자세한 내용은 <a href="https://a.com/new">여기</a>를 보세요.</p>'
    updated, ok, _ = build_anchor_html(_orphan(), html)
    assert ok is False and updated == html


# ──────────────────────────────────────────────────────────────────────────────
# 실행 안전장치
# ──────────────────────────────────────────────────────────────────────────────

def test_missing_audit_file_does_not_crash(tmp_path, monkeypatch):
    import inbound_linker as il
    monkeypatch.setattr(il, "_DOCS_DATA", str(tmp_path))
    r = il.run(limit=5, apply_changes=False)
    assert r["linksAdded"] == 0 and r["orphansHandled"] == 0


def test_defaults_are_conservative():
    """발행된 글을 수정하므로 기본값이 공격적이면 안 됩니다."""
    import inbound_linker as il
    assert il.LINKS_PER_ORPHAN <= 3
    assert il.MAX_ADDED_PER_SOURCE <= 5
    assert il.MIN_RELEVANCE >= 1
