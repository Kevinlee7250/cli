"""내부 링크 구조 진단 — 고아 페이지를 찾습니다.

`internal_linker`는 글을 만들 때 한 번만, 한 방향으로만 돕니다:

    새 글 ──링크──▶ 기존 글 (최대 5개)     ← 있음
    기존 글 ──링크──▶ 새 글                ← 만드는 코드가 없음

그래서 모든 새 글은 **들어오는 내부 링크가 0개**인 상태로 태어납니다.
사이트 안에서 아무도 가리키지 않는 페이지는 구글이 크롤 예산을 배정할
이유가 약하고, 이는 "Discovered - currently not indexed"의 대표적 원인입니다.

이 모듈은 그 가설을 숫자로 검증합니다. 추정하지 않고 Blogger에서 실제
본문을 받아 링크를 세며, **읽기만 하고 아무것도 바꾸지 않습니다.**

집계 내용:
  · 글별 인바운드(들어오는) / 아웃바운드(나가는) 내부 링크 수
  · 고아 페이지 — 인바운드 0개
  · 색인 상태와의 교차 (index_status.json이 있으면)

Usage:
  python internal_link_audit.py                # 전체 블로그
  python internal_link_audit.py --blog blog1
  python internal_link_audit.py --limit 100    # 블로그당 최대 조회 수
"""

import argparse
import json
import logging
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"
_BASE_DIR = os.path.dirname(__file__)
_DOCS_DATA = os.path.join(_BASE_DIR, "..", "docs", "data")
REPORT_PATH = os.path.join(_DOCS_DATA, "internal_links.json")

_HREF_RE = re.compile(r'<a[^>]+href=["\']([^"\']+)["\']', re.I)


def _normalize(url: str) -> str:
    """비교용 URL 정규화 — 스킴·www·끝 슬래시·쿼리 차이를 흡수합니다."""
    if not url:
        return ""
    u = urlparse(url if "//" in url else f"https://{url}")
    host = (u.netloc or "").lower().removeprefix("www.")
    path = (u.path or "").rstrip("/")
    return f"{host}{path}"


def extract_internal_links(html: str, own_hosts: set[str]) -> set[str]:
    """본문에서 같은 사이트(들)를 가리키는 링크만 뽑습니다.

    같은 글 안에서 같은 대상을 여러 번 링크해도 1개로 셉니다 —
    구조를 보는 것이지 링크 개수를 자랑하려는 게 아닙니다.
    """
    out: set[str] = set()
    for href in _HREF_RE.findall(html or ""):
        if href.startswith("#") or href.startswith("mailto:"):
            continue
        norm = _normalize(href)
        if not norm:
            continue
        host = norm.split("/")[0]
        if host in own_hosts:
            out.add(norm)
    return out


def fetch_posts(blog_cfg: dict, limit: int = 500) -> list[dict]:
    """Blogger에서 발행 글 본문을 받아옵니다 (읽기 전용)."""
    from blogger_uploader import _get_access_token

    name = blog_cfg.get("name") or blog_cfg.get("id", "")
    blog_id = blog_cfg.get("blog_id", "")
    token = _get_access_token(blog_cfg)
    if not (blog_id and token):
        logger.error(f"[{name}] blog_id 또는 토큰 없음 — 건너뜀")
        return []

    posts: list[dict] = []
    page_token = ""
    while len(posts) < limit:
        params = {"maxResults": 50, "status": "live", "fetchBodies": "true",
                  "fields": "nextPageToken,items(id,title,url,published,content)"}
        if page_token:
            params["pageToken"] = page_token
        r = requests.get(f"{BLOGGER_API_BASE}/blogs/{blog_id}/posts",
                         headers={"Authorization": f"Bearer {token}"},
                         params=params, timeout=30)
        if r.status_code != 200:
            logger.error(f"[{name}] 글 목록 조회 실패 [{r.status_code}]: {r.text[:200]}")
            break
        data = r.json()
        posts.extend(data.get("items", []))
        page_token = data.get("nextPageToken", "")
        if not page_token:
            break

    logger.info(f"[{name}] 발행 글 {len(posts)}건 조회")
    return posts[:limit]


def build_link_graph(all_posts: list[dict], own_hosts: set[str]) -> dict:
    """{정규화 URL: {inbound, outbound, ...}} 링크 그래프를 만듭니다."""
    nodes: dict[str, dict] = {}
    for p in all_posts:
        key = _normalize(p.get("url", ""))
        if not key:
            continue
        nodes[key] = {
            "url": p.get("url", ""),
            "title": (p.get("title") or "")[:70],
            "blog": p.get("_blog", ""),
            "published": (p.get("published") or "")[:10],
            "outbound": 0,
            "inbound": 0,
            "inboundFrom": [],
        }

    for p in all_posts:
        src = _normalize(p.get("url", ""))
        if src not in nodes:
            continue
        targets = extract_internal_links(p.get("content", ""), own_hosts)
        targets.discard(src)                       # 자기 자신 링크는 제외
        nodes[src]["outbound"] = len(targets)
        for t in targets:
            if t in nodes:                         # 발행 글끼리의 링크만 집계
                nodes[t]["inbound"] += 1
                if len(nodes[t]["inboundFrom"]) < 5:
                    nodes[t]["inboundFrom"].append(nodes[src]["title"])
    return nodes


