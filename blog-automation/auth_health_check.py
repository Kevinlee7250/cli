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


def _publisher_id() -> str:
    """ADSENSE_CLIENT_ID(ca-pub-...)에서 ads.txt용 게시자 ID(pub-...)를 추출합니다."""
    raw = (os.getenv("ADSENSE_CLIENT_ID", "") or "").strip()
    if not raw or "XXXX" in raw.upper():
        return ""
    return raw[3:] if raw.startswith("ca-pub-") else raw


def check_ads_txt(blog_url: str, blog_name: str, publisher_id: str) -> dict:
    """블로그의 /ads.txt가 서빙되고 내 게시자 ID를 포함하는지 확인합니다.

    Blogger의 맞춤 ads.txt 설정은 대시보드 어디에도 드러나지 않아, 설정이
    풀리거나 게시자 ID가 틀려도 AdSense 사이트 목록에서 "찾을 수 없음"을
    직접 보기 전까지 알 수 없었음. 수익에 직접 영향을 주므로 매일 확인한다.
    """
    name = f"ads_txt:{blog_name or blog_url}"
    if not blog_url:
        return {"name": name, "ok": False, "error": "블로그 URL 없음"}

    url = blog_url.rstrip("/") + "/ads.txt"
    try:
        resp = requests.get(url, timeout=15)
    except requests.exceptions.RequestException as e:
        return {"name": name, "ok": False, "error": f"요청 실패: {e}"}

    if resp.status_code != 200:
        return {"name": name, "ok": False,
                "error": f"HTTP {resp.status_code} — Blogger 설정 → 수익에서 맞춤 ads.txt를 켜세요"}

    body = resp.text or ""
    if "google.com" not in body.lower():
        return {"name": name, "ok": False, "error": "ads.txt에 google.com 항목 없음"}
    if publisher_id and publisher_id.lower() not in body.lower():
        return {"name": name, "ok": False,
                "error": f"ads.txt에 내 게시자 ID({publisher_id}) 없음 — 다른 계정 ID일 수 있음"}
    return {"name": name, "ok": True, "error": None}


def check_all_ads_txt() -> list[dict]:
    """설정된 모든 블로그의 ads.txt를 확인합니다."""
    pub_id = _publisher_id()
    if not pub_id:
        return [{"name": "ads_txt", "ok": False,
                 "error": "ADSENSE_CLIENT_ID 미설정 — 게시자 ID를 확인할 수 없음"}]
    try:
        from config import get_blog_configs
        blogs = get_blog_configs()
    except Exception as e:
        return [{"name": "ads_txt", "ok": False, "error": f"블로그 설정 로드 실패: {e}"}]

    results = []
    for b in blogs:
        if not b.get("enabled", True):
            continue
        # 커스텀 도메인이 있으면 그쪽이 실제 서빙 주소
        url = (b.get("gsc_site_url") or b.get("blog_url") or "").strip()
        results.append(check_ads_txt(url, b.get("name") or b.get("id", ""), pub_id))
    return results or [{"name": "ads_txt", "ok": False, "error": "확인할 블로그 없음"}]


def run() -> dict:
    checks = [check_google_oauth()] + check_all_ads_txt()
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
