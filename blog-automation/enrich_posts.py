"""기존 발행 글 FAQ·출처 자동 보강 — AdSense "가치가 별로 없는 콘텐츠" 대응

AdSense 감사에서 blog2 발행 글 97개 중 53개가 FAQ 없음, 11개가 출처 없음으로
확인됨 — 이 두 항목은 adsense_audit.py의 자동 보완 범위 밖(본문 생성 필요)이라
리포트로만 남고 수동 수정 대상이었음. 이 모듈이 그 빈틈을 채웁니다.

동작:
  1. Blogger API로 발행 글을 스캔해 FAQ/출처 섹션 유무를 감사와 동일한
     기준으로 판별
  2. FAQ 없음 → 본문 내용만 근거로 Claude가 Q&A 2~4개 생성해
     기존 FAQ 카드와 동일한 스타일로 글 하단에 삽입
     (본문에 없는 새 사실 생성 금지 — 낚시/허위 콘텐츠 방지)
  3. 출처 없음 → research_collector로 실제 뉴스·신뢰 도메인 자료를 수집해
     참고자료 섹션 삽입. 실존 URL만 사용하며, 자료를 못 찾으면 그 글은
     건너뜀 (가짜 URL 삽입은 "존재하지 않는 콘텐츠 링크" 정책 위반이라
     안 하느니만 못함)
  4. 결과는 docs/data/enrich_report.json에 저장

Usage:
  python enrich_posts.py --blog blog2 --dry-run     # 대상만 확인
  python enrich_posts.py --blog blog2 --limit 10    # 10개만 실제 보강
  python enrich_posts.py --blog blog2 --faq-only    # FAQ만 (출처 생략)
"""

import argparse
import html as _html_esc
import json
import logging
import os
import re
import sys
import time
from datetime import datetime

import requests
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"
_BASE_DIR = os.path.dirname(__file__)
REPORT_PATH = os.path.join(_BASE_DIR, "..", "docs", "data", "enrich_report.json")

_FAQ_RE = re.compile(r'자주\s*묻는\s*질문|Frequently Asked Questions|FAQ', re.I)
_SOURCES_RE = re.compile(r'참고\s*자료|출처|références|reference', re.I)
# 면책 박스·쿠팡 파트너스 섹션 앞에 삽입하기 위한 마커 (글 끝 고정 요소들)
_TAIL_MARKERS = ['<div style="margin-top:2.5em;padding:16px 20px;background:#fffbeb', '쿠팡 파트너스']


def _plain_text(html: str, limit: int = 5000) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def needs_faq(content: str) -> bool:
    return not _FAQ_RE.search(content)


def needs_sources(content: str) -> bool:
    return not _SOURCES_RE.search(content)


# ──────────────────────────────────────────────────────────────────────────────
# FAQ 생성 (Claude — 본문 근거만 사용)
# ──────────────────────────────────────────────────────────────────────────────

