"""발행 글 죽은 링크(href="#") 스캔·수정 — AdSense '탐색' 정책 위반 대응

글 생성기가 본문 하단에 넣던 <a href="#">관련 글</a> 링크는 어디로도
연결되지 않아 AdSense '존재하지 않는 콘텐츠로 연결되는 링크' 위반입니다.

동작:
  1. 발행 글 전체 스캔 → href="#" 링크 감지
  2. (실제 수정 시) 같은 블로그의 실제 발행 글 중 제목 유사도가 높은 글의
     URL로 교체, 매칭할 글이 없으면 링크 태그 제거(텍스트만 남김/블록 정리)
  3. 리포트 docs/data/dead_links.json 저장

Usage:
  python fix_dead_links.py --dry-run           # 스캔만 (수정 없음)
  python fix_dead_links.py                     # 실제 수정
  python fix_dead_links.py --blog blog1
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from blogger_posts import ListingTruncated, iter_posts  # noqa: F401
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"
_DOCS_DATA = os.path.join(os.path.dirname(__file__), "..", "docs", "data")

_DEAD_A_RE = re.compile(r'<a\b[^>]*href="#"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)


def _iter_posts(blog_id: str, token: str):
    """블로그의 발행(live) 글 전체를 순회합니다 (공용 구현 위임).

    예전에는 이 모듈이 자체 사본을 들고 있었고, 비200 응답에 로그만 남기고
    return해 목록이 조용히 잘렸습니다. 사본이 넷이라 수정이 한 곳에만
    반영돼 나머지는 버그를 그대로 안고 있었습니다.
    """
    yield from iter_posts(blog_id, token)


def _title_words(t: str) -> set:
    return {w for w in re.split(r"[\s,·—-]+", (t or "").lower()) if len(w) >= 2}


def _best_match_url(link_text: str, catalog: list[dict], self_url: str) -> str:
    """죽은 링크 텍스트와 제목이 가장 유사한 실제 발행 글 URL (임계 미달 시 "")."""
    lw = _title_words(link_text)
    if not lw:
        return ""
    best, best_score = "", 0.0
    for p in catalog:
        if p["url"] == self_url:
            continue
        tw = _title_words(p["title"])
        if not tw:
            continue
        score = len(lw & tw) / len(lw | tw)
        if score > best_score:
            best, best_score = p["url"], score
    return best if best_score >= 0.25 else ""


def fix_dead_links_in_content(content: str, catalog: list[dict], self_url: str) -> tuple[str, int, int]:
    """href="#" 링크를 실제 URL로 교체하거나 제거. Returns (new, replaced, removed)."""
    replaced = removed = 0

    def _sub(m: re.Match) -> str:
        nonlocal replaced, removed
        text = m.group(1)
        plain = re.sub(r"<[^>]+>", "", text).strip()
        url = _best_match_url(plain, catalog, self_url)
        if url:
            replaced += 1
            return m.group(0).replace('href="#"', f'href="{url}"')
        removed += 1
        return plain  # 링크 제거, 텍스트만 유지

    new = _DEAD_A_RE.sub(_sub, content)
    if removed:
        # 링크가 전부 제거돼 "제목1 / 제목2 / 제목3"만 남은 관련 글 블록 정리:
        # 구분자 슬래시가 어색하게 남는 것 정도는 허용 (텍스트 자체는 무해)
        pass
    return new, replaced, removed


def scan_and_fix(blogs: list[dict], dry_run: bool) -> dict:
    from blogger_uploader import _get_access_token

    report_items = []
    total_scanned = total_dead = fixed_posts = failed = 0

    for cfg in blogs:
        name = cfg.get("name") or cfg.get("id", "")
        blog_id = cfg.get("blog_id", "")
        if not blog_id:
            continue
        token = _get_access_token(cfg)
        if not token:
            logger.error(f"[{name}] 토큰 없음 — 건너뜀")
            continue

        logger.info(f"── [{name}] 발행 글 스캔 ──")
        posts = list(_iter_posts(blog_id, token))
        catalog = [{"title": p.get("title", ""), "url": p.get("url", "")} for p in posts]

        for p in posts:
            total_scanned += 1
            content = p.get("content", "")
            dead = _DEAD_A_RE.findall(content)
            if not dead:
                continue
            total_dead += len(dead)
            texts = [re.sub(r"<[^>]+>", "", d).strip()[:30] for d in dead[:3]]
            logger.info(f"  🔗 죽은 링크 {len(dead)}개: '{p.get('title','')[:40]}' — {texts}")

            item = {"blog": name, "title": p.get("title", "")[:60],
                    "url": p.get("url", ""), "dead_links": len(dead),
                    "link_texts": texts}

            if not dry_run:
                new_content, rep, rem = fix_dead_links_in_content(content, catalog, p.get("url", ""))
                pr = requests.patch(
                    f"{BLOGGER_API_BASE}/blogs/{blog_id}/posts/{p['id']}",
                    headers={"Authorization": f"Bearer {token}",
                             "Content-Type": "application/json"},
                    json={"content": new_content}, timeout=30)
                if pr.status_code == 200:
                    fixed_posts += 1
                    item["result"] = f"교체 {rep} / 제거 {rem}"
                    logger.info(f"    ✅ 수정 완료 (실제 글 교체 {rep} / 링크 제거 {rem})")
                else:
                    failed += 1
                    item["result"] = f"실패 {pr.status_code}"
                    logger.error(f"    ❌ 수정 실패 [{pr.status_code}]")
                time.sleep(1)
            report_items.append(item)

    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "scanned_posts": total_scanned,
        "posts_with_dead_links": len(report_items),
        "total_dead_links": total_dead,
        "fixed_posts": fixed_posts,
        "failed": failed,
        "items": report_items[:100],
    }
    try:
        os.makedirs(_DOCS_DATA, exist_ok=True)
        with open(os.path.join(_DOCS_DATA, "dead_links.json"), "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"리포트 저장 실패: {e}")

    mode = "(미리보기) " if dry_run else ""
    logger.info("=" * 55)
    logger.info(
        f"{mode}완료 — 글 {total_scanned}건 스캔 / 죽은 링크 보유 글 {len(report_items)}건 "
        f"(링크 {total_dead}개) / 수정 {fixed_posts}건 / 실패 {failed}건"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="죽은 링크(href=#) 스캔·수정")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--blog", default="")
    args = parser.parse_args()

    from config import get_blog_configs
    blogs = get_blog_configs()
    if args.blog:
        blogs = [b for b in blogs if b.get("id") == args.blog] or blogs

    report = scan_and_fix(blogs, args.dry_run)
    return 0 if report.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
