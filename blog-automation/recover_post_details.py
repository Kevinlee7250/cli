"""글 상세(FAQ·출처)를 실행 이력에서 되살립니다.

왜 필요한가
──────────
posts.json은 목록만, faq·sources는 post_details.json에 따로 둡니다. 그런데
워크플로 커밋 목록에 post_details.json이 빠져 있으면 러너가 만든 상세가
버려집니다 — 목록에는 "FAQ 3개" 배지가 남고 모달을 열면 비어 있습니다.
2026-08-22~23 발행분 2편이 실제로 이 상태가 됐습니다.

다행히 원본은 logs/run_history.json에 남습니다. 실행 이력은 별도 경로로
커밋되기 때문입니다. 여기서 그걸 대조해 되살립니다.

  python recover_post_details.py            # 무엇을 되살릴지 보기만
  python recover_post_details.py --apply    # 실제로 기록

커밋 목록 누락 자체는 test_workflow_pending_files.py가 막습니다. 이 스크립트는
이미 유실된 것을 되돌리는 용도이고, 앞으로도 같은 일이 생기면 다시 씁니다.
"""

import argparse
import json
import logging
import os

logger = logging.getLogger(__name__)

_BASE = os.path.dirname(__file__)
HISTORY_FILE = os.path.join(_BASE, "logs", "run_history.json")
POSTS_FILE = os.path.join(_BASE, "..", "docs", "data", "posts.json")
DETAILS_FILE = os.path.join(_BASE, "..", "docs", "data", "post_details.json")


def _read(path, fallback):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return fallback
    return data if isinstance(data, type(fallback)) else fallback


def index_history(history: list[dict]) -> dict:
    """실행 이력의 글을 (제목, 키워드)로 찾을 수 있게 펼칩니다.

    posts.json의 id는 내보내기 시점에 만들어져 실행 이력에는 없습니다.
    제목과 키워드 둘 다 맞아야 같은 글로 봅니다 — 제목만 보면 재발행된
    동명의 글과 섞입니다.
    """
    found: dict[tuple, dict] = {}
    for run in history:
        for post in run.get("posts") or []:
            key = (post.get("title"), post.get("keyword"))
            if key[0] and key not in found:      # 최신 실행이 앞에 오므로 먼저 만난 것 유지
                found[key] = post
    return found


def find_recoverable(posts: list[dict], details: dict, history: list[dict]) -> list[dict]:
    """상세가 없는데 이력에는 남아 있는 글을 찾습니다."""
    by_key = index_history(history)
    out = []
    for post in posts:
        pid = post.get("id")
        if not pid or pid in details:
            continue
        # 상세가 있었어야 하는 글만 대상 — 원래 FAQ·출처가 없던 글은 정상입니다
        if not (post.get("faqCount") or post.get("sourceCount")):
            continue
        src = by_key.get((post.get("title"), post.get("keyword")))
        if not src:
            continue
        faq = src.get("faq") or []
        sources = src.get("sources") or []
        if not (faq or sources):
            continue
        out.append({"id": pid, "title": post.get("title", ""),
                    "faq": faq, "sources": sources})
    return out


def run(apply_changes: bool) -> dict:
    posts = _read(POSTS_FILE, [])
    details = _read(DETAILS_FILE, {})
    history = _read(HISTORY_FILE, [])

    recoverable = find_recoverable(posts, details, history)
    missing_total = sum(
        1 for p in posts
        if p.get("id") and p["id"] not in details and (p.get("faqCount") or p.get("sourceCount"))
    )

    for r in recoverable:
        logger.info(f"  복구 대상: FAQ {len(r['faq'])}개 / 출처 {len(r['sources'])}개 — {r['title'][:50]}")
    unrecoverable = missing_total - len(recoverable)
    if unrecoverable:
        logger.warning(f"  이력에도 없어 복구 불가: {unrecoverable}건")

    if apply_changes and recoverable:
        for r in recoverable:
            details[r["id"]] = {"faq": r["faq"], "sources": r["sources"]}
        from dashboard_exporter import write_data
        write_data(os.path.normpath(DETAILS_FILE), details)
        logger.info(f"✅ {len(recoverable)}건 복구 — post_details.json에 기록")
    elif recoverable:
        logger.info("🔍 미리보기 모드 — --apply 로 실제 기록")
    else:
        logger.info("복구할 것이 없습니다")

    return {"missing": missing_total, "recovered": len(recoverable) if apply_changes else 0,
            "recoverable": len(recoverable), "unrecoverable": unrecoverable}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="글 상세(FAQ·출처) 복구")
    parser.add_argument("--apply", action="store_true", help="실제로 기록 (기본은 미리보기)")
    args = parser.parse_args()
    result = run(args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
