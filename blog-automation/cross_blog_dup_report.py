"""블로그 3개 사이에 같은 주제로 공개된 글 쌍을 찾습니다 (읽기 전용 보고서).

왜 필요한가
────────────
글 선정 단계의 중복 검사(keyword_collector._is_too_similar)는 '같은 블로그'
안에서만 봅니다. 블로그 간 중복은 발행 이틀 사이만 거릅니다. 그래서 할로윈
파티처럼 blog2·blog3에 같은 주제가 따로 공개되는 일이 생겼습니다(AIOPS-86
PR #117 소급 비교 표).

이 보고서는 선정 규칙을 바꾸지 않습니다. PR #117(같은 블로그 공개 글 전체와
비교)이 keyword_collector.py를 고치고 있어 같은 파일을 건드리지 않으려고, 우선
'지금 공개된 글' 사이의 블로그 간 겹침을 세어 오너가 막을지 판단할 근거만
만듭니다. 판단 기준은 선정 단계와 같은 함수(_is_too_similar)를 그대로 씁니다
— 기준이 둘이면 반드시 어긋납니다.

입력
────
  · docs/data/live_posts.json   지금 공개된 주소 목록
  · logs/post_registry.json     주소 → 제목·키워드
  · 최신 백업(backups/)          레지스트리에 없는 주소의 제목 보완

결과: docs/data/cross_blog_dups.json

Usage:
  python cross_blog_dup_report.py
  python cross_blog_dup_report.py --no-write
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone

import post_sources

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(HERE, "logs", "post_registry.json")
LIVE = os.path.join(post_sources.DOCS_DATA, "live_posts.json")

#: blog1은 커스텀 도메인과 blogspot 주소가 같은 글입니다.
_ALIASES = {"://hoguwhat1.blogspot.com": "://www.hoguwhat.com"}


def norm_url(u: str) -> str:
    u = (u or "").split("?")[0].split("#")[0].replace("http://", "https://")
    for a, b in _ALIASES.items():
        u = u.replace(a, b)
    return u


def blog_of(url: str) -> str:
    if "hoguwhat" in url:
        return "blog1"
    if "hogugolfntraval" in url:
        return "blog2"
    if "hoguasset" in url:
        return "blog3"
    return ""


def load_corpus() -> tuple[list[dict], dict]:
    with open(LIVE, encoding="utf-8") as f:
        live = json.load(f)
    urls = [norm_url(u) for u in live.get("urls", [])]
    with open(REGISTRY, encoding="utf-8") as f:
        reg = json.load(f)
    by_url: dict[str, dict] = {}
    for p in reg if isinstance(reg, list) else []:
        u = norm_url(p.get("blogUrl", ""))
        if u:
            by_url[u] = {"title": p.get("title", ""), "keyword": p.get("keyword", "")}
    try:
        posts, _ = post_sources.from_backup()
        for p in posts:
            u = norm_url(p["url"])
            by_url.setdefault(u, {"title": p["title"], "keyword": ""})
    except FileNotFoundError:
        pass
    corpus, missing = [], 0
    for u in urls:
        info = by_url.get(u)
        if not info or not (info["title"] or info["keyword"]):
            missing += 1
            continue
        corpus.append({"url": u, "blogId": blog_of(u), **info})
    meta = {"liveSyncedAt": live.get("syncedAt", ""), "liveCount": len(urls),
            "compared": len(corpus), "noTitle": missing}
    return corpus, meta


def find_pairs(corpus: list[dict]) -> list[dict]:
    from keyword_collector import _is_too_similar

    pairs = []
    for i, a in enumerate(corpus):
        for b in corpus[i + 1:]:
            if not a["blogId"] or a["blogId"] == b["blogId"]:
                continue
            hit = None
            for fa, fb in (("title", "title"), ("keyword", "keyword"), ("keyword", "title"), ("title", "keyword")):
                if a[fa] and b[fb] and _is_too_similar(a[fa], [b[fb]]):
                    hit = f"{fa}↔{fb}"
                    break
            if hit:
                pairs.append({"by": hit,
                              "a": {k: a[k] for k in ("blogId", "url", "title")},
                              "b": {k: b[k] for k in ("blogId", "url", "title")}})
    return pairs


def main() -> int:
    ap = argparse.ArgumentParser(description="블로그 간 중복 주제 보고서(읽기 전용)")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()
    corpus, meta = load_corpus()
    pairs = find_pairs(corpus)
    combo: dict[str, int] = {}
    for p in pairs:
        k = "-".join(sorted((p["a"]["blogId"], p["b"]["blogId"])))
        combo[k] = combo.get(k, 0) + 1
    report = {"checkedAt": datetime.now(timezone.utc).isoformat(), **meta,
              "rule": "keyword_collector._is_too_similar (선정 단계와 같은 기준)",
              "pairs": len(pairs), "byBlogPair": combo, "items": pairs}
    logger.info(f"공개 {meta['liveCount']}건 중 비교 {meta['compared']}건(제목 없음 {meta['noTitle']}) · "
                f"블로그 간 겹침 {len(pairs)}쌍 {combo}")
    if not args.no_write:
        logger.info(f"기록: {post_sources.write_report('cross_blog_dups.json', report)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
