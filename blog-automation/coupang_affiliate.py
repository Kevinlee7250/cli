"""쿠팡파트너스 제휴 링크 삽입 모듈

docs/data/affiliate_links.json 에서 링크를 읽어 글 하단에 삽입합니다.
파일이 없거나 비어 있으면 아무것도 삽입하지 않습니다.
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

_LINKS_FILE = os.path.join(
    os.path.dirname(__file__), "..", "docs", "data", "affiliate_links.json"
)

_MAX_LINKS_PER_POST = 3


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

    items_html = "\n    ".join(
        f'<a href="{ln["url"]}" target="_blank" rel="nofollow sponsored noopener" '
        f'style="display:inline-block;padding:10px 18px;'
        f'background:linear-gradient(135deg,#ff6600,#ff8c00);'
        f'color:#fff;text-decoration:none;border-radius:8px;'
        f'font-size:13px;font-weight:700;margin:4px;'
        f'box-shadow:0 2px 6px rgba(255,102,0,.3);">'
        f'🛒 {ln["name"]}</a>'
        for ln in selected
    )

    section = (
        '\n<div style="margin-top:40px;padding:22px 20px;'
        'background:linear-gradient(135deg,#fff9f5,#fff3eb);'
        'border:1px solid #ffd4b0;border-radius:12px;text-align:center;'
        'font-family:\'Apple SD Gothic Neo\',\'Malgun Gothic\',sans-serif;">\n'
        '  <p style="font-size:14px;font-weight:700;color:#c84b00;'
        'margin:0 0 14px">📦 관련 상품 추천</p>\n'
        '  <div style="display:flex;flex-wrap:wrap;gap:8px;justify-content:center">\n'
        f'    {items_html}\n'
        '  </div>\n'
        '  <p style="font-size:10px;color:#bbb;margin:14px 0 0;line-height:1.5">'
        '이 포스트는 쿠팡 파트너스 활동의 일환으로, '
        '이에 따른 일정액의 수수료를 제공받을 수 있습니다.</p>\n'
        '</div>'
    )

    logger.info(f"쿠팡파트너스 링크 {len(selected)}개 삽입: {[ln['name'] for ln in selected]}")
    return content_html + section
