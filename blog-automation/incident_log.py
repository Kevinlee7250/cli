"""인시던트 로그 — 세션이 끝나도 남는 장애 대응 지식 저장소.

디버깅 세션마다 근본 원인을 처음부터 다시 추리하지 않도록, 발견한 문제와
수정 내역을 구조화해서 기록합니다. 다음 세션(또는 다음 담당자)이
docs/data/incident_log.json을 먼저 검색하면 같은 장애를 훨씬 빨리
진단할 수 있습니다.

Usage (코드에서):
  from incident_log import add_incident
  add_incident(
      title="GSC 도메인 속성 403",
      symptom="사이트맵 제출이 blog1에서만 403",
      root_cause="URL-프리픽스 조회가 도메인 속성 GSC에 안 맞음",
      fix="_domain_property_for() 폴백 추가",
      files=["blog_analytics.py", "gsc_indexing.py"],
      prevention="tests/test_auth_flow.py에 회귀 테스트 추가",
  )

CLI:
  python incident_log.py --list                 # 최근 인시던트 목록
  python incident_log.py --search "invalid_grant"  # 키워드 검색
"""

import argparse
import json
import os
import re
from datetime import datetime, timezone

_DOCS_DATA = os.path.join(os.path.dirname(__file__), "..", "docs", "data")
_LOG_FILE = os.path.join(_DOCS_DATA, "incident_log.json")


def _load() -> list[dict]:
    if not os.path.exists(_LOG_FILE):
        return []
    try:
        with open(_LOG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save(entries: list[dict]) -> None:
    os.makedirs(_DOCS_DATA, exist_ok=True)
    with open(_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def add_incident(
    title: str,
    symptom: str,
    root_cause: str,
    fix: str,
    files: list[str] | None = None,
    prevention: str = "",
) -> dict:
    """새 인시던트를 기록하고 저장합니다."""
    entry = {
        "id": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
        "date": datetime.now(timezone.utc).isoformat(),
        "title": title,
        "symptom": symptom,
        "root_cause": root_cause,
        "fix": fix,
        "files": files or [],
        "prevention": prevention,
    }
    entries = _load()
    entries.insert(0, entry)
    _save(entries[:200])  # 최대 200건 보관
    return entry


def search(keyword: str) -> list[dict]:
    kw = keyword.lower()
    return [
        e for e in _load()
        if kw in json.dumps(e, ensure_ascii=False).lower()
    ]


_STOPWORDS = {"the", "a", "an", "of", "to", "for", "and", "or", "is", "are", "in", "on"}


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z0-9_]+|[가-힣]+", text.lower())
    return {w for w in words if len(w) > 1 and w not in _STOPWORDS}


def match_known(message: str, min_overlap: int = 2) -> dict | None:
    """새 진단 메시지를 과거 인시던트와 자동 대조합니다 (자가진단 대조 봇).

    같은 종류의 장애(예: GSC 403, invalid_grant)가 재발했을 때, 사람이 다시
    처음부터 원인을 추리하지 않도록 이미 기록된 root_cause/fix를 즉시 보여줍니다.
    토큰 겹침 개수로만 판단하는 단순 매칭 — 정교한 유사도가 아니라 "이거 전에
    본 문제 같은데?"를 빠르게 알려주는 용도입니다.
    """
    msg_tokens = _tokenize(message)
    if not msg_tokens:
        return None

    best, best_score = None, 0
    for entry in _load():
        haystack = " ".join([entry.get("title", ""), entry.get("symptom", "")])
        overlap = len(msg_tokens & _tokenize(haystack))
        if overlap > best_score:
            best, best_score = entry, overlap

    if best and best_score >= min_overlap:
        return {
            "incident_id": best["id"],
            "title": best["title"],
            "root_cause": best["root_cause"],
            "fix": best["fix"],
            "match_score": best_score,
        }
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="인시던트 로그 조회")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--search", default="")
    args = parser.parse_args()

    if args.search:
        results = search(args.search)
    else:
        results = _load()[:10]

    if not results:
        print("기록된 인시던트가 없습니다.")
        return 0

    for e in results:
        print(f"\n[{e['date'][:10]}] {e['title']}")
        print(f"  증상: {e['symptom']}")
        print(f"  원인: {e['root_cause']}")
        print(f"  조치: {e['fix']}")
        if e.get("prevention"):
            print(f"  재발방지: {e['prevention']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
