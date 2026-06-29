"""
블로그 자동화 시스템 — 자동 수리 모듈

진단 → 수리 → 리포트 루프로 시스템을 항상 최적 상태로 유지합니다.

사용법:
  python auto_repair.py          # 진단 + 자동 수리
  python auto_repair.py --dry    # 진단만 (실제 수리 없음)
"""

import json
import logging
import os
import re
import shutil
import sys
from datetime import datetime, timedelta

_BASE = os.path.dirname(os.path.abspath(__file__))
_LOGS = os.path.join(_BASE, "logs")
_DOCS = os.path.join(_BASE, "..", "docs", "data")

REPAIR_FILE   = os.path.join(_LOGS, "repair_history.json")
RUN_HISTORY   = os.path.join(_LOGS, "run_history.json")
USED_KW_FILE  = os.path.join(_LOGS, "used_keywords.json")
SERIES_FILE   = os.path.join(_LOGS, "series.json")
PENDING_FILE  = os.path.join(_DOCS, "pending_posts.json")
LOG_FILE      = os.path.join(_LOGS, "automation.log")

logger = logging.getLogger(__name__)


# ── 유틸 ──────────────────────────────────────────────────────────────────────

def _load_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── 진단 함수들 ───────────────────────────────────────────────────────────────

def _diagnose_upload_failures(runs: list[dict]) -> list[dict]:
    """최근 5회 중 3회 이상 업로드 0건이면 critical 이슈로 등록."""
    issues = []
    recent = runs[:5]  # 최신순 (insert(0, …) 방식으로 저장됨)
    fail_runs = [r for r in recent if r.get("bloggerUploaded", 0) == 0 and r.get("errors", 0) > 0]
    if len(fail_runs) >= 3:
        issues.append({
            "id": "consecutive_upload_failures",
            "level": "critical",
            "message": f"최근 {len(fail_runs)}회 연속 업로드 실패 (0건 업로드)",
            "context": {"fail_count": len(fail_runs), "recent_dates": [r.get("date") for r in fail_runs]},
            "fix": "check_blogger_connection",
        })
    return issues


def _diagnose_no_runs_recently(runs: list[dict]) -> list[dict]:
    """마지막 실행이 30시간 이상 전이면 스케줄 중단 의심."""
    issues = []
    if not runs:
        return issues
    last_run_at = runs[0].get("runAt", "")
    if not last_run_at:
        return issues
    try:
        last_dt = datetime.fromisoformat(last_run_at)
        hours_ago = (datetime.now() - last_dt).total_seconds() / 3600
        if hours_ago > 30:
            issues.append({
                "id": "schedule_stalled",
                "level": "high",
                "message": f"마지막 실행이 {hours_ago:.0f}시간 전 — 스케줄 중단 의심",
                "context": {"last_run": last_run_at, "hours_ago": round(hours_ago, 1)},
                "fix": None,  # 수동 조치 필요
            })
    except ValueError:
        pass
    return issues


def _diagnose_keyword_exhaustion(used_kw: dict) -> list[dict]:
    """90일 이상 된 키워드가 많으면 풀 소진으로 판단."""
    issues = []
    if not isinstance(used_kw, dict):
        return issues
    total = len(used_kw)
    if total < 100:
        return issues
    cutoff = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    old_count = sum(1 for v in used_kw.values() if isinstance(v, str) and v < cutoff)
    if old_count > 50:
        issues.append({
            "id": "keyword_pool_exhaustion",
            "level": "warning",
            "message": f"사용 키워드 {total}개 중 {old_count}개 90일 초과 — 재사용 해제 필요",
            "context": {"total": total, "old_count": old_count, "cutoff": cutoff},
            "fix": "prune_old_keywords",
        })
    return issues


def _diagnose_history_bloat(runs: list[dict]) -> list[dict]:
    """실행 이력 200개 초과 시 정리."""
    issues = []
    if len(runs) > 200:
        issues.append({
            "id": "history_bloat",
            "level": "low",
            "message": f"실행 이력 {len(runs)}개 — 최근 150개로 정리 필요",
            "context": {"count": len(runs)},
            "fix": "trim_history",
        })
    return issues


