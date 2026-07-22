"""주간 운영 브리핑 — 지난 7일간의 발행·건강·인시던트를 한 번에 요약합니다.

매일 쌓이는 runs.json/repairs.json/incident_log.json을 일일이 확인하지 않아도
"이번 주에 무슨 일이 있었는지"를 한 문단으로 파악할 수 있게 만듭니다.

Usage:
  python weekly_brief.py
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_BASE_DIR = os.path.dirname(__file__)
_DOCS_DATA = os.path.join(_BASE_DIR, "..", "docs", "data")
_OUT_FILE = os.path.join(_DOCS_DATA, "weekly_brief.json")

_PERIOD_DAYS = 7


def _load(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _save(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _within_period(value: str, cutoff: datetime) -> bool:
    dt = _parse_dt(value)
    return dt is not None and dt >= cutoff


def generate_brief() -> dict:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=_PERIOD_DAYS)

    runs = _load(os.path.join(_DOCS_DATA, "runs.json"), [])
    repairs = _load(os.path.join(_DOCS_DATA, "repairs.json"), [])
    incidents = _load(os.path.join(_DOCS_DATA, "incident_log.json"), [])
    grade_cleanup = _load(os.path.join(_DOCS_DATA, "grade_cleanup.json"), {})
    posts = _load(os.path.join(_DOCS_DATA, "posts.json"), [])
    auth_health = _load(os.path.join(_DOCS_DATA, "auth_health.json"), {})

    week_runs = [r for r in runs if _within_period(r.get("runAt", ""), cutoff)]
    week_repairs = [r for r in repairs if _within_period(r.get("timestamp", ""), cutoff)]
    week_incidents = [i for i in incidents if _within_period(i.get("date", ""), cutoff)]

    posts_generated = sum(r.get("postsGenerated", 0) for r in week_runs)
    posts_uploaded = sum(r.get("bloggerUploaded", 0) for r in week_runs)
    total_errors = sum(r.get("errors", 0) for r in week_runs)

    by_blog: dict[str, dict] = {}
    for r in week_runs:
        bid = r.get("blogId", "unknown")
        b = by_blog.setdefault(bid, {"blogName": r.get("blogName", bid), "generated": 0, "uploaded": 0})
        b["generated"] += r.get("postsGenerated", 0)
        b["uploaded"] += r.get("bloggerUploaded", 0)

    scores = [r.get("health_score") for r in week_repairs if r.get("health_score") is not None]
    avg_health = round(sum(scores) / len(scores), 1) if scores else None
    min_health = min(scores) if scores else None

    all_issues = [iss for r in week_repairs for iss in r.get("issues", [])]
    critical_issues = [iss for iss in all_issues if iss.get("level") == "critical"]
    recurring = [iss for iss in all_issues if iss.get("known_incident")]

    deleted_this_week = grade_cleanup.get("deleted", 0) if _within_period(grade_cleanup.get("checked_at", ""), cutoff) else 0

    risks = []
    if auth_health and not auth_health.get("all_ok", True):
        risks.append("Google OAuth 인증 문제 감지됨 — 재인증 필요")
    if critical_issues:
        risks.append(f"critical 등급 이슈 {len(critical_issues)}건 발생")
    if min_health is not None and min_health < 60:
        risks.append(f"건강점수 최저 {min_health}/100까지 하락")
    if total_errors > 0:
        risks.append(f"발행 오류 {total_errors}건 발생")

    highlights = []
    if posts_uploaded > 0:
        highlights.append(f"이번 주 {posts_uploaded}건 발행 완료 ({len(by_blog)}개 블로그)")
    if week_incidents:
        highlights.append(f"새 인시던트 {len(week_incidents)}건 기록 (재발 방지 조치 포함)")
    if recurring:
        highlights.append(f"자가진단 봇이 과거 인시던트와 일치하는 이슈 {len(recurring)}건 자동 식별")
    if deleted_this_week:
        highlights.append(f"저성과 글 {deleted_this_week}건 정리")

    blog_lines = ", ".join(
        f"{b['blogName']} {b['uploaded']}건" for b in by_blog.values()
    ) or "발행 없음"

    summary_text = (
        f"지난 {_PERIOD_DAYS}일간 총 {posts_generated}건 생성, {posts_uploaded}건 발행({blog_lines}). "
        f"평균 건강점수 {avg_health if avg_health is not None else '측정 안 됨'}/100. "
        + (f"위험 신호 {len(risks)}건 확인됨." if risks else "특이 위험 신호 없음.")
    )

    brief = {
        "generated_at": now.isoformat(),
        "period_days": _PERIOD_DAYS,
        "period_start": cutoff.isoformat(),
        "period_end": now.isoformat(),
        "summary_text": summary_text,
        "metrics": {
            "posts_generated": posts_generated,
            "posts_uploaded": posts_uploaded,
            "errors": total_errors,
            "avg_health_score": avg_health,
            "min_health_score": min_health,
            "by_blog": by_blog,
            "new_incidents": len(week_incidents),
            "recurring_issues_auto_matched": len(recurring),
            "deleted_low_grade_posts": deleted_this_week,
            "total_published_posts": len(posts),
        },
        "highlights": highlights,
        "risks": risks,
        "new_incidents": week_incidents,
    }

    _save(_OUT_FILE, brief)
    logger.info(f"[WeeklyBrief] {summary_text}")
    for h in highlights:
        logger.info(f"  ✅ {h}")
    for r in risks:
        logger.warning(f"  ⚠️ {r}")
    return brief


if __name__ == "__main__":
    generate_brief()
