"""
트렌드 키워드 수집 모듈
- Google Trends RSS (무료, 인증 불필요)
- Claude AI 키워드 생성 (Google Trends 결과 부족 시 2순위)
- Google Search Console 고성과 카테고리 우선 정렬 (GSC_SITE_URL 설정 시)
- 폴백: 고정 키워드 목록 (중복 방지 로테이션, GSC 성과 카테고리 먼저)
- 유사 키워드 필터링 (단어 겹침 비율 기반)
- 포스트 제목/키워드 이력과 비교하여 주제 중복 방지
- 30일 경과 키워드는 자동 재사용 가능
"""

import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

_USED_KW_FILE = os.path.join(os.path.dirname(__file__), "logs", "used_keywords.json")
_HISTORY_FILE = os.path.join(os.path.dirname(__file__), "logs", "run_history.json")

# 키워드 재사용 허용 기간 (일)
_REUSE_AFTER_DAYS = 30

# 유사도 판단 단어 겹침 임계값 (0~1)
_SIMILARITY_THRESHOLD = 0.55

# 폴백 키워드 — 2026년 6월 기준 트렌드 반영, 매번 다른 키워드가 선택되도록 충분히 유지
_FALLBACK_KEYWORDS_KR = [
    # 금융·투자 (2026년 트렌드)
    "2026년 ETF 투자 전략", "미국 주식 투자 방법", "금리 인하 수혜주 추천",
    "배당주 포트폴리오 구성법", "코스피 하반기 전망", "달러 환율 재테크",
    "ISA 계좌 절세 방법", "퇴직연금 DC형 운용법", "코인 비트코인 2026 전망",
    "개인연금 세액공제 방법",
    # 부동산
    "2026년 아파트 청약 전략", "전세 월세 전환 시점", "부동산 PF 위기 대응",
    "재건축 재개발 투자", "상가 임대수익률 분석", "역세권 오피스텔 투자",
    # AI·기술
    "AI 업무 자동화 방법", "챗GPT o3 활용법", "클로드 AI 사용법",
    "AI 이미지 생성 수익화", "유튜브 AI 편집 자동화", "노코드 앱 개발 입문",
    "AI 주식 투자 도구", "딥러닝 자격증 취득법",
    # 건강·의료
    "2026년 건강검진 항목 정리", "다이어트 GLP-1 주사 효과", "혈당 스파이크 예방법",
    "면역력 높이는 식단", "수면 질환 자가진단", "갱년기 증상 관리법",
    "실손보험 청구 방법", "암보험 비교 가이드",
    # 세금·법률
    "2026년 종합소득세 신고 방법", "상속세 절세 전략", "증여세 비과세 한도",
    "프리랜서 종합소득세 신고", "교통사고 합의금 산정", "이혼 재산분할 방법",
    # 부업·수익화
    "블로그 애드센스 수익화 2026", "쿠팡파트너스 부업", "스마트스토어 창업",
    "전자책 출판 수익화", "온라인 강의 만들기", "유튜브 쇼츠 수익화",
    # 여행·라이프
    "일본 여행 엔화 환율 절약법", "동남아 한 달 살기 비용", "유럽 여행 항공권 저렴하게",
    "국내 캠핑 명소 추천", "전기차 충전 요금 비교", "중고차 시세 확인법",
    # 교육·자기계발
    "2026년 인기 자격증 추천", "영어 회화 독학 방법", "공무원 시험 준비",
    "파이썬 코딩 독학", "재취업 이력서 작성법", "MBTI 직업 추천",
]

