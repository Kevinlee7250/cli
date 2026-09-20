"""사람이 쓴 보강 원고를 발행 글에 끼워 넣습니다.

왜 별도 도구인가
────────────────
분량이 모자란 글을 AI로 자동 증량하는 기능은 **일부러 만들지 않았습니다.**
2026-09-12 AdSense 거절 사유가 지어낸 내용이었고, "글자수를 채워라"는
지시만큼 지어내기를 부르는 요구도 없습니다.

대신 이 도구는 **이미 사람이 검증해 git에 넣은 원고**를 옮겨 붙이기만
합니다. 원고는 expansions/ 아래 JSON으로 리뷰를 거쳐 들어오고, 여기서는
아무것도 생성하지 않습니다.

안전장치
────────
  · 앵커가 본문에 정확히 1번 없으면 중단 — 엉뚱한 자리에 넣지 않습니다
  · 이미 들어간 원고면 건너뜀 (marker로 판정, 몇 번 돌려도 같음)
  · 넣은 뒤 experience_audit을 돌려 경험 주장이 생기면 반려
  · 기본은 dry-run

사용
────
  python apply_expansion.py --list
  python apply_expansion.py --slug samsung-stock          # 미리보기
  python apply_expansion.py --slug samsung-stock --apply
"""

import argparse
import glob
import json
import logging
import os
import sys

import requests
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"
_BASE = os.path.dirname(__file__)
EXPANSION_DIR = os.path.join(_BASE, "expansions")
MIN_CHARS = 2500


def load_expansions(slug: str = "") -> list[dict]:
    out = []
    for p in sorted(glob.glob(os.path.join(EXPANSION_DIR, "*.json"))):
        name = os.path.basename(p)[:-5]
        if slug and name != slug:
            continue
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"{name}: 읽기 실패 — {e}")
            continue
        data["slug"] = name
        out.append(data)
    return out


def _find_post(token: str, blog_id: str, url: str) -> dict | None:
    r = requests.get(
        f"{BLOGGER_API_BASE}/blogs/{blog_id}/posts/bypath",
        headers={"Authorization": f"Bearer {token}"},
        params={"path": "/" + url.split("/", 3)[-1]}, timeout=30)
    if r.status_code == 200:
        return r.json()
    logger.error(f"글 조회 실패 [{r.status_code}]: {r.text[:200]}")
    return None


def expand(content: str, exp: dict) -> tuple[str, str]:
    """(새 본문, 사유). 넣지 못하면 새 본문은 원본 그대로."""
    marker = exp.get("marker") or ""
    if marker and marker in content:
        return content, "이미 반영됨"

    anchor = exp.get("anchor") or ""
    html = exp.get("html") or ""
    if not html:
        return content, "원고가 비어 있음"

    if anchor:
        n = content.count(anchor)
        if n != 1:
            return content, f"앵커가 {n}번 나타남 — 위치를 특정할 수 없어 중단"
        new = content.replace(anchor, html + "\n" + anchor)
    else:
        new = content + "\n" + html

    from experience_audit import analyze_text, _strip_html
    hits = analyze_text(_strip_html(html))
    if hits:
        labels = ", ".join(sorted({h["label"] for h in hits}))
        return content, f"원고에 경험 주장이 있어 반려 ({labels})"

    return new, ""


def run(slug: str = "", apply_changes: bool = False) -> int:
    from config import get_blog_configs
    from blogger_uploader import _get_access_token
    from experience_audit import _strip_html

    items = load_expansions(slug)
    if not items:
        logger.warning("적용할 원고가 없습니다 (expansions/*.json)")
        return 0

    blogs = {b.get("id"): b for b in get_blog_configs()}
    applied = 0
    for exp in items:
        cfg = blogs.get(exp.get("blog"))
        if not cfg:
            logger.error(f"[{exp['slug']}] 블로그 '{exp.get('blog')}' 설정 없음")
            continue
        token = _get_access_token(cfg)
        blog_id = cfg.get("blog_id", "")
        if not (token and blog_id):
            logger.error(f"[{exp['slug']}] 토큰 없음")
            continue

        post = _find_post(token, blog_id, exp.get("url", ""))
        if not post:
            continue

        content = post.get("content", "") or ""
        new, why = expand(content, exp)
        before, after = len(_strip_html(content)), len(_strip_html(new))

        if why:
            logger.warning(f"  ⏭️  [{exp['slug']}] {why}")
            continue

        logger.info(f"  {'✅' if apply_changes else '📝'} [{exp['slug']}] "
                    f"{post.get('title','')[:34]} — 본문 {before:,} → {after:,}자"
                    + ("" if after >= MIN_CHARS else f" (⚠️ {MIN_CHARS}자 미달)"))

        if not apply_changes:
            continue

        r = requests.patch(
            f"{BLOGGER_API_BASE}/blogs/{blog_id}/posts/{post['id']}",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json={"content": new}, timeout=30)
        if r.status_code != 200:
            logger.error(f"     수정 실패 [{r.status_code}]: {r.text[:200]}")
            continue
        applied += 1

    logger.info(f"완료 — {applied}편 {'반영' if apply_changes else '반영 예정'}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="검증된 보강 원고를 발행 글에 반영")
    p.add_argument("--slug", default="", help="expansions/<slug>.json 하나만")
    p.add_argument("--apply", action="store_true", help="실제로 반영 (기본: 미리보기)")
    p.add_argument("--list", action="store_true", help="원고 목록만 출력")
    args = p.parse_args()

    if args.list:
        for e in load_expansions():
            print(f"  {e['slug']:24} {e.get('blog','?'):6} {e.get('url','')}")
        return 0
    return run(args.slug, args.apply)


if __name__ == "__main__":
    sys.exit(main())
