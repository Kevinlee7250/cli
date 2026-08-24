"""저자 경험 자료가 실제로 글에 반영되는지 점검합니다.

왜 필요한가
──────────
author_profile.json은 조용히 실패합니다. 비어 있어도 워크플로는 초록으로
끝나고, 모든 글이 조사·분석형으로 나갑니다 — 그게 정상 동작이라 아무도
"경험형이 한 번도 안 켜졌다"는 사실을 눈치채지 못합니다. 실제로 이 파일은
템플릿 예시(`예: ISA 계좌`)만 든 채 방치돼 있었고, AdSense가 보는 E-E-A-T의
Experience 축이 통째로 비어 있었습니다.

이 스크립트는 두 가지를 보여 줍니다.
  1. 지금 등록된 경험이 몇 건이고 실제로 매칭에 쓰이는지
  2. 각 항목을 채우면 최근 발행 글 중 몇 편이 경험형으로 바뀌는지

  python author_profile_check.py            # 현황
  python author_profile_check.py --posts 60 # 최근 60편 기준으로 계산
"""

import argparse
import json
import logging
import os
import sys

logger = logging.getLogger(__name__)

_BASE = os.path.dirname(__file__)
_POSTS = os.path.join(_BASE, "..", "docs", "data", "posts.json")


def _load_posts(limit: int) -> list[dict]:
    try:
        with open(os.path.normpath(_POSTS), encoding="utf-8") as f:
            posts = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    return posts[:limit] if isinstance(posts, list) else []


def analyze(limit: int = 40) -> dict:
    """등록 현황과 '채우면 몇 편이 바뀌는지'를 계산합니다."""
    from config import get_author_profile
    from content_generator import _match_experience

    profile = get_author_profile()
    entries = [e for e in (profile.get("experiences") or []) if isinstance(e, dict)]

    def _usable(e):
        """실제로 매칭에 쓰이는 항목인지 — 예시 토픽뿐이거나 summary가 비면 아닙니다."""
        topics = [t for t in (e.get("topics") or []) if not str(t).strip().startswith("예:")]
        return bool(topics) and bool(str(e.get("summary", "")).strip())

    posts = _load_posts(limit)
    active = sum(1 for e in entries if _usable(e))

    # 지금 기준으로 경험형이 되는 글
    now_exp = sum(1 for p in posts
                  if _match_experience(p.get("keyword", ""), p.get("blogId", "")))

    # 항목별로 "이것만 채우면 몇 편이 바뀌는지"
    #
    # 판정은 반드시 _match_experience를 그대로 씁니다. 여기에 자체 매칭 로직을
    # 두면 실제 동작과 어긋납니다 — 처음에 부분문자열로 셌다가 "골프"가
    # "골프장"과 맞는 것처럼 과대 보고했습니다. 실제 매칭은 단어 단위입니다.
    per_entry = []
    for e in entries:
        topics = [str(t).strip() for t in (e.get("topics") or [])
                  if not str(t).strip().startswith("예:")]
        blogs = e.get("blogs") or []
        probe = {"topics": topics, "blogs": blogs, "summary": "확인용", "detail": ""}
        monkey = {"experiences": [probe]}
        hits = 0
        for p in posts:
            import config as _cfg
            _orig = _cfg.get_author_profile
            _cfg.get_author_profile = lambda: monkey
            try:
                if _match_experience(p.get("keyword", ""), p.get("blogId", "")):
                    hits += 1
            finally:
                _cfg.get_author_profile = _orig
        per_entry.append({
            "topics": topics[:4],
            "blogs": blogs,
            "filled": _usable(e),
            "wouldCover": hits,
        })

    return {
        "entries": len(entries),
        "active": active,
        "postsChecked": len(posts),
        "experienceNow": now_exp,
        "perEntry": per_entry,
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="저자 경험 자료 점검")
    parser.add_argument("--posts", type=int, default=40, help="최근 몇 편 기준으로 볼지")
    args = parser.parse_args()

    r = analyze(args.posts)
    print("\n" + "=" * 62)
    print("저자 경험 자료 현황")
    print("=" * 62)
    print(f"  등록 항목        {r['entries']}건")
    print(f"  실제 매칭에 사용 {r['active']}건" +
          ("   ⚠️ summary가 비면 매칭되지 않습니다" if r["active"] < r["entries"] else ""))
    print(f"  최근 {r['postsChecked']}편 중 경험형  {r['experienceNow']}편")
    print("-" * 62)
    print("  항목별 — 채우면 최근 글 몇 편이 경험형으로 바뀌는지")
    for e in r["perEntry"]:
        mark = "✅" if e["filled"] else "⬜"
        topics = ", ".join(e["topics"]) or "(토픽 없음)"
        blogs = ",".join(e["blogs"]) or "전체"
        print(f"   {mark} {topics[:38]:38} [{blogs:11}] {e['wouldCover']:2}편")
    print("=" * 62)
    if r["active"] == 0:
        print("모든 글이 조사·분석형으로 나갑니다. summary를 채우면 그 주제부터")
        print("1인칭 경험 서술이 열립니다 (자료 범위 안에서만).")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
