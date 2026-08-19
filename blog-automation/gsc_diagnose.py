"""GSC 연결 진단 — "왜 색인이 안 되는가"를 한 번에 보여줍니다.

2026-08-18 점검에서 색인 0/20이 나왔고, 원인을 로그로 좁힐 수 없었습니다.
사이트맵 제출 실패가 403 한 줄로 지나갔고, 그 403이 '권한 부족'인지
'속성 유형 불일치'인지 구분하지 않았기 때문입니다.

2026-08-19 첫 실행 결과 설정에는 문제가 없었습니다 — 쓰기 권한 있음,
3개 블로그 모두 GSC 속성 매칭, 사이트맵 등록·크롤 정상, 오류 0.
즉 병목은 설정이 아니라 구글의 크롤 예산 배정입니다. 그래도 이 모듈은
계속 필요합니다: 설정이 깨졌을 때 조용히 넘어가지 않게 하는 안전망이고,
"설정 문제가 아니다"를 매번 근거로 확인해 주기 때문입니다.

이 모듈은 추측 대신 사실을 확인합니다:
  1) 토큰이 실제로 가진 권한 (쓰기 가능한가)
  2) 토큰이 볼 수 있는 GSC 속성 목록과 각 속성의 권한 수준
  3) 각 블로그가 그중 어디에 매칭되는가 (URL-프리픽스 / 도메인 속성 / 없음)
  4) 사이트맵이 실제로 등록돼 있는가, 마지막으로 읽힌 게 언제인가, 오류는 없는가

읽기만 하므로 안전합니다 — 아무것도 바꾸지 않습니다.

Usage:
  python gsc_diagnose.py
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import requests
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
GSC_API_BASE = "https://www.googleapis.com/webmasters/v3"
WRITE_SCOPE = "https://www.googleapis.com/auth/webmasters"
REPORT_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "data", "gsc_diagnosis.json")

# 사이트맵이 이 기간 넘게 안 읽혔으면 사실상 전달되지 않는 것으로 봅니다
SITEMAP_STALE_DAYS = 7


def _save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_token_and_scopes() -> tuple[str, str, str]:
    """(access_token, granted_scope, error)."""
    from config import BLOGGER_CLIENT_ID, BLOGGER_CLIENT_SECRET, BLOGGER_REFRESH_TOKEN
    if not (BLOGGER_CLIENT_ID and BLOGGER_REFRESH_TOKEN):
        return "", "", "GOOGLE_CLIENT_ID / GOOGLE_REFRESH_TOKEN 미설정"
    try:
        resp = requests.post(TOKEN_URL, data={
            "client_id": BLOGGER_CLIENT_ID,
            "client_secret": BLOGGER_CLIENT_SECRET,
            "refresh_token": BLOGGER_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        }, timeout=15)
    except requests.exceptions.RequestException as e:
        return "", "", f"토큰 요청 실패: {e}"
    if resp.status_code != 200:
        return "", "", f"토큰 발급 실패 (HTTP {resp.status_code})"
    body = resp.json()
    return body.get("access_token", ""), body.get("scope", ""), ""


def list_properties(token: str) -> tuple[list[dict], str]:
    """토큰이 볼 수 있는 GSC 속성과 권한 수준."""
    try:
        r = requests.get(f"{GSC_API_BASE}/sites",
                         headers={"Authorization": f"Bearer {token}"}, timeout=20)
    except requests.exceptions.RequestException as e:
        return [], f"속성 조회 실패: {e}"
    if r.status_code != 200:
        return [], f"속성 조회 실패 (HTTP {r.status_code})"
    return [{"property": s.get("siteUrl", ""),
             "permission": s.get("permissionLevel", "")}
            for s in r.json().get("siteEntry", [])], ""


def match_property(site_url: str, properties: list[dict]) -> str:
    """블로그 URL에 대응하는 GSC 속성을 찾습니다. 없으면 빈 문자열."""
    if not site_url:
        return ""
    host = urlparse(site_url if "//" in site_url else f"https://{site_url}").netloc
    bare = host.removeprefix("www.")
    known = {p["property"] for p in properties}
    for candidate in (site_url, site_url.rstrip("/") + "/",
                      f"https://{host}/", f"https://www.{bare}/",
                      f"https://{bare}/", f"sc-domain:{bare}"):
        if candidate in known:
            return candidate
    return ""


def sitemap_state(token: str, property_id: str, site_url: str) -> dict:
    """해당 속성에 등록된 사이트맵 상태를 요약합니다.

    ⚠️ 응답의 contents[].indexed는 구글이 지원을 중단한 필드로 **항상 0**입니다.
    실제 색인 수가 아닙니다. 이 값을 색인률로 읽으면 "제출 421 / 색인 0 = 0%"
    같은 잘못된 결론에 이릅니다 (2026-08-19에 실제로 그럴 뻔했음).
    색인 여부는 URL 검사 API 결과(docs/data/index_status.json)나
    Search Console 화면으로 판단하세요. 그래서 아래에서는 이 값을
    indexedUrlsDeprecated로 이름 붙이고 경고 문구를 함께 실어 보냅니다.
    """
    try:
        r = requests.get(f"{GSC_API_BASE}/sites/{quote(property_id, safe='')}/sitemaps",
                         headers={"Authorization": f"Bearer {token}"}, timeout=20)
    except requests.exceptions.RequestException as e:
        return {"ok": False, "error": f"조회 실패: {e}"}
    if r.status_code != 200:
        return {"ok": False, "error": f"HTTP {r.status_code}"}

    entries = r.json().get("sitemap", []) or []
    if not entries:
        return {"ok": False, "registered": 0,
                "error": "등록된 사이트맵 없음 — 구글이 글을 발견할 경로가 없습니다"}

    out = []
    for s in entries:
        submitted = sum(int(c.get("submitted", 0) or 0) for c in (s.get("contents") or []))
        indexed = sum(int(c.get("indexed", 0) or 0) for c in (s.get("contents") or []))
        out.append({
            "path": s.get("path", ""),
            "lastDownloaded": (s.get("lastDownloaded") or "")[:10],
            "errors": int(s.get("errors", 0) or 0),
            "warnings": int(s.get("warnings", 0) or 0),
            "submittedUrls": submitted,
            # 이름에 Deprecated를 박아 둔 이유는 위 docstring 참고 — 항상 0입니다
            "indexedUrlsDeprecated": indexed,
            "isPending": bool(s.get("isPending")),
        })
    never_read = all(not s["lastDownloaded"] for s in out)
    return {
        "ok": not never_read,
        "registered": len(out),
        "sitemaps": out,
        # 리포트를 나중에 읽는 사람이 indexedUrlsDeprecated=0을 색인률로
        # 오해하지 않도록, 데이터 옆에 경고를 붙여 둡니다
        "note": ("indexedUrlsDeprecated는 구글이 지원 중단한 필드로 항상 0입니다 — "
                 "색인 여부는 index_status.json(URL 검사)으로 판단하세요"),
        "error": "등록됐지만 구글이 한 번도 읽지 않았습니다" if never_read else "",
    }


def run() -> dict:
    from config import get_blog_configs
    report: dict = {
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "canWrite": False,
        "grantedScope": "",
        "properties": [],
        "blogs": [],
        "problems": [],
    }

    token, scope, err = get_token_and_scopes()
    if not token:
        report["problems"].append(f"인증 실패: {err}")
        _save(REPORT_PATH, report)
        logger.error(f"진단 불가: {err}")
        return report

    report["grantedScope"] = scope
    # scope가 응답에 실릴 때만 판정 가능 — 없으면 실제 호출 결과로 드러납니다.
    # 부분 문자열로 비교하면 webmasters.readonly가 webmasters를 포함해 통과해버리므로
    # 공백으로 쪼개 정확히 일치하는 항목이 있는지 본다.
    report["canWrite"] = (WRITE_SCOPE in scope.split()) if scope else None
    if report["canWrite"] is False:
        report["problems"].append(
            "토큰에 사이트맵 쓰기 권한(webmasters)이 없습니다 — 사이트맵 제출이 항상 403으로 "
            "실패하며, 이것이 구글이 글을 발견하지 못하는 직접 원인입니다. "
            "로컬에서 get_refresh_token.py를 다시 실행해 재발급하세요."
        )

    properties, perr = list_properties(token)
    report["properties"] = properties
    if perr:
        report["problems"].append(perr)
    logger.info(f"접근 가능한 GSC 속성 {len(properties)}개")
    for p in properties:
        logger.info(f"  {p['property']}  ({p['permission']})")

    for cfg in get_blog_configs():
        site = (cfg.get("gsc_site_url") or cfg.get("url") or "").strip()
        name = cfg.get("name") or cfg.get("id", "?")
        entry = {"blog": name, "siteUrl": site, "property": "", "sitemap": {}}
        if not site:
            entry["problem"] = "블로그 URL 미설정"
            report["problems"].append(f"[{name}] 사이트 URL이 설정되지 않았습니다")
            report["blogs"].append(entry)
            continue

        prop = match_property(site, properties)
        entry["property"] = prop
        if not prop:
            entry["problem"] = "GSC에 등록되지 않음"
            report["problems"].append(
                f"[{name}] {site} 에 대응하는 Search Console 속성이 없습니다 — "
                "속성을 먼저 등록해야 색인이 시작됩니다"
            )
        else:
            entry["sitemap"] = sitemap_state(token, prop, site)
            if not entry["sitemap"].get("ok"):
                report["problems"].append(f"[{name}] 사이트맵: {entry['sitemap'].get('error', '알 수 없음')}")
        report["blogs"].append(entry)

    _save(REPORT_PATH, report)

    logger.info("=" * 60)
    if report["problems"]:
        logger.warning(f"발견된 문제 {len(report['problems'])}건:")
        for p in report["problems"]:
            logger.warning(f"  • {p}")
    else:
        logger.info("✅ GSC 연결·사이트맵에 이상 없음")
    return report


def main() -> int:
    run()
    return 0   # 진단 실패가 워크플로를 멈추게 하지 않습니다


if __name__ == "__main__":
    sys.exit(main())
