"""제목 A/B 개선 추적 및 복구 — 변경 전후 성과 비교, 하락 시 복원 제안.

기록 파일: logs/title_changes.json
대시보드 출력: docs/data/title_changes.json

레코드 스키마:
{
  "blogUrl": "...", "old_title": "...", "new_title": "...",
  "changed_at": "ISO8601", "reason": "저CTR 검색어 '...' (CTR 1.2%)",
  "baseline": {"ctr": 1.2, "position": 15.3, "impressions": 200, "clicks": 2},
  "after": {...} | null,          # 28일 후 성과
  "verdict": "improved|declined|neutral" | null,
  "rollback_suggested": bool,
  "restored": bool,
  "evaluated_at": "ISO8601" | null
}

규칙:
- 변경 전 제목·날짜·원인·기준 성과 저장
- 28일 전후 데이터 비교 → CTR과 순위가 모두 하락하면 자동 복원 제안
- 한 번에 제목과 본문을 동시에 변경하지 않음 (양쪽 모듈이 이 파일로 상호 확인)

복원 실행: python title_ab_tracker.py --restore "<blogUrl>"
"""
import argparse
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_BASE = Path(__file__).parent
CHANGES_FILE = _BASE / "logs" / "title_changes.json"
FIX_HISTORY_FILE = _BASE / "logs" / "fix_history.json"
DASHBOARD_FILE = _BASE.parent / "docs" / "data" / "title_changes.json"

EVAL_AFTER_DAYS = 28  # 변경 후 이 기간이 지나면 전후 비교


