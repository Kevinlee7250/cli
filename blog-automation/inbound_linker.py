"""역방향 내부 링크 — 고아 페이지에 들어오는 링크를 만들어 줍니다.

`internal_linker`는 글을 만들 때 한 방향으로만 돕니다:

    새 글 ──링크──▶ 기존 글 (최대 5개)     있음
    기존 글 ──링크──▶ 새 글                이 모듈이 담당

2026-08-21 측정 결과 발행 글 431건 중 **175건(40.6%)이 고아**였고, 최근
고아 50건은 전부 8월 발행분이었습니다. 오래된 글은 새 글이 계속 링크해
인바운드가 쌓이는데(최대 17) 새 글은 아무도 가리키지 않는 구조입니다.

⚠️ 기대치에 대해 정직하게: 같은 측정에서 색인 검사 20건 중 고아 10건과
   링크 있는 글 10건이 **똑같이 미색인**이었습니다. 내부 링크를 만든다고
   색인이 풀린다는 근거는 아직 없습니다(표본이 전부 미색인이라 인과를
   판정할 수 없음). 이 작업은 "색인 해결책"이 아니라 사이트 구조상
   정당한 개선으로 보고 진행합니다.

안전 규칙:
  · 발행된 글을 수정하므로 기본은 dry-run — --apply가 있어야 실제 반영
  · 출처 글 하나에 링크를 무한정 넣지 않음 (MAX_ADDED_PER_SOURCE)
  · 이미 그 대상을 링크하고 있으면 건너뜀 (멱등)
  · 제목·기존 앵커·script/style 안에는 삽입하지 않음
    → internal_linker의 검증된 로직을 그대로 재사용합니다
  · 관련성 점수가 임계값 미만이면 링크하지 않음 (억지 링크 금지)

Usage:
  python inbound_linker.py                     # 대상만 확인 (변경 없음)
  python inbound_linker.py --apply --limit 10  # 고아 10건에 링크 생성
  python inbound_linker.py --blog blog1
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"
_BASE_DIR = os.path.dirname(__file__)
_DOCS_DATA = os.path.join(_BASE_DIR, "..", "docs", "data")
REPORT_PATH = os.path.join(_DOCS_DATA, "inbound_links.json")

# 고아 하나당 만들 인바운드 링크 수 — 많을수록 부자연스럽고 스팸처럼 보입니다
LINKS_PER_ORPHAN = 2
# 출처 글 하나가 이 작업으로 받게 될 최대 링크 수 (본문이 링크 목록이 되는 것 방지)
MAX_ADDED_PER_SOURCE = 3
# 관련성 점수가 이 값 미만이면 링크하지 않음 — 억지 링크는 안 하느니만 못합니다
MIN_RELEVANCE = 2


def _save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def find_link_targets(orphan: dict, candidates: list[dict],
                      already_linked: set[str], per_orphan: int = LINKS_PER_ORPHAN,
                      min_relevance: int = MIN_RELEVANCE) -> list[dict]:
    """고아 글에 링크를 걸어 줄 '출처 글'을 고릅니다.

    조건:
      · 고아보다 먼저 발행된 글 (나중 글이 앞 글을 링크하는 건 부자연스러움)
      · 관련성 점수 임계값 이상
      · 이미 그 대상을 링크하고 있지 않음
      · 인바운드가 많은(=구글이 이미 아는) 글을 우선 — 크롤 경로가 이어짐
    """
    from internal_linker import _score_relevance

    orphan_tags = set(orphan.get("tags") or [])
    orphan_kw = (orphan.get("keyword") or "")
    orphan_pub = orphan.get("published") or ""

    scored = []
    for c in candidates:
        if c.get("url") == orphan.get("url"):
            continue
        if c.get("url") in already_linked:
            continue
        if orphan_pub and (c.get("published") or "") >= orphan_pub:
            continue
        score = _score_relevance(c, orphan_tags, orphan_kw,
                                 orphan.get("articleType", ""))
        if score < min_relevance:
            continue
        # 관련성 우선, 같으면 이미 링크를 많이 받은 글 우선
        scored.append((score, c.get("inbound", 0), c))

    scored.sort(key=lambda x: (-x[0], -x[1]))
    return [c for _, _, c in scored[:per_orphan]]


def build_anchor_html(orphan: dict, source_html: str) -> tuple[str, bool, str]:
    """출처 글 본문에 고아 글로 가는 링크를 삽입합니다.

    반환: (수정된 html, 삽입 여부, 사용한 앵커 텍스트)
    본문에 자연스럽게 쓸 수 있는 표현이 없으면 삽입하지 않습니다 —
    억지로 문장을 만들어 붙이지 않습니다.
    """
    from internal_linker import _extract_keywords, _insert_link_in_text

    for kw in _extract_keywords(orphan):
        if len(kw) < 3:
            continue
        updated, ok = _insert_link_in_text(
            source_html, kw, orphan.get("url", ""), orphan.get("title", "")[:60])
        if ok:
            return updated, True, kw
    return source_html, False, ""


def _load_audit() -> dict:
    path = os.path.join(_DOCS_DATA, "internal_links.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def run(blog_filter: str = "", limit: int = 10, apply_changes: bool = False) -> dict:
    """고아 글에 인바운드 링크를 만듭니다. 기본은 리포트만."""
    from config import get_blog_configs
    from internal_link_audit import fetch_posts, build_link_graph, _normalize

    audit = _load_audit()
    if not audit.get("orphans"):
        logger.warning("internal_links.json에 고아 목록이 없습니다 — "
                       "먼저 internal_link_audit.py를 실행하세요")
        return {"orphansHandled": 0, "linksAdded": 0, "details": []}

    blogs = get_blog_configs()
    if blog_filter:
        blogs = [b for b in blogs if b.get("id") == blog_filter] or blogs

    # 실제 본문을 다시 받아옵니다 — 링크를 넣으려면 최신 HTML이 필요합니다
    own_hosts, all_posts, token_by_blog = set(), [], {}
    from blogger_uploader import _get_access_token
    for cfg in blogs:
        token_by_blog[cfg.get("id")] = (_get_access_token(cfg), cfg.get("blog_id", ""))
        for p in fetch_posts(cfg, 500):
            p["_blog"] = cfg.get("name") or cfg.get("id", "")
            p["_blogId"] = cfg.get("id")
            all_posts.append(p)
            host = _normalize(p.get("url", "")).split("/")[0]
            if host:
                own_hosts.add(host)

    if not all_posts:
        logger.warning("조회된 글이 없습니다 — 자격증명을 확인하세요")
        return {"orphansHandled": 0, "linksAdded": 0, "details": []}

    graph = build_link_graph(all_posts, own_hosts)
    by_url = {p.get("url", ""): p for p in all_posts}

    # 그래프 정보를 후보에 실어 관련성·인바운드로 정렬할 수 있게 합니다
    candidates = []
    for p in all_posts:
        node = graph.get(_normalize(p.get("url", "")), {})
        candidates.append({
            "url": p.get("url", ""), "title": p.get("title", ""),
            "published": (p.get("published") or "")[:10],
            "tags": p.get("labels") or [],
            "keyword": p.get("title", ""),
            "inbound": node.get("inbound", 0),
            "_blogId": p.get("_blogId"),
        })
    cand_by_url = {c["url"]: c for c in candidates}

    orphans = [o for o in audit["orphans"] if o.get("url") in by_url][:limit]
    logger.info(f"고아 {len(orphans)}건 처리 시작 (apply={apply_changes})")

    added_per_source: dict[str, int] = {}
    details, links_added = [], 0

    for orphan in orphans:
        o_full = cand_by_url.get(orphan["url"], {})
        o_full.setdefault("url", orphan["url"])
        o_full.setdefault("title", orphan.get("title", ""))

        # 이 고아를 이미 링크하고 있는 글은 후보에서 제외 (멱등성)
        node = graph.get(_normalize(orphan["url"]), {})
        already = set()
        for c in candidates:
            src_links = graph.get(_normalize(c["url"]), {})
            if src_links and _normalize(orphan["url"]) in str(src_links.get("inboundFrom", "")):
                already.add(c["url"])

        targets = find_link_targets(o_full, candidates, already)
        targets = [t for t in targets
                   if added_per_source.get(t["url"], 0) < MAX_ADDED_PER_SOURCE]

        entry = {"orphan": orphan.get("title", "")[:60], "url": orphan["url"],
                 "currentInbound": node.get("inbound", 0), "sources": []}

        for t in targets:
            source_post = by_url.get(t["url"])
            if not source_post:
                continue
            updated, ok, anchor = build_anchor_html(o_full, source_post.get("content", ""))
            if not ok:
                entry["sources"].append({"title": t["title"][:50], "result": "본문에 쓸 표현 없음"})
                continue

            if apply_changes:
                token, blogger_id = token_by_blog.get(source_post.get("_blogId"), ("", ""))
                if not (token and blogger_id):
                    entry["sources"].append({"title": t["title"][:50], "result": "토큰 없음"})
                    continue
                r = requests.patch(
                    f"{BLOGGER_API_BASE}/blogs/{blogger_id}/posts/{source_post['id']}",
                    headers={"Authorization": f"Bearer {token}",
                             "Content-Type": "application/json"},
                    json={"content": updated}, timeout=30)
                if r.status_code != 200:
                    logger.warning(f"수정 실패 [{r.status_code}]: {t['title'][:40]}")
                    entry["sources"].append({"title": t["title"][:50],
                                             "result": f"실패 HTTP {r.status_code}"})
                    continue
                source_post["content"] = updated
                time.sleep(1)          # Blogger 쓰기 레이트 리밋 배려

            added_per_source[t["url"]] = added_per_source.get(t["url"], 0) + 1
            links_added += 1
            entry["sources"].append({"title": t["title"][:50], "anchor": anchor,
                                     "result": "삽입" if apply_changes else "삽입 예정"})
            logger.info(f"  {'✅' if apply_changes else '📝'} '{anchor}' "
                        f"[{t['title'][:30]}] → {orphan.get('title','')[:30]}")

        details.append(entry)

    report = {
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "applied": apply_changes,
        "orphansHandled": len(orphans),
        "linksAdded": links_added,
        "orphansRemaining": max(0, audit.get("orphanCount", 0) - len(orphans)),
        "details": details,
    }
    logger.info("=" * 60)
    logger.info(f"고아 {len(orphans)}건 처리 → 링크 {links_added}건 "
                f"{'생성' if apply_changes else '생성 예정 (--apply 필요)'}")
    if report["orphansRemaining"]:
        logger.info(f"남은 고아 {report['orphansRemaining']}건 — 다음 실행에서 이어서 처리")

    try:
        _save(REPORT_PATH, report)
        logger.info(f"리포트 저장: {REPORT_PATH}")
    except OSError as e:
        logger.warning(f"리포트 저장 실패 (무시): {e}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="역방향 내부 링크 (고아 페이지 해소)")
    parser.add_argument("--apply", action="store_true",
                        help="실제로 글을 수정 (기본: 대상만 확인)")
    parser.add_argument("--limit", type=int, default=10,
                        help="이번 실행에서 처리할 고아 수 (기본 10)")
    parser.add_argument("--blog", default="", help="특정 블로그 ID만")
    args = parser.parse_args()
    run(args.blog, args.limit, args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
