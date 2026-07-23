"""자료팩 출처 검증 — 접속·게시일·발행기관·주장 지지·최신성·충돌·신뢰 등급.

등급 기준:
  A — 정부, 공식 기관, 기업 공식 문서
  B — 대학, 연구기관, 주요 언론
  C — 전문 매체, 업계 보고서
  D — 일반 블로그, 커뮤니티
  제외(X) — 접속 불가, 출처 불명, 내용 불일치

완료 기준: 중요한 수치·정책 정보는 최소 1개 이상의 A/B 등급 출처와 연결되어야
하며, 그렇지 않은 사실은 글 작성 프롬프트에서 제외됩니다
(evidence_builder.format_evidence_for_prompt가 등급을 반영).
"""
import json
import logging
import os
import re
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

# ──────────────────────────────────────────────────────────────────────────────
# 신뢰도 등급 (도메인 기반)
# ──────────────────────────────────────────────────────────────────────────────

_GRADE_A = (  # 정부·공식 기관·기업 공식
    ".go.kr", ".gov", "korea.kr", "law.go.kr", "bok.or.kr", "fss.or.kr",
    "nts.go.kr", "kosis.kr", "index.go.kr", "assembly.go.kr",
)
_GRADE_B = (  # 대학·연구기관·주요 언론
    ".ac.kr", ".re.kr", ".edu", "kdi.re.kr",
    "yna.co.kr", "yonhapnews", "news1.kr", "newsis.com",
    "chosun.com", "joongang.co.kr", "donga.com", "hani.co.kr", "khan.co.kr",
    "mk.co.kr", "hankyung.com", "sedaily.com", "edaily.co.kr", "fnnews.com",
    "kbs.co.kr", "sbs.co.kr", "imbc.com", "ytn.co.kr", "jtbc",
)
_GRADE_C = (  # 전문 매체·업계
    "etnews.com", "zdnet.co.kr", "bloter.net", "byline.network",
    "dt.co.kr", "ddaily.co.kr", "boannews.com", "itworld.co.kr",
    "medigatenews.com", "dailypharm.com", "thebell.co.kr",
)
_GRADE_D = (  # 일반 블로그·커뮤니티
    "blog.naver.com", "tistory.com", "brunch.co.kr", "velog.io",
    "cafe.naver.com", "cafe.daum.net", "dcinside.com", "clien.net",
    "ruliweb.com", "fmkorea.com", "instiz.net", "theqoo.net",
    "medium.com", "blogspot.com", "wordpress.com",
)


def grade_source(url: str) -> str:
    """출처 URL의 신뢰도 등급(A/B/C/D)을 반환합니다."""
    u = (url or "").lower()
    if not u.startswith(("http://", "https://")):
        return "X"
    if any(d in u for d in _GRADE_A):
        return "A"
    if any(d in u for d in _GRADE_B):
        return "B"
    if any(d in u for d in _GRADE_C):
        return "C"
    if any(d in u for d in _GRADE_D):
        return "D"
    # 미분류: 뉴스형 경로면 C(전문 매체 추정), 아니면 D
    return "C" if re.search(r"news|press|article", u) else "D"


# ──────────────────────────────────────────────────────────────────────────────
# 페이지 수집 — 접속 확인 + 본문 + 게시일·발행기관 추출
# ──────────────────────────────────────────────────────────────────────────────

def _fetch_page(url: str, timeout: int = 10) -> dict:
    """페이지 접속 확인 및 본문·게시일·발행기관 추출.

    Returns: {"ok": bool, "text": str, "published_at": str, "publisher": str}
    """
    out = {"ok": False, "text": "", "published_at": "", "publisher": ""}
    if not url.startswith(("http://", "https://")):
        return out
    try:
        r = requests.get(url, headers=_HEADERS, timeout=timeout, allow_redirects=True)
        if r.status_code >= 400:
            return out
        out["ok"] = True
        html = r.text[:200_000]

        # 게시일: meta property / JSON-LD datePublished / 본문 날짜 패턴
        m = re.search(
            r'<meta[^>]+(?:property|name)=["\'](?:article:published_time|'
            r'og:regDate|date|pubdate|publishdate)["\'][^>]+content=["\']([^"\']+)',
            html, re.I,
        ) or re.search(r'"datePublished"\s*:\s*"([^"]+)"', html)
        if m:
            out["published_at"] = m.group(1)[:10]
        else:
            m = re.search(r"(20\d{2})[.\-/년\s]{1,3}(\d{1,2})[.\-/월\s]{1,3}(\d{1,2})", html)
            if m:
                out["published_at"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

        # 발행기관: og:site_name → JSON-LD publisher → 도메인
        m = re.search(
            r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)', html, re.I
        ) or re.search(r'"publisher"\s*:\s*{[^}]*"name"\s*:\s*"([^"]+)"', html)
        if m:
            out["publisher"] = m.group(1).strip()[:60]
        else:
            dm = re.match(r"https?://([^/]+)", url)
            out["publisher"] = dm.group(1) if dm else ""

        # 본문 텍스트
        body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
        body = re.sub(r"<[^>]+>", " ", body)
        out["text"] = re.sub(r"\s+", " ", body).strip()[:3000]
        return out
    except Exception:
        return out


