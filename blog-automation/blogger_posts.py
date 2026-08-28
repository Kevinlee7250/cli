#!/usr/bin/env python3
"""Blogger 글 목록 순회 — 모든 일괄 수정 도구가 함께 쓰는 한 벌.

왜 따로 두는가
──────────────
이 함수는 네 모듈에 복사돼 있었습니다. 2026-08-25에 "목록이 조용히 잘려
'다 처리했다'를 알 수 없던 문제"를 고쳤는데, 사본이 넷이라 수정이
fix_unlicensed_images 한 곳에만 들어갔습니다. 나머지 셋은 두 달 뒤에도
같은 버그를 안고 돌게 됩니다 — 코드만 봐서는 티가 나지 않습니다.

무엇이 문제였나
───────────────
비200 응답에 로그만 남기고 return하면 제너레이터가 그냥 끝납니다. 호출부에는
"그 블로그에는 글이 이만큼뿐"으로 보이고, 도구는 절반만 훑은 채 성공으로
끝납니다. 그러면 "몇 편이 남았는가"를 아무도 말할 수 없습니다.

실제로 같은 `limit 0` 실행이 437 → 382 → 291편으로 줄었습니다. 글이 준 게
아니라 PATCH를 연달아 보낸 뒤 API가 목록 요청을 거절한 것이었습니다.
그 사이 broken 집계는 104 → 30 → 80 → 16으로 오르내렸는데, 이미지가
되살아난 게 아니라 매번 다른 범위를 본 것입니다.

그래서 조용히 끝내지 않습니다. 일시적 거절은 재시도로 넘기고, 그래도 안 되면
ListingTruncated를 올려 호출부가 "덜 봤다"를 알 수 있게 합니다.
"""

import logging
import time

import requests

logger = logging.getLogger(__name__)

BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"

# published가 있어야 "가장 오래된 글 유지" 같은 판단이 됩니다. 필드를 줄여도
# 응답이 크게 가벼워지지 않으므로 기본값 하나로 통일합니다.
DEFAULT_FIELDS = "nextPageToken,items(id,title,url,content,published)"

MAX_RETRIES = 2


class ListingTruncated(RuntimeError):
    """글 목록을 끝까지 읽지 못했습니다 — 부분 결과를 전체로 보고하면 안 됩니다."""


def iter_posts(blog_id: str, token: str, *,
               api_base: str = BLOGGER_API_BASE,
               fields: str = DEFAULT_FIELDS):
    """블로그의 발행(live) 글 전체를 최신순으로 순회합니다.

    Raises:
        ListingTruncated: 재시도 후에도 목록을 끝까지 읽지 못한 경우.
            호출부는 이걸 잡아 "이 블로그는 덜 봤다"고 기록해야 합니다.
            조용히 넘기면 부분 결과가 전체로 보고됩니다.
    """
    page_token = ""
    fetched = 0
    attempt = 0
    while True:
        params = {
            "maxResults": 100,
            "status": "live",
            "fetchBodies": "true",
            "fields": fields,
        }
        if page_token:
            params["pageToken"] = page_token
        r = requests.get(
            f"{api_base}/blogs/{blog_id}/posts",
            headers={"Authorization": f"Bearer {token}"},
            params=params, timeout=30,
        )
        if r.status_code != 200:
            if attempt < MAX_RETRIES:
                wait = 3 * (attempt + 1)
                logger.warning(
                    f"글 목록 조회 실패 [{r.status_code}] — {wait}초 후 재시도")
                time.sleep(wait)
                attempt += 1
                continue
            raise ListingTruncated(
                f"글 목록을 끝까지 읽지 못했습니다 (HTTP {r.status_code}, "
                f"{fetched}편까지 조회): {r.text[:120]}")
        attempt = 0
        data = r.json()
        items = data.get("items", [])
        fetched += len(items)
        yield from items
        page_token = data.get("nextPageToken", "")
        if not page_token:
            return
