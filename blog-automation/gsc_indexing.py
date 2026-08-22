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


def _domain_property_for(site_url: str) -> str:
    """URL-프리픽스 사이트 URL에서 도메인 속성(sc-domain:) 식별자를 만듭니다.

    커스텀 도메인은 Search Console에 도메인 속성으로 등록된 경우가 많아
    (예: hoguwhat.com), URL-프리픽스 형식(https://www.hoguwhat.com/)으로
    호출하면 403이 남 — 이 경우 sc-domain: 형식으로 재시도해야 함.
    """
    from urllib.parse import urlparse
    netloc = urlparse(site_url).netloc.removeprefix("www.")
    return f"sc-domain:{netloc}" if netloc else site_url


def _is_scope_error(text: str) -> bool:
    """403이 권한(스코프) 부족 때문인지 판별합니다.

    같은 403이라도 원인이 둘입니다: (a) 토큰에 쓰기 권한이 없음,
    (b) 속성 유형이 URL-프리픽스가 아니라 도메인 속성임.
    (a)를 (b)로 오해하면 엉뚱한 재시도만 반복하게 됩니다.
    """
    low = (text or "").lower()
    return "insufficient" in low or "scope" in low or "permission" in low


def submit_sitemaps(blogs: list[dict], token: str | None = None) -> dict:
    """각 블로그의 sitemap.xml을 GSC에 (재)제출합니다. 멱등 — 반복 호출 안전."""
    token = token or _access_token()
    if not token:
        return {"submitted": 0, "failed": 0, "scopeDenied": 0}
    submitted = failed = scope_denied = 0
    for cfg in blogs:
        site = _site_url_for(cfg)
        name = cfg.get("name") or cfg.get("id", "?")
        if not site:
            logger.info(f"[{name}] 사이트 URL 없음 — 건너뜀 (blogs.json에 url 또는 gsc_site_url 설정)")
            continue
        sitemap = site + "sitemap.xml"

        def _submit(property_id: str):
            return requests.put(
                f"{GSC_API_BASE}/sites/{quote(property_id, safe='')}/sitemaps/{quote(sitemap, safe='')}",
                headers={"Authorization": f"Bearer {token}"}, timeout=20,
            )

        try:
            r = _submit(site)
            if r.status_code == 403 and not _is_scope_error(r.text):
                domain_property = _domain_property_for(site)
                logger.info(f"[{name}] URL-프리픽스 속성 403 — 도메인 속성으로 재시도: {domain_property}")
                r = _submit(domain_property)
            if r.status_code in (200, 204):
                logger.info(f"✅ [{name}] 사이트맵 제출: {sitemap}")
                submitted += 1
            elif r.status_code == 403 and _is_scope_error(r.text):
                # 속성 유형 문제로 오해하면 엉뚱한 곳을 고치게 됨 — 원인을 명시한다
                logger.error(
                    f"❌ [{name}] 사이트맵 제출 권한 없음 — refresh_token이 읽기 전용입니다. "
                    "로컬에서 get_refresh_token.py를 다시 실행해 "
                    "https://www.googleapis.com/auth/webmasters (읽기 전용 아님) 권한으로 재발급하세요."
                )
                scope_denied += 1
                failed += 1
            else:
                logger.warning(f"⚠️ [{name}] 사이트맵 제출 실패 [{r.status_code}]: {r.text[:150]}")
                failed += 1
        except Exception as e:
            logger.warning(f"⚠️ [{name}] 사이트맵 제출 오류: {e}")
            failed += 1
    if scope_denied:
        logger.error(
            f"🚨 사이트맵 {scope_denied}건이 권한 부족으로 제출되지 않았습니다 — "
            "구글이 새 글을 발견하지 못하는 직접 원인입니다"
        )
    return {"submitted": submitted, "failed": failed, "scopeDenied": scope_denied}


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
    return _sample_spread(items, limit)


def _sample_spread(items: list[dict], limit: int) -> list[dict]:
    """최신 절반 + 오래된 글에서 고르게 절반을 뽑습니다.

    최신순으로만 자르면 검사 대상이 항상 1~2일 된 글뿐이라, 발행 직후에는
    원래 색인이 안 되는 게 정상이므로 "미색인 20건"이 무엇을 뜻하는지 알 수
    없습니다. 정작 궁금한 건 "몇 주 지난 글이 색인됐는가"인데 그 표본이
    한 번도 포함되지 않았습니다 (2026-08-18 확인: 검사 20건 전부 1~2일 글).
    """
    if limit <= 0 or len(items) <= limit:
        return items[:limit] if limit > 0 else []
    recent_n = max(1, limit // 2)
    recent = items[:recent_n]
    older = items[recent_n:]
    step = max(1, len(older) // (limit - recent_n))
    spread = older[::step][:limit - recent_n]
    return recent + spread


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
            def _inspect(site_id: str):
                return requests.post(
                    INSPECT_API,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json={"inspectionUrl": p["url"], "siteUrl": site_id},
                    timeout=20,
                )

            # 어느 속성 형식이 통했는지 기록해 둡니다. 대시보드가 GSC
            # "URL 검사" 딥링크를 만들 때 resource_id로 그대로 써야 하는데,
            # 속성 형식(URL-프리픽스 vs sc-domain)을 틀리면 링크가 열리지
            # 않습니다. 여기서 실제로 200을 받은 값이 유일하게 확실한 정답입니다.
            used_property = p["site"]
            r = _inspect(used_property)
            if r.status_code == 403:
                used_property = _domain_property_for(p["site"])
                r = _inspect(used_property)
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
                            "coverage": coverage, "last_crawl": last_crawl[:10],
                            "gsc_property": used_property})
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


SITEMAP_STATUS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "docs", "data", "sitemap_status.json")


def save_sitemap_status(result: dict, blogs: list[dict]) -> None:
    """사이트맵 제출 결과를 산출물로 남깁니다.

    워크플로가 `|| true`로 이 단계를 감싸고 있어, 403·404로 실패해도
    실행은 성공으로 끝납니다. 발행을 막을 이유는 없지만 결과가 어딘가에는
    남아야 합니다 — 지금은 로그에만 있어 대시보드에도 알림에도 안 나옵니다
    (2026-08-22 확인. 같은 패턴으로 발행 중단·검증 실패를 며칠씩 놓쳤습니다).
    """
    from datetime import datetime, timezone
    payload = {
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "blogs": [b.get("name") or b.get("id", "") for b in blogs],
        **result,
        "ok": result.get("failed", 0) == 0 and result.get("submitted", 0) > 0,
    }
    path = os.path.normpath(SITEMAP_STATUS_PATH)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.warning(f"사이트맵 상태 저장 실패 (무시): {e}")


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

    exit_code = 0
    if do_submit:
        result = submit_sitemaps(blogs, token)
        save_sitemap_status(result, blogs)
        if result.get("failed"):
            # 워크플로가 || true로 감싸므로 발행을 막지는 않습니다.
            # 다만 종료 코드는 사실대로 돌려줘야 나중에 판단할 수 있습니다.
            logger.error(
                f"사이트맵 제출 실패 {result['failed']}건 "
                f"(성공 {result.get('submitted', 0)}건"
                + (f", 권한 부족 {result['scopeDenied']}건" if result.get("scopeDenied") else "")
                + ")"
            )
            exit_code = 1
    if do_inspect:
        inspect_recent(blogs, args.inspect or 20, token)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
