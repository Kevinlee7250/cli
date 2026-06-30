"""
내부 링크 자동 삽입 모듈

신규 포스트 생성 직후, Blogger 업로드 전에 호출합니다.
posts.json 의 기존 포스트 중 태그/키워드가 겹치는 최대 5개를 찾아
본문 HTML 에 컨텍스트 앵커 링크를 자동 삽입합니다.

사용법 (main.py 에서):
    from internal_linker import insert_internal_links
    post_data["content"] = insert_internal_links(post_data)

규칙:
  - 한 대상 포스트 당 1개 링크만 삽입 (동일 URL 중복 방지)
  - 포스트당 최대 MAX_LINKS 개 링크
  - <a>, <h1>, <h2>, HTML 태그 내부에는 삽입 안 함
  - 제목(title) 전체 또는 핵심 키워드(2~4자) 기준으로 본문 검색
  - 이미 링크된 텍스트 재링크 방지
"""

import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

POSTS_JSON = Path(__file__).parent.parent / "docs" / "data" / "posts.json"
MAX_LINKS  = 5   # 포스트당 최대 삽입 내부 링크 수
MIN_CHARS  = 2   # 링크 앵커 텍스트 최소 글자 수


# ──────────────────────────────────────────────────────────────────────────────
# 포스트 인덱스 구축
# ──────────────────────────────────────────────────────────────────────────────

def _load_posts_index() -> list[dict]:
    """posts.json 로드, blogUrl 없는 항목 제거"""
    if not POSTS_JSON.exists():
        logger.debug(f"posts.json 없음: {POSTS_JSON}")
        return []
    try:
        with open(POSTS_JSON, encoding="utf-8") as f:
            posts = json.load(f)
        return [p for p in posts if p.get("blogUrl") and p.get("title")]
    except Exception as e:
        logger.warning(f"posts.json 로드 오류: {e}")
        return []


def _extract_keywords(post: dict) -> list[str]:
    """포스트에서 매칭에 사용할 키워드 목록 추출 (태그, 키워드, 제목 핵심어)"""
    kws = set()
    # 태그
    for tag in post.get("tags", []) or []:
        tag = tag.strip()
        if len(tag) >= MIN_CHARS:
            kws.add(tag)
    # 직접 키워드
    kw = (post.get("keyword") or "").strip()
    if len(kw) >= MIN_CHARS:
        kws.add(kw)
    # 제목의 중요 단어 (2자 이상 명사형)
    title = (post.get("title") or "")
    for word in re.split(r'[\s\-—·,·()\[\]]+', title):
        word = word.strip()
        if len(word) >= 3 and not re.fullmatch(r'[\d]+', word):
            kws.add(word)
    return sorted(kws, key=len, reverse=True)  # 긴 키워드 우선 매칭


def _score_relevance(candidate: dict, current_tags: set, current_keyword: str) -> int:
    """후보 포스트와 현재 포스트의 관련도 점수 (공유 태그 수 기반)"""
    cand_tags = set(candidate.get("tags", []) or [])
    shared    = len(current_tags & cand_tags)
    # 키워드 단어 겹침 보너스
    cand_kw = (candidate.get("keyword") or "").lower()
    for word in current_keyword.lower().split():
        if len(word) >= 2 and word in cand_kw:
            shared += 1
    return shared


# ──────────────────────────────────────────────────────────────────────────────
# HTML 안전 링크 삽입
# ──────────────────────────────────────────────────────────────────────────────

def _find_safe_positions(html: str) -> list[tuple[int, int]]:
    """
    링크 삽입이 안전한 텍스트 블록(태그 내부, 기존 앵커, 제목 태그 제외) 위치 목록을 반환.
    반환: [(start, end), ...] - 삽입 가능한 텍스트 구간
    """
    safe_ranges: list[tuple[int, int]] = []
    # HTML 태그 전체 마스킹: <...>
    skip_ranges = []
    for m in re.finditer(r'<[^>]+>', html, re.DOTALL):
        skip_ranges.append((m.start(), m.end()))

    # 기존 <a ...>...</a> 블록 전체 제외
    for m in re.finditer(r'<a\b[^>]*>.*?</a>', html, re.IGNORECASE | re.DOTALL):
        skip_ranges.append((m.start(), m.end()))

    # <h1>, <h2> 블록 제외 (제목에 링크 금지)
    for m in re.finditer(r'<h[12][^>]*>.*?</h[12]>', html, re.IGNORECASE | re.DOTALL):
        skip_ranges.append((m.start(), m.end()))

    # <script>, <style> 블록 제외
    for m in re.finditer(r'<(script|style)[^>]*>.*?</\1>', html, re.IGNORECASE | re.DOTALL):
        skip_ranges.append((m.start(), m.end()))

    # skip_ranges 를 정렬 후 병합
    skip_ranges.sort()
    merged: list[tuple[int, int]] = []
    for s, e in skip_ranges:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    # 안전 구간: 태그 밖의 텍스트
    prev = 0
    for s, e in merged:
        if prev < s:
            safe_ranges.append((prev, s))
        prev = e
    if prev < len(html):
        safe_ranges.append((prev, len(html)))

    return safe_ranges


