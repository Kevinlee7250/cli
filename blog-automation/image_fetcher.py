"""
이미지 자동 검색 & 삽입 모듈
- DuckDuckGo 이미지 검색 (API 키 불필요)
- 네이버 이미지 검색 (NAVER_CLIENT_ID 설정 시 우선 사용)
- Wikimedia Commons (폴백)
"""

import base64
import html
import json
import os
import re
import logging
import requests
from config import claude_text

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


# ──────────────────────────────────────────────────────────────────────────────
# 이미지 검색 소스들
# ──────────────────────────────────────────────────────────────────────────────

def _ddg_images(keyword: str, count: int) -> list[dict]:
    """DuckDuckGo 이미지 검색 (API 키 불필요)."""
    try:
        # 1단계: vqd 토큰 획득 (CI 환경에서 bot-detection으로 자주 실패 → 타임아웃 단축)
        r = requests.get(
            "https://duckduckgo.com/",
            params={"q": keyword, "iax": "images", "ia": "images"},
            headers=_HEADERS,
            timeout=6,
        )
        vqd = (re.search(r'vqd="([^"]+)"', r.text) or
               re.search(r"vqd='([^']+)'", r.text) or
               re.search(r'vqd-5="([^"]+)"', r.text) or
               re.search(r"vqd-5='([^']+)'", r.text))
        if not vqd:
            return []

        # 2단계: 이미지 목록 요청
        jr = requests.get(
            "https://duckduckgo.com/i.js",
            params={"q": keyword, "o": "json", "vqd": vqd.group(1), "f": ",,,,,", "p": "1"},
            headers={**_HEADERS, "Referer": "https://duckduckgo.com/"},
            timeout=12,
        )
        images = []
        for item in jr.json().get("results", []):
            url = item.get("image", "")
            if not re.search(r"\.(jpe?g|png|webp)", url, re.I):
                continue
            if item.get("width", 0) < 400:
                continue
            images.append({
                "url": url,
                "title": item.get("title", keyword),
                "width": item.get("width", 800),
                "height": item.get("height", 450),
                "source": "ddg",
            })
            if len(images) >= count:
                break
        return images
    except Exception as e:
        logger.debug(f"DDG 이미지 검색 실패: {e}")
        return []


def _pixabay_images(keyword: str, count: int, api_key: str) -> list[dict]:
    """Pixabay 이미지 검색 API (저작권 무료, 상업적 사용 가능).
    https://pixabay.com/api/docs/
    """
    if not api_key:
        return []
    try:
        # 한국어 키워드 → 영어로 변환 (Pixabay는 영문 검색 품질이 높음)
        en_terms = re.findall(r'[A-Za-z][A-Za-z0-9]{1,}', keyword)
        if en_terms:
            query = " ".join(en_terms[:4])
        else:
            # 순수 한국어: 영어 변환 실패 시 Pixabay 건너뜀 (네이버가 한국어 담당)
            query = _ko_to_en_query(keyword)
            if not query:
                return []

        r = requests.get(
            "https://pixabay.com/api/",
            params={
                "key": api_key,
                "q": query,
                "image_type": "photo",
                "orientation": "horizontal",
                "safesearch": "true",
                "per_page": min(count * 3, 20),
                "min_width": 400,
                "lang": "en",
                "order": "popular",
            },
            headers=_HEADERS,
            timeout=12,
        )
        if r.status_code != 200:
            logger.debug(f"Pixabay API 오류: HTTP {r.status_code}")
            return []
        images = []
        for item in r.json().get("hits", []):
            # largeImageURL은 화질이 좋지만 서명·만료되는 주소입니다
            # (pixabay.com/get/<해시>_1280.jpg). 발행 글에 그대로 박아 두면
            # 얼마 뒤 400을 돌려주며 이미지가 깨집니다 — 2026-08-25 소급 작업에서
            # 35장 중 34장이 이 형태로 이미 죽어 있었습니다.
            # webformatURL(cdn.pixabay.com/photo/...)은 영구 주소입니다.
            #
            # 그래서 화질 좋은 쪽을 쓰되, 영구 주소를 stable_url로 함께 들고
            # 갑니다. 복제에 성공하면 만료는 무의미해지고, 복제가 실패하거나
            # 자체 호스팅이 꺼져 있으면 영구 주소로 갈아탑니다.
            img_url = item.get("largeImageURL") or item.get("webformatURL", "")
            if not img_url:
                continue
            stable = item.get("webformatURL", "")
            images.append({
                "url": img_url,
                "stable_url": stable if stable != img_url else "",
                "title": item.get("tags", keyword).replace(",", " /"),
                "width": item.get("imageWidth", item.get("webformatWidth", 800)),
                "height": item.get("imageHeight", item.get("webformatHeight", 450)),
                "source": "pixabay",
            })
            if len(images) >= count:
                break
        if images:
            logger.debug(f"Pixabay 이미지 {len(images)}개 수집: '{query}'")
        return images
    except Exception as e:
        logger.debug(f"Pixabay 이미지 검색 실패: {e}")
        return []


