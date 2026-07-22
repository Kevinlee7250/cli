"""인증 헬스체크 — Google OAuth 자격증명이 조용히 만료됐는지 매일 확인합니다.

콘텐츠 생성 파이프라인은 자체 오류 처리가 튼튼하지만, GOOGLE_REFRESH_TOKEN이나
GOOGLE_CLIENT_SECRET이 무효해지면 각 워크플로가 "GSC 토큰 발급 실패 — 건너뜀"
같은 경고만 남기고 조용히 성공(success)으로 끝나버려 사람이 우연히 발견하기
전까지 아무도 모르는 문제가 있었습니다 (2026-07-22 발견).

이 스크립트는 실제 API를 호출하지 않고 OAuth 토큰 갱신 1회만 시도해서
자격증명이 살아있는지만 확인합니다. 실패해도 다른 워크플로에 영향을 주지 않습니다.

Usage:
  python auth_health_check.py
"""

import json
import logging
import os
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
_DOCS_DATA = os.path.join(os.path.dirname(__file__), "..", "docs", "data")


def check_google_oauth() -> dict:
    """GOOGLE_REFRESH_TOKEN + GOOGLE_CLIENT_ID/SECRET으로 access_token 갱신을 시도합니다."""
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
    refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN", "")

    if not (client_id and client_secret and refresh_token):
        return {"name": "google_oauth", "ok": False, "error": "필수 값 없음 (GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN)"}

    try:
        resp = requests.post(TOKEN_URL, data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }, timeout=15)
    except requests.exceptions.RequestException as e:
        return {"name": "google_oauth", "ok": False, "error": f"네트워크 오류: {e}"}

    if resp.status_code == 200:
        return {"name": "google_oauth", "ok": True, "error": None}

    try:
        err = resp.json().get("error", "")
    except Exception:
        err = resp.text[:100]
    return {"name": "google_oauth", "ok": False, "error": f"HTTP {resp.status_code} {err}"}


def run() -> dict:
    checks = [check_google_oauth()]
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "all_ok": all(c["ok"] for c in checks),
        "checks": checks,
        # client_id는 공개돼도 무해함(OAuth 재인증 URL을 대시보드에서 바로 구성하기 위해 노출) —
        # client_secret/refresh_token은 절대 여기 포함하지 않는다.
        "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
    }

    for c in checks:
        if c["ok"]:
            logger.info(f"✅ {c['name']}: 정상")
        else:
            logger.error(f"❌ {c['name']}: {c['error']}")

    os.makedirs(_DOCS_DATA, exist_ok=True)
    with open(os.path.join(_DOCS_DATA, "auth_health.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return report


if __name__ == "__main__":
    result = run()
    print(f"\n{'✅ 전체 정상' if result['all_ok'] else '❌ 이상 감지'}")
    raise SystemExit(0 if result["all_ok"] else 1)