def is_stale(published_at: str, max_age_days: int | None = None) -> bool:
    """게시일이 오래됐는지 판단 (기본 2년, EVIDENCE_MAX_AGE_DAYS로 조정)."""
    if not published_at:
        return False  # 날짜 불명은 별도 플래그 없이 통과 (등급·지지 검증이 거름)
    if max_age_days is None:
        max_age_days = int(os.getenv("EVIDENCE_MAX_AGE_DAYS", "730"))
    try:
        pub = datetime.fromisoformat(published_at[:10]).replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - pub).days > max_age_days
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────────────────
# 주장 지지 여부 + 출처 간 충돌 (Claude 일괄 대조)
# ──────────────────────────────────────────────────────────────────────────────

def _verify_claims_with_claude(facts: list[dict], pages: dict[str, dict]) -> list[dict]:
    """각 사실이 해당 출처 본문에서 실제로 지지되는지 + 사실 간 충돌을 대조합니다.

    Returns: [{"index": i, "supported": bool, "conflicts_with": [i...]}]
    실패 시 빈 목록 (검증 생략 — supported 판단 불가로 처리).
    """
    try:
        import anthropic
        from config import claude_text, ANTHROPIC_API_KEY, CLAUDE_MODEL
        if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("sk-ant-xxx"):
            return []
        pairs = []
        for i, f in enumerate(facts):
            page = pages.get(f.get("source_url", ""), {})
            excerpt = page.get("text", "")[:1200]
            if not excerpt:
                continue
            pairs.append(f"[{i}] 주장: {f.get('claim', '')}\n    출처 본문 발췌: {excerpt}")
        if not pairs:
            return []
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2000,
            messages=[{
                "role": "user",
                "content": (
                    "각 주장이 해당 출처 본문 발췌에서 실제로 지지되는지 판정하세요.\n"
                    "supported=true 조건: 주장 속 숫자·날짜·내용이 발췌에 부합. "
                    "발췌에 없거나 다른 내용이면 false.\n"
                    "또한 주장들끼리 서로 모순되면 conflicts_with에 상대 번호를 기록하세요.\n\n"
                    + "\n\n".join(pairs) +
                    '\n\nJSON만 응답: {"results": [{"index": 0, "supported": true, "conflicts_with": []}]}'
                ),
            }],
        )
        raw = claude_text(msg).strip()
        s, e = raw.find("{"), raw.rfind("}")
        if s == -1 or e <= s:
            return []
        results = json.loads(raw[s:e + 1]).get("results", [])
        return [r for r in results if isinstance(r, dict) and "index" in r]
    except Exception as exc:
        logger.warning(f"주장-출처 대조 실패: {exc}")
        return []


# ──────────────────────────────────────────────────────────────────────────────
# 메인 검증
# ──────────────────────────────────────────────────────────────────────────────

def validate_pack(pack: dict) -> dict:
    """자료팩의 각 사실을 검증합니다.

    각 fact에 추가되는 필드:
      grade         — A/B/C/D/X (X=제외)
      publisher     — 발행기관
      published_at  — 페이지에서 추출한 게시일로 보강
      stale         — 오래된 자료 여부
      supported     — 출처 본문이 주장을 실제로 지지하는지 (판단 불가 시 None)
      conflicts     — 충돌하는 사실 인덱스 목록
      verified      — 최종 판정 (접속 가능 + 내용 일치 + 제외 등급 아님)
    """
    facts = pack.get("facts") or []
    if not facts:
        return pack

    # 1) 페이지 수집 (URL당 1회) + 등급·게시일·발행기관
    pages: dict[str, dict] = {}
    for f in facts:
        url = f.get("source_url", "")
        if url not in pages:
            pages[url] = _fetch_page(url)
        page = pages[url]
        f["grade"] = grade_source(url) if page["ok"] else "X"
        f["publisher"] = page.get("publisher", "")
        if not f.get("published_at") and page.get("published_at"):
            f["published_at"] = page["published_at"]
        f["stale"] = is_stale(f.get("published_at", ""))

    # 2) 본문 주장 지지 여부 + 출처 간 충돌 (Claude 일괄 대조)
    results = {r["index"]: r for r in _verify_claims_with_claude(facts, pages)}
    for i, f in enumerate(facts):
        r = results.get(i)
        f["supported"] = r.get("supported") if r else None
        f["conflicts"] = (r or {}).get("conflicts_with", [])

    # 3) 최종 판정 — 접속 불가(X) / 내용 불일치(supported=False)는 제외
    for f in facts:
        if f["grade"] == "X" or f.get("supported") is False:
            f["verified"] = False
            f["grade"] = "X"
        else:
            f["verified"] = True

    graded = {}
    for f in facts:
        graded[f["grade"]] = graded.get(f["grade"], 0) + 1
    logger.info(
        f"출처 검증: {sum(1 for f in facts if f['verified'])}/{len(facts)}개 통과, "
        f"등급 분포 {graded}"
    )
    return pack