def _naver_images(keyword: str, count: int, client_id: str, client_secret: str) -> list[dict]:
    """네이버 이미지 검색 API."""
    try:
        r = requests.get(
            "https://openapi.naver.com/v1/search/image",
            params={"query": keyword, "display": count * 2, "sort": "sim", "filter": "large"},
            headers={"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret},
            timeout=10,
        )
        if r.status_code != 200:
            logger.debug(f"Naver 이미지 API 오류: HTTP {r.status_code}")
            return []
        images = []
        for item in r.json().get("items", []):
            link = item.get("link", "")
            if re.search(r"\.(jpe?g|png|webp)", link, re.I):
                try:
                    width = int(item.get("sizewidth") or 0)
                except (ValueError, TypeError):
                    width = 0
                try:
                    height = int(item.get("sizeheight") or 0)
                except (ValueError, TypeError):
                    height = 0
                images.append({
                    "url": link,
                    "title": re.sub(r"<[^>]+>", "", item.get("title", keyword)).strip(),
                    "width": width,
                    "height": height,
                    "source": "naver",
                })
            if len(images) >= count:
                break
        return images
    except Exception as e:
        logger.debug(f"Naver 이미지 검색 실패: {e}")
        return []


def _wikimedia_search_titles(keyword: str, count: int) -> list[str]:
    """Wikimedia Commons에서 파일 제목 목록을 반환합니다."""
    try:
        base = "https://commons.wikimedia.org/w/api.php"
        sr = requests.get(base, params={
            "action": "query", "list": "search", "srnamespace": 6,
            "srsearch": keyword, "srlimit": count * 3, "format": "json",
        }, headers=_HEADERS, timeout=10)
        if sr.status_code != 200:
            return []
        return [r["title"] for r in sr.json().get("query", {}).get("search", [])]
    except Exception as e:
        logger.debug(f"Wikimedia 검색 오류: {e}")
        return []


def _wikimedia_images(keyword: str, count: int) -> list[dict]:
    """Wikimedia Commons 이미지 (저작권 없는 공개 이미지). 한국어 키워드 실패 시 영어 단어로 재시도."""
    try:
        base = "https://commons.wikimedia.org/w/api.php"
        titles = _wikimedia_search_titles(keyword, count)

        # 한국어 키워드로 결과 없으면 영어 단순 변환 시도 (공백→ 언더스코어 제거 후 영단어 추출)
        if not titles:
            # 숫자/영어 단어만 추출해 영어 쿼리로 재시도
            en_keyword = " ".join(re.findall(r'[A-Za-z0-9]+', keyword))
            if en_keyword and en_keyword != keyword:
                titles = _wikimedia_search_titles(en_keyword, count)

        images = []
        for title in titles:
            ir = requests.get(base, params={
                "action": "query", "titles": title,
                "prop": "imageinfo", "iiprop": "url|size|mime", "format": "json",
            }, headers=_HEADERS, timeout=8)
            if ir.status_code != 200:
                continue
            for page in ir.json().get("query", {}).get("pages", {}).values():
                for info in page.get("imageinfo", []):
                    if info.get("mime", "").startswith("image/") and info.get("width", 0) >= 400:
                        images.append({
                            "url": info["url"],
                            "title": title.replace("File:", ""),
                            "width": info.get("width", 800),
                            "height": info.get("height", 450),
                            "source": "wikimedia",
                            "page_url": f"https://commons.wikimedia.org/wiki/{title.replace(' ', '_')}",
                        })
                        break
            if len(images) >= count:
                break
        return images
    except Exception as e:
        logger.debug(f"Wikimedia 이미지 검색 실패: {e}")
        return []


# ──────────────────────────────────────────────────────────────────────────────
# 쿼리 단순화
# ──────────────────────────────────────────────────────────────────────────────

# 체험담식 키워드의 수식어 — 이미지 검색에 방해만 되는 단어들
_QUERY_FLUFF = {
    "실수담", "솔직", "후기", "직접", "처음", "해봤더니", "해봤어요", "몰랐던",
    "알게", "공개", "현실", "진짜", "갔을", "받아보고", "써봤더니", "저지른",
    "이야기", "느낀", "겪은", "달랐던", "생각보다", "막상", "저도", "제가",
    "했을", "안", "것들", "것", "때", "저는", "완벽", "정리", "총정리",
    "실수들", "실수", "투자할", "혼자", "비슷하면", "이유", "방법", "꿀팁",
    # 간결·임팩트형 제목에서 자주 나오는 수식어·동사형
    "받는", "하는", "되는", "가장", "많이", "바로", "지금", "해보니",
    "비교해보니", "써보니", "가본", "다녀온", "추천", "기준", "이내",
    # 숫자에서 분리된 단위어 (예: "40만원" → "만원")
    "만원", "천원", "억원", "원대", "가지", "개월", "주일", "박일",
}

# 단어 끝 조사 — 떼어내고 남은 어근이 2자 이상이면 어근을 사용 (예: "초보가" → "초보")
# 로·에 등은 명사 일부인 경우가 많아 제외 (예: "고속도로")
_TRAILING_JOSA = ("가", "은", "는", "을", "를", "의")


def _strip_josa(word: str) -> str:
    """한국어 단어 끝의 조사를 제거합니다 (어근 2자 이상 유지될 때만)."""
    for j in _TRAILING_JOSA:
        if word.endswith(j) and len(word) - len(j) >= 2:
            return word[: -len(j)]
    return word


def _core_terms(text: str, max_terms: int = 3) -> list[str]:
    """검색 쿼리에서 수식어를 제거하고 핵심 명사만 추출합니다."""
    words = re.findall(r'[A-Za-z][A-Za-z0-9&]{1,9}|[가-힣]{2,}', text)
    core = []
    for w in words:
        if re.search(r'[가-힣]', w):
            w = _strip_josa(w)
        if w in _QUERY_FLUFF or w.lower() in {c.lower() for c in core}:
            continue
        core.append(w)
        if len(core) >= max_terms:
            break
    return core


def _simplify_query(query: str, max_terms: int = 3) -> str:
    """긴 체험담식 쿼리를 이미지 검색에 적합한 핵심 명사 조합으로 줄입니다."""
    return " ".join(_core_terms(query, max_terms))


# ──────────────────────────────────────────────────────────────────────────────
# 통합 검색 & HTML 삽입
# ──────────────────────────────────────────────────────────────────────────────

def _score_title_relevance(img: dict, query: str) -> float:
    """이미지 제목·URL과 쿼리 단어의 겹침 비율 (0~1). 관련성 순위 정렬에 사용.
    한국어 쿼리는 영어 번역 단어도 포함해 영어 이미지 제목과 매칭합니다."""
    query_words = set(re.findall(r'[가-힣]{2,}|[A-Za-z]{3,}', query.lower()))
    # 한국어 쿼리인 경우 Pixabay/DDG 영어 이미지와의 관련성 채점을 위해 번역 단어 추가
    if _is_korean_query(query):
        en_q = _ko_to_en_query(query)
        query_words |= set(re.findall(r'[A-Za-z]{3,}', en_q.lower()))
    if not query_words:
        return 0.0
    haystack = (img.get("title", "") + " " + img.get("url", "")).lower()
    title_words = set(re.findall(r'[가-힣]{2,}|[A-Za-z]{3,}', haystack))
    return len(query_words & title_words) / len(query_words)


# ──────────────────────────────────────────────────────────────
# 저작권 화이트리스트 — 여기 없는 도메인의 이미지는 본문에 넣지 않습니다.
# ──────────────────────────────────────────────────────────────
# 2026-08-19 감사에서 사용 이미지 835장 중 71%가 무단 저작물로 확인됐습니다
# (imgnews.naver.net 299장, 다음·핀터레스트·나무위키·유튜브 썸네일,
#  한국경제·동아일보, 뽐뿌·보배드림·인스티즈 등).
# AdSense 정책상 저작권은 감점이 아니라 즉시 탈락 요건이고, 승인 후
# 발견되면 계정 정지 사유입니다. 그래서 "관련성 좋은 이미지"보다
# "권리가 확실한 이미지"를 우선합니다 — 못 찾으면 직접 만듭니다.
#
# ⚠️ 이 목록에 도메인을 추가할 때는 그 서비스의 라이선스가 상업적 재사용을
#    허용하는지 반드시 확인하세요. "출처를 적으면 된다"는 라이선스가 아닙니다.
_ALLOWED_IMAGE_HOSTS = (
    "pixabay.com",            # Pixabay Content License — 상업적 사용 가능
    "cdn.pixabay.com",
    "upload.wikimedia.org",   # Wikimedia Commons — CC / 퍼블릭 도메인
    "commons.wikimedia.org",
    "unsplash.com",           # Unsplash License — 상업적 사용 가능
    "images.unsplash.com",
    "source.unsplash.com",
    "i.ibb.co",               # ImgBB — 우리가 직접 업로드한 AI 이미지·썸네일
    "ibb.co",
    "kevinlee7250.github.io", # 우리 GitHub Pages — image_mirror가 올린 복제본
)

# 화이트리스트를 끄는 스위치는 두지 않습니다. 저작권은 설정으로 켜고 끌
# 성질의 것이 아니고, 급할 때 꺼두고 잊는 것이 바로 지금 상태를 만들었습니다.


def is_license_safe(url: str) -> bool:
    """이미지 URL이 저작권 안전 화이트리스트에 속하는지 판정합니다.

    data URI(직접 생성한 SVG 썸네일)는 우리가 만든 것이므로 항상 허용합니다.
    """
    u = (url or "").strip()
    if not u:
        return False
    if u.startswith("data:image/"):
        return True
    # 우리가 직접 올린 복제본. 호스트 이름이 저장소 설정에 따라 달라지므로
    # 고정 목록이 아니라 실제 공개 경로와 대조합니다 (포크·이름 변경 대응).
    try:
        from image_mirror import is_mirrored_url
        if is_mirrored_url(u):
            return True
    except ImportError:
        pass
    m = re.match(r'https?://([^/:]+)', u, re.I)
    if not m:
        return False
    host = m.group(1).lower()
    return any(host == h or host.endswith("." + h) for h in _ALLOWED_IMAGE_HOSTS)


def filter_license_safe(images: list[dict]) -> list[dict]:
    """화이트리스트 밖 이미지를 걸러내고, 걸러낸 건 로그에 남깁니다."""
    kept, dropped = [], []
    for img in images or []:
        (kept if is_license_safe(img.get("url", "")) else dropped).append(img)
    if dropped:
        hosts = {re.sub(r'^https?://([^/:]+).*', r'\1', d.get("url", ""))[:40] for d in dropped}
        logger.warning(
            f"🚫 저작권 화이트리스트 밖 이미지 {len(dropped)}장 차단: {', '.join(sorted(hosts))}"
        )
    return kept


def _search_all_sources(
    query: str,
    naver_client_id: str = "",
    naver_client_secret: str = "",
    n_candidates: int = 4,
    pixabay_api_key: str = "",
) -> list[dict]:
    """저작권 안전 소스만 순서대로 검색합니다: Pixabay → Unsplash → Wikimedia.

    네이버 이미지 검색과 DuckDuckGo는 2026-08-19에 검색 경로에서 제거했습니다.
    두 소스 모두 "웹에 있는 이미지"를 반환할 뿐 라이선스를 보장하지 않으며,
    실제로 언론사 뉴스 사진과 커뮤니티 게시물을 대량으로 끌어왔습니다.
    naver_client_id / naver_client_secret 인자는 호출부 호환을 위해 남겨두었고
    사용하지 않습니다.

    여기서 결과가 없으면 호출부가 AI 생성 이미지 → SVG 제목 썸네일 순으로
    폴백합니다(generate_fallback_image). 둘 다 우리가 만든 것이라 안전합니다.
    """
    # 1순위: Pixabay (Pixabay Content License)
    if pixabay_api_key:
        candidates = filter_license_safe(_pixabay_images(query, n_candidates, pixabay_api_key))
        if candidates:
            return candidates
    # 2순위: Wikimedia Commons (CC / 퍼블릭 도메인)
    return filter_license_safe(_wikimedia_images(query, n_candidates))


# 관련성 최소 임계값 — 이 미만이면 엉뚱한 이미지(Wikimedia 잡음 등)로 판단하고 버림
_MIN_RELEVANCE = 0.15


def _is_korean_query(text: str) -> bool:
    """쿼리 단어 중 한글 비율이 50% 이상이면 한국어 쿼리로 판정합니다."""
    words = re.findall(r'[가-힣]{2,}|[A-Za-z]{2,}', text)
    if not words:
        return False
    ko = sum(1 for w in words if re.search(r'[가-힣]', w))
    return ko / len(words) >= 0.5


# 한국어 → 영어 범용 매핑 (이미지 검색 친화적 카테고리)
#
# 2026-08-19 확장: 네이버·DDG를 검색 경로에서 제거하면서 Pixabay 적중률이
# 곧 이미지 확보율이 됐습니다. 기존 매핑은 금융·시사 어휘가 얇아
# "종부세 개편", "가계부채 2000조", "국채 금리" 같은 실제 키워드에서
# 전부 빈 문자열을 반환했고, 그래서 네이버 뉴스 사진으로 떨어졌습니다.
# 세 블로그에서 실제로 쓰인 어휘를 기준으로 보강했습니다.
_KO_EN = {
    # 건강·생활
    "건강": "health", "의료": "healthcare", "운동": "exercise", "다이어트": "diet",
    "체중": "weight loss", "수영": "swimming", "마라톤": "marathon", "헬스": "gym",
    "검진": "medical checkup", "영양": "nutrition", "수면": "sleep",
    # 금융·경제 (대폭 보강)
    "투자": "investment", "주식": "stock market", "ETF": "ETF", "금융": "finance",
    "부동산": "real estate", "경제": "economy", "재테크": "personal finance",
    "금리": "interest rate", "환율": "exchange rate", "적금": "savings account",
    "예금": "bank deposit", "은행": "bank", "채권": "bonds", "국채": "government bonds",
    "증시": "stock exchange", "코스피": "stock index", "지수": "market index",
    "배당": "dividend", "수익률": "investment return", "자산": "assets",
    "가계부채": "household debt", "부채": "debt", "신용": "credit",
    "종부세": "property tax", "소득세": "income tax", "세제": "taxation",
    "청약": "housing subscription", "분양": "apartment sales", "공급": "housing supply",
    "전세": "rental housing", "월세": "monthly rent", "임대": "lease",
    "아파트": "apartment building", "빌라": "townhouse", "주택": "house",
    "그린벨트": "green belt land", "재건축": "reconstruction",
    "비트코인": "bitcoin", "가상자산": "cryptocurrency", "코인": "cryptocurrency",
    "금": "gold bullion", "유가": "oil price", "원유": "crude oil", "달러": "us dollar",
    "반도체": "semiconductor", "물가": "inflation", "인플레이션": "inflation",
    "가계부": "household budget", "지출": "spending", "결제": "payment",
    "카드": "credit card", "포인트": "reward points",
    # 여행·숙박
    "여행": "travel", "관광": "tourism", "맛집": "restaurant", "숙소": "hotel",
    "항공권": "airplane travel", "항공": "airplane", "공항": "airport",
    "호텔": "hotel", "리조트": "resort", "펜션": "guest house",
    "해외": "overseas travel", "국내": "domestic travel", "명소": "landmark",
    "온천": "hot spring", "바다": "sea beach", "섬": "island",
    "축제": "festival", "연휴": "holiday", "추석": "harvest festival",
    # 취미·스포츠
    "캠프": "camp", "캠핑": "camping", "글램핑": "glamping", "차박": "car camping",
    "등산": "hiking", "자전거": "cycling", "골프": "golf", "라운딩": "golf course",
    "스포츠": "sports", "축구": "soccer", "야구": "baseball", "농구": "basketball",
    "테니스": "tennis", "경기": "sports stadium", "선수": "athlete",
    # 문화·연예
    "드라마": "drama", "영화": "movie", "음악": "music", "공연": "concert",
    "아이돌": "stage performance", "앨범": "music album", "배우": "theater stage",
    "리뷰": "review notebook", "후기": "review notebook",
    # 일상·계절
    "독서": "reading books", "책": "books", "교육": "education", "학습": "learning",
    "요리": "cooking", "음식": "food", "카페": "cafe", "커피": "coffee",
    "패션": "fashion", "뷰티": "beauty", "화장": "makeup", "스킨케어": "skincare",
    "육아": "parenting", "아이": "child", "가족": "family",
    "여름": "summer", "봄": "spring", "가을": "autumn", "겨울": "winter",
    "장마": "rainy season", "폭염": "heat wave", "날씨": "weather",
    "선물": "gift box", "쇼핑": "shopping",
    # 일·제도
    "취업": "job", "직장": "workplace", "창업": "startup", "부업": "side job",
    "세금": "tax", "연금": "pension", "보험": "insurance", "대출": "loan",
    "절약": "saving money", "절세": "tax saving", "공부": "studying",
    "노후": "retirement", "임신": "pregnancy", "출산": "childbirth",
    "정책": "policy", "지원": "support", "혜택": "benefit", "신청": "application",
    "이사": "moving house", "제도": "government policy", "개편": "policy reform",
    "전망": "business forecast", "분석": "data analysis", "비교": "comparison chart",
    "전략": "strategy planning", "계획": "planning", "체크리스트": "checklist",
    # 기술
    "AI": "artificial intelligence", "기술": "technology", "스마트폰": "smartphone",
    "방학": "school vacation", "대비": "preparation", "관리": "management",
}

# 긴 표제어부터 검사해야 "가계부채"가 "가계부"로 잘못 매칭되지 않습니다.
_KO_EN_KEYS = sorted(_KO_EN, key=len, reverse=True)


def _ko_en_lookup(word: str) -> str:
    """한 단어를 영어로 변환합니다. 정확히 일치하지 않으면 부분 일치를 시도합니다.

    한국어는 조사·접미사가 붙어 "절세법", "1주택자", "금리는"처럼 변형되므로
    정확 일치만으로는 대부분 놓칩니다. 표제어가 단어 안에 포함돼 있으면
    같은 뜻으로 봅니다 — 이미지 검색어 생성이라 이 정도 근사면 충분합니다.
    """
    if word in _KO_EN:
        return _KO_EN[word]
    for key in _KO_EN_KEYS:
        if len(key) >= 2 and key in word:
            return _KO_EN[key]
    return ""


def _ko_to_en_query(query: str) -> str:
    """한국어 핵심 명사를 기반으로 Pixabay용 영어 쿼리를 생성합니다.

    매핑되는 단어가 없으면 빈 문자열을 반환합니다 — 범용어("lifestyle blog" 등)로
    검색하면 주제와 무관한 동일 인기 이미지가 모든 글에 반복 첨부되므로,
    차라리 검색을 건너뛰고 AI 생성 이미지·제목 썸네일로 폴백하는 편이 낫습니다.
    """
    # 영어 단어가 있으면 우선 사용
    en_words = re.findall(r'[A-Za-z][A-Za-z0-9]{2,}', query)
    if en_words:
        return " ".join(en_words[:3])

    ko_words = re.findall(r'[가-힣]{2,}', query)
    en_terms: list[str] = []
    for w in ko_words:
        term = _ko_en_lookup(w)
        if term and term not in en_terms:
            en_terms.append(term)
        if len(en_terms) >= 2:
            break
    return " ".join(en_terms)


# ──────────────────────────────────────────────────────────────────────────────
# 글 간 이미지 중복 방지 — 이미 사용한 이미지 URL을 기록·회피
# ──────────────────────────────────────────────────────────────────────────────

_USED_IMAGES_FILE = os.path.join(os.path.dirname(__file__), "logs", "used_images.json")
_USED_IMAGES_MAX = 1000  # 최근 N개만 유지


def _norm_img_title(title: str) -> str:
    """이미지 제목/태그 문자열 정규화 — 같은 사진의 다른 URL 감지용 지문."""
    return re.sub(r"\s+", " ", (title or "").strip().lower())[:80]


def _load_used_images() -> set[str]:
    try:
        with open(_USED_IMAGES_FILE, encoding="utf-8") as f:
            return set(json.load(f).get("urls", []))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return set()


def _load_used_titles() -> set[str]:
    try:
        with open(_USED_IMAGES_FILE, encoding="utf-8") as f:
            return set(json.load(f).get("titles", []))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return set()


def _origin_url(url: str) -> str:
    """복제본 URL이면 원본으로, 아니면 그대로."""
    try:
        from image_mirror import origin_of
        return origin_of(url) or url
    except Exception:
        return url


def mark_images_used(urls: list[str], titles: list[str] | None = None) -> None:
    """삽입된 이미지 URL(+제목 지문)을 기록해 이후 글에서 같은 이미지를 피하게 합니다.
    제목 지문은 같은 사진이 다른 URL로 재등장하는 것까지 차단합니다.
    (data URI 생성 썸네일은 글마다 고유하므로 기록 제외)"""
    # 복제본 URL은 원본으로 되돌려 기록합니다. 자체 호스팅 뒤에는 같은 사진이
    # 매번 다른 복제 경로로 보이므로, 그대로 적으면 중복 방지가 무력해집니다.
    urls = [_origin_url(u) for u in urls]
    real = [u for u in urls if u and not u.startswith("data:")]
    norm_titles = [t for t in (_norm_img_title(t) for t in (titles or [])) if t]
    if not real and not norm_titles:
        return
    try:
        try:
            with open(_USED_IMAGES_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            data = {}
        existing = data.get("urls", [])
        existing_titles = data.get("titles", [])
        merged = existing + [u for u in real if u not in existing]
        merged_titles = existing_titles + [t for t in norm_titles if t not in existing_titles]
        os.makedirs(os.path.dirname(_USED_IMAGES_FILE), exist_ok=True)
        with open(_USED_IMAGES_FILE, "w", encoding="utf-8") as f:
            json.dump({"urls": merged[-_USED_IMAGES_MAX:],
                       "titles": merged_titles[-_USED_IMAGES_MAX:]}, f, ensure_ascii=False, indent=1)
    except Exception as e:
        logger.warning(f"used_images.json 기록 실패: {e}")


def _fetch_best_image(
    query: str,
    naver_client_id: str = "",
    naver_client_secret: str = "",
    n_candidates: int = 4,
    pixabay_api_key: str = "",
) -> dict | None:
    """
    후보 이미지를 가져와 제목 관련성이 가장 높은 것을 반환합니다.
    긴 체험담식 쿼리는 결과가 없으므로 점진적으로 단순화하며 재시도합니다:
    ① 원본 쿼리 → ② 핵심 명사 3개 → ③ 핵심 명사 2개
    한국어 쿼리는 영어 변환 쿼리도 추가 시도.
    관련성 임계값 미달 시에도 후보가 있으면 최상위 이미지를 반환합니다
    (Claude _filter_relevant_images에서 최종 필터링).
    """
    is_korean = _is_korean_query(query)
    attempts = [query]
    simple3 = _simplify_query(query, 3)
    simple2 = _simplify_query(query, 2)
    if simple3 and simple3 != query:
        attempts.append(simple3)
    if simple2 and simple2 not in attempts:
        attempts.append(simple2)

    # 한국어 쿼리: 영어 변환 버전도 시도 (Pixabay/DDG/Wikimedia 결과 개선)
    if is_korean:
        en_q = _ko_to_en_query(query)
        if en_q and en_q not in attempts:
            attempts.append(en_q)

    # 관련성 채점은 항상 단순화된 핵심 명사 기준
    score_query = simple2 or simple3 or query

    used_urls = _load_used_images()      # 이전 글들에서 이미 쓴 이미지 URL 회피
    used_titles = _load_used_titles()    # 같은 사진의 다른 URL(제목 지문)도 회피
    best_fallback = None  # 임계값 미달이라도 후보가 있으면 보관
    for attempt_q in attempts:
        candidates = _search_all_sources(
            attempt_q, naver_client_id, naver_client_secret, n_candidates,
            pixabay_api_key=pixabay_api_key,
        )
        fresh = [c for c in candidates
                 if c.get("url", "") not in used_urls
                 and _norm_img_title(c.get("title", "")) not in used_titles]
        if candidates and not fresh:
            logger.debug(f"후보 전부 기사용 이미지: '{attempt_q}' — 다음 쿼리 시도")
            continue
        candidates = fresh
        if not candidates:
            continue
        best = max(candidates, key=lambda img: _score_title_relevance(img, score_query))
        score = _score_title_relevance(best, score_query)
        if score >= _MIN_RELEVANCE:
            return best
        logger.debug(f"관련성 미달 후보 보관: '{attempt_q}' → '{best.get('title','')[:30]}' (score={score:.2f})")
        if best_fallback is None:
            best_fallback = best

    # 임계값을 넘는 이미지가 없어도 후보가 있으면 최상위 반환
    # (Claude _filter_relevant_images가 최종 필터링 담당)
    if best_fallback:
        logger.debug(f"관련성 미달 폴백 이미지 사용: '{best_fallback.get('title','')[:40]}'")
        return best_fallback
    return None


def _filter_relevant_images(
    images: list[dict],
    keyword: str,
    article_plain_text: str,
) -> list[dict]:
    """
    Claude를 사용해 글 내용과 관련 없는 이미지를 제거합니다.
    API 오류 시 모두 허용(기본 통과)하여 자동화를 중단시키지 않습니다.
    """
    if not images:
        return images
    try:
        import anthropic
        from config import claude_text, ANTHROPIC_API_KEY, CLAUDE_MODEL
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        img_list = "\n".join(
            f"{i + 1}. 검색어={img.get('search_query', '')} / 제목={img.get('title', '')}"
            for i, img in enumerate(images)
        )
        # 본문 앞뒤 각 400자 → 글 전체 주제와 마지막 섹션 주제를 모두 커버
        summary = article_plain_text[:400]
        if len(article_plain_text) > 800:
            summary += " ... " + article_plain_text[-200:]

        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": (
                    f"블로그 주제: {keyword}\n"
                    f"글 내용 요약: {summary}\n\n"
                    f"아래 각 이미지의 검색어와 제목을 보고, 이 블로그 글의 시각적 자료로 "
                    f"적합한 이미지 번호만 쉼표로 나열하세요.\n"
                    f"기준: 글 주제·섹션 내용과 직접 관련된 이미지만 포함. "
                    f"키워드와 무관하거나 전혀 다른 주제의 이미지는 제외.\n"
                    f"모두 관련 없으면 '없음'.\n\n"
                    f"{img_list}\n\n"
                    "번호만 답 (예: 1,3 또는 없음):"
                ),
            }],
        )
        answer = claude_text(msg).strip()
        logger.debug(f"이미지 관련성 평가 결과: {answer}")

        # '없음' 변형 처리
        if re.search(r'^없음[\.!,]?$', answer, re.IGNORECASE) or answer.lower() in ("none", "없음"):
            logger.info("이미지 관련성 검증: 관련 이미지 없음 — 전체 제거")
            return []

        keep = set()
        for part in re.split(r'[,\s]+', answer.replace(".", "")):
            if part.isdigit():
                keep.add(int(part) - 1)

        filtered = [img for i, img in enumerate(images) if i in keep]
        removed = len(images) - len(filtered)
        if removed:
            logger.info(f"이미지 관련성 검증: {removed}개 제거, {len(filtered)}개 유지")
        # 파싱 결과가 비어있으면 (인덱스 오류 포함) 원본 반환
        if not filtered:
            logger.debug("이미지 관련성 검증 파싱 실패 또는 범위 초과 — 원본 유지")
            return images
        return filtered

    except Exception as e:
        logger.debug(f"이미지 관련성 검증 오류 (기본 허용): {e}")
        return images