_FALLBACK_KEYWORDS_EN = [
    # Finance & Investing (2026)
    "AI stock trading strategies 2026", "dividend investing beginners", "index fund vs ETF 2026",
    "interest rate impact on stocks", "real estate market outlook 2026", "crypto regulation update",
    "passive income side hustles", "tax optimization strategies 2026", "emergency fund building",
    # AI & Tech
    "AI tools for productivity 2026", "Claude AI vs ChatGPT comparison", "best AI image generators",
    "no-code app development", "AI automation side income", "YouTube AI editing tools",
    "prompt engineering guide", "AI freelancing opportunities",
    # Health
    "GLP-1 weight loss guide", "blood sugar management tips", "sleep optimization methods",
    "mental health apps review", "anti-aging supplements 2026", "gut health diet plan",
    # Career & Money
    "remote work best practices", "freelancer tax guide 2026", "LinkedIn profile optimization",
    "online course creation guide", "dropshipping 2026 guide", "Etsy seller tips",
    # Travel & Lifestyle
    "budget travel hacks 2026", "best travel credit cards", "electric vehicle buying guide",
    "home energy saving tips", "minimalist lifestyle benefits", "subscription box reviews",
]


# ──────────────────────────────────────────────────────────────────────────────
# 사용 이력 관리
# ──────────────────────────────────────────────────────────────────────────────

def _load_used_keywords() -> dict:
    """최근 사용된 키워드 목록을 로드합니다."""
    if os.path.exists(_USED_KW_FILE):
        try:
            with open(_USED_KW_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"keywords": [], "entries": []}


def _save_used_keywords(used_data: dict) -> None:
    """사용된 키워드 목록을 저장합니다."""
    try:
        os.makedirs(os.path.dirname(_USED_KW_FILE), exist_ok=True)
        # keywords 리스트는 최근 300개만 유지
        used_data["keywords"] = used_data.get("keywords", [])[-300:]
        # entries도 최근 300개만 유지
        used_data["entries"] = used_data.get("entries", [])[-300:]
        used_data["updatedAt"] = datetime.now().isoformat()
        with open(_USED_KW_FILE, "w", encoding="utf-8") as f:
            json.dump(used_data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error(f"키워드 이력 저장 실패: {e}")


def _get_active_used_set(used_data: dict) -> set[str]:
    """
    아직 재사용 금지 기간(_REUSE_AFTER_DAYS)이 지나지 않은 키워드 집합을 반환합니다.
    entries 필드가 있으면 날짜 기반으로, 없으면 keywords 전체를 반환합니다.
    """
    entries = used_data.get("entries", [])
    if not entries:
        # 구버전 호환: entries 없으면 keywords 전체 사용
        return set(used_data.get("keywords", []))

    cutoff = datetime.now() - timedelta(days=_REUSE_AFTER_DAYS)
    active = set()
    for entry in entries:
        try:
            used_at = datetime.fromisoformat(entry["usedAt"])
            if used_at >= cutoff:
                active.add(entry["keyword"])
        except (KeyError, ValueError):
            # 날짜 파싱 불가 시 안전하게 활성으로 처리
            active.add(entry.get("keyword", ""))
    return active


# ──────────────────────────────────────────────────────────────────────────────
# 포스팅 이력 로드
# ──────────────────────────────────────────────────────────────────────────────

def _load_recent_post_corpus(limit_runs: int = 30) -> list[str]:
    """
    최근 포스팅 이력에서 키워드 + 제목 코퍼스를 수집합니다.
    유사도 비교에 사용됩니다.
    """
    if not os.path.exists(_HISTORY_FILE):
        return []
    try:
        with open(_HISTORY_FILE, encoding="utf-8") as f:
            history = json.load(f)
        corpus = []
        for run in history[:limit_runs]:
            corpus.extend(run.get("keywords", []))
            for post in run.get("posts", []):
                if post.get("keyword"):
                    corpus.append(post["keyword"])
                if post.get("title"):
                    corpus.append(post["title"])
        return corpus
    except Exception as e:
        logger.debug(f"포스팅 이력 로드 실패: {e}")
        return []


# ──────────────────────────────────────────────────────────────────────────────
# 유사도 판단
# ──────────────────────────────────────────────────────────────────────────────

def _tokenize(text: str) -> set[str]:
    """한국어/영어 단어 단위로 토크나이징합니다 (2글자 이상만)."""
    return {w for w in re.findall(r'[가-힣]{2,}|[a-zA-Z]{3,}', text.lower()) if w}


def _similarity(a: str, b: str) -> float:
    """두 문자열의 단어 겹침 비율 (Jaccard 유사도)을 반환합니다."""
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta or not tb:
        return 1.0 if a.strip() == b.strip() else 0.0
    return len(ta & tb) / len(ta | tb)


def _is_too_similar(candidate: str, corpus: list[str], threshold: float = _SIMILARITY_THRESHOLD) -> bool:
    """
    후보 키워드가 코퍼스 내 어느 항목과라도 너무 유사하면 True를 반환합니다.
    - 완전 일치
    - 한쪽이 다른 쪽을 포함
    - Jaccard 유사도 >= threshold
    """
    cand = candidate.strip().lower()
    for item in corpus:
        item = item.strip().lower()
        if not item:
            continue
        if cand == item:
            return True
        if cand in item or item in cand:
            return True
        if _similarity(cand, item) >= threshold:
            return True
    return False


# ──────────────────────────────────────────────────────────────────────────────
# 트렌드 수집 소스
# ──────────────────────────────────────────────────────────────────────────────

def _google_trends_rss(country: str = "KR", count: int = 10) -> list[str]:
    """Google Trends 일간 트렌드 RSS에서 키워드를 수집합니다."""
    url = f"https://trends.google.com/trends/trendingsearches/daily/rss?geo={country.upper()}"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=12)
        if r.status_code != 200:
            logger.debug(f"Google Trends RSS 실패: HTTP {r.status_code}")
            return []

        root = ET.fromstring(r.content)
        keywords = []
        for item in root.findall(".//item"):
            title = item.findtext("title", "").strip()
            if title:
                keywords.append(title)
            if len(keywords) >= count:
                break

        logger.info(f"Google Trends {country}: {len(keywords)}개 키워드 수집")
        return keywords
    except Exception as e:
        logger.debug(f"Google Trends RSS 오류: {e}")
        return []


