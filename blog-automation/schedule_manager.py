#!/usr/bin/env python3
"""
schedule_manager.py — 스케줄 실행 이력 추적 + 실패 감지 엔진
--------------------------------------------------------------
기능:
  1. GitHub Actions API로 워크플로우 실행 결과 수집
  2. docs/data/schedule_history.json에 이력 저장
  3. 연속 실패 감지 → GitHub Issue 자동 생성
  4. schedule_config.json 기반으로 모든 워크플로우 모니터링

사용법:
  python schedule_manager.py               # 이력 수집 + 실패 감지
  python schedule_manager.py --report      # 현황 요약 출력
  python schedule_manager.py --issue-test  # 테스트 이슈 생성
"""

import os
import json
import sys
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# ────────────────────────────────────────────
# 설정
# ────────────────────────────────────────────
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO  = os.environ.get("GITHUB_REPOSITORY", "Kevinlee7250/cli")
BRANCH       = os.environ.get("GITHUB_REF_NAME", "claude/blog-automation-system-KAbtE")

OWNER, REPO  = GITHUB_REPO.split("/") if "/" in GITHUB_REPO else ("", GITHUB_REPO)

BASE_DIR          = Path(__file__).parent
DATA_DIR          = BASE_DIR.parent / "docs" / "data"
SCHEDULE_CONFIG   = DATA_DIR / "schedule_config.json"
HISTORY_FILE      = DATA_DIR / "schedule_history.json"

