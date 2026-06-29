"""Blogger 업로드 — AdSense 4슬롯 + 구조화 데이터 + 목차 포함"""

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

def _get_access_token(blog_config: dict | None = None) -> str | None:
    cfg = blog_config or {}
    client_id = cfg.get("client_id") or BLOGGER_CLIENT_ID
    client_secret = cfg.get("client_secret") or BLOGGER_CLIENT_SECRET
    refresh_token = cfg.get("refresh_token") or BLOGGER_REFRESH_TOKEN
    try:
        resp = requests.post(TOKEN_URL, data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }, timeout=15)
    except requests.exceptions.RequestException as e:
        logger.error(f"토큰 요청 네트워크 오류: {e}")
        return None
    if resp.status_code == 200:
        try:
            token = resp.json().get("access_token")
            if token:
                return token
        except json.JSONDecodeError as e:
            logger.error(f"토큰 응답 JSON 파싱 실패: {e}")
            return None
    logger.error(f"토큰 발급 실패: {resp.status_code} {resp.text[:200]}")
    if "invalid_grant" in resp.text:
        logger.error("💡 해결: blog-automation/get_refresh_token.py 실행 후 GOOGLE_REFRESH_TOKEN Secret을 새 토큰으로 교체하세요.")
    return None


# ──────────────────────────────────────────────────────────────────────────────
# AdSense 광고 슬롯 생성
# ──────────────────────────────────────────────────────────────────────────────

def _ad_unit(slot_index: int, blog_config: dict | None = None) -> str:
    """반응형 AdSense 광고 유닛 HTML."""
    cfg = blog_config or {}
    adsense_client = cfg.get("adsense_client_id") or ADSENSE_CLIENT_ID
    adsense_slots = cfg.get("adsense_slot_ids") or ADSENSE_SLOT_IDS
    if not adsense_client or adsense_client == "ca-pub-XXXXXXXXXXXXXXXXX":
        return ""
    slot_id = adsense_slots[slot_index % len(adsense_slots)] if adsense_slots else "0000000000"
    return f"""
<!-- AdSense 광고 슬롯 {slot_index + 1} -->
<div style="margin:2em auto;text-align:center;max-width:728px;overflow:hidden;">
  <ins class="adsbygoogle"
    style="display:block;width:100%;min-height:100px;"
    data-ad-client="{adsense_client}"
    data-ad-slot="{slot_id}"
    data-ad-format="auto"
    data-full-width-responsive="true"></ins>
  <script>(adsbygoogle = window.adsbygoogle || []).push({{}});</script>
</div>
"""


def _inject_ads(html: str, blog_config: dict | None = None) -> str:
    """
    광고 슬롯 4개를 전략적 위치에 삽입 (AdSense 콘텐츠 대비 광고 비율 준수):
      슬롯 1 — 도입부 첫 <p> 다음 (Above the fold, 최고 CTR)
      슬롯 2 — 3번째 H2 앞 (본문 중간)
      슬롯 3 — 5번째 H2 앞 (후반부)
      슬롯 4 — 본문 끝
    """
    # 슬롯 1: 목차 div 이후 첫 번째 </p> 뒤 (목차 내부 삽입 방지)
    ad0 = _ad_unit(0, blog_config)
    toc_end = html.lower().find('</div>', html.lower().find('📋 목차'))
    search_start = toc_end + 6 if toc_end != -1 else 0
    p_match = re.search(r'</p>', html[search_start:], re.IGNORECASE)
    if p_match:
        insert_at = search_start + p_match.end()
        html = html[:insert_at] + ad0 + html[insert_at:]
    else:
        html = re.sub(r'</p>', lambda m: m.group(0) + ad0, html, count=1, flags=re.IGNORECASE)

    # 슬롯 2~3: H2 태그 앞 (3번째, 5번째 — 본문 중간·후반)
    h2_positions = [m.start() for m in re.finditer(r'<h2', html, re.IGNORECASE)]
    targets = [p for i, p in enumerate(h2_positions) if i in (2, 4)]
    offset = 0
    for i, pos in enumerate(targets):
        ad = _ad_unit(i + 1, blog_config)
        actual = pos + offset
        html = html[:actual] + ad + html[actual:]
        offset += len(ad)

    # 슬롯 4: 본문 끝
    html += _ad_unit(3, blog_config)
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