# ──────────────────────────────────────────────────────────────────────────────
# 제목 기반 썸네일 자동 생성 (이미지 검색 전부 실패 시 폴백)
# ──────────────────────────────────────────────────────────────────────────────

# 주제별 그라디언트·이모지 (content_generator 테마와 톤 일치 — 순환 임포트 방지 위해 자체 정의)
_THUMB_THEMES = [
    # (감지 키워드, 그라디언트 시작, 끝, 액센트, 이모지)
    ({"여행", "관광", "명소", "숙소", "호텔", "맛집", "항공", "제주", "투어", "휴양"},
     "#0369a1", "#0ea5e9", "#e0f2fe", "✈️"),
    ({"드라마", "영화", "넷플릭스", "ott", "결말", "출연진", "배우"},
     "#6d28d9", "#a78bfa", "#f3e8ff", "🎬"),
    ({"아이돌", "컴백", "k-pop", "kpop", "음반", "신곡", "콘서트", "걸그룹", "보이그룹", "월드투어", "팬덤"},
     "#be185d", "#f472b6", "#fce7f3", "🎵"),
    ({"투자", "주식", "etf", "금융", "경제", "금리", "환율", "부동산", "재테크", "세금"},
     "#1d4ed8", "#3b82f6", "#dbeafe", "📈"),
    ({"축구", "야구", "농구", "골프", "스포츠", "경기", "선수", "손흥민"},
     "#dc2626", "#f87171", "#fee2e2", "⚽"),
    ({"건강", "다이어트", "운동", "의료", "영양", "식단"},
     "#047857", "#34d399", "#d1fae5", "💪"),
]
_THUMB_DEFAULT = ("#1e3a8a", "#60a5fa", "#dbeafe", "📝")

