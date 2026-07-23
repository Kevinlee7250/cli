"""글 작성 전 자료 조사 — 검색 의도 분석 + 공식 자료 검색.

흐름: 키워드 → 검색 의도 분석(Claude) → 네이버 뉴스/웹 검색 → 원문 수집
결과는 evidence_builder가 자료팩(facts)으로 정리합니다.
"""
import json
import logging
import os
import re

import requests

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

# 공식·신뢰 도메인 (검색 결과 우선순위)
_TRUSTED_DOMAINS = (
    ".go.kr", ".or.kr", ".gov", "korea.kr", "law.go.kr",
    "bok.or.kr", "fss.or.kr", "kdi.re.kr", "nts.go.kr",
    "yna.co.kr", "yonhapnews", "mk.co.kr", "hankyung.com",
    "chosun.com", "joongang.co.kr", "donga.com", "hani.co.kr",
    "khan.co.kr", "sbs.co.kr", "kbs.co.kr", "imbc.com", "ytn.co.kr",
)


def _is_trusted(url: str) -> bool:
    return any(d in url.lower() for d in _TRUSTED_DOMAINS)


def analyze_search_intent(keyword: str) -> dict:
    """키워드의 검색 의도와 필요한 사실 목록을 Claude로 분석합니다."""
    try:
        import anthropic
        from config import claude_text, ANTHROPIC_API_KEY, CLAUDE_MODEL
        if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("sk-ant-xxx"):
            return {}
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2000,
            messages=[{
                "role": "user",
                "content": (
                    f"블로그 키워드: \"{keyword}\"\n\n"
                    "이 키워드로 정확한 글을 쓰려면 어떤 사실 확인이 필요한지 분석하세요.\n"
                    "JSON만 응답:\n"
                    '{"intent": "검색 의도 한 줄", '
                    '"required_facts": ["확인 필요한 사실1", "사실2", "사실3"], '
                    '"search_queries": ["검색어1", "검색어2", "검색어3"]}'
                ),
            }],
        )
        raw = claude_text(msg).strip()
        s, e = raw.find("{"), raw.rfind("}")
        if s != -1 and e > s:
            data = json.loads(raw[s:e + 1])
            if isinstance(data, dict):
                logger.info(f"검색 의도: {data.get('intent', '')[:60]}")
                return data
    except Exception as exc:
        logger.warning(f"검색 의도 분석 실패: {exc}")
    return {}


def _naver_search(query: str, kind: str, display: int = 5) -> list[dict]:
    """네이버 검색 API (news 또는 webkr)."""
    cid = os.getenv("NAVER_CLIENT_ID", "")
    csec = os.getenv("NAVER_CLIENT_SECRET", "")
    if not cid or not csec:
        return []
    try:
        r = requests.get(
            f"https://openapi.naver.com/v1/search/{kind}.json",
            headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": csec},
            params={"query": query, "display": display,
                    **({"sort": "date"} if kind == "news" else {})},
            timeout=10,
        )
        if r.status_code != 200:
            return []
        items = []
        for it in r.json().get("items", []):
            title = re.sub(r"<[^>]+>", "", it.get("title", "")).strip()
            desc = re.sub(r"<[^>]+>", "", it.get("description", "")).strip()
            url = it.get("originallink") or it.get("link", "")
            if not title or not url:
                continue
            items.append({
                "title": title,
                "url": url,
                "snippet": desc,
                "published_at": (it.get("pubDate") or "")[:16],
                "kind": kind,
            })
        return items
    except Exception as exc:
        logger.debug(f"네이버 {kind} 검색 실패 ({query}): {exc}")
        return []


def _fetch_page_text(url: str, max_chars: int = 2500) -> str:
    """검색 결과 페이지 본문 텍스트 수집 (실패해도 무해)."""
    try:
        r = requests.get(url, headers=_HEADERS, timeout=8)
        if r.status_code != 200:
            return ""
        html = r.text
        # script/style 제거 후 태그 제거
        html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]
    except Exception:
        return ""


def collect_research(keyword: str, max_materials: int = 8) -> dict:
    """키워드에 대한 조사 자료를 수집합니다.

    Returns:
        {"keyword", "intent", "required_facts", "materials": [{title,url,snippet,body,...}]}
        수집 실패 시 materials가 빈 목록.
    """
    intent = analyze_search_intent(keyword)
    queries = intent.get("search_queries") or [keyword]

    seen_urls: set[str] = set()
    materials: list[dict] = []
    for q in queries[:3]:
        for kind in ("news", "webkr"):
            for it in _naver_search(q, kind):
                if it["url"] in seen_urls:
                    continue
                seen_urls.add(it["url"])
                it["trusted"] = _is_trusted(it["url"])
                materials.append(it)

    # 신뢰 도메인 우선 정렬 후 상위 N개만 본문 수집
    materials.sort(key=lambda x: (not x["trusted"],))
    materials = materials[:max_materials]
    for it in materials[:5]:
        body = _fetch_page_text(it["url"])
        if body:
            it["body"] = body

    logger.info(
        f"자료 조사: {len(materials)}개 수집 "
        f"(신뢰 도메인 {sum(1 for m in materials if m['trusted'])}개) — '{keyword}'"
    )
    return {
        "keyword": keyword,
        "intent": intent.get("intent", ""),
        "required_facts": intent.get("required_facts", []),
        "materials": materials,
    }
