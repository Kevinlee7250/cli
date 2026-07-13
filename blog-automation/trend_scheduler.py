"""
시즌 트렌드 자동 반영 스케줄러 (Feature C)
=========================================
한국 연간 계절 이벤트 캘린더를 기반으로 2주 전부터 관련 포스트를 자동 예약합니다.

동작 흐름:
  1. 오늘 기준 ±lead_days 이내 다가오는 시즌 이벤트 탐지
  2. 각 이벤트의 기본 키워드를 Claude Haiku로 SEO 최적화 확장 (3~5개)
  3. Naver DataLab API로 검색량 추이 검증 (상승세 우선 정렬)
  4. pytrends (Google Trends)로 교차 확인 (선택적)
  5. logs/scheduled_keywords.json 큐에 저장
  6. keyword_collector.py가 이 큐를 -1순위로 소비

CLI 사용법:
  python trend_scheduler.py              # 실행 + 큐 업데이트
  python trend_scheduler.py --preview    # 예약 키워드 미리보기만 (쓰기 없음)
  python trend_scheduler.py --days 21    # 탐지 윈도우 21일로 확장
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Optional

import requests
from config import claude_text

# ──────────────────────────────────────────────────────────────────────────────
# 로거 설정
# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# 파일 경로
# ──────────────────────────────────────────────────────────────────────────────
_DIR = os.path.dirname(__file__)
_SCHEDULED_KW_FILE = os.path.join(_DIR, "logs", "scheduled_keywords.json")
_USED_KW_FILE = os.path.join(_DIR, "logs", "used_keywords.json")

# category → blog_id 매핑
# travel/drama/kpop/entertainment → blog1 (HOGU What? — 여행·드라마·연예·K-POP)
# sports → blog2 (HOGU 여행,스포츠,연예)
# finance → blog3 (금융NEWS)
# life/health/general → "" (모든 블로그 공용)
_CATEGORY_BLOG_MAP: dict[str, str] = {
    "travel":        "blog1",
    "drama":         "blog1",
    "kpop":          "blog1",
    "entertainment": "blog1",
    "sports":        "blog2",
    "finance":       "blog3",
    "life":          "",
    "health":        "",
}

# ──────────────────────────────────────────────────────────────────────────────
# 한국 연간 시즌 이벤트 캘린더
# - month / day: 이벤트 기준일 (음력 이벤트는 평균 양력 날짜 사용)
# - lead_days: 며칠 전부터 포스트 예약 시작
# - base_keywords: Claude 확장의 씨앗 키워드
# - category: 주제 분류 (finance / travel / life / health / drama / kpop)
# ──────────────────────────────────────────────────────────────────────────────
SEASONAL_EVENTS = [
    # ── 1월 ──────────────────────────────────────────────────────────────────
    {
        "month": 1, "day": 1, "name": "새해/신년",
        "lead_days": 14,
        "base_keywords": ["새해 목표", "신년 재테크 계획", "새해 건강 관리", "연간 예산 짜는 법"],
        "category": "life",
    },
    {
        "month": 1, "day": 20, "name": "설날연휴",  # 음력 1.1 ≈ 양력 1월 하순
        "lead_days": 21,
        "base_keywords": ["설 연휴 여행지", "설날 차례상 준비", "설 세뱃돈 재테크", "설날 선물 추천"],
        "category": "life",
    },
    # ── 2월 ──────────────────────────────────────────────────────────────────
    {
        "month": 2, "day": 14, "name": "발렌타인데이",
        "lead_days": 14,
        "base_keywords": ["발렌타인 선물", "초콜릿 만들기", "발렌타인 데이트 코스"],
        "category": "life",
    },
    {
        "month": 2, "day": 20, "name": "봄학기준비",
        "lead_days": 14,
        "base_keywords": ["신학기 준비물", "3월 입학 준비", "봄 방학 여행지"],
        "category": "life",
    },
    # ── 3월 ──────────────────────────────────────────────────────────────────
    {
        "month": 3, "day": 1, "name": "삼일절연휴",
        "lead_days": 10,
        "base_keywords": ["3월 국내여행", "봄 드라이브 코스", "봄 여행 준비"],
        "category": "travel",
    },
    {
        "month": 3, "day": 15, "name": "봄벚꽃예고",
        "lead_days": 21,
        "base_keywords": ["벚꽃 명소 추천", "서울 벚꽃 개화 시기", "벚꽃 드라이브 코스", "봄꽃 여행"],
        "category": "travel",
    },
    # ── 4월 ──────────────────────────────────────────────────────────────────
    {
        "month": 4, "day": 5, "name": "벚꽃절정",
        "lead_days": 14,
        "base_keywords": ["벚꽃 명소", "봄 나들이 코스", "4월 여행지", "봄 피크닉 준비"],
        "category": "travel",
    },
    {
        "month": 4, "day": 15, "name": "봄소풍시즌",
        "lead_days": 7,
        "base_keywords": ["봄 도시락 레시피", "가족 봄나들이", "4월 국내 여행"],
        "category": "life",
    },
    # ── 5월 ──────────────────────────────────────────────────────────────────
    {
        "month": 5, "day": 5, "name": "어린이날",
        "lead_days": 14,
        "base_keywords": ["어린이날 선물 추천", "어린이날 행사", "가족 나들이 장소", "어린이날 쿠폰"],
        "category": "life",
    },
    {
        "month": 5, "day": 8, "name": "어버이날",
        "lead_days": 14,
        "base_keywords": ["어버이날 선물 추천", "부모님 선물", "어버이날 맛집", "카네이션 선물"],
        "category": "life",
    },
    {
        "month": 5, "day": 15, "name": "스승의날",
        "lead_days": 7,
        "base_keywords": ["스승의날 선물", "선생님 선물 추천", "감사 선물"],
        "category": "life",
    },
    {
        "month": 5, "day": 25, "name": "연휴황금연휴",
        "lead_days": 14,
        "base_keywords": ["5월 황금연휴 여행", "국내 5월 여행지 추천", "5월 여행 코스"],
        "category": "travel",
    },
    # ── 6월 ──────────────────────────────────────────────────────────────────
    {
        "month": 6, "day": 1, "name": "여름준비",
        "lead_days": 14,
        "base_keywords": ["여름 다이어트 방법", "여름 피부 관리", "여름 냉방병 예방", "여름 옷 추천"],
        "category": "health",
    },
    {
        "month": 6, "day": 6, "name": "현충일연휴",
        "lead_days": 10,
        "base_keywords": ["현충일 연휴 여행", "6월 국내여행", "당일치기 여행"],
        "category": "travel",
    },
    # ── 7월 ──────────────────────────────────────────────────────────────────
    {
        "month": 7, "day": 1, "name": "여름휴가예약",
        "lead_days": 30,
        "base_keywords": ["여름 휴가지 추천", "국내 여름 여행지", "여름 해외여행 추천", "휴가 항공권 저렴하게"],
        "category": "travel",
    },
    {
        "month": 7, "day": 20, "name": "장마/폭염대비",
        "lead_days": 14,
        "base_keywords": ["장마 건강 관리", "폭염 대비 방법", "에어컨 전기세 절약", "여름 냉방 꿀팁"],
        "category": "life",
    },
    # ── 8월 ──────────────────────────────────────────────────────────────────
    {
        "month": 8, "day": 1, "name": "여름방학성수기",
        "lead_days": 21,
        "base_keywords": ["여름방학 자녀 교육", "여름 캠프 추천", "방학 동안 할 일", "여름 독서 추천"],
        "category": "life",
    },
    {
        "month": 8, "day": 15, "name": "광복절연휴",
        "lead_days": 7,
        "base_keywords": ["8월 여행지 추천", "광복절 연휴 국내여행", "여름 끝 여행"],
        "category": "travel",
    },
    # ── 9월 ──────────────────────────────────────────────────────────────────
    {
        "month": 9, "day": 1, "name": "추석준비",  # 음력 8.15 ≈ 양력 9월 초
        "lead_days": 21,
        "base_keywords": ["추석 선물 추천", "추석 차례상 준비", "추석 연휴 여행지", "명절 선물 세트"],
        "category": "life",
    },
    {
        "month": 9, "day": 20, "name": "가을시즌",
        "lead_days": 14,
        "base_keywords": ["가을 여행지 추천", "가을 드라이브 코스", "9월 국내여행", "가을 등산 코스"],
        "category": "travel",
    },
    # ── 10월 ─────────────────────────────────────────────────────────────────
    {
        "month": 10, "day": 10, "name": "단풍시즌",
        "lead_days": 14,
        "base_keywords": ["단풍 명소 추천", "10월 단풍 여행", "가을 단풍 드라이브", "단풍 트레킹"],
        "category": "travel",
    },
    {
        "month": 10, "day": 31, "name": "할로윈",
        "lead_days": 14,
        "base_keywords": ["할로윈 파티 준비", "할로윈 코스튬 추천", "할로윈 소품"],
        "category": "life",
    },
    # ── 11월 ─────────────────────────────────────────────────────────────────
    {
        "month": 11, "day": 11, "name": "빼빼로데이",
        "lead_days": 7,
        "base_keywords": ["빼빼로데이 선물", "11월 선물 추천", "과자 선물 세트"],
        "category": "life",
    },
    {
        "month": 11, "day": 14, "name": "수능",
        "lead_days": 21,
        "base_keywords": ["수능 후 여행지", "수능 이후 할 일", "재수 결정하는 방법", "수능 끝나고 준비"],
        "category": "life",
    },
    # ── 12월 ─────────────────────────────────────────────────────────────────
    {
        "month": 12, "day": 1, "name": "연말정산시즌",
        "lead_days": 30,
        "base_keywords": [
            "연말정산 소득공제", "연말정산 환급 늘리는 법", "연말정산 준비 서류",
            "연금저축 세액공제", "연말정산 IRP 공제",
        ],
        "category": "finance",
    },
    {
        "month": 12, "day": 25, "name": "크리스마스",
        "lead_days": 14,
        "base_keywords": ["크리스마스 선물 추천", "크리스마스 데이트 코스", "크리스마스 맛집", "크리스마스 이벤트"],
        "category": "life",
    },
    {
        "month": 12, "day": 31, "name": "연말마무리",
        "lead_days": 10,
        "base_keywords": ["연말 모임 장소", "한 해 마무리 여행", "연말 결산 재테크", "새해맞이 명소"],
        "category": "life",
    },
    # ── 드라마·영화 시즌 (blog1) ────────────────────────────────────────────────
    {
        "month": 1, "day": 10, "name": "겨울드라마시즌",
        "lead_days": 7,
        "base_keywords": ["1월 신작 드라마 추천", "겨울 드라마 순위", "OTT 신작 드라마 리뷰"],
        "category": "drama",
    },
    {
        "month": 4, "day": 1, "name": "봄드라마시즌",
        "lead_days": 7,
        "base_keywords": ["4월 신작 드라마 추천", "봄 드라마 시청률 순위", "넷플릭스 4월 신작"],
        "category": "drama",
    },
    {
        "month": 7, "day": 1, "name": "여름드라마시즌",
        "lead_days": 7,
        "base_keywords": ["7월 신작 드라마 추천", "여름 드라마 순위", "OTT 여름 신작 리뷰"],
        "category": "drama",
    },
    {
        "month": 9, "day": 15, "name": "추석특선영화",
        "lead_days": 7,
        "base_keywords": ["추석 특선 영화 추천", "명절 TV 영화 편성표", "추석 연휴 볼만한 영화"],
        "category": "drama",
    },
    {
        "month": 10, "day": 1, "name": "가을드라마시즌",
        "lead_days": 7,
        "base_keywords": ["10월 신작 드라마 추천", "가을 드라마 시청률", "OTT 10월 신작"],
        "category": "drama",
    },
    {
        "month": 12, "day": 15, "name": "연말영화시즌",
        "lead_days": 14,
        "base_keywords": ["연말 개봉 영화 추천", "12월 극장 영화 순위", "겨울 방학 볼 만한 영화"],
        "category": "drama",
    },
    # ── K-POP·연예 시즌 (blog1) ─────────────────────────────────────────────────
    {
        "month": 1, "day": 15, "name": "신년아이돌컴백",
        "lead_days": 10,
        "base_keywords": ["1월 아이돌 컴백 일정", "신년 K-POP 신보 추천", "1월 음반 발매 예정"],
        "category": "kpop",
    },
    {
        "month": 3, "day": 1, "name": "봄컴백시즌",
        "lead_days": 14,
        "base_keywords": ["봄 K-POP 컴백 일정", "3월 아이돌 신보", "봄 음악 차트 예상"],
        "category": "kpop",
    },
    {
        "month": 5, "day": 1, "name": "황금연휴콘서트",
        "lead_days": 21,
        "base_keywords": ["5월 콘서트 일정", "황금연휴 공연 추천", "K-POP 콘서트 티케팅 팁"],
        "category": "kpop",
    },
    {
        "month": 7, "day": 1, "name": "여름컴백시즌",
        "lead_days": 14,
        "base_keywords": ["여름 K-POP 컴백", "7월 아이돌 신보", "여름 음악 차트 분석"],
        "category": "kpop",
    },
    {
        "month": 9, "day": 1, "name": "가을컴백시즌",
        "lead_days": 14,
        "base_keywords": ["가을 K-POP 컴백 일정", "9월 아이돌 신보", "연말 앨범 사전 분석"],
        "category": "kpop",
    },
    {
        "month": 11, "day": 1, "name": "연말시상식시즌",
        "lead_days": 21,
        "base_keywords": ["MAMA 시상식 예상 수상자", "멜론뮤직어워드 2026", "연말 K-POP 시상식 일정"],
        "category": "kpop",
    },
]


# ──────────────────────────────────────────────────────────────────────────────
# 이벤트 탐지 — 오늘 기준 window_days 이내 이벤트 추출
# ──────────────────────────────────────────────────────────────────────────────

def get_upcoming_events(today: datetime, window_days: int = 14) -> list[dict]:
    """
    오늘 기준 앞으로 window_days일 내에 시작해야 할 이벤트를 반환합니다.
    각 이벤트는 event_date에서 lead_days를 뺀 날짜(start_date)가
    오늘 ± 1일 이내인 경우만 포함합니다.
    """
    year = today.year
    upcoming = []

    for ev in SEASONAL_EVENTS:
        for y in (year, year + 1):  # 연말 이벤트가 다음 해로 넘어갈 수 있음
            try:
                event_date = datetime(y, ev["month"], ev["day"])
            except ValueError:
                continue

            start_date = event_date - timedelta(days=ev["lead_days"])
            days_until_start = (start_date - today).days

            # 이미 지났거나 window_days보다 먼 경우 제외
            if days_until_start < -1 or days_until_start > window_days:
                continue

            upcoming.append({
                **ev,
                "event_date": event_date.strftime("%Y-%m-%d"),
                "start_date": start_date.strftime("%Y-%m-%d"),
                "days_until_start": days_until_start,
            })

    # 시작일 순 정렬
    upcoming.sort(key=lambda x: x["days_until_start"])
    logger.info(f"탐지된 시즌 이벤트 {len(upcoming)}개: {[e['name'] for e in upcoming]}")
    return upcoming


# ──────────────────────────────────────────────────────────────────────────────
# Claude Haiku — 시즌 키워드 SEO 최적화 확장
# ──────────────────────────────────────────────────────────────────────────────

def expand_keywords_with_claude(
    event: dict,
    count: int = 5,
) -> list[str]:
    """
    이벤트 기본 키워드를 Claude Haiku로 SEO 롱테일 키워드로 확장합니다.
    Claude 미설치/키 없을 시 base_keywords를 그대로 반환합니다.
    """
    base = event.get("base_keywords", [])
    try:
        import anthropic
        from config import claude_text, ANTHROPIC_API_KEY, CLAUDE_MODEL
        if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("sk-ant-xxx"):
            return base[:count]

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        today_str = datetime.now().strftime("%Y년 %m월 %d일")
        base_str = ", ".join(base)
        prompt = (
            f"오늘 날짜: {today_str}\n"
            f"이벤트: {event['name']} (이벤트일: {event['event_date']})\n"
            f"카테고리: {event['category']}\n"
            f"기본 키워드: {base_str}\n\n"
            f"위 시즌 이벤트에 맞는 AdSense 안전 블로그 포스트 SEO 키워드 {count}개를 생성하세요.\n\n"
            "조건:\n"
            "1. 기본 키워드를 참고해 검색 의도가 명확한 롱테일 키워드 (8~25자)\n"
            "2. '직접 해본 후기', '솔직 비교', '추천 방법', '저렴하게' 등 경험 기반 각도 포함\n"
            "3. {이벤트} + {연도(2026)} 조합 등 시의성 있는 표현 활용\n"
            "4. 정치·갈등·혐오 주제 완전 제외\n"
            f'5. 재테크/건강/여행/생활 카테고리: {event["category"]}\n\n'
            f'JSON 배열만 응답: ["키워드1", ..., "키워드{count}"]'
        )
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = claude_text(msg).strip()
        s, e = raw.find("["), raw.rfind("]")
        if s != -1 and e > s:
            kws = json.loads(raw[s : e + 1])
            result = [str(k).strip() for k in kws if str(k).strip()][:count]
            logger.info(f"[{event['name']}] Claude 키워드 확장: {result}")
            return result
    except Exception as exc:
        logger.debug(f"Claude 키워드 확장 실패 ({event['name']}): {exc}")

    return base[:count]


# ──────────────────────────────────────────────────────────────────────────────
# Naver DataLab — 검색량 추이 검증
# ──────────────────────────────────────────────────────────────────────────────

def validate_with_datalab(
    keywords: list[str],
    naver_client_id: str,
    naver_client_secret: str,
) -> dict[str, float]:
    """
    Naver DataLab API로 각 키워드의 검색량 추이를 확인합니다.
    최근 2주 평균 / 이전 2주 평균 비율(ratio)을 반환합니다.
    ratio > 1.0: 상승세, ratio < 1.0: 하락세
    API 실패 시 모든 키워드에 1.0 반환 (중립)
    """
    if not naver_client_id or not naver_client_secret or not keywords:
        return {kw: 1.0 for kw in keywords}

    scores: dict[str, float] = {}
    today = datetime.now()
    end_date = today.strftime("%Y-%m-%d")
    start_date = (today - timedelta(days=28)).strftime("%Y-%m-%d")

    headers = {
        "X-Naver-Client-Id": naver_client_id,
        "X-Naver-Client-Secret": naver_client_secret,
        "Content-Type": "application/json",
    }

    # DataLab API는 한 번에 최대 5개 키워드 그룹 처리
    for kw in keywords:
        try:
            payload = {
                "startDate": start_date,
                "endDate": end_date,
                "timeUnit": "week",
                "keywordGroups": [{"groupName": kw, "keywords": [kw]}],
            }
            resp = requests.post(
                "https://openapi.naver.com/v1/datalab/search",
                headers=headers,
                json=payload,
                timeout=10,
            )
            if resp.status_code != 200:
                scores[kw] = 1.0
                continue

            data = resp.json()
            results = data.get("results", [{}])[0].get("data", [])
            if len(results) >= 4:
                recent = sum(r.get("ratio", 0) for r in results[-2:]) / 2
                prev = sum(r.get("ratio", 0) for r in results[-4:-2]) / 2
                ratio = (recent / prev) if prev > 0 else 1.0
            else:
                ratio = 1.0

            scores[kw] = round(ratio, 3)
            logger.debug(f"DataLab [{kw}]: ratio={ratio:.2f}")
        except Exception as exc:
            logger.debug(f"DataLab 오류 [{kw}]: {exc}")
            scores[kw] = 1.0

    return scores


# ──────────────────────────────────────────────────────────────────────────────
# pytrends — Google Trends 교차 검증 (선택적)
# ──────────────────────────────────────────────────────────────────────────────

def validate_with_pytrends(keywords: list[str]) -> dict[str, float]:
    """
    pytrends로 Google Trends 관심도 추이를 교차 검증합니다.
    최근 1개월 평균 / 직전 1개월 평균 비율을 반환합니다.
    pytrends 미설치 시 모든 키워드에 1.0 반환 (중립)
    """
    try:
        from pytrends.request import TrendReq  # noqa: PLC0415
    except ImportError:
        logger.debug("pytrends 미설치 — Google Trends 검증 생략")
        return {kw: 1.0 for kw in keywords}

    scores: dict[str, float] = {}

    try:
        pytrends = TrendReq(hl="ko", tz=540, timeout=(5, 20), retries=1)

        # 한 번에 1개씩 처리 (rate limit 방지)
        for kw in keywords:
            try:
                pytrends.build_payload([kw], timeframe="today 3-m", geo="KR")
                df = pytrends.interest_over_time()
                if df.empty or kw not in df.columns:
                    scores[kw] = 1.0
                    continue

                series = df[kw].values
                mid = len(series) // 2
                recent_avg = series[mid:].mean()
                prev_avg = series[:mid].mean()
                ratio = float(recent_avg / prev_avg) if prev_avg > 0 else 1.0
                scores[kw] = round(ratio, 3)
                logger.debug(f"pytrends [{kw}]: ratio={ratio:.2f}")

                import time; time.sleep(1)  # rate limit 방지
            except Exception as exc:
                logger.debug(f"pytrends 오류 [{kw}]: {exc}")
                scores[kw] = 1.0
    except Exception as exc:
        logger.debug(f"pytrends 초기화 실패: {exc}")
        return {kw: 1.0 for kw in keywords}

    return scores


# ──────────────────────────────────────────────────────────────────────────────
# 예약 큐 관리 — scheduled_keywords.json
# ──────────────────────────────────────────────────────────────────────────────

def load_scheduled_queue() -> dict:
    """현재 예약 키워드 큐를 로드합니다."""
    if os.path.exists(_SCHEDULED_KW_FILE):
        try:
            with open(_SCHEDULED_KW_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"updatedAt": "", "queue": []}


def save_scheduled_queue(queue_data: dict) -> None:
    """예약 키워드 큐를 저장합니다."""
    os.makedirs(os.path.dirname(_SCHEDULED_KW_FILE), exist_ok=True)
    queue_data["updatedAt"] = datetime.now().isoformat()
    with open(_SCHEDULED_KW_FILE, "w", encoding="utf-8") as f:
        json.dump(queue_data, f, ensure_ascii=False, indent=2)
    logger.info(f"scheduled_keywords.json 저장 완료 ({len(queue_data['queue'])}개)")


def _load_used_set() -> set[str]:
    """30일 이내 사용된 키워드 집합을 반환합니다."""
    if not os.path.exists(_USED_KW_FILE):
        return set()
    try:
        with open(_USED_KW_FILE, encoding="utf-8") as f:
            data = json.load(f)
        cutoff = datetime.now() - timedelta(days=30)
        active = set()
        for entry in data.get("entries", []):
            try:
                if datetime.fromisoformat(entry["usedAt"]) >= cutoff:
                    active.add(entry["keyword"])
            except (KeyError, ValueError):
                pass
        return active
    except Exception:
        return set()


# ──────────────────────────────────────────────────────────────────────────────
# 메인 실행 함수
# ──────────────────────────────────────────────────────────────────────────────

def run_scheduler(
    window_days: int = 14,
    dry_run: bool = False,
    naver_client_id: str = "",
    naver_client_secret: str = "",
) -> list[dict]:
    """
    시즌 트렌드 스케줄러 메인 함수.
    반환값: 큐에 추가된 항목 리스트 (preview/logging용)
    """
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    # 1. 다가오는 이벤트 탐지
    upcoming = get_upcoming_events(today, window_days)
    if not upcoming:
        logger.info("향후 탐지 범위 내 시즌 이벤트 없음 — 스케줄러 종료")
        return []

    # 2. 이미 사용된 키워드 집합 로드
    used_set = _load_used_set()

    # 3. 현재 큐 로드 (중복 방지)
    current_queue = load_scheduled_queue()
    existing_kws = {item["keyword"] for item in current_queue.get("queue", [])}

    new_items: list[dict] = []
    all_new_kws: list[str] = []

    for ev in upcoming:
        # Claude로 키워드 확장
        expanded = expand_keywords_with_claude(ev, count=5)

        # 사용 이력 및 기존 큐 중복 필터
        filtered = [
            kw for kw in expanded
            if kw not in used_set and kw not in existing_kws
        ]
        if not filtered:
            logger.info(f"[{ev['name']}] 신규 키워드 없음 (전부 사용됨 또는 이미 큐에 있음)")
            continue

        all_new_kws.extend(filtered)
        for kw in filtered:
            new_items.append({
                "keyword": kw,
                "event": ev["name"],
                "event_date": ev["event_date"],
                "scheduledFor": ev["start_date"],
                "category": ev["category"],
                "blog_id": _CATEGORY_BLOG_MAP.get(ev["category"], ""),
                "priority": 1 if ev["days_until_start"] <= 3 else 2,
                "datalabRatio": 1.0,   # 아래에서 업데이트
                "pytrendsRatio": 1.0,  # 아래에서 업데이트
                "addedAt": datetime.now().isoformat(),
                "consumed": False,
            })

    if not all_new_kws:
        logger.info("큐에 추가할 신규 시즌 키워드 없음")
        return []

    # 4. Naver DataLab 검증 (상승세 점수 계산)
    datalab_scores = validate_with_datalab(all_new_kws, naver_client_id, naver_client_secret)

    # 5. pytrends 교차 검증
    pytrends_scores = validate_with_pytrends(all_new_kws)

    # 6. 점수 반영 + 정렬 (상승세 키워드 우선)
    for item in new_items:
        kw = item["keyword"]
        item["datalabRatio"] = datalab_scores.get(kw, 1.0)
        item["pytrendsRatio"] = pytrends_scores.get(kw, 1.0)
        # 복합 점수: DataLab 70% + pytrends 30%
        item["trendScore"] = round(
            item["datalabRatio"] * 0.7 + item["pytrendsRatio"] * 0.3, 3
        )

    new_items.sort(key=lambda x: (-x["priority"], -x["trendScore"]))

    # 7. 결과 출력
    logger.info(f"\n{'='*60}")
    logger.info(f"  시즌 트렌드 예약 키워드 — {len(new_items)}개")
    logger.info(f"{'='*60}")
    for item in new_items:
        logger.info(
            f"  [{item['event']}] {item['keyword']}"
            f" | score={item['trendScore']:.2f}"
            f" | 포스팅 시작: {item['scheduledFor']}"
        )
    logger.info(f"{'='*60}\n")

    if dry_run:
        logger.info("--preview 모드: 큐 저장 생략")
        return new_items

    # 8. 큐에 추가 저장 (소비된 항목 제거 후 병합)
    existing_items = [
        item for item in current_queue.get("queue", [])
        if not item.get("consumed", False)
    ]
    current_queue["queue"] = existing_items + new_items
    save_scheduled_queue(current_queue)

    return new_items


# ──────────────────────────────────────────────────────────────────────────────
# CLI 엔트리포인트
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="시즌 트렌드 자동 반영 스케줄러",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예:
  python trend_scheduler.py               # 실행 + 큐 업데이트
  python trend_scheduler.py --preview     # 미리보기만 (저장 없음)
  python trend_scheduler.py --days 21     # 3주 전 예약 탐지
        """,
    )
    parser.add_argument("--preview", action="store_true", help="저장 없이 예약 키워드만 출력")
    parser.add_argument("--days", type=int, default=14, help="탐지 윈도우 (일, 기본 14)")
    args = parser.parse_args()

    # 환경변수에서 Naver API 키 로드
    try:
        from config import NAVER_CLIENT_ID, NAVER_CLIENT_SECRET  # noqa: PLC0415
        naver_id = NAVER_CLIENT_ID or ""
        naver_secret = NAVER_CLIENT_SECRET or ""
    except ImportError:
        naver_id = os.getenv("NAVER_CLIENT_ID", "")
        naver_secret = os.getenv("NAVER_CLIENT_SECRET", "")

    result = run_scheduler(
        window_days=args.days,
        dry_run=args.preview,
        naver_client_id=naver_id,
        naver_client_secret=naver_secret,
    )

    if not result:
        sys.exit(0)

    print(f"\n✅ 시즌 예약 키워드 {len(result)}개 {'(미리보기)' if args.preview else '큐 저장 완료'}")
    for item in result:
        tag = "🔥" if item["trendScore"] >= 1.2 else "📅"
        print(f"  {tag} [{item['event']}] {item['keyword']}")


if __name__ == "__main__":
    main()