# 대시보드 테마 선택값 → _THUMB_THEMES 인덱스 (순서 일치)
_THUMB_THEME_NAMES = ["travel", "drama", "kpop", "finance", "sports", "health"]


def _thumb_theme(text: str, theme_name: str = "") -> tuple[str, str, str, str]:
    if theme_name and theme_name in _THUMB_THEME_NAMES:
        _, c1, c2, accent, emoji = _THUMB_THEMES[_THUMB_THEME_NAMES.index(theme_name)]
        return c1, c2, accent, emoji
    if theme_name == "default":
        return _THUMB_DEFAULT
    t = text.lower()
    for kws, c1, c2, accent, emoji in _THUMB_THEMES:
        if any(w in t for w in kws):
            return c1, c2, accent, emoji
    return _THUMB_DEFAULT


def _wrap_title(title: str, max_chars: int = 13, max_lines: int = 3) -> list[str]:
    """제목을 단어 단위로 줄바꿈합니다 (한 줄 max_chars자, 최대 max_lines줄)."""
    words = title.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        cand = f"{cur} {w}".strip()
        if len(cand) <= max_chars or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = w
        if len(lines) == max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    # 넘친 마지막 줄 말줄임
    if lines and (len(lines) == max_lines and len(" ".join(words)) > sum(len(l) for l in lines) + len(lines) - 1):
        last = lines[-1]
        lines[-1] = (last[:max_chars - 1] + "…") if len(last) > max_chars else last + "…"
    return lines or [title[:max_chars]]


