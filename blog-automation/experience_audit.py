#!/usr/bin/env python3
"""발행된 글에서 '지어낸 1인칭 경험 주장'을 찾아 심각도별로 분류합니다.

왜 필요한가
──────────
2026-09-12 AdSense가 hoguwhat.com을 **"가치가 별로 없는 콘텐츠"**로 거절했습니다.
원인을 추적한 결과 발행글 266편 중 62편(23%)이 하지 않은 경험을 했다고
주장하고 있었습니다. 대표 사례:

    "저는 2024년 11월 한 달 동안 제주시 이도동의 원룸 오피스텔에서…"
    총 178만원 (주거 98만 · 식비 52만 · 교통 22만 · 기타 6만)

날짜·동네·금액 내역까지 구체적인데 전부 지어낸 것이고, 삽화는 제주 사진이
아니라 그라디언트 SVG 카드입니다. 심사관이 한 편만 열어도 판별됩니다.
이건 품질 미달이 아니라 신뢰성 문제이며, 여행·금융 의사결정에 쓰일 수 있는
수치라는 점에서 더 무겁습니다.

`content_generator.py`는 2026-08-26에 가드레일이 들어가 신규 글은 막혔지만
(`_experience_style_block`), 그 이전에 발행된 글은 그대로 게시 중입니다.
이 도구는 그 소급 대상을 정확히 세는 것이 목적입니다 — 고치는 것은
`fix_experience_titles.py`(제목)와 `fix_experience_claims.py`(본문)입니다.

심각도
──────
  critical : 1인칭 + 지어낸 구체 사실(날짜·금액·주소). 최우선 비공개 대상
  high     : 명시적 경험 주장("직접 써봤", "제가 겪은"). 리라이팅 대상
  medium   : 경험을 암시하는 제목 표현("솔직 후기"). 제목만 손보면 되는 경우
  ok       : 조사·분석형("후기를 종합하면"). 손대지 않음

author_profile.json에 실제 경험 자료가 있으면 그 주제는 감점하지 않습니다.
(현재 4건 모두 summary가 비어 있어 실질 0건 — 즉 지금은 모든 1인칭이 조작입니다.)

사용
────
  python experience_audit.py --offline          # 제목만, API 없이 즉시
  python experience_audit.py                    # 제목+본문 전수 (Blogger API)
  python experience_audit.py --blog blog1       # 특정 블로그만
  python experience_audit.py --severity critical  # 특정 심각도만 출력
"""
import argparse
import json
import logging
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"
_HERE = os.path.dirname(os.path.abspath(__file__))
_DOCS_DATA = os.path.join(_HERE, "..", "docs", "data")
REPORT_PATH = os.path.join(_DOCS_DATA, "experience_audit.json")

# ──────────────────────────────────────────────────────────────────────────────
# 탐지 규칙
# ──────────────────────────────────────────────────────────────────────────────
#
# 한국어에서 "후기"는 두 가지로 쓰입니다:
#   (a) "제가 써본 후기"        → 경험 주장 (문제)
#   (b) "이용자 후기를 종합하면" → 조사 서술 (정상)
#
# 단어만 보면 둘을 구분할 수 없어 오탐이 쏟아집니다. 그래서 조사형 표현을
# 먼저 걸러내고(RESEARCH_FRAMING), 남은 것에만 경험 패턴을 적용합니다.

# 조사·분석형 — 이 표현이 감싸고 있으면 경험 주장이 아닙니다.
RESEARCH_FRAMING = re.compile(
    r"(후기(를|들을)?\s*종합|후기\s*기반|리뷰(를)?\s*종합|자료(를)?\s*조사|"
    r"공식\s*(발표|안내|자료|홈페이지)|이용자\s*(후기|반응|평)|"
    r"조사해\s*보니|자료에\s*따르면|기준으로는|알려져\s*있습니다)"
)