def _diagnose_stuck_series(series_list: list[dict]) -> list[dict]:
    """24시간 이상 generating/partial 상태 시리즈 감지."""
    issues = []
    cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
    stuck = [
        s for s in series_list
        if s.get("status") in ("generating", "partial")
        and s.get("created_at", "9999") < cutoff
    ]
    if stuck:
        issues.append({
            "id": "stuck_series",
            "level": "warning",
            "message": f"24시간 이상 멈춘 시리즈 {len(stuck)}개",
            "context": {"series": [s.get("series_title", "?")[:30] for s in stuck[:5]]},
            "fix": "reset_stuck_series",
        })
    return issues


def _diagnose_stale_pending(pending: list[dict]) -> list[dict]:
    """30일 이상 pending 상태인 포스트 감지."""
    issues = []
    cutoff = (datetime.now() - timedelta(days=30)).isoformat()[:10]
    old = [
        p for p in pending
        if p.get("status") == "pending"
        and p.get("date", "9999") < cutoff
    ]
    if old:
        issues.append({
            "id": "stale_pending_posts",
            "level": "low",
            "message": f"30일 이상 대기 중인 포스트 {len(old)}개",
            "context": {"count": len(old), "titles": [p.get("title", "?")[:30] for p in old[:3]]},
            "fix": "expire_old_pending",
        })
    return issues


def _diagnose_log_size() -> list[dict]:
    """자동화 로그 파일 10MB 초과 감지."""
    issues = []
    if os.path.exists(LOG_FILE):
        size_mb = os.path.getsize(LOG_FILE) / 1024 / 1024
        if size_mb > 10:
            issues.append({
                "id": "log_file_bloat",
                "level": "low",
                "message": f"로그 파일 {size_mb:.1f}MB — 회전 필요",
                "context": {"size_mb": round(size_mb, 1)},
                "fix": "rotate_log",
            })
    return issues


def _diagnose_adsense_config() -> list[dict]:
    """AdSense 미설정 감지."""
    issues = []
    try:
        from config import ADSENSE_CLIENT_ID
        if not ADSENSE_CLIENT_ID or ADSENSE_CLIENT_ID == "ca-pub-XXXXXXXXXXXXXXXXX":
            issues.append({
                "id": "adsense_not_configured",
                "level": "warning",
                "message": "AdSense 미설정 — 광고 수익화 비활성화 상태",
                "context": {},
                "fix": None,
            })
    except Exception:
        pass
    return issues


# ── 수리 함수들 ────────────────────────────────────────────────────────────────

def _fix_prune_old_keywords(issue: dict) -> dict:
    """90일 초과 사용 키워드 삭제 — 키워드 풀 재사용."""
    used_kw = _load_json(USED_KW_FILE, {})
    if not isinstance(used_kw, dict):
        return {"success": False, "detail": "used_keywords.json 형식 오류"}
    cutoff = issue["context"]["cutoff"]
    before = len(used_kw)
    pruned = {k: v for k, v in used_kw.items() if not (isinstance(v, str) and v < cutoff)}
    removed = before - len(pruned)
    _save_json(USED_KW_FILE, pruned)
    return {
        "success": True,
        "detail": f"키워드 {removed}개 삭제 (90일 경과, 재사용 가능 상태로 전환)",
        "removed": removed,
    }


def _fix_trim_history(issue: dict) -> dict:
    """실행 이력 최근 150개로 축소."""
    runs = _load_json(RUN_HISTORY, [])
    if not isinstance(runs, list):
        return {"success": False, "detail": "run_history.json 형식 오류"}
    before = len(runs)
    trimmed = runs[:150]
    _save_json(RUN_HISTORY, trimmed)
    return {
        "success": True,
        "detail": f"이력 {before}개 → {len(trimmed)}개로 축소",
        "removed": before - len(trimmed),
    }


def _fix_reset_stuck_series(issue: dict) -> dict:
    """24시간 이상 멈춘 시리즈를 completed로 마킹."""
    series_list = _load_json(SERIES_FILE, [])
    if not isinstance(series_list, list):
        return {"success": False, "detail": "series.json 형식 오류"}
    cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
    fixed = 0
    for s in series_list:
        if s.get("status") in ("generating", "partial") and s.get("created_at", "9999") < cutoff:
            s["status"] = "completed"
            s["auto_fixed_at"] = datetime.now().isoformat()
            fixed += 1
    _save_json(SERIES_FILE, series_list)
    return {
        "success": True,
        "detail": f"멈춘 시리즈 {fixed}개 → completed 처리",
        "fixed": fixed,
    }


