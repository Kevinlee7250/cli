#!/usr/bin/env python3
"""
sitemap_generator.py
posts.json → sitemap.xml 생성 + Google Search Console 자동 제출
"""

import os
import json
import logging
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# ─── 경로 설정 ────────────────────────────────────────────────
_DIR = Path(__file__).parent
_POSTS_JSON  = (_DIR / ".." / "docs" / "data" / "posts.json").resolve()
_SITEMAP_OUT = (_DIR / ".." / "docs" / "sitemap.xml").resolve()

# 사이트 / Sitemap 정보
BLOG_URL    = "https://hoguwhat1.blogspot.com"
SITEMAP_URL = os.getenv("SITEMAP_URL",
              "https://kevinlee7250.github.io/cli/sitemap.xml")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ─── OAuth ────────────────────────────────────────────────────
def get_oauth_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    if not all([client_id, client_secret, refresh_token]):
        return ""
    data = urllib.parse.urlencode({
        "client_id":     client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type":    "refresh_token",
    }).encode()
    try:
        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token", data=data, method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp).get("access_token", "")
    except Exception as e:
        logger.warning(f"OAuth 토큰 발급 실패: {e}")
        return ""


# ─── 포스트 로드 ──────────────────────────────────────────────
def load_posts() -> list[dict]:
    if not _POSTS_JSON.exists():
        logger.error(f"posts.json 없음: {_POSTS_JSON}")
        return []
    posts = json.loads(_POSTS_JSON.read_text(encoding="utf-8"))
    logger.info(f"포스트 로드: {len(posts)}개")
    return posts


# ─── Sitemap 생성 ─────────────────────────────────────────────
def generate_sitemap(posts: list[dict]) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_dt = datetime.now()

    # 등급별 우선순위
    grade_priority = {"S": "0.9", "A": "0.8", "B": "0.7", "C": "0.5"}

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        '',
        '  <!-- 홈페이지 -->',
        '  <url>',
        f'    <loc>{BLOG_URL}/</loc>',
        f'    <lastmod>{today}</lastmod>',
        '    <changefreq>daily</changefreq>',
        '    <priority>1.0</priority>',
        '  </url>',
        '',
    ]

    valid_count = 0
    for post in posts:
        url = post.get("blogUrl", "").strip()
        if not url or not url.startswith("http"):
            continue

        date     = post.get("date", today)
        grade    = post.get("grade", "B")
        priority = grade_priority.get(grade, "0.7")

        # 경과일 → changefreq
        try:
            days_old = (now_dt - datetime.strptime(date, "%Y-%m-%d")).days
            if days_old <= 7:
                changefreq = "daily"
            elif days_old <= 30:
                changefreq = "weekly"
            else:
                changefreq = "monthly"
        except Exception:
            changefreq = "weekly"

        lines += [
            '  <url>',
            f'    <loc>{url}</loc>',
            f'    <lastmod>{date}</lastmod>',
            f'    <changefreq>{changefreq}</changefreq>',
            f'    <priority>{priority}</priority>',
            '  </url>',
        ]
        valid_count += 1

    lines.append('</urlset>')
    logger.info(f"sitemap 생성: {valid_count}개 포스트 URL + 1개 홈")
    return "\n".join(lines)


# ─── 저장 ─────────────────────────────────────────────────────
def save_sitemap(xml_content: str) -> None:
    _SITEMAP_OUT.parent.mkdir(parents=True, exist_ok=True)
    _SITEMAP_OUT.write_text(xml_content, encoding="utf-8")
    logger.info(f"✅ sitemap.xml 저장: {_SITEMAP_OUT} ({len(xml_content):,} bytes)")


# ─── GSC Sitemap 제출 ──────────────────────────────────────────
def submit_to_gsc(token: str, site_url: str, sitemap_url: str) -> bool:
    if not token:
        logger.warning("OAuth 토큰 없음 — GSC 제출 건너뜀")
        return False

    encoded_site    = urllib.parse.quote(site_url,    safe="")
    encoded_sitemap = urllib.parse.quote(sitemap_url, safe="")
    api_url = (
        f"https://www.googleapis.com/webmasters/v3/"
        f"sites/{encoded_site}/sitemaps/{encoded_sitemap}"
    )

    req = urllib.request.Request(
        api_url, data=b"", method="PUT",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Length": "0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            logger.info(f"✅ GSC sitemap 제출 성공: HTTP {resp.status}")
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:400]
        logger.warning(f"GSC 제출 실패: HTTP {e.code} — {body}")
        return False
    except Exception as e:
        logger.warning(f"GSC 제출 오류: {e}")
        return False


# ─── Blogger 기본 sitemap도 제출 ───────────────────────────────
def submit_blogger_atom_sitemap(token: str, site_url: str) -> None:
    """Blogger atom 피드도 sitemap으로 GSC 제출 (전체 피드 — 26개 제한 없음)"""
    atom_url = f"{BLOG_URL}/feeds/posts/default?alt=rss"
    logger.info(f"Blogger RSS 피드 GSC 제출 시도: {atom_url}")
    submit_to_gsc(token, site_url, atom_url)


# ─── Google Ping ───────────────────────────────────────────────
def ping_google(sitemap_url: str) -> None:
    ping_url = f"https://www.google.com/ping?sitemap={urllib.parse.quote(sitemap_url)}"
    try:
        with urllib.request.urlopen(ping_url, timeout=10) as resp:
            logger.info(f"Google ping: HTTP {resp.status}")
    except Exception as e:
        logger.debug(f"Google ping (무시): {e}")


# ─── Main ─────────────────────────────────────────────────────
def main() -> None:
    client_id     = os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
    refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN", "")
    gsc_site_url  = os.getenv("GSC_SITE_URL", f"{BLOG_URL}/")
    sitemap_url   = SITEMAP_URL

    logger.info("=" * 55)
    logger.info("  🗺️  Sitemap Generator")
    logger.info("=" * 55)
    logger.info(f"  블로그  : {BLOG_URL}")
    logger.info(f"  Sitemap : {sitemap_url}")
    logger.info(f"  GSC URL : {gsc_site_url}")

    # 1. 포스트 로드
    posts = load_posts()
    if not posts:
        logger.error("포스트 없음 — 종료")
        return

    # 2. sitemap 생성 & 저장
    xml_content = generate_sitemap(posts)
    save_sitemap(xml_content)

    # 3. OAuth 토큰
    token = get_oauth_token(client_id, client_secret, refresh_token)
    if token:
        logger.info("OAuth 토큰 발급 성공")
    else:
        logger.warning("OAuth 없음 — sitemap 파일만 생성됨 (GSC 제출 건너뜀)")

    # 4. GSC에 커스텀 sitemap 제출
    gsc_ok = submit_to_gsc(token, gsc_site_url, sitemap_url)

    # 5. Blogger RSS 피드도 추가 제출
    submit_blogger_atom_sitemap(token, gsc_site_url)

    # 6. Google ping
    ping_google(sitemap_url)

    # 결과 요약
    url_count = xml_content.count("<loc>")
    logger.info("=" * 55)
    logger.info(f"  ✅ sitemap URL 수   : {url_count}개")
    logger.info(f"  {'✅' if gsc_ok else '⚠️'} GSC 제출        : {'성공' if gsc_ok else '실패/건너뜀'}")
    logger.info(f"  🌐 sitemap 접근 URL : {sitemap_url}")
    logger.info("=" * 55)


if __name__ == "__main__":
    main()
