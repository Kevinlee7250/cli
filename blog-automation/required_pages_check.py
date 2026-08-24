"""AdSense 심사에 필요한 페이지가 블로그에 실제로 있는지 확인합니다 (읽기 전용).

왜 필요한가
──────────
page_creator.py가 개인정보처리방침·소개 페이지를 만들 수 있는데, 그걸 부르는
진입점은 `main.py --setup` 하나뿐이고 **어떤 워크플로도 그 경로를 실행하지
않습니다**. 즉 누군가 로컬에서 한 번 돌렸는지 여부에 달려 있고, 돌렸더라도
나중에 지워졌는지 아무도 모릅니다. AdSense 심사에서 이 페이지들이 없으면
바로 걸리는 항목인데, 시스템 어디에도 "있다/없다"가 기록되지 않았습니다.

이 스크립트는 확인만 합니다. 만들지 않습니다 — 발행된 블로그에 페이지를
자동으로 얹는 것은 사람이 승인할 일입니다. 없으면 어떻게 만드는지만 알립니다.

  python required_pages_check.py              # 확인 + docs/data/required_pages.json 기록
  python required_pages_check.py --blog blog1

없을 때 만드는 법:  python main.py --setup --blog blog1
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_BASE = os.path.dirname(__file__)
REPORT_PATH = os.path.normpath(
    os.path.join(_BASE, "..", "docs", "data", "required_pages.json"))

#: 심사에 필요한 페이지. 제목이 정확히 같지 않아도 되도록 별칭을 함께 둡니다 —
#: 사람이 손으로 만들었다면 "개인정보 처리방침"처럼 띄어쓰기가 다를 수 있습니다.
REQUIRED = {
    "privacy_policy": ("개인정보처리방침", ["개인정보", "privacy"]),
    "about": ("블로그 소개", ["소개", "about", "about us"]),
    "contact": ("문의", ["문의", "연락", "contact"]),
}


def _norm(text: str) -> str:
    return "".join((text or "").lower().split())


def _find(pages: list[dict], aliases: list[str]) -> dict | None:
    for page in pages:
        title = _norm(page.get("title"))
        if any(_norm(a) in title for a in aliases):
            return page
    return None


def check(blog_filter: str = "") -> dict:
    """블로그별로 필수 페이지 존재 여부를 확인합니다. 아무것도 만들지 않습니다."""
    from config import get_blog_configs
    from page_creator import _get_access_token, _get_blog_id, _list_existing_pages

    blogs = get_blog_configs()
    if blog_filter:
        blogs = [b for b in blogs if b.get("id") == blog_filter] or blogs

    results = []
    for cfg in blogs:
        name = cfg.get("name") or cfg.get("id", "")
        entry = {"blog": name, "blogId": cfg.get("id", ""), "pages": {}, "missing": []}
        token = _get_access_token(cfg)
        if not token:
            # 토큰이 없으면 "없다"가 아니라 "모른다"입니다. 둘을 섞으면 멀쩡한
            # 페이지를 없는 것으로 보고하게 됩니다.
            entry["error"] = "토큰 발급 실패 — 확인할 수 없음"
            results.append(entry)
            logger.warning(f"[{name}] 토큰 없음 — 확인 불가")
            continue

        pages = _list_existing_pages(token, _get_blog_id(cfg))
        for key, (label, aliases) in REQUIRED.items():
            found = _find(pages, aliases)
            entry["pages"][key] = {
                "label": label,
                "exists": bool(found),
                "url": (found or {}).get("url", ""),
            }
            if not found:
                entry["missing"].append(label)
        results.append(entry)
        mark = "✅" if not entry["missing"] else "⚠️"
        logger.info(f"{mark} [{name}] 페이지 {len(pages)}개 중 "
                    f"필수 {len(REQUIRED) - len(entry['missing'])}/{len(REQUIRED)}개 확인"
                    + (f" — 없음: {', '.join(entry['missing'])}" if entry["missing"] else ""))

    checked = [r for r in results if not r.get("error")]
    report = {
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "blogs": results,
        "blogsChecked": len(checked),
        "blogsWithMissing": sum(1 for r in checked if r["missing"]),
        "unknown": len(results) - len(checked),
        # 확인한 블로그가 하나도 없으면 ok로 볼 수 없습니다 — 사이트맵 제출에서
        # "한 건도 못 보냈는데 실패 0이라 성공"으로 읽던 실수와 같은 유형입니다.
        "ok": bool(checked) and all(not r["missing"] for r in checked),
    }
    try:
        os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, separators=(",", ":"))
    except OSError as e:
        logger.warning(f"리포트 저장 실패 (무시): {e}")
    return report


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    parser = argparse.ArgumentParser(description="AdSense 필수 페이지 확인 (읽기 전용)")
    parser.add_argument("--blog", default="", help="특정 블로그만")
    args = parser.parse_args()

    r = check(args.blog)
    print("\n" + "=" * 58)
    print("AdSense 필수 페이지 확인")
    print("=" * 58)
    for b in r["blogs"]:
        if b.get("error"):
            print(f"  ❓ {b['blog']}  {b['error']}")
            continue
        for key, info in b["pages"].items():
            mark = "✅" if info["exists"] else "❌"
            print(f"  {mark} {b['blog'][:16]:16} {info['label']}")
    print("-" * 58)
    if r["unknown"]:
        print(f"  확인 불가 {r['unknown']}개 블로그 (자격증명 문제)")
    if r["blogsWithMissing"]:
        print(f"  ⚠️ {r['blogsWithMissing']}개 블로그에 필수 페이지가 없습니다")
        print("     만들려면: python main.py --setup --blog <blogId>")
        print("     (발행 중인 블로그를 수정하므로 확인 후 실행하세요)")
    elif r["ok"]:
        print("  모든 블로그에 필수 페이지가 있습니다")
    print("=" * 58 + "\n")
    # 없다고 해서 실패로 끝내지는 않습니다 — 감사 워크플로의 다른 단계를
    # 막을 이유가 없습니다. 결과는 리포트 파일과 대시보드에 남습니다.
    return 0


if __name__ == "__main__":
    sys.exit(main())