def _fix_expire_old_pending(issue: dict) -> dict:
    """30일 이상 대기 포스트를 expired 처리."""
    pending = _load_json(PENDING_FILE, [])
    if not isinstance(pending, list):
        return {"success": False, "detail": "pending_posts.json 형식 오류"}
    cutoff = (datetime.now() - timedelta(days=30)).isoformat()[:10]
    expired = 0
    for p in pending:
        if p.get("status") == "pending" and p.get("date", "9999") < cutoff:
            p["status"] = "expired"
            p["expired_at"] = datetime.now().isoformat()
            expired += 1
    _save_json(PENDING_FILE, pending)
    return {
        "success": True,
        "detail": f"대기 포스트 {expired}개 → expired 처리",
        "expired": expired,
    }


def _fix_rotate_log(issue: dict) -> dict:
    """자동화 로그 최근 2MB만 유지."""
    if not os.path.exists(LOG_FILE):
        return {"success": False, "detail": "로그 파일 없음"}
    size_mb = os.path.getsize(LOG_FILE) / 1024 / 1024
    keep_bytes = 2 * 1024 * 1024
    try:
        with open(LOG_FILE, "rb") as f:
            f.seek(0, 2)
            file_size = f.tell()
            f.seek(max(0, file_size - keep_bytes))
            tail = f.read()
        with open(LOG_FILE, "wb") as f:
            f.write(tail)
        return {
            "success": True,
            "detail": f"로그 {size_mb:.1f}MB → 2MB로 축소",
            "before_mb": round(size_mb, 1),
        }
    except OSError as e:
        return {"success": False, "detail": f"로그 회전 실패: {e}"}


def _fix_check_blogger_connection(issue: dict) -> dict:
    """Blogger API 연결 상태 확인 (토큰·blog_id 검증)."""
    try:
        from config import BLOGGER_BLOG_ID
        from blogger_uploader import _get_access_token, get_blog_info

        token = _get_access_token()
        if not token:
            return {
                "success": False,
                "detail": "OAuth 토큰 발급 실패 — GOOGLE_REFRESH_TOKEN이 만료됐을 수 있습니다",
                "action_required": (
                    "blog-automation/get_refresh_token.py 실행 후 "
                    "GOOGLE_REFRESH_TOKEN GitHub Secret 교체 필요"
                ),
            }

        info = get_blog_info()
        if info:
            return {
                "success": True,
                "detail": (
                    f"Blogger 연결 정상: {info.get('name', '?')} "
                    f"({info.get('url', '?')}) — 업로드 파라미터 문제 가능성"
                ),
            }
        return {
            "success": False,
            "detail": (
                f"블로그 접근 실패 (blog_id='{BLOGGER_BLOG_ID}') — "
                "BLOGGER_BLOG_ID Secret 값 또는 OAuth 권한 확인 필요"
            ),
            "action_required": "BLOGGER_BLOG_ID가 올바른 숫자형 ID인지 확인",
        }
    except Exception as e:
        return {"success": False, "detail": f"연결 확인 오류: {e}"}


_FIX_HANDLERS = {
    "prune_old_keywords":   _fix_prune_old_keywords,
    "trim_history":         _fix_trim_history,
    "reset_stuck_series":   _fix_reset_stuck_series,
    "expire_old_pending":   _fix_expire_old_pending,
    "rotate_log":           _fix_rotate_log,
    "check_blogger_connection": _fix_check_blogger_connection,
}


# ── 메인 ──────────────────────────────────────────────────────────────────────

