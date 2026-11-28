"""발행 글의 제휴 링크가 채널 규칙을 지키는지 점검합니다 (읽기 전용).

왜 필요한가
────────────
HOGUWHAT 03 업무 매뉴얼이 정한 제휴 링크 규칙은 사람이 글마다 눈으로
확인해 왔습니다. 규칙이 늘면서(채널별 제휴 고정 #28696, 미등록 채널 쿠팡 링크
금지, 쿠팡 추천상품 운영 규칙 #31303) 놓치기 쉬워져, 공개된 글 전체를 한 번에
훑는 점검기를 둡니다. 글은 고치지 않습니다 — 어디를 어떻게 고칠지는 사람이
정합니다(fix_affiliate_disclosure.py 의 원칙과 같습니다).

규칙 (2026-11-29 기준 · 03 업무 매뉴얼)
────────────────────────────────────────
  R1 미등록 채널 쿠팡 링크 — 쿠팡파트너스에 등록되지 않은 블로그(blog2·blog3)에
     쿠팡 제휴 링크가 있으면 위반. 등록 채널은 hoguwhat.com·hoguwhat1.blogspot.com
     (= blog1)뿐입니다(03 「쿠팡파트너스 등록 채널 현황」 2026-11-27).
  R2 채널별 제휴 고정 — Blogger는 쿠팡 채널이므로 네이버 제휴 링크(크리에이터샵·
     브랜드커넥트·쇼핑커넥트·naver.me)가 있으면 위반(#28696, 한 콘텐츠 제휴처 1개).
  R3 대가성 고지 — 쿠팡 제휴 링크가 있는데 고지 문구가 없으면 위반.
  R4 금지 표현 — 쿠팡 제휴 링크가 있는 글에 '최저가·오늘만·품절임박'이 있으면
     위반(#31303 약관·품질 필수선).

결과는 docs/data/link_policy.json 에 씁니다. 위반이 있어도 종료 코드는 0입니다
(점검 결과를 남기는 것이 목적이고, 실패로 다른 단계를 막지 않습니다).
읽기 자체가 불완전하면(목록 잘림·토큰 없음) 종료 코드 1.

Usage:
  python link_policy_audit.py                 # 최신 백업 파일 기준(로컬)
  python link_policy_audit.py --source live   # 지금 공개 글(Actions)
  python link_policy_audit.py --blog blog2
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import datetime, timezone

import post_sources

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

#: 쿠팡파트너스 등록 채널(블로그 ID). 03 매뉴얼 등록 채널 현황이 원본입니다.
#: 등록을 추가하면 여기와 매뉴얼을 함께 고칩니다.
COUPANG_REGISTERED = {"blog1"}

#: 쿠팡 '제휴' 링크 — 파트너스 단축 링크·위젯. 일반 상품 주소(coupang.com/vp/...)는
#: 제휴가 아니므로 R1·R3·R4 대상이 아니고 정보로만 셉니다.
COUPANG_AFFILIATE_RE = re.compile(
    r"https?://(?:link\.coupang\.com|coupa\.ng|ads-partners\.coupang\.com)/[^\s\"'<>]*", re.I)
COUPANG_PLAIN_RE = re.compile(r"https?://(?:www\.|m\.)?coupang\.com/[^\s\"'<>]*", re.I)

#: 네이버 제휴·커머스 링크. naver.me 는 단축 주소라 무엇으로 가는지 모르지만
#: 쿠팡 채널에 둘 이유가 없어 같이 셉니다(도착지 불명은 매뉴얼상 '확인 필요').
NAVER_AFFILIATE_RE = re.compile(
    r"https?://(?:cshop\.naver\.com|brandconnect\.naver\.com|shoppingconnect\.naver\.com|"
    r"(?:[\w-]+\.)?smartstore\.naver\.com|naver\.me)/[^\s\"'<>]*", re.I)

#: 대가성 고지 — 문구가 조금 달라도(포스트/포스팅, 받습니다/받을 수) 잡습니다.
DISCLOSURE_RE = re.compile(r"쿠팡\s*파트너스[^<]{0,80}수수료", re.S)

#: 금지 표현(#31303). 띄어쓰기 차이까지 잡습니다.
BANNED_RE = re.compile(r"최저가|오늘\s*만|품절\s*임박")

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.S | re.I)


def visible_text(html: str) -> str:
    """태그·스크립트를 뺀 글 본문(금지 표현은 독자에게 보이는 글자만 봅니다)."""
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", _SCRIPT_RE.sub(" ", html or "")))


#: 금지 표현은 쿠팡 링크 주변(앞뒤 HTML 600자)에서만 봅니다. 글 전체로 보면
#: '항공권 최저가 검색법' 같은 정보성 문장까지 걸립니다(2026-10-08 백업 기준
#: 글 전체 검사 4건 중 4건이 이런 정보성 문장이었습니다).
NEAR = 600


def banned_near_links(html: str) -> list[str]:
    found: set[str] = set()
    for m in COUPANG_AFFILIATE_RE.finditer(html):
        win = visible_text(html[max(0, m.start() - NEAR):m.end() + NEAR])
        found.update(b.group(0) for b in BANNED_RE.finditer(win))
    return sorted(found)


def check_post(post: dict) -> dict | None:
    """한 글의 위반 목록. 위반이 없으면 None."""
    html = post.get("content", "") or ""
    blog = post.get("blogId", "")
    cp = sorted(set(COUPANG_AFFILIATE_RE.findall(html)))
    nv = sorted(set(NAVER_AFFILIATE_RE.findall(html)))
    issues: list[dict] = []
    if cp and blog not in COUPANG_REGISTERED:
        issues.append({"rule": "R1", "label": "미등록 채널 쿠팡 링크", "links": cp[:5]})
    if nv:
        issues.append({"rule": "R2", "label": "쿠팡 채널에 네이버 제휴 링크", "links": nv[:5]})
    if cp:
        text = visible_text(html)
        if not DISCLOSURE_RE.search(text):
            issues.append({"rule": "R3", "label": "대가성 고지 없음", "links": cp[:3]})
        banned = banned_near_links(html)
        if banned:
            issues.append({"rule": "R4", "label": "금지 표현", "words": banned})
    if not issues:
        return None
    return {"blogId": blog, "url": post.get("url", ""), "title": post.get("title", ""),
            "published": post.get("published", ""), "issues": issues}


def audit(posts: list[dict]) -> dict:
    items = [x for x in (check_post(p) for p in posts) if x]
    by_rule: dict[str, int] = {}
    for it in items:
        for i in it["issues"]:
            by_rule[i["rule"]] = by_rule.get(i["rule"], 0) + 1
    with_cp = sum(1 for p in posts if COUPANG_AFFILIATE_RE.search(p.get("content", "") or ""))
    plain_cp = sum(1 for p in posts if COUPANG_PLAIN_RE.search(p.get("content", "") or "")
                   and not COUPANG_AFFILIATE_RE.search(p.get("content", "") or ""))
    return {"scanned": len(posts), "withCoupangAffiliate": with_cp,
            "withCoupangPlainOnly": plain_cp, "violations": len(items),
            "byRule": by_rule, "items": items}


def main() -> int:
    ap = argparse.ArgumentParser(description="제휴 링크 채널 규칙 점검(읽기 전용)")
    ap.add_argument("--source", choices=["backup", "live"], default="backup")
    ap.add_argument("--backup", default=None, help="백업 파일 경로(기본: 가장 최근)")
    ap.add_argument("--blog", default="", help="특정 블로그만 (blog1/blog2/blog3)")
    ap.add_argument("--no-write", action="store_true", help="결과 파일을 쓰지 않음")
    args = ap.parse_args()

    posts, meta = post_sources.load(args.source, args.backup, [args.blog] if args.blog else None)
    result = audit(posts)
    report = {"checkedAt": datetime.now(timezone.utc).isoformat(), **meta,
              "rules": {"R1": "미등록 채널(blog2·blog3) 쿠팡 제휴 링크",
                        "R2": "Blogger(쿠팡 채널)에 네이버 제휴 링크",
                        "R3": "쿠팡 제휴 링크 있는데 대가성 고지 없음",
                        "R4": "쿠팡 제휴 글의 금지 표현(최저가·오늘만·품절임박)"},
              **result}
    logger.info(f"점검 {result['scanned']}건 · 쿠팡 제휴 링크 {result['withCoupangAffiliate']}건 · "
                f"위반 글 {result['violations']}건 {result['byRule']}")
    if meta.get("incomplete"):
        logger.error(f"끝까지 읽지 못한 블로그: {meta['incomplete']} — 전체 점검으로 보지 마세요")
    if not args.no_write:
        logger.info(f"기록: {post_sources.write_report('link_policy.json', report)}")
    return 1 if meta.get("incomplete") else 0


if __name__ == "__main__":
    sys.exit(main())
