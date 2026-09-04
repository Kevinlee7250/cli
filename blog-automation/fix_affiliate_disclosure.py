"""발행된 글 일괄 스캔 — 쿠팡 파트너스 고지 문구 교체

이미 나간 글에는 옛 고지가 남아 있습니다.

  문구   "이 포스트는 … 제공받을 수 있습니다"  (임의로 완화된 표현)
  스타일  font-size:10px · color:#bbb          (흰 배경에서 읽히지 않음)

표시광고법상 대가를 받은 추천은 소비자가 "쉽게 인식할 수 있는" 방법으로
알려야 하므로, 발행분도 표준 문구·읽히는 크기로 맞춥니다.

동작
────
  1. BLOGS_CONFIG의 모든 블로그에서 발행 글 전체 조회 (Blogger API)
  2. 쿠팡 링크가 있는 글에서 고지 문단(<p>…수수료…</p>)을 찾아
     문구와 스타일을 현재 기준으로 교체
  3. 변경된 본문만 PATCH (제목·다른 내용은 손대지 않음)

손대지 않는 경우
────────────────
  · 쿠팡 링크가 없는 글 — 고지가 있을 이유가 없습니다
  · 이미 현재 문구·스타일인 글
  · 고지 문단을 못 찾은 글 — 링크만 있고 고지가 없다면 지어내 붙이지
    않고 경고만 남깁니다. 어디에 넣을지는 사람이 봐야 합니다.

Usage:
  python fix_affiliate_disclosure.py --dry-run   # 대상만 확인
  python fix_affiliate_disclosure.py             # 실제 교체
  python fix_affiliate_disclosure.py --blog blog1
"""

import argparse
import json
import logging
import os
import re
import sys
import time

import requests
from dotenv import load_dotenv

from blogger_posts import ListingTruncated, iter_posts
from coupang_affiliate import DISCLOSURE

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"
_DOCS_DATA = os.path.join(os.path.dirname(__file__), "..", "docs", "data")

#: 현재 기준 고지 문단. coupang_affiliate가 만드는 것과 같은 모양이어야
#: 합니다 — 다르면 교체한 글과 새로 쓴 글의 고지가 갈라집니다.
DISCLOSURE_HTML = (
    '<p style="font-size:13px;color:#6b4423;margin:16px 0 0;'
    f'line-height:1.6;font-weight:600">{DISCLOSURE}</p>'
)

#: 고지 문단 찾기. 문구가 조금씩 달라도(포스트/포스팅, 받습니다/받을 수
#: 있습니다) 잡히도록 "쿠팡 파트너스"와 "수수료"를 함께 가진 <p>를 봅니다.
_NOTICE_RE = re.compile(
    r'<p\b[^>]*>(?:(?!</p>).)*?쿠팡\s*파트너스(?:(?!</p>).)*?수수료(?:(?!</p>).)*?</p>',
    re.IGNORECASE | re.DOTALL,
)

_COUPANG_RE = re.compile(r'link\.coupang\.com', re.IGNORECASE)


def needs_fix(content: str) -> bool:
    """교체가 필요한 글인지."""
    if not _COUPANG_RE.search(content):
        return False
    m = _NOTICE_RE.search(content)
    if not m:
        return False
    return m.group(0) != DISCLOSURE_HTML


def replace_disclosure(content: str) -> str:
    """고지 문단을 현재 기준으로 바꿉니다.

    여러 개가 있으면 전부 바꾸되, 광고 상자가 하나뿐인 글에서는 한 번만
    걸립니다. 링크는 건드리지 않습니다.
    """
    return _NOTICE_RE.sub(lambda _m: DISCLOSURE_HTML, content)


