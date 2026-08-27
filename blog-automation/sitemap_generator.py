#!/usr/bin/env python3
"""posts.json → docs/sitemap.xml · docs/robots.txt

왜 모듈인가
──────────
이 로직은 원래 blog-sitemap.yml 안에 heredoc 파이썬으로 인라인돼 있었습니다.
같은 이름의 모듈이 따로 있었지만 아무도 부르지 않아, 사이트맵 구현이 두 벌
존재하고 도는 쪽에는 테스트가 없었습니다. 그 상태에서 아래 버그가 오래
살아남았습니다.

고친 버그
────────
인라인 판은 `"blogspot.com" not in url: continue`로 걸렀습니다. 커스텀
도메인을 쓰는 블로그(www.hoguwhat.com)가 통째로 사이트맵과 robots.txt에서
빠져 있었습니다 — posts.json에 31편이 있는데 sitemap.xml에는 0편.
색인에 직접 영향이 가는 문제인데, 워크플로는 계속 초록이었습니다.

이제 호스트를 가정하지 않고 posts.json의 URL에서 그대로 읽습니다. 블로그를
새로 붙이거나 도메인을 갈아도 코드를 고칠 필요가 없습니다.

GSC 제출과 ping은 여기 없습니다. 제출은 gsc_indexing.submit_sitemaps가
담당하고, 구글의 sitemap ping 엔드포인트는 폐기됐습니다.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

_DIR = Path(__file__).parent
POSTS_JSON = (_DIR / ".." / "docs" / "data" / "posts.json").resolve()
SITEMAP_OUT = (_DIR / ".." / "docs" / "sitemap.xml").resolve()
ROBOTS_OUT = (_DIR / ".." / "docs" / "robots.txt").resolve()

# 등급이 좋을수록 크롤러에 먼저 권합니다
PRIORITY_BY_GRADE = {"S": "1.0", "A": "0.8", "B": "0.6", "C": "0.5"}
DEFAULT_PRIORITY = "0.5"


def post_url(post: dict) -> str:
    """글의 공개 주소. 필드 이름이 시기마다 달라 셋 다 봅니다."""
    url = (post.get("url") or post.get("blogUrl") or post.get("link") or "").strip()
    return url if url.startswith(("http://", "https://")) else ""


def host_root(url: str) -> str:
    m = re.match(r"(https?://[^/]+)", url)
    return m.group(1) if m else ""


def normalize_date(post: dict, today: str) -> str:
    """publishedAt/savedAt/createdAt/date 중 먼저 있는 것을 YYYY-MM-DD로."""
    raw = str(post.get("publishedAt") or post.get("savedAt")
              or post.get("createdAt") or post.get("date") or "")
    if len(raw) == 14 and raw.isdigit():       # 20260826123456
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    if len(raw) > 10:
        return raw[:10]
    return raw or today


def build_entries(posts: list[dict], today: str = "") -> list[dict]:
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    roots, entries, seen = set(), [], set()

    for p in posts:
        url = post_url(p)
        if not url or url in seen:
            continue
        seen.add(url)
        root = host_root(url)
        if root:
            roots.add(root)
        entries.append({
            "url": url,
            "lastmod": normalize_date(p, today),
            "priority": PRIORITY_BY_GRADE.get(p.get("grade", ""), DEFAULT_PRIORITY),
            "changefreq": "monthly",
        })

    # 블로그 루트는 맨 앞에, 매일 크롤링 권장
    for root in sorted(roots, reverse=True):
        entries.insert(0, {"url": root + "/", "lastmod": today,
                           "priority": "1.0", "changefreq": "daily"})
    return entries


def render_sitemap(entries: list[dict]) -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for e in entries:
        lines += ["  <url>",
                  f"    <loc>{e['url']}</loc>",
                  f"    <lastmod>{e['lastmod']}</lastmod>",
                  f"    <changefreq>{e['changefreq']}</changefreq>",
                  f"    <priority>{e['priority']}</priority>",
                  "  </url>"]
    lines.append("</urlset>")
    return "\n".join(lines)


def render_robots(roots: list[str]) -> str:
    lines = ["User-agent: *", "Allow: /", ""]
    lines += [f"Sitemap: {r}/sitemap.xml" for r in sorted(roots)]
    return "\n".join(lines) + "\n"


def roots_of(entries: list[dict]) -> list[str]:
    return sorted({host_root(e["url"]) for e in entries if host_root(e["url"])})


def main() -> int:
    if not POSTS_JSON.exists():
        print(f"❌ posts.json 없음: {POSTS_JSON}")
        return 0
    posts = json.loads(POSTS_JSON.read_text(encoding="utf-8"))
    print(f"📄 포스트 수: {len(posts)}")

    entries = build_entries(posts)
    roots = roots_of(entries)

    SITEMAP_OUT.parent.mkdir(parents=True, exist_ok=True)
    SITEMAP_OUT.write_text(render_sitemap(entries), encoding="utf-8")
    print(f"✅ sitemap.xml: URL {len(entries)}개 → {SITEMAP_OUT}")

    if roots:
        ROBOTS_OUT.write_text(render_robots(roots), encoding="utf-8")
        print(f"✅ robots.txt: 사이트맵 {len(roots)}개")

    # 블로그별 내역을 남깁니다. 한 블로그가 통째로 빠져도 숫자만 보면
    # 알 수 없던 것이 이번 버그의 원인이었습니다.
    per = {}
    for e in entries:
        per[host_root(e["url"])] = per.get(host_root(e["url"]), 0) + 1
    for h, c in sorted(per.items()):
        print(f"   {h}: {c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
