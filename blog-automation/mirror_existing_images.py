#!/usr/bin/env python3
"""이미 발행된 글의 이미지를 저장소로 소급 복제하고 본문을 그쪽으로 돌립니다.

image_mirror는 앞으로 쓰는 글만 자체 호스팅합니다. 이미 발행된 425편은
여전히 남의 서버 핫링크라, 원본이 사라지면 그 글들이 조용히 깨집니다.
이 스크립트가 그 소급분을 처리합니다.

두 단계로 나눈 이유
──────────────────
복제본은 저장소에 커밋되고 GitHub Pages가 배포해야 비로소 열립니다. 파일을
내려받자마자 발행 글의 src를 그쪽으로 돌리면, 배포 전까지 발행된 글 수백
편이 404 이미지를 가리킵니다. 사람 눈에는 onerror 폴백이 가려 주지만
크롤러는 그대로 404를 봅니다. 그래서:

  1단계  --mirror-only   이미지를 내려받아 docs/images에 저장 (발행 글은 손대지 않음)
         → 커밋·푸시 → Pages 배포
  2단계  --rewrite       공개 URL이 실제로 200을 주는지 확인한 뒤에만 본문 교체

2단계는 URL 하나하나를 실제로 확인하고, 아직 안 열린 것은 건너뜁니다.
그래서 순서를 잘못 돌려도 살아 있는 글을 깨뜨릴 수 없습니다.

복제 대상
─────────
화이트리스트(is_license_safe)를 통과한 이미지만입니다. 무단 이미지를 우리
저장소로 복사하면 핫링크보다 나쁜 상태가 됩니다 — 그쪽은
fix_unlicensed_images가 교체할 일이고, 여기서는 세기만 합니다.

사용
────
  python mirror_existing_images.py --mirror-only --dry-run     # 대상 확인
  python mirror_existing_images.py --mirror-only --limit 50    # 50편 복제
  python mirror_existing_images.py --rewrite --limit 50        # 배포 뒤 본문 교체
  python mirror_existing_images.py --rewrite --blog blog1

--limit은 "처리한 글 수"입니다. 한 번에 수백 편을 PATCH하면 Blogger API
제한에 걸리므로 나눠 도는 것을 권합니다. 두 단계 모두 몇 번을 다시 돌려도
안전합니다 — 이미 복제·교체된 것은 건너뜁니다.
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
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_PATH = os.path.join(_BASE_DIR, "..", "docs", "data", "image_backfill.json")

_IMG_TAG_RE = re.compile(r'<img\b[^>]*>', re.I)
_SRC_RE = re.compile(r'src="([^"]+)"', re.I)


# ─── 대상 선별 ────────────────────────────────────────────────────────────────

def collect_targets(content: str) -> tuple[list[str], int]:
    """(복제 대상 URL, 무단 이미지 수).

    이미 복제된 것, data URI(본문에 박혀 있어 죽을 수 없음), 무단 이미지는
    대상이 아닙니다.
    """
    from image_fetcher import is_license_safe
    from image_mirror import is_mirrored_url

    targets: list[str] = []
    unlicensed = 0
    for tag in _IMG_TAG_RE.findall(content or ""):
        m = _SRC_RE.search(tag)
        if not m:
            continue
        url = m.group(1)
        if not is_license_safe(url):
            unlicensed += 1
            continue
        if url.startswith("data:") or is_mirrored_url(url):
            continue
        if url not in targets:
            targets.append(url)
    return targets, unlicensed


def point_to_mirror(content: str, old_url: str, new_url: str) -> str:
    """src를 복제본으로 바꾸고, 원본을 onerror 폴백으로 남깁니다.

    폴백을 남기는 이유: 복제본이 나중에 지워지거나 배포가 되돌아가도 원본이
    살아 있으면 글은 안 깨집니다. 이미 onerror가 있으면 건드리지 않습니다.
    """
    import html as _h
    esc_old = _h.escape(old_url, quote=True)

    def _sub(m: re.Match) -> str:
        tag = m.group(0)
        if f'src="{old_url}"' not in tag:
            return tag
        tag = tag.replace(f'src="{old_url}"', f'src="{new_url}"')
        if "onerror=" in tag.lower():
            return tag
        closer = "/>" if tag.rstrip().endswith("/>") else ">"
        body = tag.rstrip()[:-len(closer)].rstrip()
        return f'{body} onerror="this.onerror=null;this.src=\'{esc_old}\'"{closer}'

    return _IMG_TAG_RE.sub(_sub, content)


# ─── 공개 여부 확인 ───────────────────────────────────────────────────────────

class Liveness:
    """복제본이 실제로 열리는지 확인합니다 (한 번 본 것은 기억).

    이 확인이 2단계의 안전장치입니다. 아직 배포되지 않은 URL로 발행 글을
    돌려놓지 않기 위해, 낙관적으로 판단하지 않고 실제로 받아 봅니다.
    """

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self._seen: dict[str, bool] = {}

    def ok(self, url: str) -> bool:
        if url in self._seen:
            return self._seen[url]
        try:
            r = requests.head(url, timeout=self.timeout, allow_redirects=True)
            if r.status_code == 405:
                r = requests.get(url, timeout=self.timeout, stream=True)
            good = r.status_code == 200
        except requests.exceptions.RequestException as e:
            logger.warning(f"복제본 확인 실패({type(e).__name__}) — 교체 보류: {url[:80]}")
            good = False
        self._seen[url] = good
        return good


# ─── 본체 ─────────────────────────────────────────────────────────────────────

def run(blogs: list[dict], mode: str, dry_run: bool, limit: int = 0) -> dict:
    from blogger_uploader import _get_access_token
    from fix_unlicensed_images import _iter_posts
    from image_mirror import mirror_url, mirrored_url_for, stats

    live = Liveness()
    scanned = touched = failed = 0
    mirrored = rewritten = skipped_undeployed = unlicensed_total = 0
    items: list[dict] = []

    for cfg in blogs:
        name = cfg.get("name") or cfg.get("id", "")
        blog_id = cfg.get("blog_id", "")
        if not blog_id:
            logger.warning(f"[{name}] blog_id 없음 — 건너뜀")
            continue
        token = _get_access_token(cfg)
        if not token:
            logger.error(f"[{name}] 액세스 토큰 발급 실패 — 건너뜀")
            failed += 1
            continue

        logger.info(f"── [{name}] {mode} 시작 ──")
        for post in _iter_posts(blog_id, token):
            if limit and touched >= limit:
                logger.info(f"--limit {limit} 도달 — 중단합니다")
                break
            scanned += 1
            content = post.get("content", "") or ""
            title = post.get("title", "") or ""
            targets, unlicensed = collect_targets(content)
            unlicensed_total += unlicensed
            if not targets:
                continue

            actions: list[dict] = []

            if mode == "mirror":
                for url in targets:
                    if dry_run:
                        actions.append({"url": url[:90], "action": "would_mirror"})
                        continue
                    got = mirror_url(url)
                    if got:
                        mirrored += 1
                        actions.append({"url": url[:90], "action": "mirrored",
                                        "file": got["file"], "reused": got["reused"]})
                    else:
                        actions.append({"url": url[:90], "action": "mirror_failed"})
                touched += 1

            else:  # rewrite
                new_content = content
                for url in targets:
                    mirror = mirrored_url_for(url)
                    if not mirror:
                        actions.append({"url": url[:90], "action": "not_mirrored_yet"})
                        continue
                    if not live.ok(mirror):
                        skipped_undeployed += 1
                        actions.append({"url": url[:90], "action": "not_deployed_yet"})
                        continue
                    new_content = point_to_mirror(new_content, url, mirror)
                    rewritten += 1
                    actions.append({"url": url[:90], "action": "rewritten", "to": mirror})

                if new_content == content:
                    if actions:
                        items.append({"title": title[:60], "url": post.get("url", ""),
                                      "actions": actions})
                    continue
                touched += 1
                if dry_run:
                    logger.info(f"  [dry-run] '{title[:45]}' — {len(actions)}장 교체 예정")
                else:
                    pr = requests.patch(
                        f"{BLOGGER_API_BASE}/blogs/{blog_id}/posts/{post['id']}",
                        headers={"Authorization": f"Bearer {token}",
                                 "Content-Type": "application/json"},
                        json={"content": new_content}, timeout=30,
                    )
                    if pr.status_code == 200:
                        logger.info(f"  ✅ '{title[:45]}' — {len(actions)}장 자체 호스팅으로 전환")
                    else:
                        logger.error(f"  ❌ 업데이트 실패 [{pr.status_code}]: {pr.text[:200]}")
                        failed += 1
                    time.sleep(1)   # Blogger API rate limit 배려

            items.append({"title": title[:60], "url": post.get("url", ""),
                          "actions": actions})

        if limit and touched >= limit:
            break

    report = {
        "runAt": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "dryRun": dry_run,
        "scannedPosts": scanned,
        "touchedPosts": touched,
        "imagesMirrored": mirrored,
        "imagesRewritten": rewritten,
        "skippedNotDeployed": skipped_undeployed,
        "unlicensedSeen": unlicensed_total,
        "postsFailed": failed,
        "store": stats(),
        "items": items[:100],
    }
    try:
        os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.warning(f"리포트 저장 실패: {e}")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="발행 글 이미지 소급 자체 호스팅")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--mirror-only", action="store_true",
                   help="1단계: 이미지를 내려받아 저장소에 저장 (발행 글은 손대지 않음)")
    g.add_argument("--rewrite", action="store_true",
                   help="2단계: 배포 확인 후 본문 src를 복제본으로 교체")
    ap.add_argument("--dry-run", action="store_true", help="대상만 확인")
    ap.add_argument("--blog", default="", help="특정 블로그만 (blog1/blog2/blog3)")
    ap.add_argument("--limit", type=int, default=0, help="처리할 글 수 상한")
    args = ap.parse_args()

    sys.path.insert(0, _BASE_DIR)
    from config import get_blog_configs

    blogs = get_blog_configs()
    if args.blog:
        blogs = [b for b in blogs if b.get("id") == args.blog]
        if not blogs:
            logger.error(f"블로그를 찾지 못했습니다: {args.blog}")
            return 1

    mode = "mirror" if args.mirror_only else "rewrite"
    report = run(blogs, mode, args.dry_run, args.limit)

    logger.info("─" * 60)
    logger.info(f"글 {report['scannedPosts']}편 확인 / 처리 {report['touchedPosts']}편")
    if mode == "mirror":
        logger.info(f"복제 {report['imagesMirrored']}장 — 저장소 {report['store']['mirrored']}장 "
                    f"({report['store']['totalBytes'] / 1024 / 1024:.1f}MB)")
        logger.info("이제 docs/images/ 와 docs/data/image_mirror.json 을 커밋·배포한 뒤 "
                    "--rewrite 를 돌리세요.")
    else:
        logger.info(f"본문 교체 {report['imagesRewritten']}장")
        if report["skippedNotDeployed"]:
            logger.warning(f"아직 배포되지 않아 건너뛴 이미지 {report['skippedNotDeployed']}장 "
                           f"— 배포 후 다시 돌리면 처리됩니다")
    if report["unlicensedSeen"]:
        logger.warning(f"화이트리스트 밖 이미지 {report['unlicensedSeen']}장은 복제하지 "
                       f"않았습니다 — fix_unlicensed_images.py 로 교체하세요")
    return 1 if report["postsFailed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
