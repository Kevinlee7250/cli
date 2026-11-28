"""조용한 실패 감시 — '오류는 없는데 멈춰 있는' 작업을 찾습니다 (읽기 전용).

왜 필요한가
────────────
2026-11-06~07에 자동화 전체가 아무 오류 없이 멈췄고 13일 동안 아무도 몰랐습니다.
멈춘 것은 실패가 아니라 '실행 자체가 안 된 것'이라 실패 알림이 오지 않습니다.
2026-11-25에는 게시는 성공했는데 기록 push만 실패해 같은 일이 부분적으로
났습니다(AIOPS-59). 실패 기록이 아니라 '마지막으로 갱신된 시각'을 봐야 잡힙니다.

무엇을 보나
────────────
  1. 데이터 파일 신선도 — 매일·매주 갱신돼야 할 docs/data/*.json 의 시각 필드가
     정해진 시간보다 오래됐는지. 기준은 그 파일을 쓰는 워크플로 예약 주기의
     2배(매일 → 48시간, 매주 → 8일)입니다.
  2. 블로그별 발행 — docs/data/runs.json 의 블로그별 마지막 실행이 48시간을
     넘었는지, 최근 실행이 연속으로 0건(발행 없음)인지.
  3. 최근 실행 오류 — 최근 7일 실행 중 errors > 0.

이 도구는 GitHub Actions 위에서 돌므로, Actions 전체가 꺼지면 이 도구도 돌지
않습니다. 그 경우는 클라우드 주간 생존 점검(수 08:47, Notion AIOPS-65)이 잡습니다
— 둘은 서로를 대신하지 않습니다.

결과: docs/data/silent_failures.json (문제 없음도 기록합니다)
종료 코드: 문제가 있으면 1 — 워크플로 화면에 빨간 표시가 남게 합니다.

Usage:
  python silent_failure_watch.py
  python silent_failure_watch.py --now 2026-11-29T00:00:00Z --no-write
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

import post_sources

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DAY = timedelta(days=1)

#: (파일, 시각 필드, 허용 나이, 쓰는 워크플로·예약) — 예약을 바꾸면 여기도 고칩니다.
FRESHNESS = [
    ("index_status.json", "checked_at", 2 * DAY, "gsc-indexing.yml 매일"),
    ("gsc_diagnosis.json", "checkedAt", 2 * DAY, "gsc-indexing.yml 매일"),
    ("sitemap_status.json", "checkedAt", 2 * DAY, "gsc-indexing.yml·blog-run.yml 매일"),
    ("live_posts.json", "syncedAt", 2 * DAY, "blog-run.yml 매일"),
    ("alerts.json", "checkedAt", 2 * DAY, "alert-watchdog.yml 매일"),
    ("auth_health.json", "checked_at", 8 * DAY, "auto-repair.yml 매주 일"),
    ("required_pages.json", "checkedAt", 8 * DAY, "adsense-audit.yml 매주 화"),
    ("weekly_brief.json", "generated_at", 8 * DAY, "weekly-brief.yml 매주 월"),
]

BLOGS = ("blog1", "blog2", "blog3")
RUN_MAX_AGE = 2 * DAY
ZERO_STREAK = 2


def parse_ts(s: str) -> datetime | None:
    """'...Z' · '+00:00' · '+0000' · 시간대 없음(UTC로 간주)을 모두 읽습니다."""
    if not s:
        return None
    s = str(s).strip().replace("Z", "+00:00")
    if len(s) > 5 and s[-5] in "+-" and s[-3] != ":":
        s = s[:-2] + ":" + s[-2:]
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _load(name: str):
    with open(os.path.join(post_sources.DOCS_DATA, name), encoding="utf-8") as f:
        return json.load(f)


def _first_ts(data, field: str) -> str:
    if isinstance(data, dict):
        return data.get(field, "")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0].get(field, "")
    return ""


def check_freshness(now: datetime) -> list[dict]:
    out = []
    for name, field, limit, who in FRESHNESS:
        try:
            ts = parse_ts(_first_ts(_load(name), field))
        except (FileNotFoundError, json.JSONDecodeError) as e:
            out.append({"kind": "freshness", "file": name, "status": "unreadable", "detail": str(e)[:120], "by": who})
            continue
        if ts is None:
            out.append({"kind": "freshness", "file": name, "status": "no_timestamp", "by": who})
            continue
        age = now - ts
        out.append({"kind": "freshness", "file": name, "at": ts.isoformat(),
                    "ageHours": round(age.total_seconds() / 3600, 1),
                    "limitHours": int(limit.total_seconds() / 3600),
                    "status": "stale" if age > limit else "ok", "by": who})
    return out


def check_runs(now: datetime) -> list[dict]:
    try:
        runs = _load("runs.json")
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return [{"kind": "runs", "status": "unreadable", "detail": str(e)[:120]}]
    out = []
    for blog in BLOGS:
        mine = sorted((r for r in runs if r.get("blogId") == blog and parse_ts(r.get("runAt", ""))),
                      key=lambda r: parse_ts(r["runAt"]), reverse=True)
        if not mine:
            out.append({"kind": "runs", "blogId": blog, "status": "no_runs"})
            continue
        last = parse_ts(mine[0]["runAt"])
        streak = 0
        for r in mine:
            if (r.get("bloggerUploaded") or 0) > 0:
                break
            streak += 1
        recent_err = [r for r in mine if now - parse_ts(r["runAt"]) <= 7 * DAY and (r.get("errors") or 0) > 0]
        age = now - last
        status = "stale" if age > RUN_MAX_AGE else "zero_streak" if streak >= ZERO_STREAK else "ok"
        out.append({"kind": "runs", "blogId": blog, "lastRunAt": last.isoformat(),
                    "ageHours": round(age.total_seconds() / 3600, 1), "zeroStreak": streak,
                    "lastOutcome": mine[0].get("outcome", ""), "errors7d": len(recent_err),
                    "status": status})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="조용한 실패 감시(읽기 전용)")
    ap.add_argument("--now", default="", help="기준 시각(ISO, 기본: 지금)")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()
    now = parse_ts(args.now) if args.now else datetime.now(timezone.utc)

    checks = check_freshness(now) + check_runs(now)
    problems = [c for c in checks if c.get("status") != "ok"]
    report = {"checkedAt": now.isoformat(), "problems": len(problems), "checks": checks}
    for c in problems:
        logger.warning(f"⚠️ {c.get('file') or c.get('blogId')}: {c['status']} "
                       f"{c.get('ageHours', '')}h {c.get('by', '')}".rstrip())
    logger.info(f"점검 {len(checks)}항목 · 문제 {len(problems)}")
    if not args.no_write:
        logger.info(f"기록: {post_sources.write_report('silent_failures.json', report)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