def _index_status_by_url() -> dict[str, str]:
    """index_status.json이 있으면 {정규화 URL: verdict}로 돌려줍니다."""
    path = os.path.join(_DOCS_DATA, "index_status.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return {_normalize(i.get("url", "")): i.get("verdict", "")
            for i in data.get("items", []) if i.get("url")}


def summarize(nodes: dict) -> dict:
    inbound_counts = [n["inbound"] for n in nodes.values()]
    orphans = [n for n in nodes.values() if n["inbound"] == 0]
    orphans.sort(key=lambda n: n.get("published") or "", reverse=True)

    index_map = _index_status_by_url()
    cross = Counter()
    for key, n in nodes.items():
        verdict = index_map.get(key)
        if verdict:
            cross[("고아" if n["inbound"] == 0 else "링크있음", verdict)] += 1

    by_blog = defaultdict(lambda: {"posts": 0, "orphans": 0})
    for n in nodes.values():
        b = by_blog[n["blog"] or "?"]
        b["posts"] += 1
        if n["inbound"] == 0:
            b["orphans"] += 1

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "totalPosts": len(nodes),
        "orphanCount": len(orphans),
        "orphanRate": round(len(orphans) / len(nodes) * 100, 1) if nodes else 0.0,
        "avgInbound": round(sum(inbound_counts) / len(inbound_counts), 2) if inbound_counts else 0.0,
        "maxInbound": max(inbound_counts) if inbound_counts else 0,
        "byBlog": {k: v for k, v in by_blog.items()},
        # 색인 상태와의 교차 — 고아 여부가 색인과 관계있는지 보기 위함
        "indexCross": {f"{k[0]}/{k[1]}": v for k, v in cross.items()},
        "orphans": [
            {"title": n["title"], "url": n["url"], "blog": n["blog"],
             "published": n["published"], "outbound": n["outbound"]}
            for n in orphans[:50]
        ],
        "mostLinked": sorted(
            ({"title": n["title"], "url": n["url"], "inbound": n["inbound"]}
             for n in nodes.values()), key=lambda x: -x["inbound"])[:10],
    }


def run(blog_filter: str = "", limit: int = 500) -> dict:
    from config import get_blog_configs

    blogs = get_blog_configs()
    if blog_filter:
        blogs = [b for b in blogs if b.get("id") == blog_filter] or blogs

    own_hosts = set()
    for b in blogs:
        site = (b.get("gsc_site_url") or b.get("url") or "").strip()
        if site:
            own_hosts.add(_normalize(site).split("/")[0])

    all_posts: list[dict] = []
    for cfg in blogs:
        for p in fetch_posts(cfg, limit):
            p["_blog"] = cfg.get("name") or cfg.get("id", "")
            all_posts.append(p)
            host = _normalize(p.get("url", "")).split("/")[0]
            if host:
                own_hosts.add(host)      # 커스텀 도메인 등 실제 호스트도 포함

    if not all_posts:
        logger.warning("조회된 글이 없습니다 — 자격증명을 확인하세요")
        return {"totalPosts": 0, "orphanCount": 0, "orphans": []}

    nodes = build_link_graph(all_posts, own_hosts)
    report = summarize(nodes)

    logger.info("=" * 60)
    logger.info(f"발행 글 {report['totalPosts']}건 | 고아 페이지 {report['orphanCount']}건 "
                f"({report['orphanRate']}%)")
    logger.info(f"인바운드 링크 평균 {report['avgInbound']} / 최대 {report['maxInbound']}")
    for blog, v in report["byBlog"].items():
        logger.info(f"  {blog}: {v['posts']}건 중 고아 {v['orphans']}건")
    if report["indexCross"]:
        logger.info(f"색인 교차: {report['indexCross']}")
    if report["orphans"]:
        logger.info("최근 고아 페이지:")
        for o in report["orphans"][:5]:
            logger.info(f"  {o['published']} [{o['blog']}] {o['title'][:44]}")

    try:
        os.makedirs(_DOCS_DATA, exist_ok=True)
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info(f"리포트 저장: {REPORT_PATH}")
    except OSError as e:
        logger.warning(f"리포트 저장 실패 (무시): {e}")

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="내부 링크 구조 진단 (읽기 전용)")
    parser.add_argument("--blog", default="", help="특정 블로그 ID만")
    parser.add_argument("--limit", type=int, default=500, help="블로그당 최대 조회 글 수")
    args = parser.parse_args()
    run(args.blog, args.limit)
    return 0   # 진단 실패가 다른 자동화를 막지 않도록


if __name__ == "__main__":
    sys.exit(main())
