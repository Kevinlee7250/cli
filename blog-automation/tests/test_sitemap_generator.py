"""사이트맵 생성 — 특히 "블로그 하나가 통째로 빠지는" 사고를 막습니다.

이 로직은 워크플로 안에 heredoc으로 인라인돼 있어 테스트가 없었고, 그 사이
커스텀 도메인 블로그가 사이트맵에서 통째로 누락된 채 오래 돌았습니다
(posts.json 31편 → sitemap.xml 0편). 워크플로는 계속 초록이었습니다.
"""

import sitemap_generator as sg


def _p(url, **kw):
    return {"url": url, **kw}


# ── 이번에 고친 버그 ─────────────────────────────────────────────────────────

def test_custom_domain_blog_is_included():
    """blogspot이 아니라는 이유로 빠지면 안 됩니다 — 실제로 그랬습니다."""
    posts = [_p("https://www.hoguwhat.com/2026/08/a.html"),
             _p("https://hoguasset.blogspot.com/2026/08/b.html")]
    urls = [e["url"] for e in sg.build_entries(posts)]
    assert "https://www.hoguwhat.com/2026/08/a.html" in urls


def test_every_blog_gets_a_root_and_a_robots_line():
    posts = [_p("https://www.hoguwhat.com/x.html"),
             _p("https://hoguasset.blogspot.com/y.html"),
             _p("https://hogugolfntraval.blogspot.com/z.html")]
    entries = sg.build_entries(posts)
    roots = sg.roots_of(entries)
    assert len(roots) == 3
    robots = sg.render_robots(roots)
    for r in roots:
        assert f"Sitemap: {r}/sitemap.xml" in robots


def test_no_post_is_silently_dropped():
    """URL이 있는 글은 하나도 빠지지 않아야 합니다."""
    posts = [_p(f"https://a.example/{i}.html") for i in range(5)]
    entries = [e for e in sg.build_entries(posts) if not e["url"].endswith("/")]
    assert len(entries) == 5


# ── 걸러야 하는 것 ───────────────────────────────────────────────────────────

def test_post_without_url_is_skipped():
    assert sg.build_entries([{"title": "주소 없음"}]) == []


def test_relative_or_junk_url_is_skipped():
    assert sg.build_entries([_p("/2026/08/a.html"), _p("javascript:void(0)")]) == []


def test_duplicate_url_appears_once():
    posts = [_p("https://a.example/x.html"), _p("https://a.example/x.html")]
    posts_only = [e for e in sg.build_entries(posts) if not e["url"].endswith("/")]
    assert len(posts_only) == 1


# ── 필드 해석 ────────────────────────────────────────────────────────────────

def test_legacy_url_field_names_are_read():
    for field in ("url", "blogUrl", "link"):
        assert sg.build_entries([{field: "https://a.example/x.html"}])


def test_compact_timestamp_becomes_a_date():
    e = sg.build_entries([_p("https://a.example/x.html", publishedAt="20260826123456")])
    assert [x for x in e if not x["url"].endswith("/")][0]["lastmod"] == "2026-08-26"


def test_iso_timestamp_is_truncated_to_a_date():
    e = sg.build_entries([_p("https://a.example/x.html",
                             publishedAt="2026-08-26T12:34:56+00:00")])
    assert [x for x in e if not x["url"].endswith("/")][0]["lastmod"] == "2026-08-26"


def test_missing_date_falls_back_to_today():
    e = sg.build_entries([_p("https://a.example/x.html")], today="2026-01-02")
    assert all(x["lastmod"] == "2026-01-02" for x in e)


def test_grade_drives_priority():
    got = {}
    for g in ("S", "A", "B", "C", "없음"):
        e = sg.build_entries([_p("https://a.example/x.html", grade=g)])
        got[g] = [x for x in e if not x["url"].endswith("/")][0]["priority"]
    assert got == {"S": "1.0", "A": "0.8", "B": "0.6", "C": "0.5", "없음": "0.5"}


# ── 출력 형식 ────────────────────────────────────────────────────────────────

def test_sitemap_is_wellformed_xml():
    import xml.etree.ElementTree as ET
    xml = sg.render_sitemap(sg.build_entries([_p("https://a.example/x.html")]))
    root = ET.fromstring(xml)
    assert root.tag.endswith("urlset")


def test_root_url_comes_first_and_is_daily():
    entries = sg.build_entries([_p("https://a.example/x.html")])
    assert entries[0]["url"] == "https://a.example/" 
    assert entries[0]["changefreq"] == "daily" and entries[0]["priority"] == "1.0"
