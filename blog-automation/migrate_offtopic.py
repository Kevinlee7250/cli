"""blog1 주제 변경에 따른 구주제 글 정리 — 이전·보관

blog1(HOGU What?)이 여행·드라마·연예·K-POP 블로그로 개편되어,
예전 주제 글을 분류해 정리합니다:

  · 금융·투자·재테크 글  → blog3(금융NEWS)로 이전
                           (blog3에 동일 내용 발행 후 blog1 원본은 draft 전환)
  · 건강·생활·IT 등 기타 구주제 글 → blog1에서 draft 전환 (보관)
  · 여행·드라마·연예·K-POP 글      → 유지
  · 분류 애매한 글                 → 리포트만 (수동 판단)

post_registry도 최선껏 동기화하며, 결과는
docs/data/offtopic_migration.json에 저장됩니다.

Usage:
  python migrate_offtopic.py --dry-run   # 분류 결과만 확인 (권장 선행)
  python migrate_offtopic.py             # 실제 이전·보관 실행
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime

import requests
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"
_BASE_DIR   = os.path.dirname(__file__)
REPORT_PATH = os.path.join(_BASE_DIR, "..", "docs", "data", "offtopic_migration.json")

# ── 주제 분류 키워드 ──────────────────────────────────────────────────────────
_KEEP_KW = {  # 새 blog1 주제 — 유지
    "여행", "관광", "명소", "맛집", "숙소", "호텔", "항공", "제주", "부산", "온천",
    "휴양", "패키지", "배낭", "캠핑",
    "드라마", "영화", "넷플릭스", "티빙", "왓챠", "ott", "결말", "출연진", "배우",
    "개봉", "박스오피스",
    "아이돌", "컴백", "k-pop", "kpop", "콘서트", "팬미팅", "음반", "신곡", "걸그룹",
    "보이그룹", "티케팅", "시상식", "연예", "예능",
    # 2026-10-08: '면세점 할인 한도' 글이 review로 빠졌습니다 — 여행 글입니다.
    "면세점", "유류할증료", "항공권", "공항", "환승", "렌터카", "비자", "여권",
    "단풍", "축제", "숙박", "펜션", "리조트", "게스트하우스", "트래블",
    # 등산·둘레길도 blog1의 여행 주제입니다 ('가을 등산 코스 추천'이 review로 빠졌습니다).
    "등산", "명산", "트래킹", "둘레길", "산책로", "해수욕장", "야경", "일출",
}
_FINANCE_KW = {  # blog3로 이전
    "투자", "etf", "주식", "펀드", "재테크", "금융", "부동산", "세금", "절세",
    "연금", "적금", "대출", "금리", "환율", "청약", "배당", "코인", "월세", "전세",
    "가계부", "저축", "경제", "증시", "코스피", "소득세", "종소세", "세금신고",
    # 2026-10-08: '자동차보험 최저가 비교'와 '젠슨황 수혜주'가 review로 빠졌습니다.
    # '보험'은 여행자보험과 겹치지만 아래 유지 우선 규칙이 '여행'을 먼저 집습니다.
    "보험", "수혜주", "종목", "주가", "상장", "공모주", "증권", "코스닥",
    "신용", "카드값", "연말정산", "ira", "irp", "isa",
}
_ARCHIVE_KW = {  # 기타 구주제 — 보관
    "건강", "다이어트", "운동", "건강검진", "영양", "수면", "혈압", "면역",
    "생활", "절약", "살림", "청소", "미니멀", "정리수납",
    "ai", "챗gpt", "it", "스마트폰", "앱", "코딩",
    "자격증", "공부", "교육", "취업", "부업", "캠프", "장마",
    # 2026-10-08: 아래 세 종류가 review로 빠져 수동 판단 대기였습니다.
    # ① 건강 — '당뇨 초기 증상 자가진단'. 애드센스가 가장 엄격하게 보는
    #    분야인데 blog1에는 의료 자격 표기가 없습니다.
    "당뇨", "혈당", "증상", "자가진단", "질환", "통증", "복용", "처방", "콜레스테롤",
    # '독서'는 '구독서비스비교' 안에 들어 있어 음원 구독 비교 글을 보관으로
    # 보냈습니다. 값이 크지 않아 뺐습니다. '이사'도 같은 이유로 넣지 않습니다.
    # ② 패션 — '여름 옷 스타일·소재·코디'. '옷' 한 글자는 오탐이 생기므로 제외.
    "패션", "코디", "의류", "신발", "화장품", "스킨케어",
    # ③ 스포츠 — '월드컵 축구 가이드'. blog1 주제가 아닙니다. blog2는
    #    _KEEP_KW_BLOG2에 스포츠가 있어 유지 우선 규칙이 먼저 걸립니다.
    #    '경기'는 경기도와 겹쳐 넣지 않았습니다.
    "축구", "야구", "농구", "배구", "골프", "테니스", "월드컵", "올림픽",
    "kbo", "k리그", "epl", "mlb", "nba",
    # ④ 명절 선물·생활 대행·유학 — 여행도 연예도 아닙니다.
    #    '추석·설날·명절'은 주제가 아니라 수식어라서 넣지 않습니다 —
    #    '추석특선영화 편성표'(영화 글)가 '추석+명절' 2점에 밀려 보관으로
    #    분류됐습니다. 무엇에 관한 글인지는 옆 단어가 정합니다.
    "선물세트", "벌초", "제사", "성묘", "어학연수", "유학",
    "쇼핑", "택배", "대행",
}


# blog2(HOGU 여행,스포츠,연예) 유지 주제 — blog1 주제 + 스포츠
_KEEP_KW_BLOG2 = _KEEP_KW | {
    "스포츠", "축구", "야구", "농구", "배구", "골프", "테니스", "마라톤",
    "경기", "선수", "리그", "구단", "감독", "올림픽", "월드컵", "대회",
    "kbo", "k리그", "epl", "mlb", "nba", "직관", "중계", "이적", "우승",
}

_KEEP_KW_BY_BLOG = {
    "blog1": _KEEP_KW,
    "blog2": _KEEP_KW_BLOG2,
}


_ASCII_KW_RE = re.compile(r"^[a-z0-9][a-z0-9&.\-]*$")


def _count_hits(words: set[str], hay: str) -> int:
    """키워드 몇 개가 걸리는지. 영문 키워드는 단어 경계를 봅니다.

    2026-10-08: 짧은 영문 키워드가 다른 단어 안에서 걸리고 있었습니다 —
    'isa'가 'visa'(비자, 여행 글) 안에, 'ai'가 'mail'·'airport' 안에,
    'it'은 'title'·'with' 안에 들어 있습니다. 한글은 조사·복합어가 붙어
    그대로 부분 일치로 둬야 맞습니다.
    """
    hits = 0
    for w in words:
        if _ASCII_KW_RE.match(w):
            if re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", hay):
                hits += 1
        elif w in hay:
            hits += 1
    return hits


def classify(title: str, labels: list[str], blog_id: str = "blog1") -> str:
    """keep / migrate_blog3 / archive / review 분류.

    blog_id에 따라 '유지' 기준이 달라진다 — blog2는 스포츠도 현재 주제이므로
    blog1 기준으로 판단하면 정상 글이 보관 대상으로 잘못 분류된다.
    """
    hay = (title + " " + " ".join(labels or [])).lower()
    keep_kw = _KEEP_KW_BY_BLOG.get(blog_id, _KEEP_KW)
    keep    = _count_hits(keep_kw, hay)
    finance = _count_hits(_FINANCE_KW, hay)
    archive = _count_hits(_ARCHIVE_KW, hay)

    # 새 주제 신호가 있으면 유지 우선 (예: "여행 경비 절약"은 여행 글)
    if keep and keep >= max(finance, archive):
        return "keep"
    if finance > archive:
        return "migrate_blog3"
    if archive > 0:
        return "archive"
    if finance > 0:
        return "migrate_blog3"
    return "review"  # 신호 없음 — 수동 판단


def _revert_to_draft(api: str, blog_id: str, post_id: str, token: str) -> bool:
    r = requests.post(
        f"{api}/blogs/{blog_id}/posts/{post_id}/revert",
        headers={"Authorization": f"Bearer {token}"}, timeout=20,
    )
    if r.status_code == 200:
        return True
    logger.error(f"    draft 전환 실패 [{r.status_code}]: {r.text[:150]}")
    return False


def _create_on_blog3(api: str, blog3_id: str, post: dict, token: str) -> str:
    payload = {
        "title": post.get("title", ""),
        "content": post.get("content", ""),
        "labels": (post.get("labels") or [])[:5],
    }
    r = requests.post(
        f"{api}/blogs/{blog3_id}/posts/",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        params={"isDraft": "false"},
        json=payload, timeout=30,
    )
    if r.status_code == 200:
        return r.json().get("url", "")
    logger.error(f"    blog3 발행 실패 [{r.status_code}]: {r.text[:200]}")
    return ""


def _sync_registry(title: str, action: str, new_url: str = "", src_blog_id: str = "blog1") -> None:
    """post_registry를 최선껏 동기화 (실패해도 무시)."""
    try:
        from post_manager import load_registry, save_registry, export_for_dashboard
        registry = load_registry()
        changed = False
        for p in registry:
            if p.get("title") == title and p.get("blogId") == src_blog_id:
                if action == "migrate":
                    p["blogId"], p["blogName"] = "blog3", "금융NEWS"
                    if new_url:
                        p["blogUrl"] = new_url
                    p["migratedAt"] = datetime.now().isoformat()
                elif action == "archive":
                    p["status"] = "skipped"
                    p["errorMessage"] = f"{src_blog_id} 주제 개편 — 보관"
                changed = True
        if changed:
            save_registry(registry)
            export_for_dashboard(os.path.abspath(os.path.join(_BASE_DIR, "..", "docs", "data")))
    except Exception as e:
        logger.debug(f"레지스트리 동기화 실패 (무시): {e}")


def main() -> int:
    parser = argparse.ArgumentParser(description="구주제 글 이전·보관 (blog1/blog2)")
    parser.add_argument("--dry-run", action="store_true", help="분류만 하고 변경 없음")
    parser.add_argument("--blog", default="blog1", choices=["blog1", "blog2"],
                        help="대상 블로그 (기본: blog1)")
    args = parser.parse_args()

    from config import get_blog_configs
    from blogger_uploader import _get_access_token

    src_id = args.blog
    blogs = {b.get("id"): b for b in get_blog_configs()}
    b1, b3 = blogs.get(src_id), blogs.get("blog3")
    if not b1 or not b3:
        logger.error(f"BLOGS_CONFIG에 {src_id}/blog3이 필요합니다")
        return 1

    token1 = _get_access_token(b1)
    token3 = _get_access_token(b3)
    if not (token1 and token3):
        logger.error("Blogger 액세스 토큰 없음")
        return 1

    b1_id, b3_id = b1["blog_id"], b3["blog_id"]
    logger.info(f"══ [{b1.get('name', src_id)}] 구주제 글 정리 시작 ══")

    counts = {"keep": 0, "migrate_blog3": 0, "archive": 0, "review": 0, "failed": 0}
    actions = []

    page_token = ""
    while True:
        params = {"maxResults": 100, "status": "live", "fetchBodies": "true",
                  "fields": "nextPageToken,items(id,title,url,content,labels)"}
        if page_token:
            params["pageToken"] = page_token
        r = requests.get(f"{BLOGGER_API_BASE}/blogs/{b1_id}/posts",
                         headers={"Authorization": f"Bearer {token1}"}, params=params, timeout=30)
        if r.status_code != 200:
            logger.error(f"{src_id} 글 목록 조회 실패 [{r.status_code}]: {r.text[:200]}")
            return 1
        data = r.json()

        for post in data.get("items", []):
            title = post.get("title", "")
            cat = classify(title, post.get("labels", []), src_id)
            counts[cat] = counts.get(cat, 0) + 1
            entry = {"title": title, "url": post.get("url", ""), "action": cat}

            if cat == "keep":
                continue
            label = {"migrate_blog3": "→ blog3 이전", "archive": "보관(draft)",
                     "review": "수동 판단 필요"}[cat]
            logger.info(f"  [{label}] '{title[:50]}'")

            if cat == "review" or args.dry_run:
                actions.append(entry)
                continue

            if cat == "migrate_blog3":
                new_url = _create_on_blog3(BLOGGER_API_BASE, b3_id, post, token3)
                if new_url and _revert_to_draft(BLOGGER_API_BASE, b1_id, post["id"], token1):
                    logger.info(f"    ✅ 이전 완료: {new_url}")
                    entry["newUrl"] = new_url
                    _sync_registry(title, "migrate", new_url, src_blog_id=src_id)
                else:
                    counts["failed"] += 1
                    entry["action"] = "failed"
                time.sleep(1.5)

            elif cat == "archive":
                if _revert_to_draft(BLOGGER_API_BASE, b1_id, post["id"], token1):
                    logger.info("    ✅ 보관 완료 (draft 전환 — Blogger 관리자에서 복원 가능)")
                    _sync_registry(title, "archive", src_blog_id=src_id)
                else:
                    counts["failed"] += 1
                    entry["action"] = "failed"
                time.sleep(1)

            actions.append(entry)

        page_token = data.get("nextPageToken", "")
        if not page_token:
            break

    report = {
        "migratedAt": datetime.now().isoformat(),
        "blogId": src_id,
        "blogName": b1.get("name", src_id),
        "dryRun": args.dry_run,
        "counts": counts,
        "actions": actions,
    }
    try:
        os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info(f"리포트 저장: {REPORT_PATH}")
    except Exception as e:
        logger.warning(f"리포트 저장 실패 (무시): {e}")

    mode = "(dry-run) " if args.dry_run else ""
    logger.info("=" * 55)
    logger.info(
        f"{mode}완료 — 유지 {counts['keep']} / blog3 이전 {counts['migrate_blog3']} / "
        f"보관 {counts['archive']} / 수동판단 {counts['review']} / 실패 {counts['failed']}"
    )
    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
