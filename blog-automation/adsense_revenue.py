"""실제 AdSense 수익 연동 — 추정치를 실측으로 교체합니다.

지금 대시보드의 수익은 CPC 테이블 × 가정한 CTR(1%)로 계산한 추정치입니다.
카테고리별 CPC는 감(勘)에 가깝고, 실제 수익과 자릿수가 다를 수 있습니다.
AdSense Management API v2로 실제 수익·노출·RPM을 받아와,
  1) 대시보드에 실제 수익을 표시하고
  2) 블로그별 실측 RPM을 저장해 포스트별 추정의 기준으로 삼습니다.

⚠️ 권한: 기존 refresh_token은 blogger + webmasters 범위로 발급돼 있어
   adsense.readonly가 없습니다. get_refresh_token.py를 **로컬에서** 다시 실행해
   토큰을 재발급해야 실제 수익을 받아올 수 있습니다.
   (이 저장소는 공개 포크이므로 토큰 발급을 Actions에서 하면 안 됩니다.)
   권한이 없으면 이 모듈은 조용히 실패하고 기존 추정치가 그대로 쓰입니다.

Usage:
  python adsense_revenue.py            # 수집 + docs/data/adsense_revenue.json 저장
  python adsense_revenue.py --days 7
  python adsense_revenue.py --dry-run  # 저장 없이 출력만
"""

import argparse
import json
import logging
import os
import sys
from datetime import date, timedelta

import requests
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_BASE_DIR = os.path.dirname(__file__)
REPORT_PATH = os.path.join(_BASE_DIR, "..", "docs", "data", "adsense_revenue.json")
RPM_FILE = os.path.join(_BASE_DIR, "logs", "adsense_rpm.json")

API_BASE = "https://adsense.googleapis.com/v2"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ADSENSE_SCOPE = "https://www.googleapis.com/auth/adsense.readonly"

# 실측 RPM이 이 기간보다 오래되면 신뢰하지 않습니다 (계절·정책에 따라 크게 변함)
RPM_MAX_AGE_DAYS = 45


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


# ──────────────────────────────────────────────────────────────────────────────
# 인증
# ──────────────────────────────────────────────────────────────────────────────