def _upload_to_imgbb(svg_bytes: bytes) -> str:
    """SVG를 imgbb에 업로드해 공개 URL을 반환합니다. 실패 시 빈 문자열."""
    api_key = os.getenv("IMGBB_API_KEY", "")
    if not api_key:
        return ""
    try:
        r = requests.post(
            "https://api.imgbb.com/1/upload",
            data={"key": api_key, "image": base64.b64encode(svg_bytes).decode()},
            timeout=15,
        )
        if r.status_code == 200:
            return r.json().get("data", {}).get("url", "")
    except Exception as e:
        logger.debug(f"imgbb 업로드 실패: {e}")
    return ""


def _generate_ai_image(topic: str) -> dict | None:
    """검색 실패 시 AI(OpenAI 이미지 모델)로 주제 이미지를 생성합니다.

    생성 이미지는 ImgBB에 업로드해 공개 URL로 반환합니다.
    - AI_IMAGE_FALLBACK=false 로 비활성화 가능 (기본 활성)
    - OPENAI_API_KEY·IMGBB_API_KEY 둘 다 필요 (없으면 None → SVG 썸네일로)
    - 초상권·저작권 안전: 실존 인물·텍스트·워터마크 금지 프롬프트
    """
    if os.getenv("AI_IMAGE_FALLBACK", "true").strip().lower() not in ("true", "1", "yes"):
        return None
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    if not os.getenv("IMGBB_API_KEY", "").strip():
        logger.info("IMGBB_API_KEY 없음 — AI 생성 이미지 호스팅 불가, SVG 썸네일로 폴백")
        return None
    topic = (topic or "").strip()
    if not topic:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        model = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
        prompt = (
            f"Clean, modern blog header illustration about: {topic}. "
            "Soft gradients, flat design with subtle depth, warm inviting colors. "
            "Strictly NO text, NO letters, NO watermark, NO logos, "
            "NO real or recognizable people or celebrity likenesses."
        )
        resp = client.images.generate(model=model, prompt=prompt, size="1536x1024", n=1)
        data = resp.data[0]
        b64 = getattr(data, "b64_json", None)
        if b64:
            img_bytes = base64.b64decode(b64)
        else:
            src_url = getattr(data, "url", None)
            if not src_url:
                return None
            img_bytes = requests.get(src_url, timeout=30).content
        url = _upload_to_imgbb(img_bytes)
        if not url:
            logger.warning("AI 이미지 ImgBB 업로드 실패 — SVG 썸네일로 폴백")
            return None
        logger.info(f"🎨 AI 이미지 생성·업로드 완료: '{topic[:40]}' → {url[:70]}")
        return {
            "url": url,
            "title": topic,
            "width": 1536,
            "height": 1024,
            "source": "ai_generated",
        }
    except Exception as e:
        logger.warning(f"AI 이미지 생성 실패 ({type(e).__name__}): {str(e)[:120]} — SVG 썸네일로 폴백")
        return None


