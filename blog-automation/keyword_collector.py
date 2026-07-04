"""
트렌드 키워드 수집 모듈
- 네이버 실시간 뉴스 RSS + 뉴스검색 API (0순위 — 가장 최신 트렌드)
- Google Trends RSS (무료, 인증 불필요)
- Claude AI 키워드 생성 (결과 부족 시)
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
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

_USED_KW_FILE = os.path.join(os.path.dirname(__file__), "logs", "used_keywords.json")
_SCHEDULED_KW_FILE = os.path.join(os.path.dirname(__file__), "logs", "scheduled_keywords.json")
_HISTORY_FILE = os.path.join(os.path.dirname(__file__), "logs", "run_history.json")


def _get_used_kw_file(blog_id: str = "") -> str:
    """블로그별 독립 사용 키워드 파일 경로를 반환합니다."""
    if blog_id and blog_id not in ("default", "blog1"):
        return os.path.join(os.path.dirname(__file__), "logs", f"used_keywords_{blog_id}.json")
    return _USED_KW_FILE

# 키워드 재사용 허용 기간 (일)
_REUSE_AFTER_DAYS = 30

# 유사도 판단 단어 겹침 임계값 (0~1)
_SIMILARITY_THRESHOLD = 0.55

# 폴백 키워드 — 2026년 기준, 포괄적 키워드 대신 뾰족한 닌치·경험 기반 주제 중심
# E-E-A-T 전략: "직접 해본 사람 입장", "남들이 안 다루는 구체적 각도"
_FALLBACK_KEYWORDS_KR = [
    # 금융·투자 — 경험·실전 각도
    "직장인 월 30만원 ETF 투자 솔직 후기", "ISA 계좌 3년 직접 써본 결과",
    "배당주 처음 사기 전 내가 몰랐던 것", "퇴직연금 DC형 직접 운용하면서 배운 것",
    "달러 환전 타이밍 내가 틀린 적 있는 이유", "코인 투자 1년 후 솔직한 이야기",
    "종합소득세 처음 신고할 때 가장 헷갈렸던 것", "개인연금 세액공제 실수로 놓친 사람 사례",
    # 부동산 — 실제 경험 각도
    "아파트 청약 2026년 달라진 점 정리", "전세 사기 직접 겪어본 사람이 알려주는 주의사항",
    "처음 부동산 투자할 때 내가 후회한 것", "상가 투자 1년 후 임대수익 현실 공개",
    # AI·기술 — 실용 활용 각도
    "챗GPT 업무에 실제로 쓰면서 달라진 것", "AI 이미지 생성 직접 써본 무료 툴 비교",
    "노코드로 앱 만들어본 솔직 후기", "유튜브 쇼츠 AI 자동화 직접 해봤더니",
    "클로드 AI vs 챗GPT 업무 효율 비교 직접 테스트",
    # 건강 — 경험 기반 각도
    "혈당 스파이크 식단 2달 바꾸고 나서 달라진 것", "GLP-1 주사 실제 맞아본 사람 후기",
    "수면 무호흡증 검사 받아보고 알게 된 것", "면역력 영양제 직접 먹어본 솔직 리뷰",
    "건강검진 결과 보는 법 처음엔 몰랐던 항목들",
    # 세금·법률 — 실전 체험 각도
    "프리랜서 종합소득세 처음 신고하면서 실수한 것", "교통사고 합의 직접 해본 사람의 팁",
    "상속세 예상보다 많이 나온 이유", "증여세 부모님한테 돈 받을 때 주의사항",
    # 부업·수익화 — 현실적 각도
    "블로그 애드센스 승인 2026 실제로 해보니", "쿠팡파트너스 3개월 해본 솔직 수익 공개",
    "스마트스토어 첫 달 매출 0원 극복 방법", "전자책 처음 만들면서 몰랐던 것들",
    # 여행·라이프 — 체험 후기 각도
    "일본 여행 엔화 환전 직접 해본 가장 싼 방법", "동남아 한 달 살기 현실적인 비용 공개",
    "전기차 첫 구매 후 6개월 솔직 후기", "중고차 직거래 실패담과 주의사항",
    # 교육·자기계발 — 경험 기반 각도
    "자격증 독학으로 합격한 사람이 알려주는 방법", "영어 회화 6개월 독학 솔직 중간 점검",
    "파이썬 독학 3개월 후 실제 쓸 수 있는 것들", "이직 성공하고 나서 후회한 것 3가지",
]

_FALLBACK_KEYWORDS_TRAVEL_SPORTS = [
    # 국내여행 — 경험 기반
    "제주도 여행 현지인처럼 즐기는 방법 솔직 후기",
    "부산 1박2일 혼자 여행 현실 비용 공개",
    "강원도 캠핑 처음 해봤을 때 몰랐던 것들",
    "경주 당일치기 놓치면 후회하는 코스 직접 다녀와서",
    "전주 한옥마을 사람 적은 시간대와 숨은 맛집",
    "서울 근교 드라이브 코스 직접 가본 솔직 평가",
    "국내 호캉스 가성비 호텔 실제 후기 비교",
    "남해 여행 봄에 가면 좋은 이유와 준비물",
    "통영 여행 2박3일 실제 여행 경비 공개",
    "설악산 단풍 트레킹 초보자가 가도 괜찮을까",
    # 해외여행 — 실전 정보
    "일본 오사카 여행 2026 달라진 점과 환전 꿀팁",
    "베트남 다낭 4박5일 실제 비용 솔직 후기",
    "태국 방콕 처음 가는 사람이 꼭 알아야 할 것",
    "유럽 배낭여행 처음 준비하면서 실수한 것들",
    "괌 패키지 vs 자유여행 직접 비교해봤더니",
    "필리핀 세부 다이빙 입문 솔직한 경험 후기",
    "하와이 허니문 실제 비용과 아낄 수 있는 방법",
    "홍콩 싱가포르 중 여행지 선택 기준 직접 비교",
    "동유럽 여행 치안 걱정했는데 실제로 가보니",
    "모로코 여행 혼자 가도 괜찮을까 솔직 후기",
    # 스포츠 — 경기 분석·관람
    "손흥민 토트넘 2026 최신 경기 분석과 전망",
    "KBO 야구 직관 처음 가는 사람을 위한 준비물",
    "프리미어리그 중계 무료로 보는 합법적인 방법",
    "류현진 복귀 후 성적 분석 실제로 달라진 점",
    "NBA 2026 플레이오프 관전 포인트와 예상 결과",
    "국내 프로축구 K리그 직관 좌석 추천과 관람 팁",
    "테니스 입문자가 처음 라켓 살 때 알아야 할 것",
    "골프 비기너 첫 필드 나가기 전 준비 체크리스트",
    "마라톤 처음 완주한 사람이 알려주는 훈련법",
    "등산 초보가 지리산 종주 도전하면서 배운 것",
    # 스포츠 용품·건강
    "러닝화 처음 구매할 때 나이키 vs 아디다스 비교",
    "홈트레이닝 기구 6개월 써본 솔직한 후기",
    "수영 초보가 1km 완주하기까지 걸린 시간과 방법",
    "자전거 출퇴근 3개월 해본 솔직 장단점 정리",
]

_FALLBACK_KEYWORDS_EN = [
    # Finance — experience angle
    "what I learned after 1 year of dividend investing", "honest ETF investing review after 3 years",
    "mistakes I made with index funds as a beginner", "real numbers from my passive income portfolio",
    "things I wish I knew before opening an IRA", "freelancer tax mistakes I made my first year",
    # AI & Tech — practical experience
    "ChatGPT vs Claude for real work tasks honest comparison", "AI tools I actually use daily vs ones I stopped",
    "I tried 5 AI image generators here's the truth", "no-code app I built in a weekend honest review",
    # Health — personal experience
    "blood sugar changes after 2 months of diet overhaul", "GLP-1 injection honest 3-month experience",
    "sleep apnea test I finally got what I discovered", "gut health supplements I tested for 60 days",
    # Career & Money — specific experience
    "what actually changed after I switched to remote work", "I tracked my spending for 6 months here's what I found",
    "freelance rate negotiation what worked and what didn't", "side hustle income after 1 year of trying",
    # Travel & Lifestyle — honest experience
    "budget Japan trip what I spent vs what I planned", "one month in Southeast Asia real cost breakdown",
    "electric vehicle after 6 months the honest review", "minimalist experiment 30 days what I kept and ditched",
]


# ──────────────────────────────────────────────────────────────────────────────
# 사용 이력 관리
# ──────────────────────────────────────────────────────────────────────────────

def _load_used_keywords(file_path: str = _USED_KW_FILE) -> dict:
    """최근 사용된 키워드 목록을 로드합니다."""
    if os.path.exists(file_path):
        try:
            with open(file_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"keywords": [], "entries": []}


def _save_used_keywords(used_data: dict, file_path: str = _USED_KW_FILE) -> None:
    """사용된 키워드 목록을 저장합니다."""
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        # keywords 리스트는 최근 300개만 유지
        used_data["keywords"] = used_data.get("keywords", [])[-300:]
        # entries도 최근 300개만 유지
        used_data["entries"] = used_data.get("entries", [])[-300:]
        used_data["updatedAt"] = datetime.now().isoformat()
        with open(file_path, "w", encoding="utf-8") as f:
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
            kw_val = entry.get("keyword", "")
            if kw_val:
                active.add(kw_val)
    return active


# ──────────────────────────────────────────────────────────────────────────────
# 포스팅 이력 로드
# ──────────────────────────────────────────────────────────────────────────────

def _load_recent_post_corpus(limit_runs: int = 30, blog_id: str = "") -> list[str]:
    """
    최근 포스팅 이력에서 키워드 + 제목 코퍼스를 수집합니다.
    유사도 비교에 사용됩니다.
    blog_id가 주어지면 해당 블로그의 이력만 사용합니다 — 주제가 겹치는
    다른 블로그(예: blog1 재테크 ↔ blog3 금융)가 서로의 키워드를
    중복으로 차단하지 않도록 하기 위함입니다.
    과거 default로 기록된 이력은 blog1 소속으로 간주합니다.
    """
    if not os.path.exists(_HISTORY_FILE):
        return []

    def _matches(entry_blog_id: str) -> bool:
        if not blog_id:
            return True
        if entry_blog_id in ("default", ""):
            return blog_id in ("blog1", "default")
        return entry_blog_id == blog_id

    try:
        with open(_HISTORY_FILE, encoding="utf-8") as f:
            history = json.load(f)
        corpus = []
        for run in history[:limit_runs]:
            run_blog_id = run.get("blogId", "")
            if _matches(run_blog_id):
                corpus.extend(run.get("keywords", []))
            for post in run.get("posts", []):
                if not _matches(post.get("blogId", run_blog_id)):
                    continue
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

# 네이버 뉴스 카테고리 RSS 목록 (인증 불필요)
_NAVER_RSS_FEEDS = [
    ("https://www.rss.naver.com/main/rss.nhn?code=economic", "경제"),
    ("https://www.rss.naver.com/main/rss.nhn?code=social", "사회"),
    ("https://www.rss.naver.com/main/rss.nhn?code=science", "IT과학"),
    ("https://www.rss.naver.com/main/rss.nhn?code=culture", "생활문화"),
    ("https://www.rss.naver.com/main/rss.nhn?code=world", "세계"),
]

# 네이버 뉴스검색 API 보조 쿼리 (카테고리별 최신 기사 수집용)
_NAVER_API_QUERIES = ["경제 재테크", "건강 의료", "IT AI 기술", "생활 소비"]


def _naver_realtime_news(
    naver_client_id: str = "",
    naver_client_secret: str = "",
    count: int = 25,
    queries: list[str] | None = None,
) -> list[str]:
    """
    네이버 실시간 뉴스 헤드라인을 수집합니다.
    1) 네이버 뉴스 카테고리 RSS (인증 불필요)
    2) 네이버 뉴스검색 API (API 키 있을 때 추가 수집)
    queries: 블로그별 커스텀 검색 쿼리 (None이면 기본 _NAVER_API_QUERIES 사용)
    """
    headlines: list[str] = []
    api_queries = queries if queries is not None else _NAVER_API_QUERIES

    _EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

    # 1) 네이버 뉴스 카테고리 RSS — pubDate 기준 최신순 수집
    for url, name in _NAVER_RSS_FEEDS:
        try:
            r = requests.get(url, headers=_HEADERS, timeout=10)
            if r.status_code != 200:
                continue
            root = ET.fromstring(r.content)
            items_with_date: list[tuple[str, datetime]] = []
            for item in root.findall(".//item"):
                title = re.sub(r'<[^>]+>', '', item.findtext("title", "")).strip()
                if not title or len(title) < 5:
                    continue
                pub_str = item.findtext("pubDate", "").strip()
                try:
                    pub_dt = parsedate_to_datetime(pub_str)
                except Exception:
                    pub_dt = _EPOCH
                items_with_date.append((title, pub_dt))
            # 최신순 정렬 후 상위 8개
            items_with_date.sort(key=lambda x: x[1], reverse=True)
            for title, _ in items_with_date[:8]:
                headlines.append(title)
            logger.debug(f"Naver RSS [{name}]: {len(headlines)}개 누적")
        except Exception as e:
            logger.debug(f"Naver RSS [{name}] 오류: {e}")

    # 2) 네이버 뉴스검색 API (API 키 있을 때만)
    if naver_client_id and naver_client_secret:
        api_headers = {
            "X-Naver-Client-Id": naver_client_id,
            "X-Naver-Client-Secret": naver_client_secret,
        }
        for q in api_queries:
            try:
                resp = requests.get(
                    "https://openapi.naver.com/v1/search/news.json",
                    headers=api_headers,
                    params={"query": q, "display": 10, "sort": "date"},
                    timeout=10,
                )
                if resp.status_code == 200:
                    for item in resp.json().get("items", []):
                        title = re.sub(r'<[^>]+>', '', item.get("title", "")).strip()
                        if title and len(title) >= 5:
                            headlines.append(title)
            except Exception as e:
                logger.debug(f"Naver 뉴스 API [{q}] 오류: {e}")

    logger.info(f"Naver 실시간 뉴스 헤드라인 수집: {len(headlines)}개")
    return headlines[:count]


def _headlines_to_keywords(headlines: list[str], count: int = 10) -> list[str]:
    """
    뉴스 헤드라인 목록을 블로그 검색 키워드로 변환합니다.
    Claude API를 사용해 AdSense 적합 주제만 선별·다듬습니다.
    """
    if not headlines:
        return []
    try:
        import anthropic
        from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
        if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("sk-ant-xxx"):
            return []
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        now_str = datetime.now().strftime("%Y년 %m월 %d일 %H시")
        headlines_text = "\n".join(f"- {h}" for h in headlines[:25])
        prompt = (
            f"오늘({now_str}) 네이버 최신 뉴스 헤드라인을 분석해서 블로그 포스트 키워드 {count}개를 추출하세요.\n\n"
            "선별 기준:\n"
            "1. AdSense 안전 주제 — 정치·갈등·혐오·선정적 이슈 완전 제외\n"
            "2. 재테크·건강·IT·생활정보·여행·소비·부업 카테고리 우선\n"
            "3. 검색 시점 기준 최신 이슈 반영 — 지금 사람들이 실제로 찾아볼 만한 주제 우선\n"
            "   단, 오늘만 반짝하는 단순 사고·사건 속보는 제외하고 며칠간 관심이 이어질 내용 선택\n"
            "4. 경험/후기/방법/비교로 풀 수 있는 각도로 다듬을 것\n"
            "5. 헤드라인 그대로 쓰지 말고 블로그 검색 의도에 맞게 변환:\n"
            "   예) '삼성전자 2분기 실적 발표' → '삼성전자 주가 전망 2026 실적 분석'\n"
            "   예) '여름 휴가철 항공료 급등' → '여름 항공권 저렴하게 구매하는 방법'\n"
            "   예) '비트코인 신고가 경신' → '비트코인 지금 사도 될까 2026 투자 판단 기준'\n\n"
            f"헤드라인 목록:\n{headlines_text}\n\n"
            f'JSON 배열만 응답 (설명 없이): ["키워드1", ..., "키워드{count}"]'
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
                logger.info(f"Naver 뉴스 → 블로그 키워드 변환: {len(result)}개")
                return result
    except Exception as exc:
        logger.debug(f"헤드라인 → 키워드 변환 실패: {exc}")
    return []


def _naver_drama_news(
    naver_client_id: str = "",
    naver_client_secret: str = "",
) -> list[str]:
    """
    네이버 뉴스에서 현재 화제 드라마 관련 헤드라인을 수집합니다.
    RSS + 뉴스검색 API를 모두 활용합니다.
    """
    headlines: list[str] = []

    # 1) RSS에서 드라마 관련 키워드 필터링 (기존 수집 헤드라인 재활용)
    drama_rss_keywords = ["드라마", "넷플릭스", "티빙", "쿠팡플레이", "OTT", "시즌", "결말", "시청률"]
    for url, name in _NAVER_RSS_FEEDS[:3]:  # 경제·사회·IT 카테고리
        try:
            r = requests.get(url, headers=_HEADERS, timeout=10)
            if r.status_code != 200:
                continue
            root = ET.fromstring(r.content)
            for item in root.findall(".//item"):
                title = re.sub(r'<[^>]+>', '', item.findtext("title", "")).strip()
                if title and any(kw in title for kw in drama_rss_keywords):
                    headlines.append(title)
        except Exception as e:
            logger.debug(f"드라마 RSS 수집 오류 [{name}]: {e}")

    # 2) 네이버 뉴스검색 API — 드라마 전용 쿼리 (API 키 있을 때)
    if naver_client_id and naver_client_secret:
        drama_queries = ["화제 드라마 시청률", "넷플릭스 신작 드라마", "OTT 드라마 인기", "주말드라마 화제"]
        api_headers = {
            "X-Naver-Client-Id": naver_client_id,
            "X-Naver-Client-Secret": naver_client_secret,
        }
        for q in drama_queries:
            try:
                resp = requests.get(
                    "https://openapi.naver.com/v1/search/news.json",
                    headers=api_headers,
                    params={"query": q, "display": 10, "sort": "date"},
                    timeout=10,
                )
                if resp.status_code == 200:
                    for item in resp.json().get("items", []):
                        title = re.sub(r'<[^>]+>', '', item.get("title", "")).strip()
                        if title:
                            headlines.append(title)
            except Exception as e:
                logger.debug(f"드라마 뉴스 API [{q}] 오류: {e}")

    logger.info(f"드라마 뉴스 헤드라인 수집: {len(headlines)}개")
    return headlines


def extract_drama_titles(headlines: list[str]) -> list[str]:
    """
    드라마 뉴스 헤드라인에서 현재 방영 중이거나 최근 화제인 드라마 제목을 추출합니다.
    Claude API를 사용해 정확한 드라마명만 필터링합니다.
    """
    if not headlines:
        return []
    try:
        import anthropic
        from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
        if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("sk-ant-xxx"):
            return []
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        headlines_text = "\n".join(f"- {h}" for h in headlines[:25])
        prompt = (
            "다음 뉴스 헤드라인에서 현재 방영 중이거나 최근 종영한 화제 드라마 제목을 추출하세요.\n\n"
            "규칙:\n"
            "1. TV/OTT 드라마 제목만 (영화·예능·웹툰·애니메이션 제외)\n"
            "2. 정확한 공식 드라마명으로 (예: '눈물의 여왕', '지금 거신 전화는')\n"
            "3. AdSense 안전 콘텐츠에 적합한 드라마 (폭력·성인물 제외)\n"
            "4. 최대 3개, 인기순\n"
            "5. 드라마를 찾을 수 없으면 빈 배열 반환\n\n"
            f"헤드라인:\n{headlines_text}\n\n"
            'JSON 배열만 응답: ["드라마제목1", "드라마제목2"]'
        )
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        s, e = raw.find('['), raw.rfind(']')
        if s != -1 and e > s:
            titles = json.loads(raw[s:e + 1])
            if isinstance(titles, list):
                result = [str(t).strip() for t in titles if str(t).strip()]
                if result:
                    logger.info(f"화제 드라마 감지: {result}")
                return result
    except Exception as exc:
        logger.debug(f"드라마 제목 추출 실패: {exc}")
    return []


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


def _claude_ai_keywords(
    language: str = "ko",
    count: int = 10,
    topics: list[str] | None = None,
) -> list[str]:
    """Claude API로 현재 트렌드 기반 키워드를 생성합니다 (Google Trends 결과 부족 시 2순위).
    topics 목록이 있으면 해당 주제에 특화된 키워드를 생성합니다.
    """
    try:
        import anthropic
        from config import ANTHROPIC_API_KEY, CLAUDE_MODEL
        if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY.startswith("sk-ant-xxx"):
            return []
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        now = datetime.now()

        topic_hint = ""
        if topics:
            topic_hint = f"\n\n⚠️ 반드시 다음 주제 카테고리 내에서만 생성: {', '.join(topics)}"

        if language == "ko":
            date_str = now.strftime("%Y년 %m월 %d일")
            prompt = (
                f"오늘 날짜: {date_str}\n\n"
                f"구글 AdSense 승인을 목표로 하는 한국 블로그에 적합한 E-E-A-T 기반 키워드 {count}개를 생성하세요."
                f"{topic_hint}\n\n"
                "핵심 조건:\n"
                "1. '정보 나열'이 아닌 '경험과 인사이트 공유'가 가능한 주제\n"
                "2. 너무 포괄적인 주제 금지\n"
                "3. 뾰족한 닌치 각도 필수 (예: '직접 가봤더니', '솔직 후기', '처음 할 때 몰랐던 것')\n"
                "4. 검색 의도가 명확한 롱테일 키워드 (8~20자)\n"
                "5. '솔직 후기', '직접 해봤더니', '실수담', '현실 공개' 등 경험 기반 각도 포함\n\n"
                f'JSON 배열만 응답 (설명 없이): ["키워드1", ..., "키워드{count}"]'
            )
        else:
            date_str = now.strftime("%B %d, %Y")
            topic_hint_en = f"\n\n⚠️ Generate keywords ONLY within these categories: {', '.join(topics)}" if topics else ""
            prompt = (
                f"Today: {date_str}\n\n"
                f"Generate {count} E-E-A-T focused blog keywords for Google AdSense approval."
                f"{topic_hint_en}\n\n"
                "Requirements:\n"
                "1. Experience-driven topics — NOT generic information dumps\n"
                "2. No overly broad topics\n"
                "3. Niche angles: 'what I learned', 'honest review', 'mistakes beginners make'\n"
                "4. Long-tail keywords, 4-10 words each\n\n"
                f'JSON array only: ["keyword1", ..., "keyword{count}"]'
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



# ──────────────────────────────────────────────────────────────────────────────
# 시즌 예약 키워드 로드 (trend_scheduler.py가 생성한 큐)
# ──────────────────────────────────────────────────────────────────────────────

def _load_scheduled_keywords(today: datetime | None = None) -> list[str]:
    """
    logs/scheduled_keywords.json 큐에서 오늘 포스팅을 시작할 시즌 예약 키워드를 로드합니다.
    - scheduledFor <= 오늘 이면서 consumed=False 인 항목만 반환
    - 우선순위(priority) → trendScore 순으로 정렬
    - 소비 표시(consumed=True)는 keyword_collector가 실제 사용 후 main.py에서 처리하거나
      get_trending_keywords()가 result에 포함되면 자동 마킹
    """
    if today is None:
        today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")

    if not os.path.exists(_SCHEDULED_KW_FILE):
        return []

    try:
        with open(_SCHEDULED_KW_FILE, encoding="utf-8") as f:
            data = json.load(f)

        queue = data.get("queue", [])
        eligible = [
            item for item in queue
            if not item.get("consumed", False)
            and item.get("scheduledFor", "9999-99-99") <= today_str
        ]
        # 우선순위(낮을수록 높음) → trendScore 내림차순 정렬
        eligible.sort(key=lambda x: (x.get("priority", 9), -x.get("trendScore", 1.0)))
        result = [item["keyword"] for item in eligible]
        if result:
            logger.info(f"시즌 예약 키워드 {len(result)}개 로드: {result[:3]}{'...' if len(result)>3 else ''}")
        return result
    except Exception as exc:
        logger.debug(f"scheduled_keywords.json 로드 실패: {exc}")
        return []


def _mark_scheduled_keywords_consumed(keywords: list[str]) -> None:
    """사용된 시즌 예약 키워드를 큐에서 consumed=True로 표시합니다."""
    if not keywords or not os.path.exists(_SCHEDULED_KW_FILE):
        return
    try:
        with open(_SCHEDULED_KW_FILE, encoding="utf-8") as f:
            data = json.load(f)
        used_set = set(keywords)
        changed = False
        for item in data.get("queue", []):
            if item.get("keyword") in used_set and not item.get("consumed", False):
                item["consumed"] = True
                item["consumedAt"] = datetime.now().isoformat()
                changed = True
        if changed:
            data["updatedAt"] = datetime.now().isoformat()
            with open(_SCHEDULED_KW_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug(f"시즌 키워드 소비 표시: {list(used_set)[:3]}")
    except Exception as exc:
        logger.debug(f"시즌 키워드 consumed 표시 실패: {exc}")

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
    blog_config: dict | None = None,
) -> list[str]:
    """
    트렌드 키워드를 수집합니다.
    - 이미 사용된 키워드(30일 이내)는 제외
    - 포스팅 이력과 유사한 주제도 제외 (Jaccard 유사도 기반)
    - 우선순위: 네이버 실시간 뉴스 → Google Trends RSS → Claude AI → 고정 폴백 목록
    - blog_config: 블로그별 설정 (topics, naver_api_queries 등)
    """
    cfg = blog_config or {}
    blog_id = cfg.get("id", "")
    topics: list[str] | None = cfg.get("topics") or None
    blog_naver_queries: list[str] | None = cfg.get("naver_api_queries") or None

    used_kw_file = _get_used_kw_file(blog_id)
    used_data = _load_used_keywords(used_kw_file)
    active_used_set = _get_active_used_set(used_data)

    # 포스팅 이력 코퍼스 (키워드 + 제목) — 현재 블로그의 이력만
    post_corpus = _load_recent_post_corpus(blog_id=blog_id)
    logger.info(f"포스팅 이력 코퍼스: {len(post_corpus)}개 항목 로드 (blog_id={blog_id or '전체'} 중복 방지 기준)")

    candidates: list[str] = []
    keyword_sources: dict[str, str] = {}  # 키워드별 수집 출처 추적

    # -1순위: 시즌 예약 키워드 (trend_scheduler.py가 2주 전 생성한 큐)
    season_kws = _load_scheduled_keywords()
    for kw in season_kws:
        keyword_sources[kw] = "season_scheduled"
    candidates = season_kws[:]  # 최상단에 배치

    # 0순위: 네이버 실시간 뉴스 (한국어 블로그일 때만)
    if language == "ko":
        naver_headlines = _naver_realtime_news(
            naver_client_id, naver_client_secret, queries=blog_naver_queries
        )
        naver_kws = _headlines_to_keywords(naver_headlines, count * 2)
        for kw in naver_kws:
            keyword_sources[kw] = "naver_realtime"
        candidates = naver_kws
        logger.info(f"네이버 실시간 뉴스 키워드: {len(naver_kws)}개")

    # 1순위: Google Trends RSS
    trends_kws = _google_trends_rss(country, count * 4)
    for kw in trends_kws:
        if kw not in keyword_sources:
            keyword_sources[kw] = "google_trends"
    candidates = candidates + [kw for kw in trends_kws if kw not in keyword_sources or keyword_sources[kw] != "naver_realtime"]

    # 2순위: Claude AI (결과 부족 시)
    if len(candidates) < count * 2:
        claude_kws = _claude_ai_keywords(language, count * 2, topics=topics)
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
    _TRAVEL_SPORTS_TOPICS = {"여행", "스포츠", "travel", "sports"}
    is_travel_sports = bool(topics and _TRAVEL_SPORTS_TOPICS.intersection(set(t.lower() for t in topics)))
    if is_travel_sports:
        fallback = _FALLBACK_KEYWORDS_TRAVEL_SPORTS
    elif language == "ko":
        fallback = _FALLBACK_KEYWORDS_KR
    else:
        fallback = _FALLBACK_KEYWORDS_EN
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

    # 시즌 예약 키워드 consumed 마킹 (result에 포함된 것만)
    season_used = [kw for kw in result if keyword_sources.get(kw) == "season_scheduled"]
    if season_used:
        _mark_scheduled_keywords_consumed(season_used)

    # 사용 이력 업데이트
    now_iso = datetime.now().isoformat()
    existing_entries = used_data.get("entries", [])
    new_entries = [
        {"keyword": kw, "usedAt": now_iso, "source": keyword_sources.get(kw, "unknown")}
        for kw in result
    ]
    used_data["keywords"] = used_data.get("keywords", []) + result
    used_data["entries"] = existing_entries + new_entries
    _save_used_keywords(used_data, used_kw_file)

    # 수집 출처별 요약 로그
    source_summary: dict[str, list[str]] = {}
    for kw in result:
        src = keyword_sources.get(kw, "unknown")
        source_summary.setdefault(src, []).append(kw)
    for src, kws in source_summary.items():
        logger.info(f"  [{src}] {len(kws)}개: {kws}")

    logger.info(f"최종 선정 키워드 {len(result)}개: {result}")
    return result
