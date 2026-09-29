"""쿠팡파트너스 제휴 링크 삽입 모듈

docs/data/affiliate_links.json 에서 링크를 읽어 글 하단에 삽입합니다.
파일이 없거나 비어 있으면 아무것도 삽입하지 않습니다.
"""
import json
import logging
import os
import re
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_LINKS_FILE = os.path.join(
    os.path.dirname(__file__), "..", "docs", "data", "affiliate_links.json"
)

_MAX_LINKS_PER_POST = 3

#: HTML 배너는 이 플래그가 켜져야 들어갑니다. 텍스트 링크는 영향 없습니다.
#:
#: feature_flags는 "정의되지 않은 플래그는 켜진 것으로" 보므로,
#: feature_flags.json에 false로 반드시 적혀 있어야 합니다.
BANNER_FLAG = "coupang_banner"

#: 배너 HTML 안에서 허용하는 호스트. 쿠팡이 준 코드만 통과시킵니다.
_ALLOWED_HOST_SUFFIXES = ("coupang.com", "coupangcdn.com")

#: 허용 태그. 배너는 이것들로 충분합니다.
_ALLOWED_TAGS = {"iframe", "a", "img", "div", "span", "p", "script", "ins", "br"}

_TAG_RE = re.compile(r"<\s*/?\s*([a-zA-Z][a-zA-Z0-9]*)")
_URL_ATTR_RE = re.compile(r"""\b(?:src|href|data-src)\s*=\s*["']([^"']+)["']""", re.I)
_EVENT_ATTR_RE = re.compile(r"""\bon[a-z]+\s*=""", re.I)

#: 인라인 스크립트에서 보이면 안 되는 것들. 쿠팡 위젯 초기화 코드에는
#: 나오지 않습니다.
_SCRIPT_DENY = ("document.write", "eval(", "xmlhttprequest", "fetch(",
                "localstorage", "document.cookie", "innerhtml")


def _host_allowed(url: str) -> bool:
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    if not url.lower().startswith(("http://", "https://")):
        return False
    host = urlparse(url).hostname or ""
    host = host.lower()
    return any(host == s or host.endswith("." + s) for s in _ALLOWED_HOST_SUFFIXES)


def validate_banner_html(html: str) -> tuple[bool, str]:
    """배너 HTML이 안전한지 봅니다. (통과여부, 이유)

    이 HTML은 손대지 않고 그대로 글 본문에 들어가 독자 브라우저에서
    실행됩니다. 그래서 쿠팡이 준 코드인지 확인합니다 — 붙여넣기 하다
    엉뚱한 것이 섞여도 발행 전에 걸리도록.

    검사 항목
      · 태그가 배너에 쓰이는 것들인가
      · 모든 src/href가 쿠팡 도메인인가
      · onclick 같은 이벤트 속성이 없는가
      · 인라인 스크립트가 쿠팡 위젯 초기화 코드인가
    """
    if not html or not html.strip():
        return False, "배너 HTML이 비어 있습니다"

    if _EVENT_ATTR_RE.search(html):
        return False, "onclick 같은 이벤트 속성은 사용할 수 없습니다"

    tags = {t.lower() for t in _TAG_RE.findall(html)}
    bad_tags = tags - _ALLOWED_TAGS
    if bad_tags:
        return False, f"허용하지 않는 태그입니다: {', '.join(sorted(bad_tags))}"

    urls = _URL_ATTR_RE.findall(html)
    for url in urls:
        if not _host_allowed(url):
            return False, f"쿠팡 도메인이 아닌 주소가 있습니다: {url[:80]}"

    # 인라인 스크립트(src 없는 <script>)는 쿠팡 위젯 초기화만 허용합니다.
    for body in re.findall(r"<script\b([^>]*)>(.*?)</script\s*>", html, re.I | re.S):
        attrs, inner = body
        if "src" in attrs.lower():
            continue  # src는 위에서 도메인 검사를 마쳤습니다
        low = inner.lower()
        if "partnerscoupang" not in low:
            return False, "쿠팡 위젯 초기화가 아닌 스크립트는 넣을 수 없습니다"
        hit = next((d for d in _SCRIPT_DENY if d in low), "")
        if hit:
            return False, f"스크립트에 허용되지 않는 코드가 있습니다: {hit}"

    if not urls and "script" not in tags:
        return False, "쿠팡 주소가 하나도 없습니다 — 배너 코드가 맞는지 확인하세요"

    return True, ""


def banners_enabled() -> bool:
    """HTML 배너 삽입이 켜져 있는지."""
    try:
        from feature_flags import is_enabled
        return is_enabled(BANNER_FLAG)
    except Exception:
        return False


def load_affiliate_links() -> list[dict]:
    """docs/data/affiliate_links.json 에서 활성화된 링크 목록을 로드합니다."""
    path = os.path.abspath(_LINKS_FILE)
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        return [ln for ln in data if ln.get("enabled", True)]
    except Exception as e:
        logger.warning(f"affiliate_links.json 로드 실패: {e}")
        return []