def _insert_link_in_text(
    html: str,
    keyword: str,
    target_url: str,
    target_title: str,
    used_offset: int = 0,
) -> tuple[str, bool]:
    """
    HTML 에서 keyword 의 첫 번째 안전한 등장 위치에 앵커 태그 삽입.
    반환: (수정된 html, 삽입 성공 여부)
    used_offset: 이미 삽입한 링크로 인한 오프셋 보정 (연속 삽입 시 위치 보정)
    """
    safe_ranges = _find_safe_positions(html)
    # 대소문자 구별 없이 검색 (한국어도 처리)
    pattern = re.compile(re.escape(keyword), re.IGNORECASE)

    for r_start, r_end in safe_ranges:
        text_block = html[r_start:r_end]
        m = pattern.search(text_block)
        if not m:
            continue
        # 실제 HTML 내 절대 위치
        abs_start = r_start + m.start()
        abs_end   = r_start + m.end()
        matched   = html[abs_start:abs_end]
        anchor    = (
            f'<a href="{target_url}" title="{target_title}" '
            f'style="color:#1d4ed8;text-decoration:underline;">{matched}</a>'
        )
        html = html[:abs_start] + anchor + html[abs_end:]
        logger.debug(f"  내부 링크 삽입: '{keyword}' -> {target_url}")
        return html, True

    return html, False


# ──────────────────────────────────────────────────────────────────────────────
# 메인 함수
# ──────────────────────────────────────────────────────────────────────────────

def insert_internal_links(post_data: dict) -> str:
    """
    신규 포스트 HTML 에 내부 링크를 자동 삽입합니다.

    Args:
        post_data: generate_post() 반환값 (content, tags, keyword, title 포함)

    Returns:
        내부 링크가 삽입된 HTML content 문자열
    """
    content = post_data.get("content", "")
    if not content:
        return content

    current_title   = post_data.get("title", "")
    current_keyword = (post_data.get("keyword") or "").lower()
    current_tags    = set(post_data.get("tags", []) or [])
    current_url     = post_data.get("blogUrl", "")  # 아직 업로드 전이면 비어있음

    # 기존 포스트 인덱스 로드
    all_posts = _load_posts_index()
    if not all_posts:
        logger.debug("posts.json 비어있음 — 내부 링크 삽입 건너뜀")
        return content

    # 현재 포스트 자신을 제외
    candidates = [p for p in all_posts if p.get("blogUrl") != current_url]

    # 관련도 점수 계산 → 상위 MAX_LINKS 개 선택
    scored = [
        (p, _score_relevance(p, current_tags, current_keyword))
        for p in candidates
    ]
    scored = [(p, s) for p, s in scored if s > 0]
    scored.sort(key=lambda x: x[1], reverse=True)
    top_related = scored[:MAX_LINKS]

    if not top_related:
        logger.debug(f"관련 포스트 없음 (현재 태그: {list(current_tags)[:3]})")
        return content

    logger.info(f"내부 링크 후보 {len(top_related)}개 발견")
    inserted = 0
    used_urls: set[str] = set()

    for candidate, score in top_related:
        if inserted >= MAX_LINKS:
            break

        target_url   = candidate["blogUrl"]
        target_title = candidate.get("title", "")
        if not target_url or target_url in used_urls:
            continue

        # 후보 포스트의 키워드 목록 (긴 것부터 시도)
        kws = _extract_keywords(candidate)
        link_inserted = False

        for kw in kws:
            # 현재 포스트 제목과 동일한 키워드는 삽입 안 함 (자기 참조 방지)
            if kw.lower() in current_title.lower():
                continue
            # 너무 짧은 단어는 오매칭 위험
            if len(kw) < 3:
                continue

            content, ok = _insert_link_in_text(content, kw, target_url, target_title)
            if ok:
                used_urls.add(target_url)
                inserted += 1
                link_inserted = True
                logger.info(f"  [{inserted}/{MAX_LINKS}] '{kw}' -> {target_url[:60]}")
                break

        if not link_inserted:
            logger.debug(f"  링크 삽입 실패 (매칭 키워드 없음): {target_title[:40]}")

    if inserted > 0:
        logger.info(f"내부 링크 {inserted}개 삽입 완료")
    else:
        logger.info("내부 링크 삽입 대상 텍스트 없음 (키워드 미등장)")

    return content


# ──────────────────────────────────────────────────────────────────────────────
# 테스트용 CLI
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    # 간단한 동작 확인
    sample_post = {
        "title":   "ETF 투자 초보 가이드 2026년",
        "keyword": "ETF 투자",
        "tags":    ["ETF", "주식투자", "재테크", "인덱스펀드"],
        "content": (
            "<p>ETF 투자는 개인 투자자에게 가장 효율적인 방법 중 하나입니다.</p>"
            "<h2>ETF란 무엇인가?</h2>"
            "<p>Exchange Traded Fund의 약자로, 주식처럼 거래할 수 있는 펀드입니다.</p>"
            "<p>재테크를 시작하는 직장인이라면 ETF부터 시작하는 것이 좋습니다.</p>"
        ),
    }

    posts = _load_posts_index()
    print(f"로드된 포스트: {len(posts)}개")
    if posts:
        result = insert_internal_links(sample_post)
        print("\n--- 내부 링크 삽입 결과 (처음 500자) ---")
        print(result[:500])
    else:
        print("posts.json 없음 — 실제 실행 환경에서 테스트하세요")
