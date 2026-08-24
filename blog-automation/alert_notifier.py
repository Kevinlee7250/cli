"""운영 알림 워치독 — 실패를 사람이 대시보드를 열어봐야만 아는 문제 해소.

지금 텔레그램 알림은 blog-run.yml에만 붙어 있고 나머지 61개 워크플로에는
없습니다. 61곳에 같은 스텝을 복붙하면 유지보수가 불가능하므로, 이 모듈이
GitHub Actions API로 저장소 전체 실행을 주기적으로 훑어 한 번에 보고합니다.

보고 대상:
  1) 최근 N시간 내 실패한 워크플로 실행 (전체 워크플로 대상)
  2) 자동수리 건강점수 급락 / critical 이슈
  3) 인증·ads.txt 이상 (일시적 응답은 제외)
  4) 성과 측정 중단 (등급·학습의 근거가 사라진 상태)

같은 문제로 매번 알림이 오지 않도록 직전 발송 내용을 기록해 중복을 거릅니다.
텔레그램 설정이 없으면 로그만 남기고 정상 종료합니다 — 알림 실패가
다른 자동화를 멈추게 하면 안 되기 때문입니다.

Usage:
  python alert_notifier.py                 # 감지 + 발송
  python alert_notifier.py --dry-run       # 감지만 (발송 없음)
  python alert_notifier.py --hours 24
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_BASE_DIR = os.path.dirname(__file__)
_DOCS_DATA = os.path.join(_BASE_DIR, "..", "docs", "data")
STATE_FILE = os.path.join(_BASE_DIR, "logs", "alert_state.json")
REPORT_PATH = os.path.join(_DOCS_DATA, "alerts.json")

GITHUB_API = "https://api.github.com"
DEFAULT_HOURS = 12
HEALTH_SCORE_FLOOR = 70          # 이 아래로 떨어지면 알림
# 실패해도 알리지 않을 워크플로 (npm/cli 포크에서 딸려온 것들 — 우리 시스템과 무관)
_IGNORED_PREFIXES = ("ci-", "ci.", "codeql", "node-", "release", "pull-request", "audit")


def _load(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _is_ours(workflow_path: str) -> bool:
    name = (workflow_path or "").split("/")[-1]
    return not any(name.startswith(p) for p in _IGNORED_PREFIXES)


# ──────────────────────────────────────────────────────────────────────────────
# 1) 워크플로 실패 수집
# ──────────────────────────────────────────────────────────────────────────────

def fetch_failed_runs(repo: str, token: str, hours: int = DEFAULT_HOURS) -> list[dict]:
    """최근 N시간 내 실패한 워크플로 실행 목록을 반환합니다."""
    if not (repo and token):
        logger.warning("GITHUB_REPOSITORY 또는 토큰 없음 — 워크플로 실패 조회 생략")
        return []

    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        resp = requests.get(
            f"{GITHUB_API}/repos/{repo}/actions/runs",
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json"},
            params={"status": "failure", "created": f">={since}", "per_page": 50},
            timeout=20,
        )
    except requests.exceptions.RequestException as e:
        logger.warning(f"워크플로 실행 조회 실패: {e}")
        return []

    if resp.status_code != 200:
        logger.warning(f"워크플로 실행 조회 실패: HTTP {resp.status_code} {resp.text[:150]}")
        return []

    out = []
    for run in resp.json().get("workflow_runs", []):
        if not _is_ours(run.get("path", "")):
            continue
        out.append({
            "id": run.get("id"),
            "name": run.get("name", ""),
            "path": run.get("path", ""),
            "created_at": run.get("created_at", ""),
            "url": run.get("html_url", ""),
        })
    return out


# ──────────────────────────────────────────────────────────────────────────────
# 2) 시스템 상태 수집
# ──────────────────────────────────────────────────────────────────────────────

_TRANSIENT_MARKERS = ("HTTP 429", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504",
                      "timeout", "Timeout", "일시적")


def _is_transient_error(error) -> bool:
    """일시적 응답인지 메시지로 판별 (transient 플래그가 없는 옛 리포트 대비)."""
    text = str(error or "")
    return any(m in text for m in _TRANSIENT_MARKERS)


def collect_system_alerts() -> list[dict]:
    """자동수리·인증·측정 리포트에서 알릴 만한 상태를 뽑습니다."""
    alerts: list[dict] = []

    repairs = _load(os.path.join(_DOCS_DATA, "repairs.json"), [])
    if isinstance(repairs, list) and repairs:
        latest = repairs[0]
        score = latest.get("health_score")
        if isinstance(score, (int, float)) and score < HEALTH_SCORE_FLOOR:
            alerts.append({"key": f"health:{int(score)}",
                           "text": f"⚠️ 시스템 건강점수 {score}/100 (기준 {HEALTH_SCORE_FLOOR} 미만)"})
        for issue in latest.get("issues", []):
            if issue.get("level") == "critical":
                alerts.append({"key": f"critical:{issue.get('id')}",
                               "text": f"🔴 {issue.get('message', '')[:120]}"})

    auth = _load(os.path.join(_DOCS_DATA, "auth_health.json"), {})
    for c in (auth.get("checks") or []):
        # 일시적 응답(429/5xx)은 설정 문제가 아니므로 알리지 않는다.
        # transient 플래그가 없던 시절의 오래된 리포트도 있어 메시지로도 한 번 더 거른다.
        if not c.get("ok") and not c.get("transient") and not _is_transient_error(c.get("error")):
            alerts.append({"key": f"auth:{c.get('name')}",
                           "text": f"🔑 {c.get('name')}: {str(c.get('error',''))[:100]}"})

    summary = _load(os.path.join(_DOCS_DATA, "analytics_summary.json"), {})
    ds = (summary or {}).get("dataSource") or {}
    if ds and not ds.get("bloggerApi") and not ds.get("gscPageData"):
        alerts.append({"key": "measurement_dead",
                       "text": "📉 성과 데이터 수집 전면 실패 — 등급·학습 판단의 근거 없음"})

    return alerts


# ──────────────────────────────────────────────────────────────────────────────
# 3) 발송
# ──────────────────────────────────────────────────────────────────────────────

def send_telegram(text: str) -> bool:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if not (token and chat_id):
        logger.info("텔레그램 미설정 — 발송 생략 (알림 내용은 리포트에 저장됨)")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"},
            timeout=15,
        )
    except requests.exceptions.RequestException as e:
        logger.warning(f"텔레그램 발송 실패 (무시): {e}")
        return False
    if resp.status_code != 200:
        logger.warning(f"텔레그램 발송 실패 (무시): HTTP {resp.status_code} {resp.text[:120]}")
        return False
    return True


def build_message(failed_runs: list[dict], system_alerts: list[dict]) -> str:
    lines = ["🚨 블로그 자동화 이상 감지"]
    if system_alerts:
        lines.append("")
        lines.extend(a["text"] for a in system_alerts)
    if failed_runs:
        lines.append("")
        lines.append(f"❌ 실패한 워크플로 {len(failed_runs)}건:")
        for r in failed_runs[:5]:
            lines.append(f"· {r['name']} — {r['url']}")
        if len(failed_runs) > 5:
            lines.append(f"· 외 {len(failed_runs) - 5}건")
    return "\n".join(lines)


def run(hours: int = DEFAULT_HOURS, dry_run: bool = False) -> dict:
    repo = os.getenv("GITHUB_REPOSITORY", "")
    token = os.getenv("GITHUB_TOKEN", "") or os.getenv("GH_TOKEN", "")

    failed_runs = fetch_failed_runs(repo, token, hours)
    system_alerts = collect_system_alerts()

    # 같은 문제로 매번 알리지 않도록 직전 발송분과 비교
    state = _load(STATE_FILE, {})
    seen_runs = set(state.get("notifiedRunIds", []))
    seen_keys = set(state.get("notifiedKeys", []))

    new_runs = [r for r in failed_runs if r["id"] not in seen_runs]
    new_alerts = [a for a in system_alerts if a["key"] not in seen_keys]

    report = {
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "windowHours": hours,
        "failedRuns": failed_runs,
        "systemAlerts": system_alerts,
        "newFailedRuns": len(new_runs),
        "newSystemAlerts": len(new_alerts),
        "sent": False,
    }

    if not (new_runs or new_alerts):
        logger.info(f"새 이상 없음 (실패 {len(failed_runs)}건·상태 {len(system_alerts)}건은 이미 알림)")
        _save(REPORT_PATH, report)
        return report

    message = build_message(new_runs, new_alerts)
    logger.warning(f"알림 대상:\n{message}")

    if dry_run:
        logger.info("🔍 dry-run — 발송하지 않음")
    else:
        report["sent"] = send_telegram(message)
        # 발송 성공 여부와 무관하게 기록해 같은 문제로 반복 시도하지 않는다
        _save(STATE_FILE, {
            "notifiedRunIds": list(seen_runs | {r["id"] for r in new_runs})[-200:],
            "notifiedKeys": list(seen_keys | {a["key"] for a in new_alerts})[-100:],
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        })

    _save(REPORT_PATH, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="운영 알림 워치독")
    parser.add_argument("--hours", type=int, default=DEFAULT_HOURS, help="조회할 시간 범위")
    parser.add_argument("--dry-run", action="store_true", help="감지만 하고 발송하지 않음")
    args = parser.parse_args()
    run(hours=args.hours, dry_run=args.dry_run)
    return 0   # 알림 실패가 워크플로를 붉게 만들지 않도록 항상 0


if __name__ == "__main__":
    sys.exit(main())
