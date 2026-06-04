"""Blogger 업로드 — AdSense 6슬롯 + 구조화 데이터 + 목차 포함"""

import json
import logging
import re
import requests
from datetime import datetime

from config import (
    BLOGGER_CLIENT_ID,
    BLOGGER_CLIENT_SECRET,
    BLOGGER_BLOG_ID,
    BLOGGER_REFRESH_TOKEN,
    POST_STATUS,
    ADSENSE_CLIENT_ID,
    ADSENSE_SLOT_IDS,
)

logger = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"


# ──────────────────────────────────────────────────────────────────────────────
# OAuth
# ──────────────────────────────────────────────────────────────────────────────

def _get_access_token() -> str | None:
    resp = requests.post(TOKEN_URL, data={
        "client_id": BLOGGER_CLIENT_ID,
        "client_secret": BLOGGER_CLIENT_SECRET,
        "refresh_token": BLOGGER_REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }, timeout=15)
    if resp.status_code == 200:
        return resp.json().get("access_token")
    logger.error(f"토큰 발급 실패: {resp.status_code} {resp.text}")
    if "invalid_grant" in resp.text:
        logger.error("💡 해결: blog-automation/get_refresh_token.py 실행 후 GOOGLE_REFRESH_TOKEN Secret을 새 토큰으로 교체하세요.")
    return None


# ──────────────────────────────────────────────────────────────────────────────
# AdSense 광고 슬롯 생성
# ──────────────────────────────────────────────────────────────────────────────

def _ad_unit(slot_index: int) -> str:
    """반응형 AdSense 광고 유닛 HTML."""
    if not ADSENSE_CLIENT_ID or ADSENSE_CLIENT_ID == "ca-pub-XXXXXXXXXXXXXXXXX":
        return ""
    slots = ADSENSE_SLOT_IDS
    slot_id = slots[slot_index % len(slots)] if slots else "0000000000"
    return f"""
<!-- AdSense 광고 슬롯 {slot_index + 1} -->
<div style="margin:2em auto;text-align:center;max-width:728px;overflow:hidden;">
  <ins class="adsbygoogle"
    style="display:block;width:100%;min-height:100px;"
    data-ad-client="{ADSENSE_CLIENT_ID}"
    data-ad-slot="{slot_id}"
    data-ad-format="auto"
    data-full-width-responsive="true"></ins>
  <script>(adsbygoogle = window.adsbygoogle || []).push({{}});</script>
</div>
"""


def _inject_ads(html: str) -> str:
    """
    광고 슬롯 6개를 전략적 위치에 삽입:
      슬롯 1 — 도입부 첫 <p> 다음 (Above the fold, 최고 CTR)
      슬롯 2 — 2번째 H2 앞
      슬롯 3 — 3번째 H2 앞
      슬롯 4 — 4번째 H2 앞
      슬롯 5 — FAQ H2 앞
      슬롯 6 — 본문 끝
    """
    # 슬롯 1: 첫 번째 </p> 뒤
    ad0 = _ad_unit(0)
    html = re.sub(r'</p>', lambda m: m.group(0) + ad0, html, count=1, flags=re.IGNORECASE)

    # 슬롯 2~5: H2 태그 앞 (2~5번째)
    h2_positions = [m.start() for m in re.finditer(r'<h2', html, re.IGNORECASE)]
    targets = h2_positions[1:5]
    offset = 0
    for i, pos in enumerate(targets):
        ad = _ad_unit(i + 1)
        actual = pos + offset
        html = html[:actual] + ad + html[actual:]
        offset += len(ad)

    # 슬롯 6: 본문 끝
    html += _ad_unit(5)
    return html


# ──────────────────────────────────────────────────────────────────────────────
# 구조화 데이터 (JSON-LD)
# ──────────────────────────────────────────────────────────────────────────────

def _article_schema(post_data: dict) -> str:
    schema = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": post_data.get("title", ""),
        "description": post_data.get("meta_description", ""),
        "author": {"@type": "Organization", "name": "오늘의 핫이슈"},
        "datePublished": datetime.now().isoformat(),
        "dateModified": datetime.now().isoformat(),
        "keywords": ", ".join(post_data.get("labels", [])),
        "inLanguage": "ko-KR",
    }
    return f'<script type="application/ld+json">{json.dumps(schema, ensure_ascii=False)}</script>\n'


def _faq_schema(faq: list[dict]) -> str:
    if not faq:
        return ""
    schema = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": item.get("q", ""),
                "acceptedAnswer": {"@type": "Answer", "text": item.get("a", "")},
            }
            for item in faq
        ],
    }
    return f'<script type="application/ld+json">{json.dumps(schema, ensure_ascii=False)}</script>\n'


# ──────────────────────────────────────────────────────────────────────────────
# 목차 (Table of Contents)
# ──────────────────────────────────────────────────────────────────────────────

def _add_h2_ids(html: str) -> str:
    """H2 태그에 id 속성을 추가해 목차 앵커 링크가 작동하게 합니다. 중복 slug 방지."""
    used_slugs: dict[str, int] = {}

    def replacer(m: re.Match) -> str:
        inner = m.group(1)
        clean = re.sub(r'<[^>]+>', '', inner).strip()
        base_slug = re.sub(r'[^\w가-힣]', '-', clean).strip('-')[:40]
        count = used_slugs.get(base_slug, 0)
        used_slugs[base_slug] = count + 1
        slug = base_slug if count == 0 else f'{base_slug}-{count}'
        return f'<h2 id="{slug}">{inner}</h2>'

    return re.sub(r'<h2[^>]*>(.*?)</h2>', replacer, html, flags=re.IGNORECASE | re.DOTALL)


