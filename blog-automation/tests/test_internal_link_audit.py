"""내부 링크 구조 진단 테스트 (2026-08-20).

새 글에 들어오는 내부 링크가 0개라는 가설을 숫자로 검증하는 도구입니다.
집계가 틀리면 잘못된 결론으로 이어지므로 계산 규칙을 고정합니다.

실행: cd blog-automation && python -m pytest tests/test_internal_link_audit.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

HOSTS = {"a.com", "b.blogspot.com"}


def _post(url, content="", title="글", blog="A", published="2026-08-01"):
    return {"url": url, "content": content, "title": title,
            "_blog": blog, "published": published}


def _link(url, text="본문"):
    return f'<p>{text} <a href="{url}">링크</a></p>'


# ──────────────────────────────────────────────────────────────────────────────
# URL 정규화 — 스킴·www·끝 슬래시 차이로 링크를 놓치면 고아를 과다 집계함
# ──────────────────────────────────────────────────────────────────────────────

def test_normalize_absorbs_scheme_www_slash():
    from internal_link_audit import _normalize
    a = _normalize("https://www.a.com/2026/08/x.html")
    b = _normalize("http://a.com/2026/08/x.html/")
    assert a == b == "a.com/2026/08/x.html"


def test_normalize_handles_empty():
    from internal_link_audit import _normalize
    assert _normalize("") == "" and _normalize(None) == ""


# ──────────────────────────────────────────────────────────────────────────────
# 링크 추출
# ──────────────────────────────────────────────────────────────────────────────

def test_external_links_are_excluded():
    """외부 링크를 내부로 세면 고아가 아닌 것처럼 보임."""
    from internal_link_audit import extract_internal_links
    html = _link("https://news.example.com/x") + _link("https://a.com/p1")
    assert extract_internal_links(html, HOSTS) == {"a.com/p1"}


def test_anchor_and_mailto_ignored():
    from internal_link_audit import extract_internal_links
    html = _link("#toc") + _link("mailto:x@y.com")
    assert extract_internal_links(html, HOSTS) == set()


def test_duplicate_links_counted_once():
    """같은 대상을 세 번 링크해도 구조상 연결은 하나."""
    from internal_link_audit import extract_internal_links
    html = _link("https://a.com/p1") * 3
    assert extract_internal_links(html, HOSTS) == {"a.com/p1"}


def test_cross_blog_links_are_internal():
    """같은 운영자의 다른 블로그도 내부 링크로 셉니다."""
    from internal_link_audit import extract_internal_links
    assert extract_internal_links(_link("https://b.blogspot.com/p9"), HOSTS) == {"b.blogspot.com/p9"}


# ──────────────────────────────────────────────────────────────────────────────
# 링크 그래프
# ──────────────────────────────────────────────────────────────────────────────

def test_inbound_and_outbound_counted():
    from internal_link_audit import build_link_graph
    posts = [
        _post("https://a.com/old", _link("https://a.com/older")),
        _post("https://a.com/older"),
    ]
    g = build_link_graph(posts, HOSTS)
    assert g["a.com/old"]["outbound"] == 1
    assert g["a.com/older"]["inbound"] == 1


def test_new_post_with_no_inbound_is_orphan():
    """핵심 가설 — 새 글은 아무도 가리키지 않아 고아가 됨."""
    from internal_link_audit import build_link_graph, summarize
    posts = [
        _post("https://a.com/new", _link("https://a.com/old"), published="2026-08-20"),
        _post("https://a.com/old", published="2026-07-01"),
    ]
    s = summarize(build_link_graph(posts, HOSTS))
    assert s["orphanCount"] == 1
    assert s["orphans"][0]["url"] == "https://a.com/new"


def test_self_link_does_not_count_as_inbound():
    from internal_link_audit import build_link_graph
    posts = [_post("https://a.com/p1", _link("https://a.com/p1"))]
    g = build_link_graph(posts, HOSTS)
    assert g["a.com/p1"]["inbound"] == 0
    assert g["a.com/p1"]["outbound"] == 0


def test_link_to_unpublished_url_is_not_counted_as_inbound():
    """발행 목록에 없는 URL은 노드가 아니므로 인바운드로 잡히지 않음."""
    from internal_link_audit import build_link_graph
    posts = [_post("https://a.com/p1", _link("https://a.com/gone"))]
    g = build_link_graph(posts, HOSTS)
    assert "a.com/gone" not in g
    assert g["a.com/p1"]["outbound"] == 1


def test_summary_metrics(monkeypatch, tmp_path):
    import internal_link_audit as ila
    monkeypatch.setattr(ila, "_DOCS_DATA", str(tmp_path))    # 색인 파일 없음
    posts = [
        _post("https://a.com/1", _link("https://a.com/2") + _link("https://a.com/3")),
        _post("https://a.com/2", _link("https://a.com/3")),
        _post("https://a.com/3"),
    ]
    s = ila.summarize(ila.build_link_graph(posts, HOSTS))
    assert s["totalPosts"] == 3
    assert s["orphanCount"] == 1                 # /1만 인바운드 0
    assert s["maxInbound"] == 2                  # /3이 두 곳에서 링크됨
    assert s["mostLinked"][0]["inbound"] == 2


def test_empty_input_does_not_crash(monkeypatch, tmp_path):
    import internal_link_audit as ila
    monkeypatch.setattr(ila, "_DOCS_DATA", str(tmp_path))
    s = ila.summarize(ila.build_link_graph([], HOSTS))
    assert s["totalPosts"] == 0 and s["orphanRate"] == 0.0
