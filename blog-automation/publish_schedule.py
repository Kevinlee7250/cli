"""블로그별 자동 발행 계획.

왜 파일로 빼는가
────────────────
발행량이 워크플로 YAML 안에 박혀 있었습니다. 당번을 연중일 % 3으로 정해
하루 한 블로그만 돌았고(블로그당 3일에 1편), 이걸 바꾸려면 매번 워크플로를
고쳐 PR을 올려야 했습니다. 조정할 일이 잦은 값은 코드가 아니라 설정이어야
합니다 — 이제 이 JSON 한 곳이 원본이고, 대시보드도 같은 파일을 고칩니다.

읽는 규칙
─────────
· 파일이 없거나 깨졌으면 "블로그별 하루 1편"으로 봅니다. 설정을 못 읽었다고
  발행이 조용히 멈추면, 초록불인데 글이 안 올라오는 상태가 됩니다.
· 모르는 블로그 id는 기본값(켜짐·1편)으로 취급합니다.
· postsPerDay는 0~5로 자릅니다. 0은 "오늘은 쉼"이고 enabled=false와 같습니다.
· days는 "daily"(매일) 또는 요일 번호 목록(0=월 … 6=일)입니다.

적용 범위
─────────
스케줄 실행에만 씁니다. 수동 발행(workflow_dispatch의 blog_id·posts_per_run,
manual-publish 워크플로)은 이 계획과 무관하게 그대로 동작합니다 — 급할 때
설정을 건드리지 않고 바로 올릴 수 있어야 하기 때문입니다.
"""

import argparse
import json
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

SCHEDULE_PATH = os.path.join(os.path.dirname(__file__), "publish_schedule.json")

BLOG_IDS = ("blog1", "blog2", "blog3")
MAX_POSTS_PER_DAY = 5
DEFAULT_ENTRY = {"enabled": True, "postsPerDay": 1, "days": "daily"}

# 발행 시각은 KST 기준으로 판정합니다. 크론이 UTC 22:00(=다음날 07:00 KST)라
# UTC 요일로 보면 하루가 밀립니다.
KST = timezone(timedelta(hours=9))


def load_schedule(path: str = SCHEDULE_PATH) -> dict:
    """설정을 읽습니다. 못 읽으면 기본값 — 조용히 멈추지 않기 위해서입니다."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
        logger.warning(f"발행 계획을 읽지 못해 기본값(블로그별 1편/일)으로 진행합니다: {e}")
        return {}
    if not isinstance(data, dict):
        logger.warning("발행 계획 형식이 dict가 아닙니다 — 기본값으로 진행합니다")
        return {}
    return data


def entry_for(blog_id: str, schedule: dict | None = None) -> dict:
    """블로그 하나의 설정을 정규화해 돌려줍니다."""
    blogs = (schedule or {}).get("blogs")
    raw = blogs.get(blog_id) if isinstance(blogs, dict) else None
    if not isinstance(raw, dict):
        return dict(DEFAULT_ENTRY)

    enabled = raw.get("enabled", True)
    try:
        count = int(raw.get("postsPerDay", 1))
    except (TypeError, ValueError):
        logger.warning(f"{blog_id}의 postsPerDay 값이 숫자가 아닙니다 — 1편으로 봅니다")
        count = 1
    count = max(0, min(MAX_POSTS_PER_DAY, count))

    days = raw.get("days", "daily")
    if isinstance(days, list):
        days = [d for d in days if isinstance(d, int) and 0 <= d <= 6]
    elif days != "daily":
        logger.warning(f"{blog_id}의 days 값을 알 수 없어 매일로 봅니다: {days!r}")
        days = "daily"

    return {"enabled": bool(enabled), "postsPerDay": count, "days": days}


def posts_for_today(blog_id: str, schedule: dict | None = None,
                    now: datetime | None = None) -> int:
    """오늘 이 블로그가 발행할 편수. 0이면 오늘은 돌지 않습니다."""
    e = entry_for(blog_id, schedule)
    if not e["enabled"]:
        return 0
    days = e["days"]
    if days != "daily":
        today = (now or datetime.now(KST)).astimezone(KST).weekday()
        if today not in days:
            return 0
    return e["postsPerDay"]


def plan_for_today(schedule: dict | None = None,
                   now: datetime | None = None) -> dict[str, int]:
    sched = load_schedule() if schedule is None else schedule
    return {b: posts_for_today(b, sched, now) for b in BLOG_IDS}


def main() -> int:
    p = argparse.ArgumentParser(description="오늘의 블로그별 발행 계획을 출력합니다")
    p.add_argument("--github-output", action="store_true",
                   help="GITHUB_OUTPUT 형식으로 기록 (워크플로에서 사용)")
    args = p.parse_args()

    plan = plan_for_today()
    total = sum(plan.values())
    for blog, n in plan.items():
        print(f"  {blog}: {n}편" + (" (오늘 쉼)" if n == 0 else ""))
    print(f"오늘 발행 예정 합계: {total}편")

    if args.github_output:
        out = os.getenv("GITHUB_OUTPUT")
        if not out:
            # 워크플로 밖에서 부른 경우 — 실패시키지 않고 알리기만 합니다
            logger.warning("GITHUB_OUTPUT이 없어 출력만 했습니다")
            return 0
        with open(out, "a", encoding="utf-8") as f:
            for blog, n in plan.items():
                f.write(f"{blog}={n}\n")
            f.write(f"total={total}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