def _build_toc(html: str) -> str:
    """H2 태그를 파싱해 목차 HTML을 생성합니다."""
    headings = re.findall(r'<h2[^>]*id="([^"]+)"[^>]*>(.*?)</h2>', html, re.IGNORECASE | re.DOTALL)
    if len(headings) < 2:
        return ""

    items = []
    for slug, inner in headings:
        clean = re.sub(r'<[^>]+>', '', inner).strip()
        items.append(
            f'<li><a href="#{slug}" style="color:#4a90e2;text-decoration:none;">'
            f'{clean}</a></li>'
        )

    return f"""
<div style="background:#f8f9fa;border-left:4px solid #4a90e2;border-radius:8px;
padding:20px 24px;margin:2em 0;max-width:680px;">
  <p style="font-weight:700;font-size:16px;margin:0 0 12px;">📋 목차</p>
  <ol style="margin:0;padding-left:20px;line-height:2;">
    {"".join(items)}
  </ol>
</div>
"""


# ──────────────────────────────────────────────────────────────────────────────
# 최종 HTML 조립
# ──────────────────────────────────────────────────────────────────────────────

def _build_full_content(post_data: dict) -> str:
    """SEO 완전 최적화 HTML을 구성합니다."""
    html = post_data.get("content", "")
    faq = post_data.get("faq", [])
    labels = post_data.get("labels", [])

    # ① H2에 id 부여 (중복 slug 방지 포함)
    html = _add_h2_ids(html)

    # ② 목차 생성 — 첫 번째 </p> 뒤에 삽입
    toc = _build_toc(html)
    if toc:
        idx = html.lower().find('</p>')
        if idx != -1:
            html = html[:idx + 4] + toc + html[idx + 4:]
        else:
            html = toc + html

    # ③ AdSense 광고 삽입
    html = _inject_ads(html)

    # ④ 태그 클라우드 (내부 링크 효과)
    tag_links = "".join(
        f'<a href="/search/label/{label}" '
        f'style="display:inline-block;margin:4px;padding:5px 14px;'
        f'background:#e8f0fe;border-radius:20px;text-decoration:none;'
        f'color:#1a73e8;font-size:13px;">{label}</a>'
        for label in labels[:10]
    )
    tag_section = f"""
<div style="margin:2.5em 0;padding:20px;background:#f8f9fa;border-radius:10px;">
  <p style="font-weight:700;margin:0 0 10px;">🏷️ 관련 태그</p>
  <div>{tag_links}</div>
</div>
"""

    # ⑤ 출처 섹션
    sources = post_data.get("sources", [])
    sources_section = ""
    if sources:
        source_items = "".join(
            f'<li style="margin:6px 0;">'
            f'<a href="{s.get("url", "#")}" target="_blank" rel="nofollow noopener" '
            f'style="color:#1a73e8;text-decoration:none;">'
            f'{s.get("title", s.get("url", ""))}</a></li>'
            for s in sources
        )
        sources_section = (
            '<div style="margin:2.5em 0;padding:20px 24px;background:#f1f3f4;'
            'border-radius:10px;border-left:4px solid #5f6368;">'
            '<p style="font-weight:700;font-size:15px;margin:0 0 10px;">📚 참고 자료</p>'
            f'<ul style="margin:0;padding-left:20px;line-height:1.9;font-size:14px;">{source_items}</ul>'
            '</div>'
        )

    # ⑥ 면책조항 + 소셜 공유 유도
    footer = """
<div style="margin-top:3em;padding:18px 20px;background:#fff3cd;border-radius:10px;
border-left:4px solid #ffc107;">
  <p style="font-size:13px;color:#666;margin:0;">
    📌 이 글이 도움이 됐다면 북마크 &amp; 공유해주세요!<br>
    ⚠️ 본 콘텐츠는 AI가 최신 트렌드를 바탕으로 작성했습니다.
    투자·의료·법률 등 전문 분야는 반드시 전문가와 상담하세요.
  </p>
</div>
"""

    return (
        _article_schema(post_data)
        + _faq_schema(faq)
        + '<div class="blog-post" style="max-width:800px;margin:0 auto;'
          'font-family:\'Noto Sans KR\',sans-serif;line-height:1.9;color:#222;">'
        + html
        + tag_section
        + sources_section
        + footer
        + '</div>'
    )


# ──────────────────────────────────────────────────────────────────────────────
# 업로드
# ──────────────────────────────────────────────────────────────────────────────

def upload_post(post_data: dict) -> dict | None:
    """Blogger API로 포스트를 업로드합니다."""
    access_token = _get_access_token()
    if not access_token:
        return None

    full_content = _build_full_content(post_data)
    labels = list({*post_data.get("labels", []), post_data.get("keyword", "")})

    payload = {
        "title": post_data["title"],
        "content": full_content,
        "labels": labels[:20],
    }

    url = f"{BLOGGER_API_BASE}/blogs/{BLOGGER_BLOG_ID}/posts/"
    params = {"isDraft": POST_STATUS != "live"}
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    resp = requests.post(url, json=payload, headers=headers, params=params, timeout=30)
    if resp.status_code in (200, 201):
        result = resp.json()
        logger.info(f"업로드 성공: {result.get('url', '')}")
        return result
    logger.error(f"업로드 실패: {resp.status_code} {resp.text[:300]}")
    return None


def get_blog_info() -> dict | None:
    access_token = _get_access_token()
    if not access_token:
        return None
    resp = requests.get(
        f"{BLOGGER_API_BASE}/blogs/{BLOGGER_BLOG_ID}",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    return resp.json() if resp.status_code == 200 else None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    info = get_blog_info()
    if info:
        print(f"블로그: {info.get('name')} — {info.get('url')}")
    else:
        print("연결 실패. .env 설정을 확인하세요.")
