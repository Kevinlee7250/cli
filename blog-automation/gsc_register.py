"""Google Search Console 사이트 등록 스크립트.

blogs.json의 gsc_site_url을 Search Console API(sites.add)로 등록합니다.
Blogger 블로그는 소유 계정이면 자동 검증되므로 별도 확인 절차가 필요 없습니다.

사용법: python gsc_register.py          # 전체 블로그 등록
        python gsc_register.py --list   # 현재 등록된 사이트 목록만 출력
"""

import logging
import sys

import requests

from config import (
    BLOGGER_CLIENT_ID,
    BLOGGER_CLIENT_SECRET,
    BLOGGER_REFRESH_TOKEN,
    get_blog_configs,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
GSC_API_BASE = "https://www.googleapis.com/webmasters/v3"


def _access_token() -> str | None:
    resp = requests.post(TOKEN_URL, data={
        "client_id": BLOGGER_CLIENT_ID,
        "client_secret": BLOGGER_CLIENT_SECRET,
        "refresh_token": BLOGGER_REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }, timeout=15)
    if resp.status_code != 200:
        logger.error(f"토큰 발급 실패: {resp.status_code} {resp.text[:200]}")
        return None
    return resp.json().get("access_token")


def list_sites(token: str) -> list[dict]:
    r = requests.get(
        f"{GSC_API_BASE}/sites",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    if r.status_code != 200:
        logger.error(f"사이트 목록 조회 실패: {r.status_code} {r.text[:300]}")
        return []
    return r.json().get("siteEntry", [])


def add_site(token: str, site_url: str) -> bool:
    encoded = requests.utils.quote(site_url, safe="")
    r = requests.put(
        f"{GSC_API_BASE}/sites/{encoded}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    if r.status_code in (200, 204):
        logger.info(f"✅ 등록 성공: {site_url}")
        return True
    if r.status_code == 403 and "insufficient" in r.text.lower():
        logger.error(
            f"❌ 권한 부족: {site_url} — OAuth 토큰에 webmasters 스코프가 없습니다. "
            "get-oauth-token 워크플로우로 토큰을 재발급할 때 "
            "https://www.googleapis.com/auth/webmasters 스코프를 포함하세요."
        )
        return False
    logger.error(f"❌ 등록 실패: {site_url} — {r.status_code} {r.text[:300]}")
    return False


def main() -> int:
    token = _access_token()
    if not token:
        return 1

    existing = {s.get("siteUrl", ""): s.get("permissionLevel", "") for s in list_sites(token)}
    if existing:
        logger.info("현재 등록된 사이트:")
        for url, perm in existing.items():
            logger.info(f"  - {url} ({perm})")
    else:
        logger.info("현재 등록된 사이트 없음 (또는 조회 권한 없음)")

    if "--list" in sys.argv:
        return 0

    targets = []
    for b in get_blog_configs():
        u = b.get("gsc_site_url", "")
        if u and u not in targets:
            targets.append(u)

    ok = fail = skip = 0
    for url in targets:
        if url in existing:
            logger.info(f"⏭ 이미 등록됨: {url} ({existing[url]})")
            skip += 1
            continue
        if add_site(token, url):
            ok += 1
        else:
            fail += 1

    logger.info(f"\n완료 — 신규 등록 {ok} / 이미 등록 {skip} / 실패 {fail}")

    # 최종 상태 재확인
    final = list_sites(token)
    if final:
        logger.info("최종 등록 상태:")
        for s in final:
            logger.info(f"  - {s.get('siteUrl')} ({s.get('permissionLevel')})")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