def _match_links(links: list[dict], keyword: str, blog_id: str) -> list[dict]:
    """키워드·블로그 ID 기준으로 삽입할 링크를 선택합니다.

    우선순위:
    1. 블로그 필터 통과 + 키워드 태그 매칭
    2. 블로그 필터 통과 + 태그 없는 general 링크
    """
    kw_lower = keyword.lower()
    matched: list[dict] = []
    general: list[dict] = []

    for link in links:
        # 블로그 필터 (blogs 비어 있으면 전체 블로그)
        allowed_blogs: list[str] = link.get("blogs", [])
        if allowed_blogs and blog_id not in allowed_blogs:
            continue

        tags = [t.lower() for t in (link.get("keywords") or [])]
        if tags:
            if any(t in kw_lower for t in tags):
                matched.append(link)
        else:
            general.append(link)

    selected = (matched or general)[:_MAX_LINKS_PER_POST]
    return selected


#: 쿠팡 파트너스 고지 문구.
#:
#: 표시광고법상 대가를 받은 추천은 소비자가 "쉽게 인식할 수 있는" 방법으로
#: 알려야 합니다. 문구를 바꾸거나 빼면 법적 문제가 되므로 상수로 두고
#: 테스트로 고정합니다.
#:
#: 이전에는 10px · #bbb 회색이었습니다. 흰 배경에 옅은 회색 10px는 있어도
#: 읽히지 않아, 표시했다고 보기 어렵습니다. 본문과 같은 크기로 올렸습니다.
DISCLOSURE = (
    "이 포스팅은 쿠팡 파트너스 활동의 일환으로, "
    "이에 따른 일정액의 수수료를 제공받습니다."
)


def inject_affiliate_section(
    content_html: str,
    keyword: str,
    blog_config: dict | None = None,
) -> str:
    """글 하단에 쿠팡파트너스 추천 상품 섹션을 삽입합니다.

    AdSense 자동 광고와 겹치지 않도록 본문 HTML 맨 끝에 고정 배치합니다.
    삽입할 링크가 없으면 원본 HTML을 그대로 반환합니다.
    """
    links = load_affiliate_links()
    if not links:
        return content_html

    blog_id: str = (blog_config or {}).get("id", "blog1")
    selected = _match_links(links, keyword, blog_id)
    if not selected:
        return content_html

    banners_on = banners_enabled()
    buttons, banners = [], []

    for ln in selected:
        if (ln.get("type") or "link") != "html":
            buttons.append(ln)
            continue

        # ── HTML 배너 ──
        if not banners_on:
            logger.info(
                f"HTML 배너 '{ln.get('name', '')}' 건너뜀 — "
                f"'{BANNER_FLAG}' 기능이 꺼져 있습니다"
            )
            continue
        ok, why = validate_banner_html(ln.get("html", ""))
        if not ok:
            logger.warning(f"HTML 배너 '{ln.get('name', '')}' 건너뜀 — {why}")
            continue
        banners.append(ln)

    if not buttons and not banners:
        return content_html

    items_html = "\n    ".join(
        f'<a href="{ln["url"]}" target="_blank" rel="nofollow sponsored noopener" '
        f'style="display:inline-block;padding:10px 18px;'
        f'background:linear-gradient(135deg,#ff6600,#ff8c00);'
        f'color:#fff;text-decoration:none;border-radius:8px;'
        f'font-size:13px;font-weight:700;margin:4px;'
        f'box-shadow:0 2px 6px rgba(255,102,0,.3);">'
        f'🛒 {ln["name"]}</a>'
        for ln in buttons
    )

    # 배너는 검증을 통과한 쿠팡 코드를 그대로 씁니다. 감싸기만 합니다.
    banners_html = "\n    ".join(
        f'<div style="margin:10px auto;max-width:100%;overflow-x:auto">{ln["html"]}</div>'
        for ln in banners
    )

    section = (
        '\n<div style="margin-top:40px;padding:22px 20px;'
        'background:linear-gradient(135deg,#fff9f5,#fff3eb);'
        'border:1px solid #ffd4b0;border-radius:12px;text-align:center;'
        'font-family:\'Apple SD Gothic Neo\',\'Malgun Gothic\',sans-serif;">\n'
        '  <p style="font-size:14px;font-weight:700;color:#c84b00;'
        'margin:0 0 14px">📦 관련 상품 추천</p>\n'
        + ('  <div style="display:flex;flex-wrap:wrap;gap:8px;justify-content:center">\n'
           f'    {items_html}\n'
           '  </div>\n' if buttons else '')
        + (f'  <div style="margin-top:{14 if buttons else 0}px">\n'
           f'    {banners_html}\n'
           '  </div>\n' if banners else '')
        + f'  <p style="font-size:13px;color:#6b4423;margin:16px 0 0;'
        f'line-height:1.6;font-weight:600">{DISCLOSURE}</p>\n'
        '</div>'
    )

    logger.info(
        f"쿠팡파트너스 삽입 — 링크 {len(buttons)}개, 배너 {len(banners)}개: "
        f"{[ln.get('name', '') for ln in buttons + banners]}"
    )
    return content_html + section