# critical — 1인칭 주어 + 지어낸 구체 사실이 같은 문장 안에 있는 경우.
# 금액·날짜·기간·주소가 붙으면 독자가 사실로 받아들이므로 가장 위험합니다.
CRITICAL_PATTERNS = [
    (re.compile(
        r"(저는|제가|내가|필자는)[^.!?\n]{0,100}?"
        r"(\d{4}\s*년|\d{1,2}\s*월\s|\d+\s*박\s*\d+\s*일|\d+\s*개월\s*(동안|간))"
    ), "1인칭 + 구체적 시점"),
    (re.compile(
        r"(저는|제가|내가|필자는)[^.!?\n]{0,100}?"
        r"(\d[\d,]*\s*만?\s*원)"
    ), "1인칭 + 구체적 금액"),
    # 어순이 뒤집힌 경우: "총 178만원을 제가 지출했습니다"
    (re.compile(
        r"(\d[\d,]*\s*만?\s*원)[^.!?\n]{0,60}?(저는|제가|내가|필자는)"
    ), "구체적 금액 + 1인칭"),
    (re.compile(
        r"(제|저희|내)\s*(실제|직접)\s*(지출|비용|생활비|정산|수익|결과)"
    ), "1인칭 실지출·실수익 공개"),
    (re.compile(
        r"(정산한|정산해\s*본|공개합니다|공개해\s*봅니다)[^.!?\n]{0,40}"
        r"(실제|직접)\s*(생활비|비용|지출|수익)"
    ), "실제 정산 내역 공개 주장"),
]

# high — 명시적 경험 주장. 구체 수치는 없어도 "했다"고 단정합니다.
HIGH_PATTERNS = [
    # "직접 ~해봤" — 뒤에 오는 동사를 넉넉히 잡습니다. 초판에서 읽/보/가입 같은
    # 동사가 빠져 "직접 읽어보고 알게 된 것"을 놓쳤습니다.
    (re.compile(
        r"직접\s*[가-힣]{0,3}?"
        r"(해|써|사용|가|다녀|먹|살|예약|신청|청구|받|타|들어|읽|보|배워|가입|등록|체험)"
        # 어간과 '보-' 사이에 연결어미가 낍니다: 읽'어'보고, 먹'어'봤 …
        r"[가-힣]{0,2}?\s*(봤|본|보니|보고|와서|왔)"
    ), "직접 ~해봤"),
    (re.compile(
        r"(해봤습니다|해봤어요|써봤습니다|써봤어요|가봤습니다|먹어봤습니다|"
        r"다녀왔습니다|다녀왔어요|살아봤습니다|겪었습니다|겪어봤습니다)"
    ), "경험 완료형 서술"),
    (re.compile(
        r"(제가|저는|내가)\s*[^.!?\n]{0,30}?"
        r"(겪은|경험한|해\s*본|써\s*본|가\s*본|살아\s*본|받아\s*본|만나\s*본)"
    ), "1인칭 경험 수식"),
    (re.compile(
        r"(제\s*경험(상|으로|에)|저희\s*경험(상|으로)|경험해\s*보니|해\s*보니\s*알게)"
    ), "경험 근거 제시"),
    # 기간 + 사용 주장. "3개월 해본", "6개월 써본"처럼 '직접'이 없어도
    # 기간이 붙으면 실제로 그만큼 써봤다는 주장이라 초판보다 넓게 잡습니다.
    (re.compile(
        r"\d+\s*(개월|주|년|일|주일)\s*(동안\s*)?(직접\s*|실제로\s*)?"
        r"[가-힣]{0,3}?(써|사용|해|살|타|먹|다녀|굴려|끌어)\s*(봤|본|보니)"
    ), "기간 + 사용 경험 주장"),
    # '겪다'는 1인칭 주어가 없어도 화자의 경험을 전제합니다
    # ("물 공포증 극복하려다 겪은 첫 좌절").
    (re.compile(r"겪(은|었|어\s*본|고\s*나서)"), "'겪은' 경험 서술"),
]

# medium — 제목에서 경험을 암시하지만 본문은 조사형일 수 있는 표현.
MEDIUM_PATTERNS = [
    (re.compile(r"솔직(한)?\s*(후기|리뷰|비교|정리|평가|장단점)"), "솔직 후기·리뷰"),
    # "실제 대환대출 후기"처럼 사이에 단어가 끼는 형태까지 잡습니다.
    (re.compile(r"(실제|실사용)\s*[가-힣A-Za-z0-9·\s]{0,12}?(후기|경험|사용기)"),
     "실제 후기 표방"),
    (re.compile(r"(해\s*본|써\s*본|다녀온|가\s*본)\s*(후기|리뷰|경험)"), "~해본 후기"),
    (re.compile(r"직접\s*(비교|정리|확인|점검|계산)"), "직접 비교·정리"),
]

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "ok": 3}


