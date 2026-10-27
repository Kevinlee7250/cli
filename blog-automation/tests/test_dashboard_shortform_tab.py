"""대시보드의 '📸 제품 숏폼' 탭이 숏폼 모듈과 제대로 연결돼 있는가.

제품 숏폼 자동화는 별도 서비스(kevin-blog-commerce-pwa, Cloud Run)에서 돕니다.
대시보드는 연결 토큰으로 /api/external/shortform 을 읽고 일시정지만 보냅니다.

여기서 지키는 것
────────────────
  1. 사이드바 메뉴·페이지·navTo 훅이 서로 이어져 있다
  2. 토큰은 Authorization 헤더로만 보내고 URL 에 싣지 않는다
  3. 서버가 준 텍스트는 esc() 를 거치고, 링크는 같은 서비스의 상대 경로만 만든다
  4. 기존 메뉴는 그대로 남아 있다(연결만, 삭제 없음)
"""

import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_HTML = os.path.join(_ROOT, "docs", "index.html")


def _html() -> str:
    with open(_HTML, encoding="utf-8") as f:
        return f.read()


def _sf_render_source(html: str) -> str:
    start = html.index("function sfRender(")
    return html[start:html.index("\n}\n", start)]


def test_nav_page_and_hook_are_wired():
    html = _html()
    assert '<a data-page="shortform">' in html
    assert html.count('id="page-shortform"') == 1
    assert "if (page === 'shortform') sfLoad()" in html
    assert 'id="shortform-nav-badge"' in html


def test_token_travels_in_the_authorization_header_only():
    html = _html()
    assert "'Authorization': 'Bearer ' + sfToken()" in html
    assert "/api/external/shortform/pause" in html
    assert not re.search(r"[?&]token=", html[html.index("function sfRequest("):]), "token must never go in a URL"
    assert 'id="sf-token" type="password"' in html


def test_server_text_is_escaped_and_links_stay_on_the_service():
    html = _html()
    render = _sf_render_source(html)
    for field in ("a.text", "c.label", "c.hint", "u.publish_at_kst", "u.channel_label", "u.status", "c.label", "pub.detail"):
        assert f"esc({field})" in render, field
    assert "link(a.link" in render and "link(c.fix" in render
    assert "path.startsWith('/') && !path.startsWith('//')" in html


def test_existing_menus_are_kept():
    html = _html()
    for page in ("dashboard", "run", "posts", "keywords", "analytics", "social", "review",
                 "series", "thumbnail", "postmgr", "system", "config"):
        assert f'data-page="{page}"' in html, page
        assert f'id="page-{page}"' in html, page
