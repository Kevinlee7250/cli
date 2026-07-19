"""구글 색인 가속 — 사이트맵 재제출 + 색인 상태 추적

발행 직후 검색 노출까지 걸리는 시간을 줄입니다:
  1. submit_sitemaps: 각 블로그의 sitemap.xml을 GSC에 (재)제출
     → 구글 크롤러가 새 글을 더 빨리 발견
  2. inspect_recent: URL 검사 API로 최근 발행 글의 색인 상태 확인
     → docs/data/index_status.json 리포트 (대시보드 표시용)

사용법:
  python gsc_indexing.py                 # 사이트맵 제출 + 최근 20건 검사
  python gsc_indexing.py --submit        # 사이트맵 제출만
  python gsc_indexing.py --inspect 30    # 색인 검사만 (최근 30건)
  python gsc_indexing.py --blog blog1    # 특정 블로그만

필요 권한: GOOGLE_REFRESH_TOKEN에 webmasters 스코프 (gsc_register와 동일)
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote

import requests
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
GSC_API_BASE = "https://www.googleapis.com/webmasters/v3"
INSPECT_API = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
_DOCS_DATA = os.path.join(os.path.dirname(__file__), "..", "docs", "data")


def _access_token() -> str | None:
    from config import BLOGGER_CLIENT_ID, BLOGGER_CLIENT_SECRET, BLOGGER_REFRESH_TOKEN
    try:
        resp = requests.post(TOKEN_URL, data={
            "client_id": BLOGGER_CLIENT_ID,
            "client_secret": BLOGGER_CLIENT_SECRET,
            "refresh_token": BLOGGER_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        }, timeout=15)
        if resp.status_code == 200:
            return resp.json().get("access_token")
        logger.error(f"토큰 발급 실패: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        logger.error(f"토큰 요청 오류: {e}")
    return None


def _site_url_for(cfg: dict) -> str:
    """블로그 설정에서 GSC 사이트 URL을 결정합니다."""
    site = (cfg.get("gsc_site_url") or cfg.get("url") or "").strip()
    if site and not site.endswith("/"):
        site += "/"
    return site


def submit_sitemaps(blogs: list[dict], token: str | None = None) -> dict:
    """각 블로그의 sitemap.xml을 GSC에 (재)제출합니다. 멱등 — 반복 호출 안전."""
    token = token or _access_token()
    if not token:
        return {"submitted": 0, "failed": 0}
    submitted = failed = 0
    for cfg in blogs:
        site = _site_url_for(cfg)
        name = cfg.get("name") or cfg.get("id", "?")
        if not site:
            logger.info(f"[{name}] 사이트 URL 없음 — 건너뜀 (blogs.json에 url 또는 gsc_site_url 설정)")
            continue
        sitemap = site + "sitemap.xml"
        try:
            r = requests.put(
                f"{GSC_API_BASE}/sites/{quote(site, safe='')}/sitemaps/{quote(sitemap, safe='')}",
                headers={"Authorization": f"Bearer {token}"}, timeout=20,
            )
            if r.status_code in (200, 204):
                logger.info(f"✅ [{name}] 사이트맵 제출: {sitemap}")
                submitted += 1
            else:
                logger.warning(f"⚠️ [{name}] 사이트맵 제출 실패 [{r.status_code}]: {r.text[:150]}")
                failed += 1
        except Exception as e:
            logger.warning(f"⚠️ [{name}] 사이트맵 제출 오류: {e}")
            failed += 1
    return {"submitted": submitted, "failed": failed}


def _recent_published(blogs: list[dict], limit: int) -> list[dict]:
    """레지스트리에서 최근 발행 글을 (블로그 설정과 함께) 반환합니다."""
    reg_path = os.path.join(os.path.dirname(__file__), "logs", "post_registry.json")
    try:
        registry = json.load(open(reg_path, encoding="utf-8"))
    except Exception:
        return []
    by_id = {b.get("id"): b for b in blogs}
    items = []
    for p in registry:
        if p.get("status") != "published" or not p.get("blogUrl"):
            continue
        cfg = by_id.get(p.get("blogId")) or {}
        site = _site_url_for(cfg)
        if not site:
            # 블로그 매칭 실패 시 URL 도메인으로 추정
            from urllib.parse import urlparse
            u = urlparse(p["blogUrl"])
            site = f"{u.scheme}://{u.netloc}/"
        items.append({
            "title": p.get("title", "")[:60],
            "url": p["blogUrl"],
            "site": site,
            "blog": cfg.get("name") or p.get("blogId", "?"),
            "published_at": p.get("publishedAt") or p.get("createdAt", ""),
        })
    items.sort(key=lambda x: x.get("published_at") or "", reverse=True)
    return items[:limit]


def inspect_recent(blogs: list[dict], limit: int = 20, token: str | None = None) -> dict:
    """최근 발행 글의 색인 상태를 URL 검사 API로 확인하고 리포트를 저장합니다."""
    token = token or _access_token()
    if not token:
        return {}
    posts = _recent_published(blogs, limit)
    if not posts:
        logger.info("검사할 발행 글이 없습니다")
        return {}

    results = []
    counts = {"indexed": 0, "not_indexed": 0, "unknown": 0}
    for p in posts:
        try:
            r = requests.post(
                INSPECT_API,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"inspectionUrl": p["url"], "siteUrl": p["site"]},
                timeout=20,
            )
            if r.status_code != 200:
                logger.debug(f"검사 실패 [{r.status_code}]: {p['url']} {r.text[:100]}")
                results.append({**p, "verdict": "unknown", "coverage": f"API {r.status_code}"})
                counts["unknown"] += 1
                time.sleep(0.5)
                continue
            idx = r.json().get("inspectionResult", {}).get("indexStatusResult", {})
            verdict = idx.get("verdict", "VERDICT_UNSPECIFIED")
            coverage = idx.get("coverageState", "")
            last_crawl = idx.get("lastCrawlTime", "")
            indexed = verdict == "PASS"
            counts["indexed" if indexed else "not_indexed"] += 1
            mark = "🟢" if indexed else "🟡"
            logger.info(f"{mark} [{p['blog']}] {coverage or verdict}: {p['title'][:40]}")
            results.append({**p, "verdict": "indexed" if indexed else "not_indexed",
                            "coverage": coverage, "last_crawl": last_crawl[:10]})
        except Exception as e:
            logger.debug(f"검사 오류: {p['url']} — {e}")
            results.append({**p, "verdict": "unknown", "coverage": str(e)[:60]})
            counts["unknown"] += 1
        time.sleep(0.5)  # API rate limit 배려 (분당 60)

    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        **counts,
        "items": results,
    }
    try:
        os.makedirs(_DOCS_DATA, exist_ok=True)
        with open(os.path.join(_DOCS_DATA, "index_status.json"), "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info(
            f"📋 색인 리포트 저장: 색인됨 {counts['indexed']} / "
            f"미색인 {counts['not_indexed']} / 확인불가 {counts['unknown']}"
        )
    except Exception as e:
        logger.warning(f"리포트 저장 실패: {e}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="구글 색인 가속")
    parser.add_argument("--submit", action="store_true", help="사이트맵 제출만")
    parser.add_argument("--inspect", type=int, nargs="?", const=20, default=None,
                        help="색인 검사만 (최근 N건, 기본 20)")
    parser.add_argument("--blog", default="", help="특정 블로그 ID만")
    args = parser.parse_args()

    from config import get_blog_configs
    blogs = get_blog_configs()
    if args.blog:
        blogs = [b for b in blogs if b.get("id") == args.blog] or blogs

    token = _access_token()
    if not token:
        logger.warning("GSC 토큰 발급 실패 — 색인 요청 건너뜀 (게시에는 영향 없음)")
        return 0

    do_submit = args.submit or args.inspect is None
    do_inspect = args.inspect is not None or not args.submit

    if do_submit:
        submit_sitemaps(blogs, token)
    if do_inspect:
        inspect_recent(blogs, args.inspect or 20, token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
