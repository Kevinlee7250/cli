"""Blogger 업로드 — AdSense 4슬롯 + 구조화 데이터 + 목차 포함"""

import json
import logging
import re
import requests
from datetime import datetime
from schema_generator import generate_all_schemas
from related_posts import build_related_section

from config import (
    BLOGGER_CLIENT_ID,
    BLOGGER_CLIENT_SECRET,
    BLOGGER_BLOG_ID,
    BLOGGER_REFRESH_TOKEN,
    POST_STATUS,
    ADSENSE_CLIENT_ID,
    ADSENSE_SLOT_IDS,
    ADSENSE_MODE,
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
    """반응형 AdSense 광고 유닛 HTML.
    auto 모드에서는 빈 문자열 반환 — 광고는 Blogger 테마의 자동 광고 스크립트가 처리.
    """
    cfg = blog_config or {}
    mode = cfg.get("adsense_mode") or ADSENSE_MODE
    if mode == "auto":
        return ""
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
    # </ol> 을 기준으로 목차 끝 위치를 잡는다 — 내부 </div> 오인 방지
    ad0 = _ad_unit(0, blog_config)
    toc_pos = html.find('📋 목차')
    if toc_pos != -1:
        ol_end = html.lower().find('</ol>', toc_pos)
        search_start = ol_end + 5 if ol_end != -1 else 0
    else:
        search_start = 0
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
    """H2 태그에 id 속성을 추가해 목차 앵커 링크가 작동하게 합니다. 기존 속성 보존. 중복 slug 방지."""
    used_slugs: dict[str, int] = {}

    def replacer(m: re.Match) -> str:
        attrs = m.group(1)  # 기존 속성들 (style 포함)
        inner = m.group(2)
        # 이미 id가 있으면 slug만 덮어쓰지 않고 그대로 유지
        if re.search(r'\bid=', attrs, re.I):
            return f'<h2{attrs}>{inner}</h2>'
        clean = re.sub(r'<[^>]+>', '', inner).strip()
        base_slug = re.sub(r'[^\w가-힣]', '-', clean).strip('-')[:40]
        count = used_slugs.get(base_slug, 0)
        used_slugs[base_slug] = count + 1
        slug = base_slug if count == 0 else f'{base_slug}-{count}'
        return f'<h2{attrs} id="{slug}">{inner}</h2>'

    return re.sub(r'<h2([^>]*)>(.*?)</h2>', replacer, html, flags=re.IGNORECASE | re.DOTALL)


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

    # ① Blogger가 거부하는 속성 사전 제거 (aria-*, itemscope, itemtype 등)
    html = _sanitize_for_blogger(html)

    # ② H2에 id 부여 (중복 slug 방지 포함)
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
    from urllib.parse import quote as _url_quote
    tag_links = "".join(
        f'<a href="/search/label/{_url_quote(label, safe="")}" '
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
    # ── 관련 포스트 섹션 (유사도 기반 자동 추천) ──
    try:
        related_section = build_related_section(post_data, blog_config)
    except Exception as _rp_e:
        logger.warning(f'related_section 생성 실패: {_rp_e}')
        related_section = ''

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
        generate_all_schemas(post_data, blog_config)
        + '<div class="blog-post" style="max-width:800px;margin:0 auto;'
          'font-family:\'Noto Sans KR\',sans-serif;line-height:1.9;color:#222;">'
        + series_nav           # ⑦ 시리즈 내비게이션 (상단)
        + html
        + series_nav           # ⑧ 시리즈 내비게이션 (하단 — 읽은 후 다음 편 유도)
        + related_section
        + tag_section
        + sources_section
        + footer
        + '</div>'
    )


# ──────────────────────────────────────────────────────────────────────────────
# 업로드
# ──────────────────────────────────────────────────────────────────────────────

def _sanitize_for_blogger(html: str) -> str:
    """Blogger API 호환성: 거부되는 HTML 요소 제거 및 변환.
    실제 테스트로 확인된 Blogger API 거부 요소:
      - <script> 태그 (JSON-LD 제외 — AdSense push만 제거)
      - <ins> 태그 (AdSense <ins class="adsbygoogle"> 포함)
      - data-ad-* 속성 (AdSense 광고 데이터)
      - <nav>, <section>, <main>, <aside>, <header>, <footer> 시맨틱 태그
      - aria-* 속성
      - id 속성 (앵커 타겟)
      - href="#..." 내부 앵커 링크
    성공 사례에서 허용 확인됨: <article>, <p>, <h2>, <ul>, <li>, <div>
    """
    # <script> 태그 제거 — JSON-LD(application/ld+json)는 SEO 필수이므로 유지
    html = re.sub(
        r'<script(?![^>]*type=["\']application/ld\+json["\'])[^>]*>.*?</script>',
        '', html, flags=re.DOTALL | re.IGNORECASE
    )
    # AdSense 광고 블록 전체 제거 (<!-- AdSense ... --> 주석 + <ins> + </div>)
    html = re.sub(r'<!--\s*AdSense 광고 슬롯[^>]*-->.*?</div>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # <ins> 태그 제거 (잔여 AdSense 코드)
    html = re.sub(r'<ins[^>]*>.*?</ins>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<ins[^>]*/>', '', html, flags=re.IGNORECASE)
    # data-ad-* 속성 제거 (AdSense 커스텀 속성)
    html = re.sub(r'\s+data-ad-[\w-]+="[^"]*"', '', html, flags=re.IGNORECASE)
    html = re.sub(r"\s+data-ad-[\w-]+='[^']*'", '', html, flags=re.IGNORECASE)
    # HTML5 시맨틱 블록 태그 → <div> 변환
    for tag in ['nav', 'section', 'main', 'aside', 'header', 'footer']:
        html = re.sub(f'<{tag}([^>]*)>', r'<div\1>', html, flags=re.IGNORECASE)
        html = re.sub(f'</{tag}>', '</div>', html, flags=re.IGNORECASE)
    # aria-* 속성 제거
    html = re.sub(r'\s+aria-[\w-]+="[^"]*"', '', html)
    html = re.sub(r"\s+aria-[\w-]+='[^']*'", '', html)
    # id 속성 제거 (앵커 타겟)
    html = re.sub(r'\s+id="[^"]*"', '', html, flags=re.IGNORECASE)
    html = re.sub(r"\s+id='[^']*'", '', html, flags=re.IGNORECASE)
    # 내부 앵커 링크 href="#..." → 텍스트만 남김
    html = re.sub(
        r'<a[^>]*\shref="#[^"]*"[^>]*>(.*?)</a>',
        r'\1', html, flags=re.IGNORECASE | re.DOTALL
    )
    # /search/label/ 한국어 비인코딩 href → 텍스트로 변환 (Blogger API 400 원인)
    html = re.sub(
        r'<a[^>]*\shref="/search/label/[^"]*"[^>]*>(.*?)</a>',
        r'\1', html, flags=re.IGNORECASE | re.DOTALL
    )
    return html


# ──────────────────────────────────────────────────────────────────────────────
# AdSense 자동 광고 — Blogger 테마 주입
# ──────────────────────────────────────────────────────────────────────────────

_ADSENSE_SCRIPT_MARKER = "pagead2.googlesyndication.com/pagead/js/adsbygoogle.js"


def inject_adsense_to_theme(blog_config: dict | None = None) -> bool:
    """Blogger 테마 <head>에 AdSense 자동 광고 스크립트를 삽입합니다.

    Blogger Templates API (layout / skin)를 순차 시도하고,
    API가 지원되지 않으면 수동 설치 안내를 로그로 출력합니다.

    반환값: True=성공(또는 이미 존재), False=API 불가(수동 안내 출력됨)
    """
    cfg = blog_config or {}
    token = _get_access_token(cfg)
    if not token:
        logger.error("OAuth 토큰 발급 실패 — AdSense 테마 주입 중단")
        return False

    blog_id = str(cfg.get("blog_id") or BLOGGER_BLOG_ID).strip()
    pub_id = cfg.get("adsense_client_id") or ADSENSE_CLIENT_ID

    if not pub_id or pub_id == "ca-pub-XXXXXXXXXXXXXXXXX":
        logger.error("ADSENSE_CLIENT_ID가 설정되지 않았습니다 — GitHub Secrets에 추가하세요")
        return False

    adsense_script = (
        f'  <script async src="https://pagead2.googlesyndication.com'
        f'/pagead/js/adsbygoogle.js?client={pub_id}"'
        f' crossorigin="anonymous"></script>'
    )

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    for tpl_type in ["layout", "skin"]:
        url = f"{BLOGGER_API_BASE}/blogs/{blog_id}/templates/{tpl_type}"
        try:
            resp = requests.get(url, headers=headers, timeout=15)
        except requests.exceptions.RequestException as e:
            logger.debug(f"템플릿 GET 네트워크 오류 ({tpl_type}): {e}")
            continue

        if resp.status_code != 200:
            logger.debug(f"템플릿 {tpl_type} GET {resp.status_code} — 다음 시도")
            continue

        try:
            tpl = resp.json()
        except Exception:
            continue

        # 응답 구조에서 실제 HTML/XML 문자열 추출
        template_html = tpl.get("template") or tpl.get("skin") or ""
        if not template_html:
            continue

        if _ADSENSE_SCRIPT_MARKER in template_html:
            logger.info("✅ AdSense 자동 광고 스크립트가 이미 Blogger 테마에 존재합니다")
            return True

        # </head> 직전에 삽입
        if "</head>" in template_html:
            new_html = template_html.replace("</head>", f"{adsense_script}\n</head>", 1)
        else:
            new_html = adsense_script + "\n" + template_html

        key = "template" if "template" in tpl else "skin"
        patch_body = {**tpl, key: new_html}

        try:
            patch = requests.patch(url, headers=headers, json=patch_body, timeout=15)
        except requests.exceptions.RequestException as e:
            logger.debug(f"템플릿 PATCH 네트워크 오류 ({tpl_type}): {e}")
            continue

        if patch.status_code in (200, 201, 204):
            logger.info(f"✅ Blogger 테마({tpl_type})에 AdSense 자동 광고 스크립트 삽입 완료")
            return True
        logger.debug(f"템플릿 PATCH {patch.status_code}: {patch.text[:120]}")

    # API 미지원 → 수동 설치 안내
    logger.warning(
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️  Blogger API 테마 자동 수정 불가 → 수동 설치 필요\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Blogger 관리자 → 테마 → HTML 편집 → </head> 바로 위에 아래 코드 삽입 후 저장:\n\n"
        f"  {adsense_script}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    return False


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

    # 업로드 직전 제목 중복 검사 — 동일/유사 제목이 이미 게시된 경우 차단
    _title = post_data.get("title", "")
    _blog_cfg_id = cfg.get("id", "")
    try:
        from post_manager import find_duplicate_post
        _dup = find_duplicate_post(_title, blog_id=_blog_cfg_id)
        if _dup:
            logger.error(
                f"❌ 중복 포스트 감지 — 업로드 차단: '{_title[:60]}'\n"
                f"   기존 포스트: '{_dup.get('title', '')[:60]}' ({_dup.get('blogUrl', '')})"
            )
            return None
    except Exception as _de:
        logger.debug(f"중복 검사 오류 (무시): {_de}")

    full_content = _build_full_content(post_data, blog_config)
    kw = post_data.get("keyword") or ""
    # None-safe: Claude가 "labels": null 반환해도 안전하게 처리 (표준 스키마 tags 폴백)
    raw_labels = post_data.get("labels") or post_data.get("tags") or []
    if not isinstance(raw_labels, list):
        raw_labels = []

    # 레이블 정제: 빈 문자열·공백만인 항목 제거, 200자 초과 자르기
    def _clean_label(lb: str) -> str:
        return str(lb).strip()[:200]

    all_labels = [_clean_label(kw)] + [_clean_label(lb) for lb in raw_labels]
    labels = [lb for lb in dict.fromkeys(all_labels) if lb][:5]  # Blogger API: 5개 초과 시 400

    blog_name = cfg.get("name", "")
    logger.debug(f"업로드 레이블 ({len(labels)}개): {labels[:5]}{'…' if len(labels)>5 else ''}")
    risk = post_data.get("risk_level", "")
    if risk == "high":
        logger.info(f"⚠️ 고위험(YMYL) 주제 업로드: '{post_data.get('keyword', '')}' — 면책·팩트체크 확인 권장")
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
            logger.info("  ➡ 400 원인은 요청 본문 문제 — 차단 속성 제거 후 재시도합니다")
            # 재시도: script 태그 + aria-* + itemscope/itemtype 등 Blogger 차단 요소 제거
            safe_content = _sanitize_for_blogger(full_content)
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


def get_post_id_by_url(blog_url: str, blog_config: dict | None = None) -> str | None:
    """Blogger 포스트 URL로 숫자 포스트 ID를 조회합니다."""
    from urllib.parse import urlparse
    if not blog_url:
        return None
    path = urlparse(blog_url).path
    if not path or path == "/":
        return None

    cfg = blog_config or {}
    blog_id = cfg.get("blog_id") or BLOGGER_BLOG_ID
    access_token = _get_access_token(blog_config)
    if not access_token:
        logger.error("get_post_id_by_url: 액세스 토큰 없음")
        return None

    try:
        resp = requests.get(
            f"{BLOGGER_API_BASE}/blogs/{blog_id}/posts/bypath",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"path": path},
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json().get("id")
        logger.warning(f"get_post_id_by_url [{resp.status_code}] path={path}: {resp.text[:200]}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"get_post_id_by_url 네트워크 오류: {e}")
        return None


def update_post(blogger_post_id: str, post_data: dict, blog_config: dict | None = None) -> dict | None:
    """기존 Blogger 포스트 내용을 업데이트합니다 (PUT /posts/{postId})."""
    cfg = blog_config or {}
    blog_id = cfg.get("blog_id") or BLOGGER_BLOG_ID
    access_token = _get_access_token(blog_config)
    if not access_token:
        logger.error("update_post: 액세스 토큰 없음")
        return None

    full_content = _build_full_content(post_data, blog_config)

    kw = post_data.get("keyword") or ""
    raw_labels = post_data.get("labels") or []
    if not isinstance(raw_labels, list):
        raw_labels = []

    def _clean_label(lb: str) -> str:
        return str(lb).strip()[:200]

    all_labels = list(dict.fromkeys(
        [_clean_label(kw)] + [_clean_label(lb) for lb in raw_labels]
    ))
    all_labels = [lb for lb in all_labels if lb][:5]

    payload = {
        "title": post_data.get("title", ""),
        "content": full_content,
        "labels": all_labels,
    }

    url = f"{BLOGGER_API_BASE}/blogs/{blog_id}/posts/{blogger_post_id}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    params = {"fetchBody": "false"}

    try:
        resp = requests.put(url, json=payload, headers=headers, params=params, timeout=30)
    except requests.exceptions.RequestException as e:
        logger.error(f"update_post 네트워크 오류: {e}")
        return None

    if resp.status_code == 200:
        try:
            result = resp.json()
        except Exception as e:
            logger.error(f"update_post 응답 파싱 오류: {e} — body: {resp.text[:200]}")
            return None
        logger.info(f"포스트 업데이트 성공: {result.get('url', blogger_post_id)}")
        return result

    logger.error(f"update_post 실패 [{resp.status_code}]: {resp.text[:500]}")
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
