"""자료팩 출처 검증 — URL 실존 확인 후 verified 플래그 설정.

존재하지 않거나 접근 불가한 출처의 사실은 verified=False로 남고,
evidence_builder.format_evidence_for_prompt가 verified 사실을 우선 사용합니다.
"""
import logging

import requests

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


def _url_alive(url: str, timeout: int = 8) -> bool:
    """URL이 실제로 접근 가능한지 확인 (HEAD → 실패 시 GET 폴백)."""
    if not url.startswith(("http://", "https://")):
        return False
    try:
        r = requests.head(url, headers=_HEADERS, timeout=timeout, allow_redirects=True)
        if r.status_code < 400:
            return True
        # 일부 서버는 HEAD 거부 → GET으로 재확인
        if r.status_code in (403, 405):
            r = requests.get(url, headers=_HEADERS, timeout=timeout, stream=True)
            r.close()
            return r.status_code < 400
        return False
    except Exception:
        return False


def validate_pack(pack: dict) -> dict:
    """자료팩의 각 사실 출처 URL을 검증해 verified를 설정합니다."""
    facts = pack.get("facts") or []
    if not facts:
        return pack

    # 같은 URL은 한 번만 확인
    url_status: dict[str, bool] = {}
    for f in facts:
        url = f.get("source_url", "")
        if url not in url_status:
            url_status[url] = _url_alive(url)
        f["verified"] = url_status[url]

    ok = sum(1 for f in facts if f["verified"])
    logger.info(f"출처 검증: {ok}/{len(facts)}개 사실의 출처 확인됨")
    return pack