def _strip_html(html: str) -> str:
    """태그·스크립트를 걷어내고 본문 텍스트만 남깁니다."""
    s = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", html or "", flags=re.I | re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"&nbsp;?", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _sentences(text: str) -> list[str]:
    """마침표·물음표·느낌표·줄바꿈 기준으로 문장을 나눕니다."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]


def analyze_text(text: str, *, title_mode: bool = False) -> list[dict]:
    """텍스트에서 경험 주장을 찾아 [{severity, label, excerpt}] 로 반환합니다.

    문장 단위로 보는 이유: 조사형 표현("후기를 종합하면")과 경험 주장이
    한 글 안에 섞여 있을 때, 글 전체로 판정하면 서로를 가립니다.
    """
    hits: list[dict] = []
    units = [text] if title_mode else _sentences(text)

    for unit in units:
        if not unit:
            continue
        # 조사형 프레이밍이 있는 문장은 경험 주장으로 보지 않습니다.
        # 단 critical(구체 수치+1인칭)은 프레이밍이 있어도 위험하므로 예외입니다.
        researchy = bool(RESEARCH_FRAMING.search(unit))

        for pat, label in CRITICAL_PATTERNS:
            if pat.search(unit):
                hits.append({"severity": "critical", "label": label,
                             "excerpt": unit[:160]})
                break
        else:
            if researchy:
                continue
            for pat, label in HIGH_PATTERNS:
                if pat.search(unit):
                    hits.append({"severity": "high", "label": label,
                                 "excerpt": unit[:160]})
                    break
            else:
                for pat, label in MEDIUM_PATTERNS:
                    if pat.search(unit):
                        hits.append({"severity": "medium", "label": label,
                                     "excerpt": unit[:160]})
                        break
    return hits


def _has_real_experience(keyword: str, blog_id: str) -> bool:
    """author_profile.json에 이 주제의 실제 경험 자료가 있으면 True.

    자료가 있는 주제라면 1인칭 서술이 정당하므로 감점하지 않습니다.
    content_generator._match_experience와 같은 판정을 씁니다 —
    두 곳이 다르게 판단하면 생성은 허용하고 감사는 지적하는 모순이 생깁니다.
    """
    try:
        from content_generator import _match_experience
        return _match_experience(keyword or "", blog_id or "") is not None
    except Exception:
        return False


def _worst(hits: list[dict]) -> str:
    if not hits:
        return "ok"
    return min((h["severity"] for h in hits), key=lambda s: SEVERITY_ORDER[s])


def audit_post(title: str, body_html: str, *, keyword: str = "",
               blog_id: str = "") -> dict:
    """글 한 편을 검사합니다."""
    if _has_real_experience(keyword, blog_id):
        return {"severity": "ok", "reason": "author_profile에 실제 경험 자료 있음",
                "title_hits": [], "body_hits": []}

    title_hits = analyze_text(title or "", title_mode=True)
    body_hits = analyze_text(_strip_html(body_html or ""))
    return {
        "severity": _worst(title_hits + body_hits),
        "title_hits": title_hits,
        "body_hits": body_hits[:8],          # 리포트가 비대해지지 않게 상위 8개만
        "body_hit_count": len(body_hits),
    }


# ──────────────────────────────────────────────────────────────────────────────
# 수집
# ──────────────────────────────────────────────────────────────────────────────

def _iter_posts(blog_id: str, token: str):
    """블로그의 발행(live) 글 전체를 순회합니다."""
    page_token = ""
    while True:
        params = {
            "maxResults": 100, "status": "live", "fetchBodies": "true",
            "fields": "nextPageToken,items(id,title,url,content,published)",
        }
        if page_token:
            params["pageToken"] = page_token
        r = requests.get(
            f"{BLOGGER_API_BASE}/blogs/{blog_id}/posts",
            headers={"Authorization": f"Bearer {token}"}, params=params, timeout=30,
        )
        if r.status_code != 200:
            logger.error(f"글 목록 조회 실패 [{r.status_code}]: {r.text[:200]}")
            return
        data = r.json()
        yield from data.get("items", [])
        page_token = data.get("nextPageToken", "")
        if not page_token:
            return


def _keyword_index() -> dict:
    """URL → 생성 당시 키워드. author_profile 대조에 씁니다."""
    try:
        with open(os.path.join(_DOCS_DATA, "post_registry.json"), encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    items = raw if isinstance(raw, list) else list(raw.values())
    return {i.get("blogUrl", "").rstrip("/"): i.get("keyword", "")
            for i in items if isinstance(i, dict) and i.get("blogUrl")}


def run_offline(blog_filter: str = "") -> dict:
    """제목만 검사합니다 — API 없이 즉시 규모를 봅니다."""
    path = os.path.join(_DOCS_DATA, "post_registry.json")
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.error(f"post_registry.json 읽기 실패: {e}")
        return {"items": [], "counts": {}}

    items = raw if isinstance(raw, list) else list(raw.values())
    out = []
    for i in items:
        if not isinstance(i, dict) or i.get("status") != "published":
            continue
        bid = i.get("blogId", "")
        if blog_filter and bid != blog_filter:
            continue
        res = audit_post(i.get("title", ""), "", keyword=i.get("keyword", ""), blog_id=bid)
        if res["severity"] != "ok":
            out.append({
                "title": i.get("title", "")[:90], "url": i.get("blogUrl", ""),
                "blog": i.get("blogName", ""), "blogId": bid,
                "publishedAt": (i.get("publishedAt") or "")[:10],
                **res,
            })
    return {"items": out, "counts": Counter(x["severity"] for x in out)}


def run_full(blog_filter: str = "") -> dict:
    """제목 + 본문을 Blogger API로 전수 검사합니다."""
    from blogger_uploader import _get_access_token
    from config import get_blog_configs

    kw_index = _keyword_index()
    blogs = [b for b in get_blog_configs()
             if not blog_filter or b.get("id") == blog_filter]

    out, scanned = [], 0
    for cfg in blogs:
        name, bid = cfg.get("name", ""), cfg.get("id", "")
        blog_id = cfg.get("blog_id", "")
        if not blog_id:
            logger.warning(f"[{name}] blog_id 없음 — 건너뜀")
            continue
        token = _get_access_token(cfg)
        if not token:
            logger.error(f"[{name}] 액세스 토큰 발급 실패 — 건너뜀")
            continue

        logger.info(f"── [{name}] 검사 시작 ──")
        for post in _iter_posts(blog_id, token):
            scanned += 1
            url = (post.get("url") or "").rstrip("/")
            res = audit_post(post.get("title", ""), post.get("content", ""),
                             keyword=kw_index.get(url, ""), blog_id=bid)
            if res["severity"] == "ok":
                continue
            out.append({
                "title": (post.get("title") or "")[:90], "url": post.get("url", ""),
                "blog": name, "blogId": bid,
                "publishedAt": (post.get("published") or "")[:10],
                **res,
            })
            mark = {"critical": "🔴", "high": "🟠", "medium": "🟡"}[res["severity"]]
            logger.info(f"  {mark} {(post.get('title') or '')[:52]}")
            for h in (res["title_hits"] + res["body_hits"])[:2]:
                logger.info(f"      [{h['label']}] {h['excerpt'][:80]}")

    out.sort(key=lambda x: (SEVERITY_ORDER[x["severity"]], -x.get("body_hit_count", 0)))
    return {"items": out, "counts": Counter(x["severity"] for x in out), "scanned": scanned}


def save_report(result: dict, mode: str) -> dict:
    report = {
        "auditedAt": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "scanned": result.get("scanned", 0),
        "flagged": len(result["items"]),
        "counts": dict(result["counts"]),
        "items": result["items"],
    }
    try:
        os.makedirs(_DOCS_DATA, exist_ok=True)
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info(f"리포트 저장: {REPORT_PATH}")
    except OSError as e:
        logger.warning(f"리포트 저장 실패: {e}")
    return report


def main() -> int:
    p = argparse.ArgumentParser(description="발행 글의 지어낸 1인칭 경험 주장 감사")
    p.add_argument("--offline", action="store_true",
                   help="제목만 검사 (Blogger API 불필요, 즉시)")
    p.add_argument("--blog", default="", help="특정 블로그 ID만 (blog1/blog2/blog3)")
    p.add_argument("--severity", default="",
                   choices=["", "critical", "high", "medium"],
                   help="이 심각도만 출력")
    args = p.parse_args()

    result = run_offline(args.blog) if args.offline else run_full(args.blog)
    report = save_report(result, "offline" if args.offline else "full")

    c = report["counts"]
    logger.info("=" * 62)
    logger.info(f"{'(제목만) ' if args.offline else ''}검사 {report['scanned']}편 / "
                f"문제 {report['flagged']}편")
    logger.info(f"  🔴 critical {c.get('critical', 0):>3}편  — 지어낸 구체 사실, 비공개 우선")
    logger.info(f"  🟠 high     {c.get('high', 0):>3}편  — 명시적 경험 주장, 리라이팅")
    logger.info(f"  🟡 medium   {c.get('medium', 0):>3}편  — 제목 표현만 정정")

    if args.severity:
        logger.info("-" * 62)
        for it in report["items"]:
            if it["severity"] == args.severity:
                logger.info(f"  {it['title']}")
                logger.info(f"    {it['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