def _load(path: Path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_changes() -> list[dict]:
    return _load(CHANGES_FILE, [])


# ──────────────────────────────────────────────────────────────────────────────
# 변경 기록 + 동시 변경 방지 가드
# ──────────────────────────────────────────────────────────────────────────────

def record_title_change(blog_url: str, old_title: str, new_title: str,
                        reason: str, baseline: dict) -> None:
    """제목 변경 시점에 변경 전 제목·날짜·원인·기준 성과를 기록합니다."""
    changes = load_changes()
    changes.append({
        "blogUrl": blog_url,
        "old_title": old_title,
        "new_title": new_title,
        "changed_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "baseline": baseline,
        "after": None,
        "verdict": None,
        "rollback_suggested": False,
        "restored": False,
        "evaluated_at": None,
    })
    _save(CHANGES_FILE, changes)
    logger.info(f"제목 변경 기록: '{old_title[:30]}…' → '{new_title[:30]}…' ({reason[:40]})")


def _within_days(iso_ts: str, days: int) -> bool:
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - ts < timedelta(days=days)
    except Exception:
        return False


def title_changed_recently(blog_url: str, days: int = EVAL_AFTER_DAYS) -> bool:
    """제목 A/B 테스트 진행 중인지 — 본문 수정 모듈이 이걸로 동시 변경을 피합니다."""
    url = (blog_url or "").rstrip("/")
    return any(
        (c.get("blogUrl") or "").rstrip("/") == url and _within_days(c.get("changed_at", ""), days)
        for c in load_changes()
    )


def body_edited_recently(blog_url: str, days: int = EVAL_AFTER_DAYS) -> bool:
    """본문이 최근 수정됐는지 — 제목 변경 모듈이 이걸로 동시 변경을 피합니다."""
    url = (blog_url or "").rstrip("/")
    fixed = _load(FIX_HISTORY_FILE, {}).get("fixed", [])
    return any(
        (e.get("url") or "").rstrip("/") == url and _within_days(e.get("at", ""), days)
        for e in fixed
    )


# ──────────────────────────────────────────────────────────────────────────────
# 28일 전후 비교 → 복원 제안
# ──────────────────────────────────────────────────────────────────────────────

def evaluate_changes(page_metrics: dict[str, dict]) -> int:
    """변경 후 28일이 지난 레코드의 전후 성과를 비교하고 복원 제안을 판정합니다.

    Args:
        page_metrics: {url: {ctr, position, impressions, clicks}} — 최근 28일 GSC 데이터
    Returns: 새로 평가된 레코드 수
    """
    changes = load_changes()
    evaluated = 0
    for c in changes:
        if c.get("after") is not None or c.get("restored"):
            continue
        if _within_days(c.get("changed_at", ""), EVAL_AFTER_DAYS):
            continue  # 아직 28일 미경과
        url = (c.get("blogUrl") or "").rstrip("/")
        after = page_metrics.get(url)
        if after is None:
            after = {"ctr": 0.0, "position": 0.0, "impressions": 0, "clicks": 0}
        c["after"] = after
        c["evaluated_at"] = datetime.now(timezone.utc).isoformat()

        base = c.get("baseline") or {}
        base_ctr, base_pos = base.get("ctr", 0.0), base.get("position", 0.0)
        ctr_down = after["ctr"] < base_ctr
        # position은 낮을수록 좋음 — 숫자가 커지면 순위 하락
        pos_down = base_pos > 0 and after.get("position", 0) > base_pos

        if ctr_down and pos_down:
            c["verdict"] = "declined"
            c["rollback_suggested"] = True
        elif after["ctr"] > base_ctr:
            c["verdict"] = "improved"
            c["rollback_suggested"] = False
        else:
            c["verdict"] = "neutral"
            c["rollback_suggested"] = False
        evaluated += 1
        logger.info(
            f"제목 A/B 평가: '{c['new_title'][:30]}…' CTR {base_ctr}→{after['ctr']}% "
            f"순위 {base_pos}→{after.get('position', 0)} → {c['verdict']}"
            + (" (복원 제안)" if c["rollback_suggested"] else "")
        )
    if evaluated:
        _save(CHANGES_FILE, changes)
    export_for_dashboard()
    return evaluated


def export_for_dashboard() -> None:
    """대시보드용 title_changes.json 출력 (변경 전후 성과 표시용)."""
    changes = load_changes()
    _save(DASHBOARD_FILE, {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "changes": changes[-200:],
        "rollbackSuggested": sum(1 for c in changes if c.get("rollback_suggested") and not c.get("restored")),
    })


# ──────────────────────────────────────────────────────────────────────────────
# 복원 실행
# ──────────────────────────────────────────────────────────────────────────────

def restore_title(blog_url: str) -> bool:
    """변경 전 제목으로 복원합니다 (가장 최근 변경 레코드 기준)."""
    from gsc_optimizer import _google_token, get_post_id_by_url, update_blogger_title, _update_posts_json
    url = (blog_url or "").rstrip("/")
    changes = load_changes()
    target = None
    for c in reversed(changes):
        if (c.get("blogUrl") or "").rstrip("/") == url and not c.get("restored"):
            target = c
            break
    if not target:
        logger.error(f"복원할 변경 기록 없음: {blog_url}")
        return False
    token = _google_token()
    if not token:
        return False
    post_id = get_post_id_by_url(token, target["blogUrl"])
    if not post_id:
        logger.error("포스트 ID 조회 실패")
        return False
    ok = update_blogger_title(token, post_id, target["old_title"])
    if ok:
        target["restored"] = True
        target["restored_at"] = datetime.now(timezone.utc).isoformat()
        _save(CHANGES_FILE, changes)
        _update_posts_json(target["blogUrl"], target["old_title"])
        export_for_dashboard()
        logger.info(f"제목 복원 완료: '{target['old_title'][:40]}'")
    return ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="제목 A/B 추적·복원")
    parser.add_argument("--restore", help="복원할 포스트의 blogUrl")
    parser.add_argument("--export", action="store_true", help="대시보드 JSON만 재출력")
    args = parser.parse_args()
    if args.restore:
        restore_title(args.restore)
    elif args.export:
        export_for_dashboard()
