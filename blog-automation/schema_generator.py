"""
blog-automation/schema_generator.py
────────────────────────────────────
포스트 유형별 Schema.org JSON-LD 자동 생성 모듈.

지원 Schema 타입:
  - BlogPosting   : 모든 포스트 (기본)
  - FAQPage       : post_data["faq"] 항목이 있을 때 자동 추가
  - HowTo         : 제목/키워드에 '방법·가이드·하는법·단계·절차' 포함 시
  - Review        : 제목/키워드에 '후기·리뷰·솔직·해봤더니' 포함 시
  - BreadcrumbList: 항상 추가 (홈 > 카테고리 > 포스트)

사용법:
    from schema_generator import generate_all_schemas
    html_ld = generate_all_schemas(post_data, blog_config)
"""

import json
import re
from datetime import datetime, timezone

# ── 기본 상수 ─────────────────────────────────────────────────────────────────
_DEFAULT_BLOG_NAME = "오늘의 핫이슈"
_DEFAULT_BLOG_URL  = "https://hoguwhat1.blogspot.com"
_DEFAULT_LOGO_URL  = f"{_DEFAULT_BLOG_URL}/favicon.ico"

# ── 유형 감지 ─────────────────────────────────────────────────────────────────
_HOWTO_KEYWORDS = [
    "방법", "가이드", "하는 법", "하는법", "하는 방법",
    "절차", "단계", "따라하기", "step", "how to",
]
_REVIEW_KEYWORDS = [
    "후기", "리뷰", "솔직", "사용해봤", "써봤", "먹어봤",
    "다녀왔", "시청", "봤더니", "해봤더니", "써보니",
    "체험", "경험", "사용기", "사용 후기",
]


def _detect_types(post_data: dict) -> set[str]:
    """제목·키워드·faq 를 분석해 적용할 Schema 유형 집합 반환."""
    title   = (post_data.get("title") or "").lower()
    keyword = (post_data.get("keyword") or "").lower()
    faq     = post_data.get("faq") or []
    text    = f"{title} {keyword}"

    types: set[str] = {"BlogPosting", "BreadcrumbList"}

    if faq:
        types.add("FAQPage")
    if any(k in text for k in _HOWTO_KEYWORDS):
        types.add("HowTo")
    if any(k in text for k in _REVIEW_KEYWORDS):
        types.add("Review")

    return types


# ── 날짜 헬퍼 ─────────────────────────────────────────────────────────────────
def _parse_date(post_data: dict) -> str:
    """savedAt(YYYYMMDDHHmmss) 또는 publishedAt에서 ISO-8601 변환."""
    saved = post_data.get("savedAt") or ""
    if saved and len(saved) >= 14 and saved.isdigit():
        try:
            dt = datetime(
                int(saved[0:4]), int(saved[4:6]), int(saved[6:8]),
                int(saved[8:10]), int(saved[10:12]), int(saved[12:14]),
                tzinfo=timezone.utc,
            )
            return dt.isoformat()
        except ValueError:
            pass
    return datetime.now(timezone.utc).isoformat()


# ── 개별 Schema 빌더 ──────────────────────────────────────────────────────────
def _blog_posting(post_data: dict, cfg: dict) -> dict:
    """BlogPosting — 모든 포스트 기본 Schema."""
    blog_name = cfg.get("name") or _DEFAULT_BLOG_NAME
    blog_url  = cfg.get("blog_url") or _DEFAULT_BLOG_URL
    logo_url  = cfg.get("logo_url") or _DEFAULT_LOGO_URL

    title       = post_data.get("title") or ""
    description = (
        post_data.get("metaDescription")
        or post_data.get("meta_description")
        or title
    )
    labels  = post_data.get("labels") or []
    keyword = post_data.get("keyword") or ""
    all_kw  = list(dict.fromkeys(([keyword] if keyword else []) + labels))
    date_str = _parse_date(post_data)
    post_url = post_data.get("blogUrl") or blog_url

    return {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": title,
        "description": description,
        "keywords": ", ".join(all_kw[:10]),
        "inLanguage": "ko-KR",
        "url": post_url,
        "datePublished": date_str,
        "dateModified":  date_str,
        "author": {
            "@type": "Organization",
            "name": blog_name,
            "url":  blog_url,
        },
        "publisher": {
            "@type": "Organization",
            "name": blog_name,
            "url":  blog_url,
            "logo": {
                "@type": "ImageObject",
                "url": logo_url,
            },
        },
        "isPartOf": {
            "@type": "Blog",
            "name": blog_name,
            "url":  blog_url,
        },
        "mainEntityOfPage": {
            "@type": "WebPage",
            "@id":  post_url,
        },
    }


def _faq_page(faq: list[dict]) -> dict | None:
    """FAQPage — faq 항목이 있을 때."""
    entities = [
        {
            "@type": "Question",
            "name":  item.get("question", ""),
            "acceptedAnswer": {
                "@type": "Answer",
                "text":  item.get("answer", ""),
            },
        }
        for item in faq
        if item.get("question") and item.get("answer")
    ]
    if not entities:
        return None
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": entities,
    }


