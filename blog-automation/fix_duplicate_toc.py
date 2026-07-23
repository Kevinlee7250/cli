"""발행된 글 일괄 스캔 — 중복 목차 제거

final_editor 구버전이 본문에 목차를 직접 생성해, 업로드 시 자동 목차와
중복(목차 2개)된 발행 글을 정리합니다.

동작:
  1. BLOGS_CONFIG의 모든 블로그에서 발행 글 전체 조회 (Blogger API)
  2. 목차 블록이 2개 이상인 글 감지
     - 자동 목차 박스('📋 목차' div) 여러 개 → 첫 번째만 유지
     - 모델 생성 목차(제목 '목차' + ol/ul 목록) → 전부 제거
  3. 변경된 본문을 PATCH로 업데이트 (제목·다른 내용은 손대지 않음)

Usage:
  python fix_duplicate_toc.py            # 실제 수정
  python fix_duplicate_toc.py --dry-run  # 감지만 하고 수정 없음
  python fix_duplicate_toc.py --blog blog1
"""

import argparse
import logging
import re
import sys
import time

import requests
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"

# 자동 목차 박스: <div ...><p ...>📋 목차</p><ol ...>...</ol></div>
_AUTO_TOC_RE = re.compile(
    r'<div[^>]*>\s*<p[^>]*>\s*📋\s*목차\s*</p>\s*<ol[^>]*>.*?</ol>\s*</div>',
    re.IGNORECASE | re.DOTALL,
)
# 모델 생성 목차: '목차' 제목(h2/h3/p/strong) + 바로 뒤 ol/ul
_MODEL_TOC_RE = re.compile(
    r'<(h[23]|p|div)[^>]*>\s*(?:<strong[^>]*>\s*)?(?:📋\s*)?목차\s*(?::)?\s*'
    r'(?:</strong>\s*)?</\1>\s*<(ol|ul)[^>]*>.*?</\2>',
    re.IGNORECASE | re.DOTALL,
)


def count_tocs(content: str) -> int:
    """본문 내 목차 블록 수 (자동 박스 + 모델 생성)."""
    auto = len(_AUTO_TOC_RE.findall(content))
    # 자동 박스 내부가 모델 패턴에 재매칭되지 않도록 제거 후 카운트
    without_auto = _AUTO_TOC_RE.sub('', content)
    model = len(_MODEL_TOC_RE.findall(without_auto))
    return auto + model


def dedupe_toc(content: str) -> str:
    """목차를 정확히 1개(첫 번째 자동 박스 우선)만 남깁니다."""
    auto_boxes = list(_AUTO_TOC_RE.finditer(content))

    if auto_boxes:
        # 첫 번째 자동 박스만 유지, 나머지 자동 박스 제거
        first = auto_boxes[0]
        keep = first.group(0)
        placeholder = "\x00KEEP_TOC\x00"
        content = content[:first.start()] + placeholder + content[first.end():]
        content = _AUTO_TOC_RE.sub('', content)
        # 모델 생성 목차 전부 제거
        content = _MODEL_TOC_RE.sub('', content)
        content = content.replace(placeholder, keep)
    else:
        # 자동 박스 없음: 모델 목차가 2개 이상이면 첫 번째만 유지
        models = list(_MODEL_TOC_RE.finditer(content))
        if len(models) > 1:
            first = models[0]
            keep = first.group(0)
            placeholder = "\x00KEEP_TOC\x00"
            content = content[:first.start()] + placeholder + content[first.end():]
            content = _MODEL_TOC_RE.sub('', content)
            content = content.replace(placeholder, keep)
    return content


def _iter_posts(api_base: str, blog_id: str, token: str):
    """블로그의 발행(live) 글을 전부 순회합니다."""
    page_token = ""
    while True:
        params = {
            "maxResults": 100,
            "status": "live",
            "fetchBodies": "true",
            "fields": "nextPageToken,items(id,title,url,content)",
        }
        if page_token:
            params["pageToken"] = page_token
        r = requests.get(
            f"{api_base}/blogs/{blog_id}/posts",
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


def fix_blog(blog_cfg: dict, dry_run: bool) -> dict:
    from blogger_uploader import _get_access_token

    name = blog_cfg.get("name") or blog_cfg.get("id", "")
    blogger_blog_id = blog_cfg.get("blog_id", "")
    if not blogger_blog_id:
        logger.warning(f"[{name}] blog_id 없음 — 건너뜀")
        return {"scanned": 0, "fixed": 0, "failed": 0}

    token = _get_access_token(blog_cfg)
    if not token:
        logger.error(f"[{name}] 액세스 토큰 없음 — 건너뜀")
        return {"scanned": 0, "fixed": 0, "failed": 0}

    scanned = fixed = failed = 0
    logger.info(f"── [{name}] 발행 글 스캔 시작 ──")
    for post in _iter_posts(BLOGGER_API_BASE, blogger_blog_id, token):
        scanned += 1
        content = post.get("content", "")
        n = count_tocs(content)
        if n <= 1:
            continue

        title = post.get("title", "")[:50]
        logger.info(f"  🔍 목차 {n}개 발견: '{title}' ({post.get('url','')})")

        new_content = dedupe_toc(content)
        remain = count_tocs(new_content)
        if remain != 1 or new_content == content:
            logger.warning(f"    ⚠️ 정리 결과 이상 (남은 목차 {remain}개) — 건너뜀")
            failed += 1
            continue

        if dry_run:
            logger.info("    [dry-run] 수정 대상 (실제 변경 없음)")
            fixed += 1
            continue

        pr = requests.patch(
            f"{BLOGGER_API_BASE}/blogs/{blogger_blog_id}/posts/{post['id']}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"content": new_content}, timeout=30,
        )
        if pr.status_code == 200:
            logger.info(f"    ✅ 중복 목차 제거 완료 ({n}개 → 1개)")
            fixed += 1
        else:
            logger.error(f"    ❌ 업데이트 실패 [{pr.status_code}]: {pr.text[:200]}")
            failed += 1
        time.sleep(1)  # API rate limit 배려

    logger.info(f"── [{name}] 스캔 {scanned}건 / 정리 {fixed}건 / 실패 {failed}건 ──")
    return {"scanned": scanned, "fixed": fixed, "failed": failed}


def main() -> int:
    parser = argparse.ArgumentParser(description="발행 글 중복 목차 정리")
    parser.add_argument("--dry-run", action="store_true", help="감지만 하고 수정하지 않음")
    parser.add_argument("--blog", default="", help="특정 블로그 ID만 (기본: 전체)")
    args = parser.parse_args()

    from config import get_blog_configs
    blogs = get_blog_configs()
    if args.blog:
        blogs = [b for b in blogs if b.get("id") == args.blog] or blogs

    total = {"scanned": 0, "fixed": 0, "failed": 0}
    for cfg in blogs:
        result = fix_blog(cfg, args.dry_run)
        for k in total:
            total[k] += result[k]

    mode = "(dry-run) " if args.dry_run else ""
    logger.info("=" * 55)
    logger.info(
        f"{mode}전체 완료 — 스캔 {total['scanned']}건 / "
        f"중복 목차 정리 {total['fixed']}건 / 실패 {total['failed']}건"
    )
    return 0 if total["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