def scan_blog(blog_cfg: dict, dry_run: bool) -> dict:
    from blogger_uploader import _get_access_token

    name = blog_cfg.get("name") or blog_cfg.get("id", "")
    blogger_blog_id = blog_cfg.get("blog_id", "")
    empty = {"scanned": 0, "withLink": 0, "fixed": 0, "missing": 0,
             "failed": 0, "incomplete": 0}
    if not blogger_blog_id:
        logger.warning(f"[{name}] blog_id 없음 — 건너뜀")
        return empty

    token = _get_access_token(blog_cfg)
    if not token:
        logger.error(f"[{name}] 액세스 토큰 없음 — 건너뜀")
        return empty

    stats = dict(empty)
    logger.info(f"── [{name}] 발행 글 스캔 시작 ──")
    try:
        posts = list(iter_posts(blogger_blog_id, token))
    except ListingTruncated as e:
        # 목록을 끝까지 못 읽었으면 "다 고쳤다"고 말할 수 없습니다
        logger.error(f"[{name}] 글 목록을 끝까지 읽지 못했습니다: {e}")
        stats["incomplete"] = 1
        return stats

    for post in posts:
        stats["scanned"] += 1
        content = post.get("content", "")
        if not _COUPANG_RE.search(content):
            continue
        stats["withLink"] += 1

        title = post.get("title", "")[:44]
        if not _NOTICE_RE.search(content):
            # 링크만 있고 고지가 없는 글 — 어디에 넣을지는 사람이 정해야
            # 합니다. 임의로 붙이면 엉뚱한 자리에 들어갑니다.
            logger.warning(f"  ⚠️ 링크는 있는데 고지가 없습니다: '{title}' {post.get('url','')}")
            stats["missing"] += 1
            continue

        if not needs_fix(content):
            continue

        new_content = replace_disclosure(content)
        if new_content == content:
            logger.warning(f"  ⚠️ 치환 결과가 원본과 같습니다 — 건너뜀: '{title}'")
            stats["failed"] += 1
            continue

        logger.info(f"  🔍 고지 교체 대상: '{title}'")
        if dry_run:
            logger.info("    [dry-run] 실제 변경 없음")
            stats["fixed"] += 1
            continue

        pr = requests.patch(
            f"{BLOGGER_API_BASE}/blogs/{blogger_blog_id}/posts/{post['id']}",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json={"content": new_content}, timeout=30,
        )
        if pr.status_code == 200:
            logger.info("    ✅ 고지 문구 교체 완료")
            stats["fixed"] += 1
        else:
            logger.error(f"    ❌ 업데이트 실패 [{pr.status_code}]: {pr.text[:200]}")
            stats["failed"] += 1
        time.sleep(1)  # API rate limit 배려

    logger.info(
        f"── [{name}] 스캔 {stats['scanned']} / 링크 있는 글 {stats['withLink']} / "
        f"교체 {stats['fixed']} / 고지 없음 {stats['missing']} / 실패 {stats['failed']} ──"
    )
    return stats


def _write_report(total: dict, dry_run: bool, blogs: list[str]) -> None:
    path = os.path.join(_DOCS_DATA, "affiliate_disclosure.json")
    try:
        os.makedirs(_DOCS_DATA, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "checkedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "dryRun": dry_run,
                "blogs": blogs,
                "disclosure": DISCLOSURE,
                **total,
            }, f, ensure_ascii=False, separators=(",", ":"))
        logger.info(f"리포트 저장: {path}")
    except OSError as e:
        logger.error(f"리포트 저장 실패: {e}")


def main() -> int:
    parser = argparse.ArgumentParser(description="발행 글 쿠팡 고지 문구 교체")
    parser.add_argument("--dry-run", action="store_true", help="대상만 확인하고 수정하지 않음")
    parser.add_argument("--blog", default="", help="특정 블로그 ID만 (기본: 전체)")
    args = parser.parse_args()

    from config import get_blog_configs
    blogs = get_blog_configs()
    if args.blog:
        picked = [b for b in blogs if b.get("id") == args.blog]
        if not picked:
            # 오타로 전체가 도는 일이 없도록 멈춥니다
            logger.error(f"블로그 '{args.blog}'를 찾지 못했습니다")
            return 1
        blogs = picked

    total = {"scanned": 0, "withLink": 0, "fixed": 0, "missing": 0,
             "failed": 0, "incomplete": 0}
    for cfg in blogs:
        for k, v in scan_blog(cfg, args.dry_run).items():
            total[k] += v

    mode = "(dry-run) " if args.dry_run else ""
    logger.info("=" * 55)
    logger.info(
        f"{mode}전체 완료 — 스캔 {total['scanned']} / 링크 있는 글 {total['withLink']} / "
        f"교체 {total['fixed']} / 고지 없음 {total['missing']} / 실패 {total['failed']}"
    )
    if total["incomplete"]:
        logger.error("일부 블로그의 글 목록을 끝까지 읽지 못했습니다 — 전부 처리했다고 볼 수 없습니다")
    _write_report(total, args.dry_run, [b.get("id", "") for b in blogs])
    return 0 if not (total["failed"] or total["incomplete"]) else 1


if __name__ == "__main__":
    sys.exit(main())