def run_auto_repair(dry_run: bool = False) -> dict:
    """자동 진단·수리를 실행하고 결과 dict를 반환합니다."""
    os.makedirs(_LOGS, exist_ok=True)

    # 데이터 로드
    runs       = _load_json(RUN_HISTORY, [])
    used_kw    = _load_json(USED_KW_FILE, {})
    series_lst = _load_json(SERIES_FILE, [])
    pending    = _load_json(PENDING_FILE, [])

    # ── 진단 ─────────────────────────────────────────────────────────────────
    issues: list[dict] = []
    issues += _diagnose_upload_failures(runs)
    issues += _diagnose_no_runs_recently(runs)
    issues += _diagnose_keyword_exhaustion(used_kw)
    issues += _diagnose_history_bloat(runs)
    issues += _diagnose_stuck_series(series_lst)
    issues += _diagnose_stale_pending(pending)
    issues += _diagnose_log_size()
    issues += _diagnose_adsense_config()

    lvl_order = {"critical": 0, "high": 1, "warning": 2, "low": 3}
    issues.sort(key=lambda x: lvl_order.get(x["level"], 9))

    logger.info(f"[AutoRepair] 진단 완료: {len(issues)}개 이슈")
    for iss in issues:
        icon = {"critical": "🔴", "high": "🟠", "warning": "🟡", "low": "🔵"}.get(iss["level"], "⚪")
        logger.info(f"  {icon} [{iss['level'].upper()}] {iss['message']}")

    # ── 수리 ─────────────────────────────────────────────────────────────────
    repairs: list[dict] = []
    for issue in issues:
        fix_key = issue.get("fix")
        base = {
            "issue_id":      issue["id"],
            "issue_level":   issue["level"],
            "issue_message": issue["message"],
            "fix_applied":   fix_key,
            "timestamp":     datetime.now().isoformat(),
        }

        if not fix_key:
            entry = {**base, "success": None, "detail": "수동 조치 필요 (자동 수리 불가)"}
            repairs.append(entry)
            logger.warning(f"  ⚠️  [{issue['id']}] 수동 조치 필요: {issue['message']}")
            continue

        if dry_run:
            repairs.append({**base, "success": None, "detail": f"[dry-run] {fix_key} 건너뜀"})
            continue

        handler = _FIX_HANDLERS.get(fix_key)
        if not handler:
            repairs.append({**base, "success": False, "detail": f"수리 핸들러 없음: {fix_key}"})
            continue

        try:
            result = handler(issue)
            entry = {**base, **result}
            repairs.append(entry)
            status = "✅" if result.get("success") else "❌"
            logger.info(f"  {status} [{issue['id']}] {result.get('detail', '')}")
        except Exception as e:
            logger.error(f"  ❌ [{issue['id']}] 수리 오류: {e}")
            repairs.append({**base, "success": False, "detail": f"수리 중 예외: {e}"})

    # ── 건강 점수 계산 ────────────────────────────────────────────────────────
    score = 100
    for iss in issues:
        deduct = {"critical": 30, "high": 15, "warning": 7, "low": 3}.get(iss["level"], 2)
        score -= deduct
    health_score = max(0, score)

    fixed_count = sum(1 for r in repairs if r.get("success") is True)
    report = {
        "timestamp":       datetime.now().isoformat(),
        "health_score":    health_score,
        "issues_found":    len(issues),
        "issues":          issues,
        "repairs_applied": fixed_count,
        "repairs":         repairs,
        "dry_run":         dry_run,
    }

    # ── 저장 & 내보내기 ───────────────────────────────────────────────────────
    if not dry_run:
        # logs/repair_history.json
        history = _load_json(REPAIR_FILE, [])
        if not isinstance(history, list):
            history = []
        history.insert(0, report)
        history = history[:50]
        _save_json(REPAIR_FILE, history)

        # docs/data/repairs.json
        os.makedirs(_DOCS, exist_ok=True)
        _save_json(os.path.join(_DOCS, "repairs.json"), history)
        logger.info(f"[AutoRepair] 수리 이력 저장: {REPAIR_FILE}")

    logger.info(
        f"[AutoRepair] 완료 | 건강점수: {health_score}/100 | "
        f"이슈: {len(issues)}개 | 수리: {fixed_count}개"
    )
    return report


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _log_file = os.path.join(_LOGS, "auto_repair.log")
    os.makedirs(_LOGS, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(_log_file, encoding="utf-8"),
        ],
    )
    dry = "--dry" in sys.argv
    report = run_auto_repair(dry_run=dry)
    print(f"\n{'[DRY-RUN] ' if dry else ''}건강점수: {report['health_score']}/100")
    print(f"이슈: {report['issues_found']}개 | 수리: {report['repairs_applied']}개")
    if report["issues"]:
        for iss in report["issues"]:
            print(f"  [{iss['level'].upper()}] {iss['message']}")