def _build_full_content(post_data: dict, blog_config: dict | None = None) -> str:
    """SEO 완전 최적화 HTML을 구성합니다."""
    html = post_data.get("content", "")
    faq = post_data.get("faq", [])
    labels = post_data.get("labels", [])
    series_nav = post_data.get("series_nav", "")  # 시리즈 내비게이션 HTML

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
    html = _inject_ads(html, blog_config)

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
    ⚠️ 투자·의료·법률 등 전문 분야는 반드시 전문가와 상담하세요.
  </p>
</div>
"""

    return (
        _article_schema(post_data)
        + _faq_schema(faq)
        + '<div class="blog-post" style="max-width:800px;margin:0 auto;'
          'font-family:\'Noto Sans KR\',sans-serif;line-height:1.9;color:#222;">'
        + series_nav           # ⑦ 시리즈 내비게이션 (상단)
        + html
        + series_nav           # ⑧ 시리즈 내비게이션 (하단 — 읽은 후 다음 편 유도)
        + tag_section
        + sources_section
        + footer
        + '</div>'
    )


# ──────────────────────────────────────────────────────────────────────────────
# 업로드
# ──────────────────────────────────────────────────────────────────────────────

def upload_post(post_data: dict, blog_config: dict | None = None) -> dict | None:
    """Blogger API로 포스트를 업로드합니다."""
    if not post_data.get("title") or not post_data.get("content"):
        logger.error("포스트 제목 또는 내용이 비어있음 — 업로드 건너뜀")
        return None
    cfg = blog_config or {}
    blog_id = str(cfg.get("blog_id") or BLOGGER_BLOG_ID).strip()
    post_status = cfg.get("post_status") or POST_STATUS

    # blog_id 사전 검증 — 비어있으면 즉시 실패 (URL이 .../blogs//posts 가 됨)
    if not blog_id:
        logger.error(
            "❌ blog_id가 비어있습니다. "
            "BLOGGER_BLOG_ID Secret 또는 BLOGS_CONFIG의 blog_id 필드를 확인하세요."
        )
        return None

    access_token = _get_access_token(blog_config)
    if not access_token:
        return None

    full_content = _build_full_content(post_data, blog_config)
    kw = post_data.get("keyword", "")
    # None-safe: Claude가 "labels": null 반환해도 안전하게 처리
    raw_labels = post_data.get("labels") or []
    if not isinstance(raw_labels, list):
        raw_labels = []

    # 레이블 정제: 빈 문자열·공백만인 항목 제거, 200자 초과 자르기
    def _clean_label(lb: str) -> str:
        return str(lb).strip()[:200]

    all_labels = [_clean_label(kw)] + [_clean_label(lb) for lb in raw_labels]
    labels = [lb for lb in dict.fromkeys(all_labels) if lb][:20]

    blog_name = cfg.get("name", "")
    logger.debug(f"업로드 레이블 ({len(labels)}개): {labels[:5]}{'…' if len(labels)>5 else ''}")
    logger.info(f"업로드 대상 블로그: {blog_name or '기본'} (blog_id={blog_id})")

    payload = {
        "title": post_data.get("title", "Untitled"),
        "content": full_content,
        "labels": labels,
    }

    url = f"{BLOGGER_API_BASE}/blogs/{blog_id}/posts"
    # isDraft 파라미터: Python bool을 그대로 전달하면 "False"/"True" (대문자) 로 직렬화되어
    # Blogger API가 400을 반환할 수 있으므로 draft일 때만 명시적으로 "true" 문자열로 전달한다
    params = {"isDraft": "true"} if post_status != "live" else {}
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, params=params, timeout=30)
    except requests.exceptions.RequestException as e:
        logger.error(f"업로드 네트워크 오류: {e}")
        return None
    if resp.status_code in (200, 201):
        try:
            result = resp.json()
        except json.JSONDecodeError as e:
            logger.error(f"업로드 응답 JSON 파싱 실패: {e} — {resp.text[:300]}")
            return None
        logger.info(f"업로드 성공: {result.get('url', '')}")
        return result
    # ── 상세 에러 로깅 ─────────────────────────────────────────────────────────
    logger.error(f"업로드 실패 [{resp.status_code}]: {resp.text[:1000]}")
    logger.error(f"  요청 URL: {url} | params: {params}")
    logger.error(f"  title: {post_data.get('title', '')[:80]}")
    logger.error(f"  labels ({len(labels)}개): {labels[:5]}")

    # ── 자동 진단: 블로그 접근 확인 ───────────────────────────────────────────
    # GET /blogs/{blogId} 로 blog_id·토큰이 유효한지 먼저 검사한다
    try:
        info_resp = requests.get(
            f"{BLOGGER_API_BASE}/blogs/{blog_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        if info_resp.status_code == 200:
            blog_url = info_resp.json().get("url", "")
            logger.info(f"  ✅ 블로그 접근 확인 (blog_id·토큰 정상): {blog_url}")
            logger.info("  ➡ 400 원인은 요청 본문 문제 — <script> 태그 제거 후 재시도합니다")
            # 재시도: <script> 태그 제거 (JSON-LD 스키마 등 Blogger가 거부하는 태그 제거)
            safe_content = re.sub(
                r'<script[^>]*>.*?</script>', '', full_content,
                flags=re.DOTALL | re.IGNORECASE
            )
            payload2 = {**payload, "content": safe_content}
            try:
                resp2 = requests.post(url, json=payload2, headers=headers, params=params, timeout=30)
            except requests.exceptions.RequestException as e:
                logger.error(f"  ❌ 재시도 네트워크 오류: {e}")
                return None
            if resp2.status_code in (200, 201):
                try:
                    result = resp2.json()
                    logger.info(f"  ✅ 재시도 성공 (script 태그 제거): {result.get('url', '')}")
                    return result
                except json.JSONDecodeError:
                    pass
            logger.error(f"  ❌ 재시도도 실패 [{resp2.status_code}]: {resp2.text[:500]}")
            logger.error(f"  content 앞 300자: {safe_content[:300]}")
        elif info_resp.status_code == 404:
            logger.error(f"  ❌ 블로그 없음 [404]: BLOGGER_BLOG_ID='{blog_id}' 가 잘못됐거나 다른 계정 블로그입니다.")
        elif info_resp.status_code == 403:
            logger.error(f"  ❌ 권한 없음 [403]: OAuth 토큰에 블로그 쓰기 권한이 없습니다.")
            logger.error("  💡 blog-automation/get_refresh_token.py 실행 후 GOOGLE_REFRESH_TOKEN Secret 교체")
        else:
            logger.error(f"  ❌ 블로그 접근 실패 [{info_resp.status_code}]: {info_resp.text[:200]}")
    except requests.exceptions.RequestException as diag_e:
        logger.error(f"  진단 API 호출 오류: {diag_e}")
        logger.error(f"  content 앞 300자: {full_content[:300]}")

    return None


def get_blog_info(blog_config: dict | None = None) -> dict | None:
    cfg = blog_config or {}
    blog_id = cfg.get("blog_id") or BLOGGER_BLOG_ID
    access_token = _get_access_token(blog_config)
    if not access_token:
        return None
    try:
        resp = requests.get(
            f"{BLOGGER_API_BASE}/blogs/{blog_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        return resp.json() if resp.status_code == 200 else None
    except requests.exceptions.RequestException as e:
        logger.error(f"get_blog_info 네트워크 오류: {e}")
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    info = get_blog_info()
    if info:
        print(f"블로그: {info.get('name')} — {info.get('url')}")
    else:
        print("연결 실패. .env 설정을 확인하세요.")