def _claude_ai_keywords(language: str = "ko", count: int = 10) -> list[str]:
    """Claude API로 현재 트렌드 기반 키워드를 생성합니다 (Google Trends 결과 부족 시 2순위)."""
    try:
        import anthropic
        from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
        if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("sk-ant-xxx"):
            return []
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        now = datetime.now()
        if language == "ko":
            date_str = now.strftime("%Y년 %m월 %d일")
            prompt = (
                f"오늘 날짜: {date_str}\n\n"
                f"한국 블로그 애드센스 수익화에 적합한 검색량 높은 키워드 {count}개를 생성하세요.\n"
                "조건: 금융/재테크·AI/기술·건강·부동산·부업·세금/법률 카테고리 골고루 포함, "
                "현재 한국 트렌드 반영, 5~15자 롱테일 키워드.\n"
                f'JSON 배열만 응답 (설명 없이): ["키워드1", ..., "키워드{count}"]'
            )
        else:
            date_str = now.strftime("%B %d, %Y")
            prompt = (
                f"Today: {date_str}\n\n"
                f"Generate {count} high-CPC blog keywords for AdSense monetization.\n"
                "Categories: finance, AI/tech, health, real estate, side income, legal. "
                "Long-tail keywords, 3-8 words each, currently trending.\n"
                f'JSON array only (no explanation): ["keyword1", ..., "keyword{count}"]'
            )
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        s, e = raw.find('['), raw.rfind(']')
        if s != -1 and e > s:
            kws = json.loads(raw[s:e + 1])
            if isinstance(kws, list):
                result = [str(k).strip() for k in kws if str(k).strip()][:count]
                logger.info(f"Claude AI 키워드 생성: {len(result)}개")
                return result
    except Exception as exc:
        logger.debug(f"Claude AI 키워드 생성 실패: {exc}")
    return []


# ──────────────────────────────────────────────────────────────────────────────
# 메인 함수
# ──────────────────────────────────────────────────────────────────────────────