def _howto(post_data: dict) -> dict | None:
    """HowTo — content 내 <ol><li> 에서 step 자동 추출."""
    content = post_data.get("content") or ""
    title   = post_data.get("title") or ""
    desc    = (
        post_data.get("metaDescription")
        or post_data.get("meta_description")
        or title
    )

    # ol 블록 안 li 우선 추출
    ol_blocks = re.findall(
        r'<ol[^>]*>(.*?)</ol>', content,
        flags=re.DOTALL | re.IGNORECASE,
    )
    raw_items = []
    for block in ol_blocks:
        raw_items += re.findall(r'<li[^>]*>(.*?)</li>', block,
                                flags=re.DOTALL | re.IGNORECASE)

    # ol이 없으면 ul 전체에서 추출
    if not raw_items:
        raw_items = re.findall(
            r'<li[^>]*>(.*?)</li>', content,
            flags=re.DOTALL | re.IGNORECASE,
        )

    clean = [re.sub(r'<[^>]+>', '', li).strip() for li in raw_items]
    steps = [s for s in clean if len(s) > 5][:10]
    if len(steps) < 2:
        return None

    return {
        "@context": "https://schema.org",
        "@type": "HowTo",
        "name": title,
        "description": desc,
        "inLanguage": "ko-KR",
        "step": [
            {
                "@type": "HowToStep",
                "position": idx + 1,
                "name": step[:80],
                "text": step[:300],
            }
            for idx, step in enumerate(steps)
        ],
    }


def _review(post_data: dict, cfg: dict) -> dict:
    """Review — 후기/리뷰 포스트."""
    blog_name = cfg.get("name") or _DEFAULT_BLOG_NAME
    blog_url  = cfg.get("blog_url") or _DEFAULT_BLOG_URL
    title     = post_data.get("title") or ""
    keyword   = post_data.get("keyword") or ""

    # 리뷰 대상 추출 (키워드 우선, 없으면 제목에서 후기/리뷰 앞부분)
    item_name = keyword or re.split(r"[,\s]*(?:후기|리뷰|솔직)", title)[0].strip() or title

    return {
        "@context": "https://schema.org",
        "@type": "Review",
        "name": title,
        "reviewBody": (
            post_data.get("metaDescription")
            or post_data.get("meta_description")
            or title
        ),
        "inLanguage": "ko-KR",
        "author": {
            "@type": "Organization",
            "name": blog_name,
            "url":  blog_url,
        },
        "itemReviewed": {
            "@type": "Thing",
            "name": item_name,
        },
    }


def _breadcrumb(post_data: dict, cfg: dict) -> dict:
    """BreadcrumbList — 홈 > 카테고리 > 포스트."""
    blog_name = cfg.get("name") or _DEFAULT_BLOG_NAME
    blog_url  = cfg.get("blog_url") or _DEFAULT_BLOG_URL
    title     = post_data.get("title") or ""
    post_url  = post_data.get("blogUrl") or blog_url

    labels   = post_data.get("labels") or []
    keyword  = post_data.get("keyword") or ""
    category = labels[0] if labels else (keyword or "블로그")

    from urllib.parse import quote as _q
    cat_url = f"{blog_url}/search/label/{_q(category, safe='')}"

    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": blog_name,  "item": blog_url},
            {"@type": "ListItem", "position": 2, "name": category,   "item": cat_url},
            {"@type": "ListItem", "position": 3, "name": title,      "item": post_url},
        ],
    }


# ── 공개 API ─────────────────────────────────────────────────────────────────
def generate_all_schemas(post_data: dict, blog_config: dict | None = None) -> str:
    """
    포스트에 맞는 Schema.org JSON-LD 전체를 <script> 태그 문자열로 반환.

    Args:
        post_data   : pending_posts.json 항목 (title, keyword, labels, faq, content, ...)
        blog_config : BLOGS_CONFIG 항목 (name, blog_url, logo_url, ...)

    Returns:
        하나 이상의 <script type="application/ld+json">...</script> 연결 문자열
    """
    cfg    = blog_config or {}
    faq    = post_data.get("faq") or []
    types  = _detect_types(post_data)
    schemas: list[dict] = []

    # 1) BlogPosting — 항상
    schemas.append(_blog_posting(post_data, cfg))

    # 2) FAQPage — faq가 있을 때
    if "FAQPage" in types:
        faq_schema = _faq_page(faq)
        if faq_schema:
            schemas.append(faq_schema)

    # 3) HowTo — 방법/가이드 포스트
    if "HowTo" in types:
        howto_schema = _howto(post_data)
        if howto_schema:
            schemas.append(howto_schema)

    # 4) Review — 후기/리뷰 포스트
    if "Review" in types:
        schemas.append(_review(post_data, cfg))

    # 5) BreadcrumbList — 항상
    schemas.append(_breadcrumb(post_data, cfg))

    return "\n".join(
        f'<script type="application/ld+json">'
        f'{json.dumps(s, ensure_ascii=False, separators=(",", ":"))}'
        f'</script>'
        for s in schemas
    ) + "\n"