LOOKBACK_HOURS    = 25      # 수집 대상 실행 기간 (시간)
MAX_HISTORY_DAYS  = 30      # 이력 보관 기간 (일)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ────────────────────────────────────────────
# GitHub API 헬퍼
# ────────────────────────────────────────────
def _gh_headers() -> dict:
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _gh_get(path: str, params: dict = None) -> dict | list:
    """GitHub API GET 요청 (단일 페이지)."""
    url = f"https://api.github.com{path}"
    resp = requests.get(url, headers=_gh_headers(), params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()


def _gh_post(path: str, payload: dict) -> dict:
    """GitHub API POST 요청."""
    url = f"https://api.github.com{path}"
    resp = requests.post(url, headers=_gh_headers(), json=payload, timeout=20)
    resp.raise_for_status()
    return resp.json()


# ────────────────────────────────────────────
# 설정 로드
# ────────────────────────────────────────────
def load_schedule_config() -> dict:
    """schedule_config.json 로드."""
    if SCHEDULE_CONFIG.exists():
        return json.loads(SCHEDULE_CONFIG.read_text(encoding="utf-8"))
    # 없으면 GitHub에서 직접 가져오기
    try:
        data = _gh_get(f"/repos/{OWNER}/{REPO}/contents/docs/data/schedule_config.json",
                       {"ref": BRANCH})
        import base64
        content = base64.b64decode(data["content"]).decode("utf-8")
        return json.loads(content)
    except Exception as e:
        logger.warning(f"schedule_config.json 로드 실패: {e}")
        return {"schedules": [], "alert_rules": {"consecutive_failures": 2}}


def load_history() -> dict:
    """schedule_history.json 로드 (없으면 빈 구조 반환)."""
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    return {"runs": {}, "alerts": [], "last_updated": None}


def save_history(history: dict):
    """schedule_history.json 저장."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    history["last_updated"] = datetime.now(timezone.utc).isoformat()
    HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    logger.info(f"이력 저장 완료: {HISTORY_FILE}")


# ────────────────────────────────────────────
# 워크플로우 실행 이력 수집
# ────────────────────────────────────────────
def fetch_workflow_runs(workflow_file: str, hours: int = LOOKBACK_HOURS) -> list:
    """특정 워크플로우의 최근 실행 목록 반환."""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    try:
        data = _gh_get(
            f"/repos/{OWNER}/{REPO}/actions/workflows/{workflow_file}/runs",
            {"per_page": 10, "created": f">={since}"}
        )
        runs = data.get("workflow_runs", [])
        return [
            {
                "run_id":     r["id"],
                "status":     r["status"],          # queued / in_progress / completed
                "conclusion": r.get("conclusion"),  # success / failure / cancelled / skipped
                "started_at": r["created_at"],
                "completed_at": r.get("updated_at"),
                "html_url":   r["html_url"],
                "event":      r["event"],           # schedule / workflow_dispatch / push
                "run_number": r["run_number"],
            }
            for r in runs
        ]
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            logger.debug(f"워크플로우 없음: {workflow_file}")
        else:
            logger.warning(f"API 오류 ({workflow_file}): {e}")
        return []


def collect_all_runs(config: dict) -> dict:
    """모든 스케줄된 워크플로우의 실행 이력 수집."""
    results = {}
    schedules = config.get("schedules", [])
    seen_workflows = set()

    for sched in schedules:
        wf = sched["workflow"]
        if wf in seen_workflows:
            continue
        seen_workflows.add(wf)

        logger.info(f"수집 중: {wf}")
        runs = fetch_workflow_runs(wf)
        results[wf] = {
            "schedule_id":  sched["id"],
            "category":     sched.get("category", "unknown"),
            "enabled":      sched.get("enabled", True),
            "recent_runs":  runs,
            "fetched_at":   datetime.now(timezone.utc).isoformat(),
        }

    return results


# ────────────────────────────────────────────
# 실패 감지
# ────────────────────────────────────────────
def detect_consecutive_failures(workflow_runs: dict, threshold: int = 2) -> list:
    """연속 실패 워크플로우 목록 반환."""
    failures = []

    for wf_file, info in workflow_runs.items():
        if not info.get("enabled", True):
            continue

        runs = info.get("recent_runs", [])
        # 완료된 실행만 필터링, 최신 순 정렬
        completed = [r for r in runs if r["status"] == "completed"]
        if len(completed) < threshold:
            continue

        # 최근 N개 연속 실패 확인
        last_n = completed[:threshold]
        if all(r["conclusion"] == "failure" for r in last_n):
            failures.append({
                "workflow":   wf_file,
                "category":   info.get("category"),
                "fail_count": threshold,
                "last_run":   last_n[0],
                "runs":       last_n,
            })

    return failures


def should_alert(failures: list, history: dict) -> list:
    """이미 알림 보낸 건 제외하고 새로운 실패만 반환."""
    sent_keys = {a["workflow"] for a in history.get("alerts", [])
                 if not a.get("resolved", False)}
    return [f for f in failures if f["workflow"] not in sent_keys]


# ────────────────────────────────────────────
# GitHub Issue 알림
# ────────────────────────────────────────────
def create_failure_issue(failure: dict) -> dict | None:
    """연속 실패 워크플로우에 대해 GitHub Issue 생성."""
    wf   = failure["workflow"]
    runs = failure["runs"]
    last = failure["last_run"]

    run_links = "\n".join(
        f"- Run #{r['run_number']}: [{r['conclusion']}]({r['html_url']}) — {r['started_at'][:16]}"
        for r in runs
    )

    body = f"""## 🚨 워크플로우 연속 실패 감지

**워크플로우:** `{wf}`
**카테고리:** `{failure.get('category', 'unknown')}`
**연속 실패:** {failure['fail_count']}회

### 최근 실패 실행

{run_links}

### 조치 사항

1. 위 링크에서 실패 로그 확인
2. 오류 원인 파악 후 수동 실행 테스트
3. 문제 해결 후 이 이슈를 Close

---
*자동 생성: schedule_manager.py @ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*
"""

    payload = {
        "title": f"[🚨 자동화 실패] {wf} — {failure['fail_count']}회 연속 실패",
        "body": body,
        "labels": ["bug", "automation"],
    }

    try:
        result = _gh_post(f"/repos/{OWNER}/{REPO}/issues", payload)
        logger.info(f"이슈 생성: #{result['number']} — {wf}")
        return result
    except Exception as e:
        logger.error(f"이슈 생성 실패 ({wf}): {e}")
        return None


# ────────────────────────────────────────────
# 이력 업데이트 (오래된 항목 정리)
# ────────────────────────────────────────────
def update_history(history: dict, new_runs: dict, new_alerts: list) -> dict:
    """history에 새 실행 이력 병합 + 오래된 항목 정리."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_HISTORY_DAYS)

    # runs 병합
    for wf_file, info in new_runs.items():
        if wf_file not in history["runs"]:
            history["runs"][wf_file] = {"all_runs": []}

        existing_ids = {r["run_id"] for r in history["runs"][wf_file].get("all_runs", [])}
        for run in info.get("recent_runs", []):
            if run["run_id"] not in existing_ids:
                history["runs"][wf_file].setdefault("all_runs", []).append(run)

        # 오래된 항목 정리
        history["runs"][wf_file]["all_runs"] = [
            r for r in history["runs"][wf_file]["all_runs"]
            if r.get("started_at", "9999") >= cutoff.isoformat()
        ]

        # 최신 통계 업데이트
        all_runs = history["runs"][wf_file]["all_runs"]
        completed = [r for r in all_runs if r["status"] == "completed"]
        success_count = sum(1 for r in completed if r["conclusion"] == "success")
        fail_count    = sum(1 for r in completed if r["conclusion"] == "failure")

        history["runs"][wf_file].update({
            "category":     info.get("category"),
            "enabled":      info.get("enabled"),
            "total_runs":   len(completed),
            "success_count": success_count,
            "failure_count": fail_count,
            "success_rate": round(success_count / len(completed) * 100, 1) if completed else None,
            "last_run":     completed[0] if completed else None,
        })

    # alerts 추가
    for alert in new_alerts:
        history.setdefault("alerts", []).append({
            "workflow":   alert["workflow"],
            "fail_count": alert["fail_count"],
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "resolved":   False,
        })

    return history


# ────────────────────────────────────────────
# 리포트 출력
# ────────────────────────────────────────────
def print_report(history: dict):
    """현황 요약 출력."""
    print("\n" + "="*60)
    print("📊 스케줄 실행 현황 요약")
    print("="*60)

    runs = history.get("runs", {})
    if not runs:
        print("이력 없음")
        return

    for wf, info in sorted(runs.items()):
        last = info.get("last_run")
        rate = info.get("success_rate")
        status_icon = "✅" if rate and rate >= 80 else ("⚠️" if rate and rate >= 50 else "❌")

        print(f"\n{status_icon} {wf}")
        print(f"   총 실행: {info.get('total_runs', 0)}회 | "
              f"성공: {info.get('success_count', 0)} | "
              f"실패: {info.get('failure_count', 0)} | "
              f"성공률: {rate}%")
        if last:
            print(f"   최근 실행: {last['started_at'][:16]} → {last.get('conclusion', 'unknown')}")

    alerts = [a for a in history.get("alerts", []) if not a.get("resolved")]
    if alerts:
        print(f"\n🚨 미해결 알림: {len(alerts)}건")
        for a in alerts:
            print(f"   - {a['workflow']} ({a['detected_at'][:10]})")

    print("\n" + "="*60)


# ────────────────────────────────────────────
# 메인
# ────────────────────────────────────────────
def main():
    if not GITHUB_TOKEN:
        logger.error("GITHUB_TOKEN 환경 변수가 설정되지 않았습니다.")
        sys.exit(1)

    args = sys.argv[1:]
    report_only  = "--report" in args
    issue_test   = "--issue-test" in args

    # 설정 + 이력 로드
    config  = load_schedule_config()
    history = load_history()
    alert_threshold = config.get("alert_rules", {}).get("consecutive_failures", 2)

    if report_only:
        print_report(history)
        return

    if issue_test:
        # 테스트 이슈 생성
        test_failure = {
            "workflow":   "blog-run.yml",
            "category":   "content",
            "fail_count": 2,
            "last_run":   {"run_id": 0, "run_number": 0, "conclusion": "failure",
                           "started_at": datetime.now(timezone.utc).isoformat(),
                           "html_url": f"https://github.com/{OWNER}/{REPO}/actions"},
            "runs":       [{"run_id": 0, "run_number": 0, "conclusion": "failure",
                            "started_at": datetime.now(timezone.utc).isoformat(),
                            "html_url": f"https://github.com/{OWNER}/{REPO}/actions"}] * 2,
        }
        create_failure_issue(test_failure)
        return

    # 1. 실행 이력 수집
    logger.info(f"워크플로우 실행 이력 수집 시작 (최근 {LOOKBACK_HOURS}시간)")
    new_runs = collect_all_runs(config)
    logger.info(f"수집 완료: {len(new_runs)}개 워크플로우")

    # 2. 연속 실패 감지
    failures   = detect_consecutive_failures(new_runs, threshold=alert_threshold)
    new_alerts = should_alert(failures, history)

    if failures:
        logger.warning(f"연속 실패 감지: {len(failures)}개")
        for f in failures:
            logger.warning(f"  - {f['workflow']} ({f['fail_count']}회)")
    else:
        logger.info("연속 실패 없음")

    # 3. 새 알림 이슈 생성
    for alert in new_alerts:
        create_failure_issue(alert)

    # 4. 이력 저장
    history = update_history(history, new_runs, new_alerts)
    save_history(history)

    # 5. 리포트
    print_report(history)

    # 6. 실패 시 exit 1 (GitHub Actions에서 감지용)
    if new_alerts:
        logger.warning(f"{len(new_alerts)}개 워크플로우 신규 알림 발송")
        sys.exit(0)  # 알림은 보냈지만 모니터 자체는 성공


if __name__ == "__main__":
    main()