def _migrate_used_keywords() -> None:
    """
    구버전 used_keywords.json (keywords 리스트만 있는 형태)을
    신버전 (entries 포함) 포맷으로 자동 마이그레이션합니다.
    이미 마이그레이션됐거나 파일이 없으면 아무 작업도 하지 않습니다.
    """
    if not os.path.exists(_USED_KW_FILE):
        return
    try:
        with open(_USED_KW_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("entries") is not None:
            return  # 이미 신버전
        keywords = data.get("keywords", [])
        # 날짜 정보가 없으므로 30일 전으로 일괄 처리 (즉시 재사용 가능)
        old_date = (datetime.now() - timedelta(days=_REUSE_AFTER_DAYS + 1)).isoformat()
        data["entries"] = [{"keyword": kw, "usedAt": old_date} for kw in keywords]
        data["updatedAt"] = datetime.now().isoformat()
        with open(_USED_KW_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"used_keywords.json 마이그레이션 완료: {len(keywords)}개 키워드 (재사용 가능 상태)")
    except Exception as e:
        logger.warning(f"used_keywords.json 마이그레이션 실패 (무시): {e}")


def _sort_by_category(keywords: list[str], priority_cats: list[str]) -> list[str]:
    """GSC 고성과 카테고리 순서로 키워드 목록을 재정렬합니다."""
    # dashboard_exporter의 _categorize 함수 사용
    try:
        from dashboard_exporter import _categorize
    except ImportError:
        return keywords

    cat_order = {cat: i for i, cat in enumerate(priority_cats)}
    default_rank = len(priority_cats)

    def rank(kw: str) -> int:
        return cat_order.get(_categorize(kw), default_rank)

    return sorted(keywords, key=rank)


def get_trending_keywords(
    country: str = "KR",
    language: str = "ko",
    count: int = 5,
    naver_client_id: str = "",
    naver_client_secret: str = "",
) -> list[str]:
    """
    트렌드 키워드를 수집합니다.
    - 이미 사용된 키워드(30일 이내)는 제외
    - 포스팅 이력과 유사한 주제도 제외 (Jaccard 유사도 기반)
    - 우선순위: Google Trends RSS → Claude AI → 고정 폴백 목록
    """
    used_data = _load_used_keywords()
    active_used_set = _get_active_used_set(used_data)

    # 포스팅 이력 코퍼스 (키워드 + 제목)
    post_corpus = _load_recent_post_corpus()
    logger.info(f"포스팅 이력 코퍼스: {len(post_corpus)}개 항목 로드 (중복 방지 기준)")

    candidates: list[str] = []
    keyword_sources: dict[str, str] = {}  # 키워드별 수집 출처 추적

    # 1순위: Google Trends RSS
    trends_kws = _google_trends_rss(country, count * 4)
    for kw in trends_kws:
        keyword_sources[kw] = "google_trends"
    candidates = trends_kws

    # 2순위: Claude AI (Google Trends 결과 부족 시)
    if len(candidates) < count * 2:
        claude_kws = _claude_ai_keywords(language, count * 2)
        for kw in claude_kws:
            if kw not in keyword_sources:
                keyword_sources[kw] = "claude_ai"
        candidates += claude_kws

    # GSC 고성과 카테고리 수집 (GSC_SITE_URL 설정 시)
    gsc_high_cats: list[str] = []
    gsc_suggested: list[str] = []
    try:
        from config import GSC_SITE_URL
        if GSC_SITE_URL:
            from gsc_fetcher import get_high_performing_categories, get_gsc_suggested_keywords
            gsc_high_cats = get_high_performing_categories(GSC_SITE_URL)
            gsc_suggested = get_gsc_suggested_keywords(GSC_SITE_URL, count=count)
            # GSC 추천 키워드를 후보에 추가
            for kw in gsc_suggested:
                if kw not in keyword_sources:
                    keyword_sources[kw] = "gsc_suggested"
            candidates = gsc_suggested + candidates
    except Exception as e:
        logger.debug(f"GSC 연동 생략: {e}")

    # 3순위: 고정 폴백 (미사용 키워드 우선 + GSC 고성과 카테고리 먼저)
    fallback = _FALLBACK_KEYWORDS_KR if language == "ko" else _FALLBACK_KEYWORDS_EN
    unused_fallback = [kw for kw in fallback if kw not in active_used_set]
    if not unused_fallback:
        unused_fallback = fallback
        logger.info("폴백 키워드 전체 재사용 (30일 사이클 완료)")

    # GSC 고성과 카테고리 순서로 폴백 재정렬
    if gsc_high_cats:
        unused_fallback = _sort_by_category(unused_fallback, gsc_high_cats)
        logger.info(f"GSC 카테고리 우선 정렬 적용: {gsc_high_cats[:3]}")

    for kw in unused_fallback:
        if kw not in keyword_sources:
            keyword_sources[kw] = "fallback"
    candidates += unused_fallback

    # 중복 제거 및 유사도 필터링
    seen: set[str] = set()
    result: list[str] = []
    rejected_similar: list[str] = []
    rejected_used: list[str] = []

    # 이번 회차 선정 키워드도 코퍼스에 누적 (선정된 것끼리도 중복 방지)
    session_corpus = list(post_corpus)

    for kw in candidates:
        kw = kw.strip()
        if not kw or kw in seen:
            continue
        seen.add(kw)

        # 30일 이내 사용 키워드 제외
        if kw in active_used_set:
            rejected_used.append(kw)
            continue

        # 포스팅 이력 + 이번 회차 선정 키워드와 유사도 비교
        if _is_too_similar(kw, session_corpus):
            rejected_similar.append(kw)
            logger.debug(f"유사 주제 제외: '{kw}'")
            continue

        result.append(kw)
        session_corpus.append(kw)  # 선정된 키워드를 코퍼스에 추가

        if len(result) >= count:
            break

    if rejected_used:
        logger.info(f"최근 사용 제외 {len(rejected_used)}개: {rejected_used[:5]}")
    if rejected_similar:
        logger.info(f"유사 주제 제외 {len(rejected_similar)}개: {rejected_similar[:5]}")

    # 그래도 부족하면 유사도 기준을 낮춰서 재시도
    result_set = set(result)
    if len(result) < count:
        logger.warning(f"선정 키워드 부족 ({len(result)}/{count}) — 유사도 기준 완화하여 재시도")
        for kw in candidates:
            kw = kw.strip()
            if not kw or kw in result_set or kw in active_used_set:
                continue
            result.append(kw)
            result_set.add(kw)
            if len(result) >= count:
                break

    # 그래도 부족하면 오래된 키워드도 허용
    if len(result) < count:
        logger.warning(f"선정 키워드 여전히 부족 ({len(result)}/{count}) — 이전 사용 키워드 일부 허용")
        for kw in candidates:
            kw = kw.strip()
            if not kw or kw in result_set:
                continue
            result.append(kw)
            result_set.add(kw)
            if len(result) >= count:
                break

    # 사용 이력 업데이트
    now_iso = datetime.now().isoformat()
    existing_entries = used_data.get("entries", [])
    new_entries = [
        {"keyword": kw, "usedAt": now_iso, "source": keyword_sources.get(kw, "unknown")}
        for kw in result
    ]
    used_data["keywords"] = used_data.get("keywords", []) + result
    used_data["entries"] = existing_entries + new_entries
    _save_used_keywords(used_data)

    # 수집 출처별 요약 로그
    source_summary: dict[str, list[str]] = {}
    for kw in result:
        src = keyword_sources.get(kw, "unknown")
        source_summary.setdefault(src, []).append(kw)
    for src, kws in source_summary.items():
        logger.info(f"  [{src}] {len(kws)}개: {kws}")

    logger.info(f"최종 선정 키워드 {len(result)}개: {result}")
    return result