def get_access_token() -> tuple[str, str]:
    """(access_token, error) — 실패해도 예외를 던지지 않습니다."""
    cid = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
    secret = (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()
    refresh = (os.getenv("GOOGLE_REFRESH_TOKEN") or "").strip()
    if not (cid and refresh):
        return "", "GOOGLE_CLIENT_ID / GOOGLE_REFRESH_TOKEN 미설정"
    try:
        resp = requests.post(TOKEN_URL, data={
            "client_id": cid, "client_secret": secret,
            "refresh_token": refresh, "grant_type": "refresh_token",
        }, timeout=15)
    except requests.exceptions.RequestException as e:
        return "", f"토큰 요청 실패: {e}"
    if resp.status_code != 200:
        return "", f"토큰 발급 실패 (HTTP {resp.status_code})"

    body = resp.json()
    granted = body.get("scope", "")
    # scope가 응답에 실릴 때만 확인 가능 — 없으면 실제 호출에서 403으로 드러납니다
    if granted and ADSENSE_SCOPE not in granted:
        return "", ("refresh_token에 adsense.readonly 권한이 없습니다 — "
                    "로컬에서 get_refresh_token.py를 다시 실행해 재발급하세요")
    return body.get("access_token", ""), ""


def _permission_hint(status: int, text: str) -> str:
    if status == 403:
        return ("AdSense API 접근 거부 — refresh_token에 adsense.readonly 권한이 없거나 "
                "Google Cloud 프로젝트에서 AdSense Management API가 꺼져 있습니다")
    if status == 401:
        return "인증 만료 — refresh_token을 재발급하세요"
    return f"HTTP {status} {text[:120]}"


# ──────────────────────────────────────────────────────────────────────────────
# 수집
# ──────────────────────────────────────────────────────────────────────────────

def list_accounts(token: str) -> tuple[list[str], str]:
    """접근 가능한 AdSense 계정 이름(accounts/pub-XXXX) 목록."""
    try:
        resp = requests.get(f"{API_BASE}/accounts",
                            headers={"Authorization": f"Bearer {token}"}, timeout=20)
    except requests.exceptions.RequestException as e:
        return [], f"계정 조회 실패: {e}"
    if resp.status_code != 200:
        return [], _permission_hint(resp.status_code, resp.text)
    return [a.get("name", "") for a in resp.json().get("accounts", []) if a.get("name")], ""


def fetch_report(token: str, account: str, days: int = 30) -> tuple[dict, str]:
    """도메인별 실제 수익 리포트를 가져옵니다."""
    end = date.today()
    start = end - timedelta(days=days)
    params = [
        ("dateRange", "CUSTOM"),
        ("startDate.year", start.year), ("startDate.month", start.month),
        ("startDate.day", start.day),
        ("endDate.year", end.year), ("endDate.month", end.month),
        ("endDate.day", end.day),
        ("dimensions", "DOMAIN_NAME"),
        ("metrics", "ESTIMATED_EARNINGS"), ("metrics", "PAGE_VIEWS"),
        ("metrics", "IMPRESSIONS"), ("metrics", "CLICKS"),
        ("metrics", "PAGE_VIEWS_RPM"),
    ]
    try:
        resp = requests.get(f"{API_BASE}/{account}/reports:generate",
                            headers={"Authorization": f"Bearer {token}"},
                            params=params, timeout=30)
    except requests.exceptions.RequestException as e:
        return {}, f"리포트 조회 실패: {e}"
    if resp.status_code != 200:
        return {}, _permission_hint(resp.status_code, resp.text)
    return resp.json(), ""


def parse_report(report: dict) -> dict:
    """AdSense 리포트 응답을 {도메인: {수익·조회수·RPM}} 형태로 정리합니다.

    응답의 headers 순서가 요청한 metrics 순서와 항상 같다는 보장이 없어
    헤더 이름으로 인덱스를 찾습니다.
    """
    headers = [h.get("name", "") for h in (report.get("headers") or [])]

    def idx(name):
        return headers.index(name) if name in headers else -1

    i_dom, i_earn = idx("DOMAIN_NAME"), idx("ESTIMATED_EARNINGS")
    i_views, i_imp = idx("PAGE_VIEWS"), idx("IMPRESSIONS")
    i_clicks, i_rpm = idx("CLICKS"), idx("PAGE_VIEWS_RPM")

    def val(cells, i, cast=float):
        if i < 0 or i >= len(cells):
            return cast(0)
        try:
            return cast(cells[i].get("value") or 0)
        except (TypeError, ValueError):
            return cast(0)

    out: dict[str, dict] = {}
    for row in (report.get("rows") or []):
        cells = row.get("cells") or []
        domain = str(val(cells, i_dom, str) or "").strip()
        if not domain:
            continue
        earnings = val(cells, i_earn)
        views = val(cells, i_views, int)
        rpm = val(cells, i_rpm)
        if not rpm and views:
            rpm = round(earnings / views * 1000, 4)
        out[domain] = {
            "earnings": round(earnings, 4),
            "pageViews": views,
            "impressions": val(cells, i_imp, int),
            "clicks": val(cells, i_clicks, int),
            "rpm": round(rpm, 4),
        }
    return out


# ──────────────────────────────────────────────────────────────────────────────
# 다른 모듈이 쓰는 진입점
# ──────────────────────────────────────────────────────────────────────────────

def load_real_rpm() -> dict[str, float]:
    """{도메인: RPM} — 실측이 없거나 오래됐으면 빈 dict.

    blog_analytics가 이 값을 쓰면 CPC 가정 대신 실제 RPM으로 수익을 계산합니다.
    비어 있으면 호출부는 기존 추정 로직을 그대로 씁니다.
    """
    data = _load(RPM_FILE, {})
    rpm = data.get("byDomain") or {}
    updated = str(data.get("updatedAt") or "")[:10]
    if not (rpm and updated):
        return {}
    try:
        age = (date.today() - date.fromisoformat(updated)).days
    except ValueError:
        return {}
    if age > RPM_MAX_AGE_DAYS:
        logger.info(f"실측 RPM이 {age}일 전 데이터 — 추정치를 사용합니다")
        return {}
    return {d: float(v) for d, v in rpm.items() if v}


def revenue_from_rpm(pageviews: int, rpm: float) -> float:
    """RPM(1000회 노출당 수익)으로 수익을 계산합니다."""
    if pageviews <= 0 or rpm <= 0:
        return 0.0
    return round(pageviews / 1000 * rpm, 4)


# ──────────────────────────────────────────────────────────────────────────────
# 실행
# ──────────────────────────────────────────────────────────────────────────────

def run(days: int = 30, dry_run: bool = False) -> dict:
    result = {
        "collectedAt": date.today().isoformat(),
        "periodDays": days,
        "available": False,
        "error": "",
        "totalEarnings": 0.0,
        "byDomain": {},
    }

    token, err = get_access_token()
    if not token:
        result["error"] = err
        logger.warning(f"실제 수익 연동 불가: {err} — 기존 추정치를 계속 사용합니다")
        if not dry_run:
            _save(REPORT_PATH, result)
        return result

    accounts, err = list_accounts(token)
    if not accounts:
        result["error"] = err or "AdSense 계정이 없습니다"
        logger.warning(f"실제 수익 연동 불가: {result['error']}")
        if not dry_run:
            _save(REPORT_PATH, result)
        return result

    by_domain: dict[str, dict] = {}
    for account in accounts:
        report, err = fetch_report(token, account, days)
        if err:
            result["error"] = err
            logger.warning(f"{account} 리포트 실패: {err}")
            continue
        by_domain.update(parse_report(report))

    if not by_domain:
        result["error"] = result["error"] or "수익 데이터가 비어 있습니다 (광고 미노출 상태일 수 있음)"
        if not dry_run:
            _save(REPORT_PATH, result)
        return result

    result["available"] = True
    result["error"] = ""
    result["byDomain"] = by_domain
    result["totalEarnings"] = round(sum(d["earnings"] for d in by_domain.values()), 4)

    logger.info(f"✅ 실제 AdSense 수익 {days}일: ${result['totalEarnings']:.2f}")
    for dom, d in sorted(by_domain.items(), key=lambda kv: -kv[1]["earnings"]):
        logger.info(f"  {dom}: ${d['earnings']:.2f} · 조회 {d['pageViews']:,} · RPM ${d['rpm']:.2f}")

    if dry_run:
        logger.info("🔍 dry-run — 저장하지 않음")
        return result

    _save(REPORT_PATH, result)
    _save(RPM_FILE, {
        "updatedAt": date.today().isoformat(),
        "byDomain": {d: v["rpm"] for d, v in by_domain.items() if v["rpm"] > 0},
    })
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="실제 AdSense 수익 수집")
    parser.add_argument("--days", type=int, default=30, help="조회 기간 (기본 30일)")
    parser.add_argument("--dry-run", action="store_true", help="저장 없이 출력만")
    args = parser.parse_args()
    run(days=args.days, dry_run=args.dry_run)
    # 권한이 없어도 워크플로를 실패시키지 않습니다 — 추정치로 계속 돌아가야 하므로
    return 0


if __name__ == "__main__":
    sys.exit(main())