def generate_faq_items(title: str, content_html: str) -> list[dict]:
    """본문 내용만 근거로 FAQ 2~4개를 생성합니다. 실패 시 빈 목록."""
    import anthropic
    from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, claude_generate

    body_text = _plain_text(content_html)
    if len(body_text) < 300:
        return []

    prompt = f"""아래 블로그 글을 읽고, 독자가 실제로 궁금해할 FAQ 2~4개를 만들어 주세요.

절대 규칙:
- 답변은 반드시 아래 본문에 이미 있는 내용만 근거로 작성 (본문에 없는 수치·사실 생성 금지)
- 본문으로 답할 수 없는 질문은 만들지 말 것
- 각 답변은 2~3문장, 자연스러운 한국어

제목: {title}

본문:
{body_text}

JSON 배열만 응답: [{{"q": "질문", "a": "답변"}}, ...]"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        raw = claude_generate(
            client,
            model=CLAUDE_MODEL,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        ).strip()
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if not m:
            return []
        items = json.loads(m.group(0))
        return [
            {"q": str(it["q"]).strip(), "a": str(it["a"]).strip()}
            for it in items
            if isinstance(it, dict) and it.get("q") and it.get("a")
        ][:4]
    except Exception as e:
        logger.warning(f"FAQ 생성 실패: {e}")
        return []


def build_faq_html(items: list[dict]) -> str:
    """기존 글의 FAQ 카드(_faq_to_cards 출력)와 동일한 스타일로 렌더링."""
    if not items:
        return ""
    card_style = (
        "background:#f8fafc;border-radius:12px;padding:20px 24px;margin:14px 0;"
        "border:1px solid #e5e7eb;box-shadow:0 2px 8px rgba(0,0,0,0.06);"
    )
    q_style = "font-weight:700;color:#1d4ed8;margin:0 0 10px;font-size:1.02em;"
    a_style = "color:#374151;margin:0;line-height:1.85;"
    cards = "".join(
        f'<div style="{card_style}">'
        f'<p style="{q_style}">Q. {_html_esc.escape(it["q"])}</p>'
        f'<p style="{a_style}">{_html_esc.escape(it["a"])}</p></div>'
        for it in items
    )
    return (
        '\n<h2 style="font-size:1.42em;font-weight:800;margin:2.8em 0 1.1em;">'
        "자주 묻는 질문</h2>\n" + cards
    )


# ──────────────────────────────────────────────────────────────────────────────
# 출처 수집 (research_collector — 실존 URL만)
# ──────────────────────────────────────────────────────────────────────────────

def collect_source_links(keyword: str, max_sources: int = 3) -> list[dict]:
    """키워드로 실제 뉴스·신뢰 도메인 자료를 수집합니다. 실패 시 빈 목록."""
    try:
        from research_collector import collect_research
        research = collect_research(keyword, max_materials=6)
        materials = research.get("materials", [])
        # 신뢰 도메인 우선, 제목·URL 있는 것만
        picked = [
            {"title": m["title"], "url": m["url"]}
            for m in materials
            if m.get("title") and m.get("url")
        ][:max_sources]
        return picked
    except Exception as e:
        logger.warning(f"출처 수집 실패 ({keyword}): {e}")
        return []


def build_sources_html(sources: list[dict]) -> str:
    if not sources:
        return ""
    items = "".join(
        f'<li style="margin:6px 0;"><a href="{_html_esc.escape(s["url"], quote=True)}" '
        f'target="_blank" rel="noopener nofollow">{_html_esc.escape(s["title"])}</a></li>'
        for s in sources
    )
    return (
        '\n<h2 style="font-size:1.42em;font-weight:800;margin:2.8em 0 1.1em;">'
        f"참고자료</h2>\n<ul>{items}</ul>"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 삽입 위치 — 면책 박스·파트너스 섹션 등 글 끝 고정 요소 앞
# ──────────────────────────────────────────────────────────────────────────────

def insert_before_tail(content: str, section_html: str) -> str:
    if not section_html:
        return content
    positions = [content.find(mk) for mk in _TAIL_MARKERS if content.find(mk) != -1]
    if positions:
        pos = min(positions)
        return content[:pos] + section_html + "\n" + content[pos:]
    return content + section_html


# ──────────────────────────────────────────────────────────────────────────────
# 메인 파이프라인
# ──────────────────────────────────────────────────────────────────────────────

def enrich_blog(blog_cfg: dict, dry_run: bool, limit: int, faq_only: bool = False) -> dict:
    from blogger_uploader import _get_access_token

    name = blog_cfg.get("name") or blog_cfg.get("id", "")
    blogger_blog_id = blog_cfg.get("blog_id", "")
    token = _get_access_token(blog_cfg)
    if not (blogger_blog_id and token):
        logger.error(f"[{name}] blog_id 또는 토큰 없음 — 건너뜀")
        return {"blog": name, "scanned": 0, "enriched": 0, "posts": []}

    logger.info(f"══ [{name}] FAQ·출처 보강 시작 (limit={limit}, dry_run={dry_run}) ══")
    scanned = enriched = 0
    report_posts: list[dict] = []
    page_token = ""

    while enriched < limit:
        params = {"maxResults": 50, "status": "live", "fetchBodies": "true",
                  "fields": "nextPageToken,items(id,title,url,content)"}
        if page_token:
            params["pageToken"] = page_token
        r = requests.get(f"{BLOGGER_API_BASE}/blogs/{blogger_blog_id}/posts",
                         headers={"Authorization": f"Bearer {token}"}, params=params, timeout=30)
        if r.status_code != 200:
            logger.error(f"글 목록 조회 실패 [{r.status_code}]: {r.text[:200]}")
            break
        data = r.json()

        for post in data.get("items", []):
            if enriched >= limit:
                break
            scanned += 1
            content = post.get("content", "")
            title = post.get("title", "")
            add_faq = needs_faq(content)
            add_sources = needs_sources(content) and not faq_only
            if not add_faq and not add_sources:
                continue

            entry = {"title": title, "url": post.get("url", ""),
                     "faq_added": False, "sources_added": False, "detail": []}

            if dry_run:
                entry["detail"].append(
                    f"[dry-run] 대상: {'FAQ ' if add_faq else ''}{'출처' if add_sources else ''}".strip())
                report_posts.append(entry)
                enriched += 1
                continue

            new_content = content
            if add_faq:
                items = generate_faq_items(title, content)
                faq_html = build_faq_html(items)
                if faq_html:
                    new_content = insert_before_tail(new_content, faq_html)
                    entry["faq_added"] = True
                    entry["detail"].append(f"FAQ {len(items)}개 생성·삽입")
                else:
                    entry["detail"].append("FAQ 생성 실패 — 건너뜀")

            if add_sources:
                sources = collect_source_links(title)
                src_html = build_sources_html(sources)
                if src_html:
                    new_content = insert_before_tail(new_content, src_html)
                    entry["sources_added"] = True
                    entry["detail"].append(f"출처 {len(sources)}건 삽입 (실존 URL 검증됨)")
                else:
                    entry["detail"].append("실존 출처 못 찾음 — 가짜 URL 방지 위해 생략")

            if new_content != content:
                pr = requests.patch(
                    f"{BLOGGER_API_BASE}/blogs/{blogger_blog_id}/posts/{post['id']}",
                    headers={"Authorization": f"Bearer {token}",
                             "Content-Type": "application/json"},
                    json={"content": new_content}, timeout=30)
                if pr.status_code == 200:
                    enriched += 1
                    logger.info(f"  ✅ 보강 완료: {title[:45]} ({', '.join(entry['detail'])})")
                else:
                    entry["detail"].append(f"업데이트 실패 [{pr.status_code}]")
                    logger.error(f"  ❌ 업데이트 실패 [{pr.status_code}]: {title[:45]}")
                time.sleep(2)  # Blogger API + Claude 호출 과부하 방지

            report_posts.append(entry)

        page_token = data.get("nextPageToken", "")
        if not page_token:
            break

    logger.info(f"══ [{name}] 스캔 {scanned}건 / 보강 {enriched}건 ══")
    return {"blog": name, "scanned": scanned, "enriched": enriched, "posts": report_posts}


def main() -> int:
    parser = argparse.ArgumentParser(description="발행 글 FAQ·출처 자동 보강")
    parser.add_argument("--blog", default="blog2", help="블로그 ID (기본 blog2, 'all'=전체)")
    parser.add_argument("--dry-run", action="store_true", help="대상만 확인, 수정 없음")
    parser.add_argument("--limit", type=int, default=10, help="이번 실행에서 보강할 최대 글 수 (기본 10)")
    parser.add_argument("--faq-only", action="store_true", help="FAQ만 보강 (출처 생략)")
    args = parser.parse_args()

    from config import get_blog_configs
    blogs = get_blog_configs()
    if args.blog != "all":
        blogs = [b for b in blogs if b.get("id") == args.blog]
        if not blogs:
            logger.error(f"블로그 '{args.blog}' 없음")
            return 1

    results = [enrich_blog(cfg, args.dry_run, args.limit, args.faq_only) for cfg in blogs]

    report = {
        "enrichedAt": datetime.now().isoformat(),
        "dryRun": args.dry_run,
        "results": results,
    }
    try:
        os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info(f"보강 리포트 저장: {REPORT_PATH}")
    except Exception as e:
        logger.warning(f"리포트 저장 실패 (무시): {e}")

    total = sum(r["enriched"] for r in results)
    logger.info("=" * 55)
    logger.info(f"전체 완료 — 보강 {total}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
