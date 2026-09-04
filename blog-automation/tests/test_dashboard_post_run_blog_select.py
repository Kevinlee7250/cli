"""포스트 생성 카드에서 고른 블로그가 실행까지 전달되는가.

왜
──
"워크플로우 실행 제어 → 포스트 생성"에는 대상 블로그를 고르는 자리가
없었습니다. blog-run.yml의 수동 실행 조건은

    inputs.blog_id == '' || inputs.blog_id == 'blogN'

이라, blog_id를 안 보내면 세 블로그가 순차로 다 돕니다. 화면에는 "3편"만
보이는데 실제로는 9편이 나가고, 특정 블로그에만 올리려면 GitHub Actions
화면으로 넘어가야 했습니다. 시리즈 기획 카드에는 이미 같은 선택이 있어
포스트 생성만 빠져 있던 셈입니다.

여기서 지키는 것
────────────────
  1. 선택 자리가 있고
  2. 고른 값이 dispatch 입력(blog_id)으로 실려 가고
  3. "전체"일 때는 몇 편이 나가는지 알린 뒤 확인을 받는다
"""

import os
import re

_HTML = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..",
                                      "docs", "index.html"))


def _html() -> str:
    with open(_HTML, encoding="utf-8") as f:
        return f.read()


def _fn(name: str) -> str:
    """그 함수 본문만 잘라냅니다 (다음 최상위 function 앞까지)."""
    src = _html()
    start = src.index(f"function {name}(")
    nxt = src.find("\nfunction ", start + 1)
    return src[start:nxt if nxt > 0 else start + 2000]


def test_the_card_has_a_blog_select():
    html = _html()
    assert 'id="wf-live-blog"' in html, "포스트 생성 카드에 블로그 선택이 없습니다"
    for blog in ("blog1", "blog2", "blog3"):
        assert f'value="{blog}"' in html


def test_all_blogs_stays_the_default():
    """기본값을 특정 블로그로 바꾸면 버튼이 하던 일이 조용히 달라집니다."""
    html = _html()
    sel = html[html.index('id="wf-live-blog"'):]
    first_option = re.search(r"<option value=\"([^\"]*)\"", sel).group(1)
    assert first_option == "", f"첫 옵션(기본값)이 전체가 아닙니다: {first_option!r}"


def test_selection_reaches_the_workflow():
    body = _fn("wfRunLive")
    assert "wf-live-blog" in body, "고른 값을 읽지 않습니다"
    assert "blog_id" in body, (
        "blog_id를 dispatch 입력에 싣지 않습니다 — 화면에서 골라도 "
        "세 블로그가 모두 돕니다"
    )


def test_all_blogs_asks_first():
    body = _fn("wfRunLive")
    assert "confirm(" in body and "return" in body, (
        "전체 선택인데 확인 없이 바로 실행합니다 — 고른 편수의 3배가 나갑니다"
    )


def test_hint_says_the_real_total():
    """'3편'만 보이고 실제로 9편이 나가면 화면이 사실을 가립니다."""
    html = _html()
    assert 'id="wf-live-blog-hint"' in html
    body = _fn("wfLiveBlogChanged")
    assert "* 3" in body, "총 편수를 계산해 보여 주지 않습니다"
    # 정의만 하고 부르지 않으면 화면에는 아무것도 안 뜹니다
    assert html.count("wfLiveBlogChanged") >= 4


def test_series_card_still_has_its_own_select():
    """포스트 생성에 추가하면서 시리즈 쪽을 건드리지 않았는지."""
    assert 'id="wf-series-blog"' in _html()
