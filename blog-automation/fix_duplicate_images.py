"""발행된 글 일괄 스캔 — 중복 이미지 자동 교체

과거 범용 검색어 폴백("lifestyle blog")으로 여러 글에 같은 이미지가
첨부된 발행 글을 정리합니다.

동작:
  1. BLOGS_CONFIG의 모든 블로그에서 발행 글 전체 조회 (Blogger API)
  2. 두 글 이상에서 사용된 이미지 URL 감지 (data URI 생성 썸네일 제외)
  3. 가장 오래된 글 1곳만 유지, 나머지 글의 해당 이미지를
     글 제목 기반 새 이미지로 교체 (검색 실패 시 생성 SVG 썸네일)
  4. 스캔된 전체 이미지 URL을 used_images.json에 시드
     → 이후 새 글이 기존 글 이미지를 재사용하지 않음
  5. 결과 리포트를 docs/data/duplicate_images.json에 저장

Usage:
  python fix_duplicate_images.py            # 실제 교체
  python fix_duplicate_images.py --dry-run  # 감지만 하고 수정 없음
  python fix_duplicate_images.py --blog blog1
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
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"
_DOCS_DATA = os.path.join(os.path.dirname(__file__), "..", "docs", "data")

_IMG_TAG_RE = re.compile(r'<img\b[^>]*>', re.IGNORECASE)
_SRC_RE = re.compile(r'src="([^"]+)"', re.IGNORECASE)


def _fetch_dhash(url: str) -> int | None:
    """이미지를 내려받아 dHash(64비트 지각 해시)를 계산합니다.

    같은 사진이 서로 다른 사이트에 호스팅돼 URL이 달라도 감지할 수 있습니다.
    Pillow 미설치·다운로드 실패 시 None (URL 비교만 사용).
    """
    try:
        from PIL import Image
    except ImportError:
        return None
    import io
    try:
        r = requests.get(url, timeout=6, stream=True,
                         headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return None
        data = r.raw.read(3 * 1024 * 1024)  # 최대 3MB
        img = Image.open(io.BytesIO(data)).convert("L").resize((9, 8))
        px = list(img.getdata())
        bits = 0
        for row in range(8):
            for col in range(8):
                bits = (bits << 1) | (1 if px[row * 9 + col] > px[row * 9 + col + 1] else 0)
        return bits
    except Exception:
        return None


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


# dHash 해밍 거리가 이 값 이하이면 같은 이미지로 판정 (0=완전 동일)
_DHASH_THRESHOLD = 6


def _cluster_urls(urls: list[str], hashes: dict[str, int | None]) -> list[list[str]]:
    """같은 이미지(동일 URL 또는 dHash 유사)를 클러스터로 묶습니다."""
    parent = {u: u for u in urls}

    def find(u):
        while parent[u] != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    hashed = [(u, h) for u, h in hashes.items() if h is not None]
    for i in range(len(hashed)):
        for j in range(i + 1, len(hashed)):
            if _hamming(hashed[i][1], hashed[j][1]) <= _DHASH_THRESHOLD:
                union(hashed[i][0], hashed[j][0])

    clusters: dict[str, list[str]] = {}
    for u in urls:
        clusters.setdefault(find(u), []).append(u)
    return list(clusters.values())


def _extract_image_urls(content: str) -> list[str]:
    """본문에서 외부 이미지 URL 목록 추출 (data URI 생성 썸네일 제외)."""
    urls = []
    for tag in _IMG_TAG_RE.findall(content):
        m = _SRC_RE.search(tag)
        if m and not m.group(1).startswith("data:"):
            urls.append(m.group(1))
    return urls


def _iter_posts(blog_id: str, token: str):
    """블로그의 발행(live) 글 전체 순회 (최신순)."""
    page_token = ""
    while True:
        params = {
            "maxResults": 100,
            "status": "live",
            "fetchBodies": "true",
            "fields": "nextPageToken,items(id,title,url,content,published)",
        }
        if page_token:
            params["pageToken"] = page_token
        r = requests.get(
            f"{BLOGGER_API_BASE}/blogs/{blog_id}/posts",
            headers={"Authorization": f"Bearer {token}"},
            params=params, timeout=30,
        )
        if r.status_code != 200:
            logger.error(f"글 목록 조회 실패 [{r.status_code}]: {r.text[:200]}")
            return
        data = r.json()
        yield from data.get("items", [])
        page_token = data.get("nextPageToken", "")
        if not page_token:
            return


def _find_replacement_image(title: str, keyword: str = "") -> dict | None:
    """글 제목 기반 새 이미지 확보 — 검색(기사용 회피) 실패 시 생성 썸네일."""
    from image_fetcher import _fetch_best_image, _simplify_query, generate_fallback_image

    query = _simplify_query(title, 3) or title
    img = _fetch_best_image(
        query,
        naver_client_id=os.getenv("NAVER_CLIENT_ID", ""),
        naver_client_secret=os.getenv("NAVER_CLIENT_SECRET", ""),
        n_candidates=6,
        pixabay_api_key=os.getenv("PIXABAY_API_KEY", ""),
    )
    if img:
        img["alt_text"] = query[:50]
        return img
    thumb = generate_fallback_image(title, keyword)
    if thumb:
        kind = "AI 생성 이미지" if thumb.get("source") == "ai_generated" else "생성 썸네일"
        logger.info(f"    검색 실패 → {kind} 사용: '{title[:40]}'")
    return thumb


def _replace_image_in_content(content: str, old_url: str, new_img: dict) -> str:
    """본문에서 old_url 이미지 태그의 src/alt/title을 새 이미지로 교체."""
    import html as _h
    new_alt = _h.escape(new_img.get("alt_text", ""), quote=True)

    def _sub_tag(m: re.Match) -> str:
        tag = m.group(0)
        if f'src="{old_url}"' not in tag:
            return tag
        tag = tag.replace(f'src="{old_url}"', f'src="{new_img["url"]}"')
        for attr in ("alt", "title"):
            if new_alt and re.search(rf'{attr}="[^"]*"', tag):
                tag = re.sub(rf'{attr}="[^"]*"', f'{attr}="{new_alt}"', tag)
        return tag

    return _IMG_TAG_RE.sub(_sub_tag, content)


def scan_and_fix(blogs: list[dict], dry_run: bool) -> dict:
    from blogger_uploader import _get_access_token
    from image_fetcher import mark_images_used

    # ── 1차 스캔: 전체 발행 글의 이미지 사용처 수집 ──
    # url → [{"blog":cfg, "token":t, "post":post}] (최신순으로 쌓임)
    usage: dict[str, list[dict]] = {}
    all_urls: list[str] = []
    scanned = 0

    for cfg in blogs:
        name = cfg.get("name") or cfg.get("id", "")
        blog_id = cfg.get("blog_id", "")
        if not blog_id:
            logger.warning(f"[{name}] blog_id 없음 — 건너뜀")
            continue
        token = _get_access_token(cfg)
        if not token:
            logger.error(f"[{name}] 액세스 토큰 없음 — 건너뜀")
            continue
        logger.info(f"── [{name}] 발행 글 스캔 ──")
        for post in _iter_posts(blog_id, token):
            scanned += 1
            for url in set(_extract_image_urls(post.get("content", ""))):
                usage.setdefault(url, []).append(
                    {"blog": cfg, "blog_id": blog_id, "token": token, "post": post})
                all_urls.append(url)

    logger.info(f"스캔 완료: 글 {scanned}건, 이미지 URL {len(usage)}종")

    # ── 이미지 내용 지문(dHash) 계산 — 다른 URL의 같은 사진도 감지 ──
    from concurrent.futures import ThreadPoolExecutor
    url_list = list(usage.keys())
    logger.info(f"이미지 지문 계산 중 ({len(url_list)}개 다운로드)...")
    with ThreadPoolExecutor(max_workers=8) as pool:
        hash_results = list(pool.map(_fetch_dhash, url_list))
    hashes = dict(zip(url_list, hash_results))
    hashed_count = sum(1 for h in hashes.values() if h is not None)
    logger.info(f"지문 계산 완료: {hashed_count}/{len(url_list)}개 성공")

    clusters = _cluster_urls(url_list, hashes)
    dup_clusters = [
        c for c in clusters
        if sum(len(usage[u]) for u in c) >= 2 and (
            len(c) >= 2 or any(len(usage[u]) >= 2 for u in c))
    ]
    logger.info(f"중복 이미지 클러스터: {len(dup_clusters)}종 "
                f"(URL 동일 + 내용 동일 포함)")

    # ── 교체 계획: 클러스터마다 가장 오래된 글 1곳만 유지, 나머지 교체 ──
    # post_key → {"blog_id","token","post","dup_urls":[...]}
    plans: dict[str, dict] = {}
    for cluster in dup_clusters:
        entries = [(u, e) for u in cluster for e in usage[u]]
        # published(ISO) 기준 가장 오래된 글 유지
        entries.sort(key=lambda x: x[1]["post"].get("published", ""))
        keep_url, keep = entries[0]
        logger.info(
            f"🔁 중복 이미지 클러스터 (URL {len(cluster)}종 / 글 {len(entries)}곳): {keep_url[:70]}\n"
            f"    유지: '{keep['post'].get('title','')[:40]}'"
        )
        seen_posts = {f"{keep['blog_id']}:{keep['post']['id']}"}
        for url, e in entries[1:]:
            key = f"{e['blog_id']}:{e['post']['id']}"
            if key in seen_posts:
                continue  # 같은 글은 한 번만 (post 내 중복 url은 개별 처리)
            seen_posts.add(key)
            plan = plans.setdefault(key, {**e, "dup_urls": []})
            plan["dup_urls"].append(url)
            logger.info(f"    교체 대상: '{e['post'].get('title','')[:40]}'")

    report_items = []
    fixed = failed = 0

    for key, plan in plans.items():
        post = plan["post"]
        title = post.get("title", "")
        content = post.get("content", "")
        replaced_here = []

        for old_url in plan["dup_urls"]:
            if dry_run:
                replaced_here.append({"old": old_url[:80], "new": "(dry-run)"})
                continue
            new_img = _find_replacement_image(title)
            if not new_img:
                logger.warning(f"    ⚠️ 대체 이미지 확보 실패: '{title[:40]}' — 해당 이미지 건너뜀")
                continue
            content = _replace_image_in_content(content, old_url, new_img)
            mark_images_used([new_img.get("url", "")])
            replaced_here.append({"old": old_url[:80], "new": new_img.get("url", "")[:80]})

        if not replaced_here:
            continue

        if dry_run:
            logger.info(f"  [dry-run] '{title[:40]}' — 이미지 {len(replaced_here)}개 교체 대상")
            fixed += 1
        else:
            pr = requests.patch(
                f"{BLOGGER_API_BASE}/blogs/{plan['blog_id']}/posts/{post['id']}",
                headers={"Authorization": f"Bearer {plan['token']}",
                         "Content-Type": "application/json"},
                json={"content": content}, timeout=30,
            )
            if pr.status_code == 200:
                logger.info(f"  ✅ '{title[:40]}' — 이미지 {len(replaced_here)}개 교체 완료")
                fixed += 1
            else:
                logger.error(f"  ❌ 업데이트 실패 [{pr.status_code}]: {pr.text[:200]}")
                failed += 1
            time.sleep(1)  # API rate limit 배려

        report_items.append({
            "title": title[:60],
            "url": post.get("url", ""),
            "replaced": replaced_here,
        })

    # ── 전체 기존 이미지 URL을 used_images.json에 시드 (실제 실행 시에만) ──
    if not dry_run and all_urls:
        mark_images_used(list(set(all_urls)))
        logger.info(f"📄 used_images.json 시드: 기존 이미지 {len(set(all_urls))}종 등록")

    # ── 리포트 저장 ──
    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "scanned_posts": scanned,
        "duplicate_images": len(dup_clusters),
        "posts_fixed": fixed,
        "posts_failed": failed,
        "items": report_items[:50],
    }
    try:
        os.makedirs(_DOCS_DATA, exist_ok=True)
        with open(os.path.join(_DOCS_DATA, "duplicate_images.json"), "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"리포트 저장 실패: {e}")

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="발행 글 중복 이미지 자동 교체")
    parser.add_argument("--dry-run", action="store_true", help="감지만 하고 수정하지 않음")
    parser.add_argument("--blog", default="", help="특정 블로그 ID만 (기본: 전체)")
    args = parser.parse_args()

    from config import get_blog_configs
    blogs = get_blog_configs()
    if args.blog:
        blogs = [b for b in blogs if b.get("id") == args.blog] or blogs

    report = scan_and_fix(blogs, args.dry_run)
    mode = "(dry-run) " if report["dry_run"] else ""
    logger.info("=" * 55)
    logger.info(
        f"{mode}완료 — 글 {report['scanned_posts']}건 스캔 / "
        f"중복 이미지 {report['duplicate_images']}종 / "
        f"글 {report['posts_fixed']}건 교체 / 실패 {report['posts_failed']}건"
    )
    return 0 if report["posts_failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
