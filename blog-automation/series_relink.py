"""시리즈 회차와 실제 글을 다시 잇습니다 (post_id 도입 이전 회차 대상).

회차와 글을 잇는 유일한 끈이 제목이었는데, final_editor가 생성 후 제목을
교정하므로(`post_data["title"] = new_title`) 그 순간 연결이 끊깁니다. 2026-08-24
점검에서 pending_review 41편 중 35편이 어느 목록에서도 제목으로 찾히지
않았습니다.

앞으로 만들어지는 회차는 main.py가 post_id를 적어 두므로 끊기지 않습니다.
이 스크립트는 이미 끊긴 것을 되돌립니다.

되돌리는 방법
─────────────
1. 제목 정확 일치 → post_id 기록
2. 제목 앞부분(공백·기호 제거 후 14자) 일치 → post_id 기록
3. 그래도 못 찾으면 상태를 'lost'로 바꿉니다. 'pending_review'로 두면
   대시보드가 "검토를 기다리는 글"로 보여 주는데 실제로는 열 수 있는 글이
   없습니다 — 없는 일감을 있는 것처럼 보여 주느니 없다고 적는 편이 낫습니다.

  python series_relink.py            # 무엇이 바뀌는지만 (기본)
  python series_relink.py --apply    # 실제 반영
"""

import argparse
import json
import logging
import os
import re
import sys

logger = logging.getLogger(__name__)

_BASE = os.path.dirname(__file__)
_DATA = os.path.normpath(os.path.join(_BASE, "..", "docs", "data"))
SERIES_FILE = os.path.join(_DATA, "series.json")

#: 제목 앞부분을 몇 자까지 보고 같은 글로 볼지. 짧으면 엉뚱한 글에 붙고,
#: 길면 교정된 제목을 놓칩니다. 앞 14자 안에서 갈라지면(제목 중간을 고친
#: 경우) 못 찾습니다 — 이 한계 때문에 앞으로는 post_id로 잇습니다.
PREFIX_LEN = 14
#: 이어 붙일 수 없을 때 남길 상태. 'pending_review'로 두면 열 수 없는 일감이
#: 검토 목록에 계속 남습니다.
LOST_STATUS = "lost"


def _norm(text: str) -> str:
    return re.sub(r"[^가-힣a-z0-9]", "", (text or "").lower())


def _candidates() -> list[dict]:
    """글을 찾을 후보 — 검토 대기 + 보관 + 발행 목록 전부."""
    import pending_store
    rows = list(pending_store.load())
    # 레지스트리까지 넣습니다. posts.json은 최근 100편만 담고 있어 7월 회차를
    # 못 봅니다 — 처음에 이걸 빠뜨려 "어디에도 없다"고 성급히 결론 낼 뻔했습니다.
    for name in ("posts.json", "post_registry.json"):
        try:
            with open(os.path.join(_DATA, name), encoding="utf-8") as f:
                rows.extend(json.load(f))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
    return [r for r in rows if isinstance(r, dict)]


def relink(apply_changes: bool = False) -> dict:
    try:
        with open(SERIES_FILE, encoding="utf-8") as f:
            series = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
        logger.error(f"series.json 읽기 실패: {e}")
        return {"error": str(e)}

    posts = _candidates()
    by_title = {}
    by_prefix = {}
    for p in posts:
        t = _norm(p.get("title"))
        if not t or not p.get("id"):
            continue
        by_title.setdefault(t, p["id"])
        by_prefix.setdefault(t[:PREFIX_LEN], p["id"])

    exact = prefix = lost = already = 0
    details = []
    for sr in series:
        for ep in sr.get("episodes", []):
            if ep.get("status") != "pending_review":
                continue
            if ep.get("post_id"):
                already += 1
                continue
            t = _norm(ep.get("title"))
            pid = by_title.get(t)
            how = "제목 일치"
            if not pid and t:
                pid = by_prefix.get(t[:PREFIX_LEN])
                how = "제목 앞부분 일치"
            if pid:
                if apply_changes:
                    ep["post_id"] = pid
                exact += (how == "제목 일치")
                prefix += (how == "제목 앞부분 일치")
                details.append({"episode": ep.get("episode"), "title": ep.get("title", "")[:40],
                                "postId": pid, "how": how})
            else:
                lost += 1
                if apply_changes:
                    ep["status"] = LOST_STATUS
                    # 나중에 이 상태를 보는 사람이 "왜?"를 다시 조사하지 않도록
                    # 어디까지 찾아봤는지 남깁니다.
                    ep["lostReason"] = ("검토 대기·보관·발행 목록·레지스트리에서 "
                                        "제목으로 찾지 못함 (제목 교정으로 연결이 끊긴 뒤 "
                                        "본문 기록이 남지 않음)")
                details.append({"episode": ep.get("episode"), "title": ep.get("title", "")[:40],
                                "postId": None, "how": "찾지 못함 → lost"})

    if apply_changes:
        with open(SERIES_FILE, "w", encoding="utf-8") as f:
            json.dump(series, f, ensure_ascii=False, separators=(",", ":"))

    return {"exact": exact, "prefix": prefix, "lost": lost,
            "alreadyLinked": already, "applied": apply_changes, "details": details}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="시리즈 회차 ↔ 글 재연결")
    parser.add_argument("--apply", action="store_true", help="실제 반영")
    args = parser.parse_args()

    r = relink(args.apply)
    if r.get("error"):
        return 1
    print(f"\n제목 일치 {r['exact']}건 / 앞부분 일치 {r['prefix']}건 / "
          f"찾지 못함 {r['lost']}건 / 이미 연결됨 {r['alreadyLinked']}건")
    for d in r["details"][:12]:
        mark = "✓" if d["postId"] else "✗"
        print(f"  {mark} {d['episode']}편 {d['title'][:34]:34} {d['how']}")
    if len(r["details"]) > 12:
        print(f"  … 외 {len(r['details']) - 12}건")
    if not args.apply:
        print("\n미리보기입니다 — 반영하려면 --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