def generate_fallback_image(title: str, keyword: str = "", theme: str = "") -> dict | None:
    """검색 전부 실패 시 폴백 이미지: ① AI 생성 이미지 → ② SVG 제목 썸네일."""
    topic = (title or keyword or "").strip()
    img = _generate_ai_image(topic)
    if img:
        img["alt_text"] = topic[:50]
        img["search_query"] = topic
        return img
    return generate_title_thumbnail(title, keyword, theme=theme)


def generate_title_thumbnail(title: str, keyword: str = "", theme: str = "") -> dict | None:
    """
    제목 기반 SVG 썸네일 카드를 생성합니다 (이미지 검색 전부 실패 시 폴백).
    - 주제별 그라디언트 배경 + 카테고리 이모지 + 제목 텍스트
    - IMGBB_API_KEY 설정 시 공개 URL 업로드, 아니면 data URI로 본문에 직접 임베드
    """
    text = (title or keyword or "").strip()
    if not text:
        return None
    c1, c2, accent, emoji = _thumb_theme(f"{title} {keyword}", theme_name=theme)
    lines = _wrap_title(text)

    line_h = 78
    total_h = len(lines) * line_h
    start_y = 340 - total_h // 2 + 56
    tspans = "".join(
        f'<text x="600" y="{start_y + i * line_h}" text-anchor="middle" '
        f'font-family="\'Noto Sans KR\',\'Apple SD Gothic Neo\',sans-serif" '
        f'font-size="56" font-weight="800" fill="#ffffff">{html.escape(l)}</text>'
        for i, l in enumerate(lines)
    )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/>
  </linearGradient>
</defs>
<rect width="1200" height="630" fill="url(#bg)"/>
<circle cx="1080" cy="90" r="180" fill="{accent}" opacity="0.13"/>
<circle cx="110" cy="560" r="140" fill="{accent}" opacity="0.10"/>
<text x="600" y="150" text-anchor="middle" font-size="72">{emoji}</text>
{tspans}
<rect x="500" y="{start_y + len(lines) * line_h + 10}" width="200" height="5" rx="2.5" fill="{accent}" opacity="0.85"/>
</svg>"""
    svg_bytes = svg.encode("utf-8")

    url = _upload_to_imgbb(svg_bytes)
    if not url:
        url = "data:image/svg+xml;base64," + base64.b64encode(svg_bytes).decode()

    logger.info(f"제목 썸네일 생성: '{text[:30]}' ({'imgbb' if url.startswith('http') else 'data URI'}, {len(svg_bytes)}B)")
    return {
        "url": url,
        "title": text,
        "width": 1200,
        "height": 630,
        "source": "generated_thumbnail",
        "generated": True,
        "alt_text": text if len(text) <= 50 else text[:50].rsplit(" ", 1)[0],
        "search_query": keyword or text,
    }


def fetch_images_for_queries(
    queries: list[str],
    naver_client_id: str = "",
    naver_client_secret: str = "",
    article_plain_text: str = "",
    keyword: str = "",
    pixabay_api_key: str = "",
    title: str = "",
) -> list[dict]:
    """섹션별 쿼리로 저작권 안전 이미지(Pixabay → Wikimedia)를 검색하고 Claude로 최종 검증합니다.

    검색 결과가 없으면 AI 생성 이미지 → 제목 기반 SVG 썸네일 순으로 대체합니다.
    반환 직전에 화이트리스트를 한 번 더 적용합니다 — 검색 단계에서 이미 걸렀지만,
    폴백 경로나 앞으로 추가될 경로가 이 관문을 우회하지 못하게 하는 최종 방어선입니다.
    """
    images = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()  # 같은 사진이 다른 URL로 반복 선택되는 것 방지 (태그 문자열 기준)

    def _norm_title(im: dict) -> str:
        return re.sub(r"\s+", " ", (im.get("title") or "").strip().lower())[:80]

    def _is_dup(im: dict) -> bool:
        t = _norm_title(im)
        return im.get("url", "") in seen_urls or (bool(t) and t in seen_titles)

    def _remember(im: dict) -> None:
        seen_urls.add(im.get("url", ""))
        t = _norm_title(im)
        if t:
            seen_titles.add(t)

    for query in queries:
        img = _fetch_best_image(query, naver_client_id, naver_client_secret, n_candidates=6,
                                pixabay_api_key=pixabay_api_key)
        if img:
            if _is_dup(img):
                logger.debug(f"중복 이미지 건너뜀: '{query}' → {img.get('url','')[:60]}")
                # 같은 쿼리로 후보를 더 요청해 다른 이미지 탐색
                candidates = _search_all_sources(
                    _simplify_query(query, 2) or query,
                    naver_client_id, naver_client_secret, 8,
                    pixabay_api_key=pixabay_api_key,
                )
                alt_img = next((c for c in candidates if not _is_dup(c)), None)
                if alt_img:
                    img = alt_img
                    img["search_query"] = query
                    img["alt_text"] = query if len(query) <= 50 else query[:50].rsplit(" ", 1)[0]
                    score = _score_title_relevance(img, query)
                    logger.info(f"대체 이미지 수집: '{query}' → 제목='{img.get('title','')[:40]}' (관련성={score:.2f})")
                else:
                    logger.warning(f"중복 대체 이미지 없음: '{query}' — 건너뜀")
                    img = None
            if img:
                img["search_query"] = query
                img["alt_text"] = query if len(query) <= 50 else query[:50].rsplit(" ", 1)[0]
                score = _score_title_relevance(img, query)
                logger.info(f"이미지 수집 성공: '{query}' → 제목='{img.get('title','')[:40]}' (관련성={score:.2f})")
                _remember(img)
        else:
            logger.warning(f"이미지 없음: '{query}'")
        if img:
            images.append(img)

    # Claude로 최종 관련성 검증 (article_plain_text 제공 시, 이미지 2개 이상일 때만)
    # 이미지가 1개뿐이면 Claude 필터를 거치지 않음 — 유일한 후보를 "없음" 판정으로 제거 방지
    if images and article_plain_text and len(images) >= 2:
        images = _filter_relevant_images(images, keyword or queries[0], article_plain_text)

    # 최종 폴백: 이미지가 하나도 없으면 제목 기반 썸네일 생성
    # + 글 내용과 관련된 실제 이미지도 함께 검색해 첨부
    if not images and (title or keyword):
        thumb = generate_fallback_image(title, keyword)
        if thumb:
            # 실제 사진 이미지 추가 검색 (썸네일과 함께 제공)
            search_kw = keyword or title or ""
            simple_q = _simplify_query(search_kw, 2) or search_kw
            real_img = _fetch_best_image(
                simple_q, naver_client_id, naver_client_secret,
                n_candidates=6, pixabay_api_key=pixabay_api_key,
            )
            if real_img:
                real_img["search_query"] = simple_q
                real_img["alt_text"] = simple_q if len(simple_q) <= 50 else simple_q[:50].rsplit(" ", 1)[0]
                logger.info(f"썸네일 폴백 + 관련 이미지 추가: '{real_img.get('title','')[:40]}'")
                images.append(real_img)
            images.append(thumb)

    # 최종 관문 — 화이트리스트 밖 이미지는 여기서 반드시 걸러집니다.
    images = filter_license_safe(images)

    # 필터 결과가 비었는데 만들 재료(title/keyword)가 있으면 썸네일이라도 붙입니다.
    # 이미지 없는 글보다는 직접 만든 썸네일이 낫습니다.
    if not images and (title or keyword):
        thumb = generate_fallback_image(title, keyword)
        if thumb and is_license_safe(thumb.get("url", "")):
            images.append(thumb)

    # 자체 호스팅 — 반드시 화이트리스트 관문 **뒤**에서만 복제합니다.
    # 앞에서 하면 복제본 URL이 우리 도메인이라 무조건 통과해, 권리가 없는
    # 이미지를 우리 저장소에 복사한 뒤 안전하다고 판정하게 됩니다.
    _self_host(images)

    return images


def _self_host(images: list[dict]) -> None:
    """이미지를 저장소로 복제해 원본이 사라져도 글이 깨지지 않게 합니다.

    복제가 실패하거나 스위치가 꺼져 있으면 조용히 원본(핫링크)을 유지합니다 —
    이 단계 때문에 글 생성이 멈추면 안 됩니다. 다만 그 원본이 만료되는
    주소라면 영구 주소(stable_url)로 갈아탑니다.
    """
    try:
        from feature_flags import is_enabled
        if is_enabled("image_self_host"):
            from image_mirror import mirror_images
            mirror_images(images)
    except Exception as e:
        logger.warning(f"이미지 자체 호스팅 건너뜀: {e}")
    _prefer_stable_urls(images)


def adopt_image(img: dict | None) -> dict | None:
    """글에 넣기로 확정한 이미지 한 장을 자체 호스팅 관문에 통과시킵니다.

    검색 단계가 아니라 **채택 단계**에서 부릅니다. 후보를 고르는 동안 부르면
    버려질 이미지까지 내려받아 저장소가 부풉니다.

    이것을 빠뜨리면 만료되는 주소가 그대로 발행 글에 박힙니다 — 죽은 이미지를
    또 죽을 이미지로 바꾸는 셈이 됩니다.
    """
    if not img:
        return None
    _self_host([img])
    # 쓰기로 정한 순간 기록합니다. 이게 없으면 _fetch_best_image가 매번 같은
    # "아직 안 쓴 목록"을 보고 같은 사진을 고릅니다 — 2026-08-25 소급 교체에서
    # 원본 421건이 파일 115개로 수렴했는데, 절반은 압축 효과가 아니라 한 사진을
    # 여러 글에 반복해서 넣은 결과였습니다.
    #
    # 기록은 복제 후에 합니다. mark_images_used가 복제본 URL을 원본으로
    # 되돌려 적으므로 순서가 바뀌어도 값은 같지만, "채택 완료" 시점에 남기는
    # 편이 실패한 복제를 사용 이력에 넣지 않아 정확합니다.
    try:
        mark_images_used([img.get("url", "")], [img.get("title", "")])
    except Exception as e:
        logger.debug(f"사용 이미지 기록 실패: {e}")
    return img


def _prefer_stable_urls(images: list[dict]) -> None:
    """복제되지 않은 채 남은 이미지를 영구 주소로 바꿉니다.

    복제에 성공했다면 우리 도메인을 가리키므로 손대지 않습니다. 실패했거나
    스위치가 꺼져 있을 때만, 만료되는 주소 대신 영구 주소를 씁니다 —
    화질을 조금 잃더라도 몇 주 뒤 깨지는 것보다 낫습니다.
    """
    for img in images or []:
        stable = (img.get("stable_url") or "").strip()
        if not stable or img.get("origin_url"):
            continue
        if img.get("url") == stable:
            continue
        logger.info(f"만료되는 주소 대신 영구 주소 사용: {stable[:70]}")
        img["url"] = stable




def _safe_caption(img: dict, alt: str) -> str:
    """캡션 텍스트 결정 — 파일명·Pixabay 태그 나열·무의미한 제목은 alt로 대체합니다."""
    title = (img.get("title") or "").strip()
    if not title or re.search(r'\.(jpe?g|png|webp|svg|gif)$', title, re.I):
        return alt
    if len(title) < 4:
        return alt
    # Pixabay 태그 형식 감지: "word / word / word ..." (슬래시 2개 이상 → 태그 나열)
    if len(re.findall(r'\s*/\s*', title)) >= 2:
        return alt
    return title


# 이미지 출처 표기 — 저작권 정책 리스크 예방 + 콘텐츠 성의 신호(E-E-A-T).
# 링크는 소스 사이트 메인이 아니라 실제 자료 페이지가 있을 때만 검다
# (AdSense '탐색' 정책상 관련 없는 페이지로 보내면 안 됨).
#
# ⚠️ "네이버 이미지 검색", "웹 검색" 같은 값은 출처가 아니라 검색 경로일 뿐이며,
#    적어둔다고 사용 권리가 생기지 않습니다. 두 소스를 검색 경로에서 제거하면서
#    라벨도 함께 지웠습니다. 라이선스를 확인한 소스만 여기 둡니다.
_SOURCE_LABELS = {
    "pixabay": "Pixabay (Pixabay Content License)",
    "wikimedia": "Wikimedia Commons",
    "unsplash": "Unsplash (Unsplash License)",
    "ai_generated": "AI 생성 이미지",
    "generated_thumbnail": "직접 제작",
}


# URL 호스트 → 출처 라벨. 이미지가 교체된 뒤 캡션을 다시 쓸 때 씁니다.
# img dict의 "source" 필드는 교체 시점에만 있고 발행된 HTML에는 남지 않으므로,
# 사후 정리는 src URL만 보고 판정해야 합니다.
_HOST_SOURCE_LABELS = (
    ("pixabay.com", "Pixabay (Pixabay Content License)"),
    ("wikimedia.org", "Wikimedia Commons"),
    ("unsplash.com", "Unsplash (Unsplash License)"),
    ("ibb.co", "직접 제작"),
)


def source_label_for_url(url: str) -> str:
    """이미지 URL만 보고 출처 라벨을 판정합니다.

    화이트리스트 밖 URL은 빈 문자열을 반환합니다 — 라이선스를 확인하지 않은
    이미지에 그럴듯한 출처를 붙이면 안 됩니다.
    """
    u = (url or "").strip()
    if u.startswith("data:image/"):
        return "직접 제작"
    m = re.match(r'https?://([^/:]+)', u, re.I)
    if not m:
        return ""
    host = m.group(1).lower()
    for needle, label in _HOST_SOURCE_LABELS:
        if host == needle or host.endswith("." + needle):
            return label
    return ""


def _attribution_text(img: dict) -> str:
    """이미지 출처 표기 문구를 반환합니다 (알 수 없는 소스면 빈 문자열)."""
    label = _SOURCE_LABELS.get((img.get("source") or "").strip())
    return f"이미지 출처: {label}" if label else ""


def _make_img_html(img: dict, alt: str, caption: str = "") -> str:
    """이미지 SEO 최적화 HTML 생성 (출처 표기 포함)."""
    alt_safe = html.escape(alt, quote=True)
    caption_safe = html.escape(caption, quote=True)
    attribution = _attribution_text(img)
    fig_style = "margin:2.5em auto;text-align:center;max-width:720px;"
    img_style = (
        "max-width:100%;height:auto;border-radius:10px;"
        "box-shadow:0 3px 14px rgba(0,0,0,0.13);display:block;margin:0 auto;"
    )
    # 캡션 본문 + 출처를 한 figcaption 안에 배치 (출처만 있어도 표기)
    cap_parts = []
    if caption:
        cap_parts.append(
            f'<span style="font-style:italic;">{caption_safe}</span>'
        )
    if attribution:
        page_url = (img.get("page_url") or "").strip()
        attr_safe = html.escape(attribution, quote=True)
        attr_html = (
            f'<a href="{html.escape(page_url, quote=True)}" target="_blank" '
            f'rel="nofollow noopener" style="color:#999;text-decoration:none;">{attr_safe}</a>'
            if page_url.startswith("http") else attr_safe
        )
        cap_parts.append(
            f'<span style="font-size:11px;color:#999;">{attr_html}</span>'
        )
    cap_html = (
        f'<figcaption style="text-align:center;font-size:13px;color:#777;'
        f'margin-top:8px;line-height:1.6;">' + "<br>".join(cap_parts) + '</figcaption>'
        if cap_parts else ""
    )
    # 복제본이 아직 배포되지 않았거나(발행 ~ Pages 배포 사이 몇 분) 나중에
    # 지워졌을 때를 대비해 원본을 예비로 심어 둡니다. 자체 호스팅이 기존
    # 핫링크보다 나쁠 수 있는 유일한 경우를 이 한 줄이 막습니다.
    origin = (img.get("origin_url") or "").strip()
    fallback = (
        f' onerror="this.onerror=null;this.src=\'{html.escape(origin, quote=True)}\'"'
        if origin.startswith("http") else ""
    )
    return (
        f'\n<figure style="{fig_style}">'
        f'\n  <img src="{img["url"]}" alt="{alt_safe}" title="{alt_safe}" '
        f'style="{img_style}" loading="lazy" decoding="async" width="720"{fallback}/>'
        f'\n  {cap_html}'
        f'\n</figure>\n'
    )


def inject_images_into_content(content: str, images: list[dict], keyword: str) -> str:
    """
    블로그 본문 HTML에 이미지를 전략적으로 삽입합니다.
    - 첫 이미지: 도입부 첫 <p> 바로 다음
    - 나머지 이미지: 짝수 번째 <h2> 섹션 끝에 삽입
    """
    if not images:
        return content

    # 글 간 중복 방지: 삽입되는 이미지 URL + 제목 지문 기록
    mark_images_used([img.get("url", "") for img in images],
                     [img.get("title", "") for img in images])

    def _alt(img: dict, fallback: str) -> str:
        # 글이 정해 준 alt가 가장 정확합니다. 그 다음이 소스가 준 alt이고,
        # 검색어는 마지막입니다 — 검색어는 3단어로 줄인 결과라 '발리 겨울방학'
        # 처럼 잘린 문구가 그대로 alt로 나갔습니다.
        return img.get("plan_alt") or img.get("alt_text") or img.get("search_query", fallback)

    # ⓪ 글이 배치를 지정한 이미지는 그 H2 바로 앞에 넣습니다.
    #
    # 예전에는 위치가 순서로만 정해졌습니다(첫 <p> 뒤, 2·4번째 H2 앞). 그런데
    # 이미지는 섹션별 검색어로 따로 찾았고, 관련성 필터·중복 제거로 목록이
    # 줄면 순서가 밀려 엉뚱한 섹션에 붙었습니다.
    planned, unplaced = [], []
    for idx, img in enumerate(images):
        (planned if (img.get("plan_heading") or "").strip() else unplaced).append((idx, img))

    used_positions: list[int] = []
    for idx, img in list(planned):
        heading = img["plan_heading"].strip()
        # 제목이 본문과 정확히 같지 않을 수 있어(모델이 살짝 다듬는 경우)
        # 태그를 벗긴 텍스트로 비교합니다.
        hit = None
        for m in re.finditer(r'<h2[^>]*>(.*?)</h2>', content, re.IGNORECASE | re.DOTALL):
            text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            if text == heading or (len(heading) >= 6 and heading in text):
                hit = m.start()
                break
        if hit is None:
            logger.debug(f"이미지 배치 대상 H2를 찾지 못함 — 기본 위치로: {heading[:30]!r}")
            planned.remove((idx, img))
            unplaced.append((idx, img))
            continue
        used_positions.append(hit)

    # 뒤에서부터 넣어야 앞 위치의 인덱스가 밀리지 않습니다
    for (idx, img), pos in sorted(zip(planned, used_positions), key=lambda x: -x[1]):
        alt = _alt(img, keyword)
        content = content[:pos] + _make_img_html(img, alt, _safe_caption(img, alt)) + content[pos:]

    img_iter = iter(unplaced)

    # ① 첫 번째 이미지: 첫 <p>...</p> 바로 다음
    first_p = re.search(r'(</p>)', content, re.IGNORECASE)
    if first_p:
        try:
            idx, img = next(img_iter)
            alt = _alt(img, keyword)
            img_html = _make_img_html(img, alt, _safe_caption(img, alt))
            content = content[:first_p.end()] + img_html + content[first_p.end():]
        except StopIteration:
            return content

    # ② 배치 지정이 없는 나머지: <h2> 태그 직전에 삽입 (섹션 사이 배치)
    h2_positions = [m.start() for m in re.finditer(r'<h2', content, re.IGNORECASE)]
    insert_positions = h2_positions[1::2]  # 2번째, 4번째, 6번째 H2 앞

    offset = 0
    for pos in insert_positions:
        try:
            idx, img = next(img_iter)
            alt = _alt(img, f"{keyword} 관련 이미지 {idx + 1}")
            img_html = _make_img_html(img, alt, _safe_caption(img, alt))
            actual_pos = pos + offset
            content = content[:actual_pos] + img_html + content[actual_pos:]
            offset += len(img_html)
        except StopIteration:
            break

    # ③ H2 슬롯이 부족해 남은 이미지: 본문 끝에 배치 (버리지 않음)
    for idx, img in img_iter:
        alt = _alt(img, f"{keyword} 관련 이미지 {idx + 1}")
        content = content + _make_img_html(img, alt, _safe_caption(img, alt))

    return content
