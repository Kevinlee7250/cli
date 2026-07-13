"""블로그 포스트 생성 — AdSense 최적화 + 이미지 자동 삽입 + 재시도 로직"""

import html as _html_esc
import json
import logging
import os
import re
import time

import anthropic

from config import (
    claude_text, claude_generate, gpt_generate,
    ANTHROPIC_API_KEY, CLAUDE_MODEL,
    OPENAI_API_KEY, OPENAI_MODEL,
    AI_PROVIDER, BLOG_LANGUAGE,
)
from coupang_affiliate import inject_affiliate_section
from image_fetcher import fetch_images_for_queries, inject_images_into_content

logger = logging.getLogger(__name__)
_client: anthropic.Anthropic | None = None
_openai_client = None  # openai.OpenAI 인스턴스 (지연 초기화)


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def _fetch_drama_references(keyword: str) -> str:
    """
    드라마·영화 키워드에 대한 실제 리뷰·반응 데이터를 네이버 블로그/뉴스 API로 수집합니다.
    수집된 내용은 Claude 프롬프트에 참고 자료로 주입됩니다.
    API 키가 없거나 실패하면 빈 문자열을 반환합니다.
    """
    import requests as _req
    naver_id = os.getenv("NAVER_CLIENT_ID", "")
    naver_secret = os.getenv("NAVER_CLIENT_SECRET", "")
    if not naver_id or not naver_secret:
        return ""

    headers = {
        "X-Naver-Client-Id": naver_id,
        "X-Naver-Client-Secret": naver_secret,
    }
    snippets: list[str] = []

    # 블로그 리뷰 수집 (최신순 5개)
    try:
        r = _req.get(
            "https://openapi.naver.com/v1/search/blog.json",
            headers=headers,
            params={"query": keyword + " 리뷰", "display": 5, "sort": "date"},
            timeout=8,
        )
        if r.status_code == 200:
            for item in r.json().get("items", []):
                title = re.sub(r"<[^>]+>", "", item.get("title", "")).strip()
                desc = re.sub(r"<[^>]+>", "", item.get("description", "")).strip()
                if title and desc:
                    snippets.append(f"[블로그 리뷰] {title}: {desc}")
    except Exception:
        pass

    # 뉴스 수집 (최신 5개)
    try:
        r = _req.get(
            "https://openapi.naver.com/v1/search/news.json",
            headers=headers,
            params={"query": keyword, "display": 5, "sort": "date"},
            timeout=8,
        )
        if r.status_code == 200:
            for item in r.json().get("items", []):
                title = re.sub(r"<[^>]+>", "", item.get("title", "")).strip()
                desc = re.sub(r"<[^>]+>", "", item.get("description", "")).strip()
                if title and desc:
                    snippets.append(f"[뉴스] {title}: {desc}")
    except Exception:
        pass

    if not snippets:
        return ""

    lines = "\n".join(f"- {s}" for s in snippets[:8])
    return f"""
━━━ 실제 시청자·관객 반응 참고 자료 (네이버 최신 검색 결과) ━━━

아래는 이 작품에 대한 실제 블로그 리뷰와 뉴스 요약입니다.
반드시 이 내용을 참고해서 실제 시청자 반응과 평가를 글에 자연스럽게 녹여주세요.
단, 아래 내용을 그대로 복사하지 말고, 개인 시청 경험과 결합해 재구성하세요.

{lines}

위 참고 자료를 바탕으로:
- 실제 시청자들이 공통적으로 언급하는 장면·배우·스토리 포인트를 글에 포함할 것
- 호불호가 갈리는 요소가 있다면 양쪽 시각 모두 언급할 것
- 수치(시청률, 박스오피스 순위, 별점 등)가 언급된 경우 글에 반영할 것
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        try:
            from openai import OpenAI
            _openai_client = OpenAI(api_key=OPENAI_API_KEY)
        except ImportError:
            raise RuntimeError("openai 패키지가 설치되지 않았습니다. pip install openai 를 실행하세요.")
    return _openai_client


def _resolve_ai_provider(blog_config: dict | None) -> str:
    """블로그별 ai_provider 설정 → 없으면 전역 AI_PROVIDER 사용."""
    if blog_config:
        provider = blog_config.get("ai_provider", "").strip().lower()
        if provider in ("claude", "openai"):
            return provider
    return AI_PROVIDER.lower()


def _ai_generate(system: str, prompt: str, ai_provider: str) -> str:
    """ai_provider에 따라 Claude 또는 GPT API를 호출하고 원본 텍스트를 반환합니다."""
    if ai_provider == "openai":
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY가 설정되지 않았습니다.")
        return gpt_generate(
            _get_openai_client(),
            model=OPENAI_MODEL,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=8000,
            temperature=1.0,
        )
    # 기본: Claude
    return claude_generate(
        _get_client(),
        model=CLAUDE_MODEL,
        max_tokens=24000,
        temperature=1.0,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )


def _detect_article_type(keyword: str) -> str:
    """키워드 기반 아티클 유형 감지"""
    kw = keyword.lower()
    # 드라마·영화 리뷰 — 가장 먼저 체크 (리뷰 타입과 겹치지 않게)
    if any(w in kw for w in ["드라마", "영화", "시즌", "넷플릭스", "티빙", "쿠팡플레이", "ott", "왓챠",
                              "결말 해석", "등장인물", "ost 추천", "명장면", "영화 리뷰", "영화 후기",
                              "박스오피스", "개봉"]):
        return "drama_review"
    # 여행 가이드
    if any(w in kw for w in ["여행", "관광", "투어", "코스", "명소", "숙소", "호텔", "맛집",
                              "공항", "비자", "패키지", "자유여행", "배낭", "현지"]):
        return "travel_guide"
    # 스포츠 분석·리뷰
    if any(w in kw for w in ["경기", "축구", "야구", "농구", "테니스", "골프", "k리그", "kbo",
                              "nba", "epl", "선수", "감독", "시즌", "분석", "전망", "순위",
                              "스포츠", "마라톤", "트레킹", "등산", "러닝", "수영", "자전거"]):
        return "sports_review"
    if any(w in kw for w in ["방법", "하는법", "어떻게", "가이드", "절차", "단계"]):
        return "how_to"
    if any(w in kw for w in ["후기", "리뷰", "써봤", "직접", "경험", "솔직히", "추천"]):
        return "review"
    if any(w in kw for w in ["비교", "vs", "차이", "장단점", "선택"]):
        return "comparison"
    if any(w in kw for w in ["뭐야", "란", "이란", "개념", "정의", "이해", "알아보"]):
        return "explainer"
    return "analysis"


# 유형별 구조 가이드
_STRUCTURE_GUIDE = {
    "how_to": """
- 도입부: 처음 하는 사람이 흔히 겪는 어려움이나 헷갈리는 지점 언급
- 본문: 단계별 설명 — 각 단계에서 확인해야 할 것과 흔한 실수 사례 포함
- 섹션 제목: 실제로 하다 보면 마주치는 상황 중심 (예: "처음 시작할 때 가장 헷갈리는 것")
- 중간에 "근데 사실 이게 제일 중요해요" 같은 코멘트로 완급 조절
- 마지막: 조사한 내용을 바탕으로 한 명확한 총평""",

    "review": """
- 도입부: 왜 이 제품/서비스가 관심을 받는지 계기 설명 (광고 아님)
- 본문: 장점 → 단점 → 의외의 포인트 → 이런 사람에게 맞다/안 맞다
- "공식 스펙·홍보 내용 vs 이용자들이 말하는 실제 사용감" 대비 구조 포함
- 이용자 후기에서 공통적으로 나오는 불만이나 아쉬운 점도 명확히 전달
- 마지막: 후기·평가를 종합한 추천 기준 + 어떤 독자에게 맞는지""",

    "comparison": """
- 도입부: 독자가 어떤 걸 선택해야 할지 고민하는 상황 공유
- 본문: 비교 기준 설명 → 항목별 비교 → 상황별 추천
- "언뜻 보면 A가 나아 보이지만 자료를 보면 B가 유리한 경우" 식의 반전 포함
- 표(table)나 항목 비교 위주의 구조 (독자가 빠르게 파악할 수 있게)
- 결론: "저라면 이런 상황엔 A, 저런 상황엔 B를 선택하겠습니다" 같은 의견 (경험 주장 아님)""",

    "explainer": """
- 도입부: 이 개념을 처음 접하는 사람이 헷갈리기 쉬운 지점 짚기
- 본문: 쉬운 비유 → 핵심 개념 → 실생활 적용 사례
- "어렵게 생각할 필요 없고요" 같은 독자와의 거리감 좁히는 표현 사용
- 전문 용어가 나오면 반드시 바로 아래에 쉬운 말로 풀어 설명
- 마지막: 이걸 알면 어떻게 달라지는지 실질적인 변화 설명""",

    "analysis": """
- 도입부: 이 주제에 내가 관심 갖게 된 계기 또는 최근 뉴스/이슈 언급
- 본문: 현황 → 내가 보는 핵심 포인트 → 구체적 근거/데이터 → 개인적 전망
- "이 부분은 제 개인적인 생각인데요" 같은 의견임을 명확히 하는 표현 포함
- 과도한 낙관론/비관론 없이 균형 잡힌 시각
- 마지막: "결국 핵심은 이거예요" 식의 짧고 명확한 결론""",

    "drama_review": """
- 도입부: 이 작품이 왜 화제인지 + 시청자 반응의 전반적 분위기 소개
- 본문 구성 (편의 focus에 따라 선택):
  • 소개 편: 줄거리 요약(스포 최소화) + 장르·분위기 소개 + 어떤 사람에게 맞는지
  • 인물 편: 주인공 감정선·성장 + 조연 캐릭터 분석 + 배우 연기에 대한 시청자 평가 + 케미
  • 명장면 편: 화제가 된 장면·대사 + "시청자들 사이에서 가장 회자되는 장면" 같은 반응 기반 소개
  • 결말 편: 결말 총평(스포 주의 경고 포함) + OST 추천 + 비슷한 드라마 추천 + 평점 반응
- 감상 표현은 시청자 반응·평점 데이터를 근거로: "이 장면에서 울었다는 반응이 많았어요", "호불호가 갈린 부분은"
- 과도한 칭찬이나 홍보성 표현 금지 — 아쉽다는 평가도 솔직하게 전달
- 마지막: "이런 취향이면 강추 / 이런 취향이면 비추" 식의 명확한 추천 기준""",

    "travel_guide": """
- 도입부: 이 여행지가 왜 주목받는지 + 기대와 현실이 다를 수 있는 지점 예고
- 본문 구성:
  • 예상 여행 경비 정리 (공개된 가격 자료 기준 — 교통·숙소·식비·관광비 항목별)
  • 여행자 후기에서 공통적으로 언급되는 "몰랐던 것" / "생각보다 좋았던 것"
  • 숨은 명소·맛집 — 포털 상위 노출이 아닌 로컬 후기 기반 스팟 위주
  • 피해야 할 시간대·시즌 또는 주의사항 (후기·공식 정보 기반)
- "유명 블로그에서 추천한 곳인데 실제 방문 후기는 갈린다" 같은 반전 정보 포함
- 마지막: 이 여행지가 어떤 사람에게 맞는지 명확한 추천 기준""",

    "sports_review": """
- 도입부: 이 경기/선수/팀이 왜 주목받는지 (팬 시점 or 분석가 시점)
- 본문 구성:
  • 최근 성적·경기 결과 요약 (수치 기반 — 득점·순위·승률 등)
  • 핵심 포인트 분석: "이 부분이 승패를 갈랐다고 생각해요" (의견임을 명확히)
  • 선수·전술·팀 운영 관련 솔직한 평가 (과도한 찬양 금지)
  • 앞으로의 전망 — 명확한 개인 의견 포함 ("제 예상엔...")
- 관람 팁은 공개된 후기·안내 정보 기반으로 정리
- 마지막: 이 팀/선수/종목에 처음 관심 갖는 독자에게 입문 팁""",
}


def _build_blog_topic_hint(blog_config: dict | None) -> str:
    """블로그 주제 힌트 문자열을 생성합니다."""
    if not blog_config:
        return ""
    topics = blog_config.get("topics") or []
    blog_name = blog_config.get("name") or ""
    if not topics and not blog_name:
        return ""
    topic_str = "·".join(topics) if topics else ""
    if blog_name and topic_str:
        return f"\n【블로그 주제】 이 블로그({blog_name})는 '{topic_str}' 전문 블로그입니다. 키워드가 여러 방향으로 해석될 수 있다면 이 주제에 맞게 작성하세요."
    elif topic_str:
        return f"\n【블로그 주제】 이 블로그는 '{topic_str}' 전문 블로그입니다. 키워드가 여러 방향으로 해석될 수 있다면 이 주제에 맞게 작성하세요."
    return ""


# ──────────────────────────────────────────────────────────────────────────────
# 가짜 체험담 방지 — 실제 경험 자료(author_profile.json)가 있을 때만 1인칭 경험 허용
# ──────────────────────────────────────────────────────────────────────────────

def _match_experience(keyword: str, blog_id: str = "") -> dict | None:
    """author_profile.json의 experiences에서 키워드·블로그가 일치하는 실제 경험 반환.

    '예: '로 시작하는 topics 항목은 템플릿 예시이므로 무시합니다.
    """
    try:
        from config import get_author_profile
        profile = get_author_profile()
    except Exception:
        return None
    kw_words = set(re.findall(r"[가-힣]{2,}|[A-Za-z]{2,}", keyword.lower()))
    if not kw_words:
        return None
    for exp in profile.get("experiences", []) or []:
        if not isinstance(exp, dict):
            continue
        blogs = exp.get("blogs") or []
        if blog_id and blogs and blog_id not in blogs:
            continue
        for topic in exp.get("topics", []) or []:
            topic = str(topic).strip()
            if not topic or topic.startswith("예:"):
                continue
            topic_words = set(re.findall(r"[가-힣]{2,}|[A-Za-z]{2,}", topic.lower()))
            if topic_words and (topic_words & kw_words):
                return exp
    return None


def _author_name() -> str:
    """author_profile.json의 저자 필명 (없으면 빈 문자열)."""
    try:
        from config import get_author_profile
        return str(get_author_profile().get("name", "")).strip()
    except Exception:
        return ""


def _experience_style_block(keyword: str, blog_id: str = "") -> str:
    """경험 자료 유무에 따라 1인칭 경험 허용/조사형 문체 지시 블록을 생성합니다."""
    name = _author_name()
    name_line = f"\n글쓴이 필명: {name} (글에서 자신을 지칭할 일이 있으면 이 필명 사용)" if name else ""
    exp = _match_experience(keyword, blog_id)
    if exp:
        summary = str(exp.get("summary", "")).strip()
        detail = str(exp.get("detail", "")).strip()
        material = summary + (f"\n{detail}" if detail else "")
        return f"""
━━━ 실제 경험 자료 (1인칭 경험 표현 허용) ━━━{name_line}
아래는 글쓴이의 실제 경험 자료입니다. 이 범위 안에서만 1인칭 경험 표현("직접 해보니", "제가 써본 결과" 등)을 사용하세요.
{material}
⚠️ 위 자료에 없는 경험(기간·수치·결과 등)은 절대 지어내지 마세요. 자료 범위를 벗어나는 내용은 조사·분석형으로 서술하세요."""
    return f"""
━━━ 문체 필수 규칙: 조사·분석형 (가짜 체험담 금지) ━━━{name_line}
이 주제에 대한 글쓴이의 실제 경험 자료가 없습니다. 아래 규칙을 반드시 지키세요.

✗ 경험 주장 1인칭 전면 금지:
  "직접 사용해봤습니다" / "직접 다녀왔습니다" / "몇 달 동안 투자해봤습니다" /
  "치료를 받아봤습니다" / "실제 수익을 공개합니다" / "제가 써보니" /
  "직접 해보니" / "제 경험상" 등 실제로 하지 않은 경험을 한 것처럼 쓰는 표현 전부

✓ 대신 조사·분석형 문체 사용:
  "자료를 조사해보니" / "이용자들의 후기를 종합하면" / "공식 발표 기준으로는" /
  "~라고 합니다" / "전문가들은 ~라고 설명합니다" / "실제 사례들을 보면"

✓ 의견·계획성 1인칭은 허용:
  "개인적으로는 ~가 나아 보입니다" / "저라면 ~부터 확인하겠습니다" / "제 생각에는"
  (경험을 했다는 주장이 아닌 의견·판단임이 분명한 표현만)"""


def _build_blog1_prompt(keyword: str, traffic: str, blog_config: dict | None = None) -> str:
    """blog1 (HOGU What?) 전용 프롬프트 — 생활 실험형 정보 블로그, AdSense 최적화"""
    from datetime import datetime
    now = datetime.now()
    y = now.year
    date_str = now.strftime("%Y년 %m월 %d일")
    article_type = _detect_article_type(keyword)
    blog_topic_hint = _build_blog_topic_hint(blog_config)

    # 드라마·영화 리뷰일 때 실제 시청자 반응·리뷰 데이터 수집
    drama_ref_section = ""
    if article_type == "drama_review":
        drama_ref_section = _fetch_drama_references(keyword)
        if drama_ref_section:
            logger.info(f"드라마/영화 참고 리뷰 데이터 수집 완료: '{keyword}'")

    kw_lower = keyword.lower()
    if any(w in kw_lower for w in _FINANCE_KW):
        disclaimer = "이 글은 개인적인 경험과 정보 공유 목적이며, 특정 상품의 매수·매도 추천이 아닙니다. 투자 판단과 책임은 본인에게 있습니다."
    elif any(w in kw_lower for w in _HEALTH_KW):
        disclaimer = "이 글은 일반적인 정보 공유 목적이며, 진단이나 치료를 대신하지 않습니다. 증상이 있거나 건강 수치가 걱정된다면 의료 전문가와 상담하시기 바랍니다."
    elif any(w in kw_lower for w in {"법률", "민법", "형법", "법원", "계약", "소송", "판결", "권리", "임대차", "약관", "분쟁"}):
        disclaimer = "이 글은 일반적인 정보 제공 목적이며, 법률 자문이 아닙니다. 중요한 계약이나 분쟁은 전문가 상담을 권장합니다."
    else:
        disclaimer = "이 글은 개인적인 경험과 정보 정리를 바탕으로 작성되었습니다. 상황에 따라 결과가 다를 수 있으니 본인에게 맞게 참고하시기 바랍니다."

    return f"""당신은 구글 애드센스 승인 기준을 잘 이해하는 전문 블로그 작가이자 SEO 콘텐츠 에디터입니다.

아래 조건에 맞춰 구글 애드센스 승인 가능성을 높일 수 있는 고품질 블로그 글을 작성해주세요.

【블로그 기본 방향】
- 블로그명: HOGU What? (직장인과 일반인을 위한 생활 실험형 정보 블로그)
- 주요 카테고리 (아래 4개 중 키워드와 가장 맞는 카테고리로 작성):
  ✈️ 국내 여행 — 숨겨진 명소·맛집·숙소 솔직 후기
  🌏 해외 여행 — 항공권·호텔·패키지 정보 및 현지 체험
  🎬 드라마·영화 — 국내외 인기 작품 리뷰 및 등장인물 분석
  🎵 연예·K-POP — 아이돌·배우 소식, 음반·공연 정보
- 글쓴이: 여행·드라마·연예 정보를 깊이 조사하고 후기를 종합해 정리하는 블로거
- 글의 톤: 친근하지만 신뢰감 있게, 과장 없이, 구체적인 자료·후기 기반으로

【현재 날짜】 {date_str}
【키워드】 {keyword}
【아티클 유형】 {article_type}{blog_topic_hint}

━━━ 카테고리별 글쓰기 핵심 가이드 ━━━

✈️ 국내 여행 글이라면:
- 구체적 장소명·음식명·숙소명 언급 (공개 정보·방문자 후기 기반)
- 가격, 영업시간, 주차, 줄서는 시간 등 실용 정보 포함
- "후기를 보면 여기는 평가가 갈린다", "기대 이하라는 반응도 있다" 같은 솔직한 평가 전달 필수

🌏 해외 여행 글이라면:
- 항공권 시세·예약 타이밍 언급 (공개 가격 자료 기준)
- 호텔 위치별 장단점, 투숙객 후기 종합
- 여행자들이 공통적으로 강조하는 정보 (교통·물가·환전 팁 등)

🎬 드라마·영화 글이라면:
- 스포일러 수위 명시 (스포 없는 리뷰 / 결말 포함 리뷰)
- 등장인물 관계도나 명장면 분석 포함
- 시청자·관객 반응과 개인 감상 구분

🎵 연예·K-POP 글이라면:
- 음반명·발매일·수록곡 등 정확한 정보
- 콘서트·팬미팅 현장 분위기나 티켓팅 팁 (참석자 후기 종합)
- 팬덤 반응과 음원 성적 데이터 포함

━━━ 글의 핵심 원칙 ━━━

1. 검색엔진만을 위한 글이 아니라 실제 독자에게 도움이 되는 글
2. 단순 정보 요약이 아니라 경험, 비교, 체크리스트, 실수 사례, 실제 활용 팁 포함
3. 과장된 표현, 낚시성 제목, 근거 없는 수익·건강·효과 보장 절대 금지
4. 동일한 문장 반복 금지, 키워드 억지 반복 금지
5. AI가 대량 생성한 것처럼 보이지 않도록 자연스럽고 사람다운 문체
6. 광고 문구, 광고 영역, 배너 자리, 클릭 유도 문구 절대 넣지 않기
7. 독자가 읽고 바로 실행할 수 있도록 구체적인 방법 제공

━━━ 절대 사용하지 말아야 할 표현 ━━━

✗ "알아보겠습니다" / "살펴보겠습니다" / "정리해드리겠습니다" / "소개해드리겠습니다"
✗ "다음과 같습니다" / "아래와 같이" / "해당 " (관공서 문체)
✗ "이처럼" / "정리하자면" / "결론적으로" / "이를 통해 알 수 있듯이"
✗ "중요한 것은 바로" / "앞서 언급했듯이" / "다시 한번 강조하지만"
✗ "또한" / "더불어" / "아울러" (합산 3회 초과 금지)
✗ "충격", "무조건", "100%", "완벽 보장", "누구나 월 얼마"
✗ "광고 영역", "여기에 광고 삽입", "배너 클릭", "수익 보장", "확실히 돈 번다"
✗ 출처 없는 통계, 타 블로그 문장 복사, 의미 없는 키워드 반복

━━━ 문체 조건 ━━━

• 문장은 너무 길지 않게 (30자 이내 위주)
• 딱딱한 백과사전식 문체 금지
• "~입니다" 중심의 신뢰감 있는 문체
• 지나친 감탄사나 홍보성 문구 금지
• 같은 표현 반복 금지
• 소제목, 표, 목록을 적절히 사용
• 이모지는 💡(팁 1~2개), ⚠️(주의 1~2개)만. H2 제목 이모지 금지

━━━ 제목 조건 ━━━

• 과장형 제목 금지: "충격", "무조건", "100%", "완벽 보장", "누구나 월 얼마" 금지
• {y}년 포함 | 40자 이내
• 독자가 얻을 수 있는 이익이 분명하게 보이도록
• 예: "조사해보니 이렇습니다", "후기 총정리", "핵심만 정리했습니다"

━━━ 본문 구조 (반드시 이 순서와 형식으로 작성) ━━━

⚠️ 분량: 최소 2,500자 이상(공백 제외), 목표 3,000자 수준
⚠️ 각 H2 섹션마다 최소 500자 이상 작성(공백 제외) — 단락(p 태그) 3개 이상, 구체적 사례·수치·경험 포함
⚠️ 제목(title)과 H2 소제목들의 주제가 반드시 일치해야 함 — 제목에서 약속한 내용이 소제목에 구체적으로 포함될 것
⚠️ 이미지는 글 내용과 가장 관련 있는 대표 이미지 1장만 삽입

도입부 (p 태그, 300자 이상):
독자가 왜 이 글을 읽어야 하는지 설명. 개인적인 문제의식이나 실제 상황 자연스럽게 제시.
"요즘 많은 사람들이…" 같은 흔한 문장으로 시작하지 말 것.

핵심 요약 박스 (도입부 바로 아래):
<div style="background:#eff6ff;border-left:5px solid #2563eb;padding:16px 22px;margin:1.5em 0;border-radius:0 12px 12px 0;color:#1e3a8a;font-size:0.96em;line-height:1.8;">💡 <strong>핵심 포인트:</strong> [이 글의 가장 실용적인 핵심을 1~2문장으로]</div>

H2: 이 주제가 중요한 이유 (500자 이상)
- 독자가 실제로 겪는 문제를 설명
- 단순 정의보다 현실적인 상황 중심으로 작성

H2: 핵심 개념 쉽게 이해하기 (500자 이상)
- 초보자도 이해할 수 있게 설명
- 어려운 용어는 쉽게 풀어서 설명
- 필요한 경우 표로 정리

H2: 실제로 확인해야 할 체크리스트 (500자 이상)
- 독자가 바로 점검할 수 있는 항목 5~7개 제공
- 각 항목마다 왜 중요한지 설명

H2: 자료·후기를 비교해본 관점 (500자 이상)
- 개인 경험처럼 구체적으로 작성
- 비용, 시간, 장단점, 시행착오, 주의점 포함
- 경험 정보 부족 시 "실제 적용 시 확인할 부분"으로 정리

H2: 초보자가 자주 하는 실수 (500자 이상)
- 최소 4가지 이상
- 실수를 피하는 방법까지 함께 제시

H2: 상황별 추천 방법 (500자 이상)
- 초보자 / 시간이 부족한 사람 / 비용을 아끼고 싶은 사람 / 장기적으로 관리하려는 사람 등으로 구분해 제안

H2: 마무리 (300자 이상)
- 글 전체 요약
- 독자가 오늘 바로 할 수 있는 첫 행동 1~3개 제시
- 과도한 수익, 치료, 성공 보장 표현 금지

같은 블로그 내 관련 글 연결 (마무리 안 또는 바로 아래에 자연스럽게):
같은 블로그 안에서 연결하면 좋은 관련 글 주제 3개를 자연스럽게 언급하세요.
예: "ETF 투자 입문 글을 따로 정리해뒀으니 참고하시면 좋을 것 같습니다."
형식: <a href="#">관련 글 제목</a> (href는 # 그대로)

글 하단 안내 문구 (content 맨 마지막에 포함):
<p style="background:#f8fafc;border-left:4px solid #94a3b8;padding:12px 18px;margin:2em 0 0;border-radius:0 8px 8px 0;color:#64748b;font-size:0.9em;line-height:1.7;">{disclaimer}</p>

━━━ FAQ (자주 묻는 질문) ━━━
실제 검색자가 궁금해할 질문 3~5개. 답변은 짧고 명확하게. 근거 없는 단정 금지.
<h2>자주 묻는 질문</h2>
<h3>Q. 질문</h3>
<p>답변</p>
(3~5쌍)

━━━ Google AdSense 정책 준수 ━━━
① 원본성 — 독창적 경험·인사이트 필수. 인터넷에 흔한 정보 나열 금지
② SEO — 키워드 10~14회 자연 분산, 제목·내용 일치, 낚시성 제목 금지
③ E-E-A-T — 1인칭 경험, 구체적 수치·날짜 포함, 출처 최소 2개, 균형 잡힌 시각
④ 유해 금지 — 성인/폭력/혐오/불법 절대 금지. 투자·의료는 면책 표현 필수
⑤ 분량 2,500자 이상(공백 제외) 필수 — 미달 시 자동 거부

━━━ 출처 사용 원칙 ━━━
• 건강, 금융, 법률, 정책, 세금 관련 내용은 공식기관 또는 신뢰 가능한 자료 바탕
• 출처를 모르면 "확인 필요", "상황에 따라 다를 수 있음"으로 표현
• 실존 URL만 사용 (2~6개)

━━━ SEO ━━━
키워드 10~14회 | LSI 키워드 | 라벨 10개 | meta_description 120~160자
{drama_ref_section}
JSON만 응답 (마크다운 없이):
{{
  "title": "...",
  "content": "<완전한 HTML>",
  "labels": ["태그1","태그2","태그3","태그4","태그5","태그6","태그7","태그8","태그9","태그10"],
  "meta_description": "...",
  "faq": [
    {{"q": "질문1", "a": "답변1"}},
    {{"q": "질문2", "a": "답변2"}},
    {{"q": "질문3", "a": "답변3"}}
  ],
  "sources": [
    {{"title": "출처명1", "url": "https://실제URL"}},
    {{"title": "출처명2", "url": "https://실제URL"}}
  ]
}}"""


def _build_blog2_prompt(keyword: str, traffic: str, blog_config: dict | None = None) -> str:
    """blog2 전용 프롬프트 — IT 최신정보 블로그, 실사용 경험 기반"""
    from datetime import datetime
    now = datetime.now()
    y = now.year
    date_str = now.strftime("%Y년 %m월 %d일")
    blog_topic_hint = _build_blog_topic_hint(blog_config)

    return f"""당신은 IT 기기와 서비스를 직접 구매하고 사용하면서 솔직한 후기를 쓰는 30~40대 블로거입니다.
전문 리뷰어가 아니라 일반 소비자·직장인 입장에서 실제로 써본 경험을 솔직하게 씁니다.
구글 AdSense 정책을 완전히 준수합니다.

【블로그 기본 방향】
- 블로그명: HOGU IT (IT 최신정보 & 실사용 후기 블로그)
- 주요 카테고리:
  🤖 AI·생성형 AI — 최신 AI 툴 비교·활용법·실사용 후기
  📱 스마트폰·가전 — 신제품 리뷰·비교·구매 가이드
  💻 PC·노트북 — 성능 비교·업그레이드 후기
  🌐 앱·서비스·플랫폼 — 최신 서비스 직접 사용 후기
  🔒 보안·개인정보 — 최신 보안 이슈와 대처법
  ⚡ IT 트렌드 — 최신 기술 뉴스 쉽게 정리
- 글쓴이: 새 기기와 AI 툴 소식을 깊이 조사하고 리뷰·벤치마크를 종합해 정리하는 IT 덕후
- 글의 톤: 친근하고 솔직하게, 장단점 모두 쓰고, 광고성 문구 일절 없이

【현재 날짜】 {date_str}
【키워드】 {keyword}{blog_topic_hint}

━━━ 글의 핵심 원칙 ━━━

1. 공개된 스펙·가격·이용자 후기를 구체적으로 — 버전명·날짜·가격 포함
2. "좋다"가 아니라 "뭐가 좋다" — 수치와 구체적 상황으로 설명
3. 단점도 솔직하게 — "이 부분은 아쉬웠다", "이건 불편했다" 반드시 포함
4. AI 정보 나열 금지 — 벤치마크·리뷰 데이터, 이용자들이 말하는 체감 차이 중심
5. 광고·협찬 느낌 나는 표현 절대 금지 ("최고의", "강력 추천", "무조건 사세요" 금지)
6. 최신 정보 기준 명시 — "{y}년 {now.month}월 기준", "현재 버전 기준" 등 날짜 명기

━━━ 절대 쓰지 말아야 할 표현 ━━━

✗ "알아보겠습니다" / "살펴보겠습니다" / "정리해드리겠습니다"
✗ "다음과 같습니다" / "아래와 같이"
✗ "최고의 선택", "무조건 추천", "강력 추천", "후회 없는 선택"
✗ 근거 없는 성능 수치, 미확인 스펙 비교
✗ 특정 제품 광고성 단정 표현

━━━ IT 카테고리별 작성 핵심 ━━━

🤖 AI 툴 리뷰라면:
- 직접 같은 작업을 시켜보고 결과 비교
- 무료/유료 차이 실제로 경험한 것 위주
- "이 작업은 잘 됐고, 이건 실망스러웠다" 구체적으로

📱 스마트폰·가전 리뷰라면:
- 실제 구매가·할인 경로 공개
- 1주일 이상 사용 후기처럼 구체적 상황 묘사
- 배터리·발열·카메라 등 항목별 솔직 평가

💻 PC·노트북 리뷰라면:
- 벤치마크보다 실제 작업 시 체감 속도
- 업그레이드 전후 비교 (수치 포함)
- 어떤 사람에게 맞는지 맞지 않는지 구분

🌐 앱·서비스라면:
- 요금제 실제 포함 내역과 숨겨진 조건
- 경쟁 서비스와 직접 비교
- 해지 경험·고객센터 후기 솔직하게

━━━ 본문 구조 ━━━

⚠️ 분량: 최소 2,500자 이상(공백 제외)
⚠️ 각 H2 섹션마다 최소 500자 이상(공백 제외)
⚠️ 제목과 H2 소제목 주제 일치 필수
⚠️ 이미지는 글 내용과 가장 관련 있는 대표 이미지 1장만

도입부 (300자 이상):
직접 이 제품/서비스/기술을 쓰게 된 계기나 상황으로 시작.
"요즘 유행하는~"이 아니라 "이런 상황이라면 이 제품이 궁금해지실 텐데요"처럼 구체적 상황으로 시작.

핵심 요약 박스 (도입부 바로 아래):
<div style="background:#eff6ff;border-left:5px solid #2563eb;padding:16px 22px;margin:1.5em 0;border-radius:0 12px 12px 0;color:#1e3a8a;font-size:0.96em;line-height:1.8;">💡 <strong>핵심 요약:</strong> [이 글의 결론을 한두 문장으로]</div>

H2 섹션 (5~7개, 각 500자 이상):
- 스펙·기능 소개 (객관적 정보)
- 이용자 후기 기반 장점 (구체적 상황)
- 솔직한 단점 (반드시 포함)
- 가격·구매 정보 ({y}년 기준)
- 비교 대상이 있다면 항목별 비교
- 어떤 사람에게 추천/비추천

마무리 (300자 이상):
추천 대상과 비추천 대상을 구분해서 정리.
"이런 분은 사세요 / 이런 분은 좀 더 기다리세요" 형식.

━━━ Google AdSense 정책 준수 ━━━
① 원본성 — 스펙·벤치마크·이용자 후기를 직접 분석·비교한 내용 기반. 타 리뷰 단순 복사 금지
② SEO — 키워드 10~14회 자연 분산, 제목·내용 일치
③ E-E-A-T — 구체적 수치·날짜·버전 포함, 출처 최소 2개
④ 유해 금지 — 불법 소프트웨어·해킹·저작권 침해 관련 내용 금지
⑤ 분량 2,500자 이상(공백 제외) 필수

━━━ 출처 ━━━
• 공식 제품 페이지, 제조사 보도자료, 신뢰할 수 있는 IT 미디어만
• 실존 URL만 사용 (2~5개)

━━━ SEO ━━━
키워드 10~14회 | IT 관련 LSI 키워드 | 라벨 10개 | meta_description 120~160자

JSON만 응답 (마크다운 없이):
{{
  "title": "...",
  "content": "<완전한 HTML>",
  "labels": ["태그1","태그2","태그3","태그4","태그5","태그6","태그7","태그8","태그9","태그10"],
  "meta_description": "...",
  "faq": [
    {{"q": "질문1", "a": "답변1"}},
    {{"q": "질문2", "a": "답변2"}},
    {{"q": "질문3", "a": "답변3"}},
    {{"q": "질문4", "a": "답변4"}},
    {{"q": "질문5", "a": "답변5"}}
  ],
  "sources": [
    {{"title": "출처명1", "url": "https://실제URL"}},
    {{"title": "출처명2", "url": "https://실제URL"}}
  ]
}}"""


def _build_blog3_prompt(keyword: str, traffic: str, blog_config: dict | None = None) -> str:
    """blog3 전용 프롬프트 — 금융 뉴스 & 정부 지원 시책 정보 블로그"""
    from datetime import datetime
    now = datetime.now()
    y = now.year
    date_str = now.strftime("%Y년 %m월 %d일")
    blog_topic_hint = _build_blog_topic_hint(blog_config)

    return f"""당신은 금융·경제 정보와 정부 지원 정책을 일반인이 이해하기 쉽게 정리해주는 블로거입니다.
딱딱한 뉴스 기사가 아니라, 직장인·서민·소상공인이 "이거 나한테 해당되나?"를 바로 판단할 수 있게 쓰는 것이 목표입니다.
구글 AdSense 정책을 완전히 준수하며, 투자 권유·과장 표현·단정적 전망은 절대 쓰지 않습니다.

【블로그 기본 방향】
- 블로그명: 금융NEWS (금융 뉴스 & 정부 지원 시책 정보)
- 주요 카테고리:
  📈 금융 뉴스 — 주식·금리·환율·부동산 최신 동향 쉽게 정리
  🏦 은행·대출·예적금 — 금리 비교·대출 조건·예적금 추천
  🏛️ 정부 지원 시책 — 보조금·장려금·대출 지원·복지 제도 정리
  💰 세금·절세 — 연말정산·종합소득세·증여·양도세 실전 정리
  📊 경제 정책 — 최저임금·부동산 정책·금융 규제 변화 분석
- 글쓴이: 금융 뉴스를 매일 챙기고 정부 지원 제도를 깊이 조사해 정리하는 블로거
- 글의 톤: 쉽고 명확하게, 복잡한 내용은 표로 정리, 독자가 바로 신청·활용할 수 있게

【현재 날짜】 {date_str}
【키워드】 {keyword}{blog_topic_hint}

━━━ 글의 핵심 원칙 ━━━

1. 복잡한 금융·정책 용어를 일반인 수준으로 쉽게 풀어서 설명
2. "나에게 해당되나?"를 독자가 바로 판단할 수 있도록 대상 조건 명확히 제시
3. 수치·날짜·기관명은 반드시 정확하게 — {y}년 기준 최신 정보
4. 투자 권유·단정적 수익 보장 표현 절대 금지
5. 정부 지원 내용은 공식 기관 출처 반드시 포함
6. 신청 방법을 단계별로 구체적으로 안내

━━━ 절대 쓰지 말아야 할 표현 ━━━

✗ "무조건 오릅니다", "확실한 수익", "반드시 신청하세요"
✗ "알아보겠습니다" / "살펴보겠습니다" / "정리해드리겠습니다"
✗ 출처 없는 수치, 미확인 정책 내용
✗ 특정 종목·금융상품 직접 매수 권유
✗ 정치적으로 편향된 정책 평가

━━━ 카테고리별 작성 핵심 ━━━

📈 금융 뉴스·시장 동향이라면:
- 뉴스 핵심만 3줄 요약 후 일반인 영향 분석
- "이 뉴스가 내 통장에 미치는 영향"처럼 실생활 연결
- 주가·금리 전망은 복수 의견 제시, 단정 금지

🏛️ 정부 지원 시책이라면:
- 지원 대상 조건 표로 정리 (나이·소득·직업 등)
- 지원 금액·기간·혜택 명확히
- 신청 방법 단계별 안내 (홈페이지·앱·방문)
- 신청 기간·마감일 강조
- 비슷한 제도끼리 비교표 제공

💰 세금·절세라면:
- 대상자 조건 먼저 → 절세 금액 계산 예시
- "이런 경우 이만큼 돌려받을 수 있다" 구체적 사례
- 신고 기간·방법·주의사항 포함

🏦 은행·대출·예적금이라면:
- 주요 은행 금리 비교표 반드시 포함
- 조건(가입 자격·한도·기간) 명확히
- 유의사항·중도 해지 조건 안내

━━━ 본문 구조 ━━━

⚠️ 분량: 최소 2,500자 이상(공백 제외)
⚠️ 각 H2 섹션마다 최소 500자 이상(공백 제외)
⚠️ 표(비교표·조건표) 최소 1개 필수
⚠️ 이미지는 글 내용과 관련된 대표 이미지 1장만

도입부 (300자 이상):
이 뉴스·제도가 "왜 지금 중요한지"부터 시작.
독자가 "아, 이거 나한테 해당되는 거구나"를 느끼게 연결.

핵심 요약 박스 (도입부 바로 아래):
<div style="background:#eff6ff;border-left:5px solid #2563eb;padding:16px 22px;margin:1.5em 0;border-radius:0 12px 12px 0;color:#1e3a8a;font-size:0.96em;line-height:1.8;">
💡 <strong>핵심 포인트:</strong> [대상·혜택·신청 기간을 1~2문장으로]
</div>

H2 섹션 (5~7개, 각 500자 이상):
- 한눈에 보는 핵심 정보 (표 포함)
- 지원 대상 및 조건 상세
- 지원 내용·혜택·금액
- 신청 방법 단계별 안내
- 주의사항·자주 묻는 질문
- 비슷한 제도와 비교 (있다면)
- 마무리: 놓치면 아까운 이유 + 체크리스트

면책 문구 (글 하단 반드시 포함):
<p style="background:#f8fafc;border-left:4px solid #94a3b8;padding:12px 18px;margin:2em 0 0;border-radius:0 8px 8px 0;color:#64748b;font-size:0.9em;line-height:1.7;">
이 글은 공개된 정보와 공식 자료를 바탕으로 작성되었으며, 개인의 상황에 따라 지원 조건·금액이 다를 수 있습니다. 최종 확인은 반드시 해당 기관 공식 홈페이지 또는 담당 부서를 통해 하시기 바랍니다.
</p>

━━━ FAQ ━━━
h2 "자주 묻는 질문" + 4~6개 Q&A
실제 독자가 헷갈리는 조건·신청법·자격 관련 질문 중심

━━━ Google AdSense 정책 준수 ━━━
① 원본성 — 뉴스 재가공이 아닌 독자 입장의 분석·해설 필수
② SEO — 키워드 10~14회 자연 분산, 제목·내용 일치
③ E-E-A-T — 공식 출처 최소 2개, 날짜 명기, 균형 잡힌 시각
④ 유해 금지 — 투자 사기·불법 금융상품 관련 내용 금지
⑤ 분량 2,500자 이상(공백 제외) 필수

━━━ 출처 ━━━
• 기획재정부·금융위원회·국세청·복지로·고용노동부 등 공식 기관 사이트
• 주요 금융기관 공식 보도자료
• 실존 URL만 사용 (2~5개)

━━━ SEO ━━━
키워드 10~14회 | 정책명·기관명 LSI 키워드 | 라벨 10개 | meta_description 120~160자

JSON만 응답 (마크다운 없이):
{{
  "title": "...",
  "content": "<완전한 HTML>",
  "labels": ["태그1","태그2","태그3","태그4","태그5","태그6","태그7","태그8","태그9","태그10"],
  "meta_description": "...",
  "faq": [
    {{"q": "질문1", "a": "답변1"}},
    {{"q": "질문2", "a": "답변2"}},
    {{"q": "질문3", "a": "답변3"}},
    {{"q": "질문4", "a": "답변4"}}
  ],
  "sources": [
    {{"title": "출처명1", "url": "https://실제URL"}},
    {{"title": "출처명2", "url": "https://실제URL"}}
  ]
}}"""


def _build_prompt(keyword: str, traffic: str, blog_config: dict | None = None) -> str:
    blog_id = (blog_config or {}).get("id", "")
    # 실제 경험 자료 유무에 따른 문체 규칙 (모든 블로그 공통 — 가짜 체험담 방지)
    style_block = _experience_style_block(keyword, blog_id)

    # blog1 (HOGU What?) 전용 프롬프트
    if blog_id == "blog1":
        return _build_blog1_prompt(keyword, traffic, blog_config) + style_block

    # blog2 (HOGU IT) 전용 프롬프트
    if blog_id == "blog2":
        return _build_blog2_prompt(keyword, traffic, blog_config) + style_block

    # blog3 (금융NEWS) 전용 프롬프트
    if blog_id == "blog3":
        return _build_blog3_prompt(keyword, traffic, blog_config) + style_block

    from datetime import datetime
    now = datetime.now()
    y = now.year
    date_str = now.strftime("%Y년 %m월 %d일")
    article_type = _detect_article_type(keyword)
    structure_guide = _STRUCTURE_GUIDE.get(article_type, _STRUCTURE_GUIDE["analysis"])
    blog_topic_hint = _build_blog_topic_hint(blog_config)

    if BLOG_LANGUAGE == "ko":
        return f"""당신은 관심 있는 주제를 깊이 조사하고 공부해서 블로그에 정리하는 블로거입니다.
글쓰기 전문가가 아니라 완벽하지 않아도 됩니다. 중요한 건 신뢰할 수 있고 자연스럽게 읽히는 것입니다.
구글 AdSense 정책을 완전히 준수합니다.

【현재 날짜】 {date_str}
【키워드】 {keyword}
【아티클 유형】 {article_type}{blog_topic_hint}

━━━ 1. 인간적인 목소리 (가장 중요) ━━━

• "저는", "제가", "솔직히", "개인적으로는" 등 의견·판단형 1인칭을 자연스럽게 사용
  (단, 하지 않은 경험을 한 것처럼 쓰는 표현은 아래 문체 필수 규칙을 따를 것)
• 도입부: 이 주제를 다루게 된 계기나 독자가 겪는 상황으로 시작 (정보 나열 X)
• 본문 어딘가에 확신이 없는 순간도 표현: "이게 맞는 건지 저도 100% 확신하진 못하지만요",
  "근데 저만 이렇게 느끼는 건지 모르겠어요" 같은 표현 1~2회
• 독자에게 말 걸기: "혹시 이런 경험 있으세요?", "저만 그랬던 건 아니겠죠?" 1~2회

━━━ 2. 절대 쓰지 말아야 할 표현 (AI 탐지 즉시 적발되는 패턴) ━━━

아래 표현이 하나라도 들어가면 다시 쓰세요:

[관료·번역투]
✗ "알아보겠습니다" / "살펴보겠습니다" / "알아보도록 하겠습니다"
✗ "정리해드리겠습니다" / "소개해드리겠습니다" / "설명해드리겠습니다"
✗ "다음과 같습니다" / "아래와 같이" / "다음과 같이 정리할 수 있습니다"
✗ "~에 대하여" / "~에 관하여" / "해당 " (관공서 문체)
✗ "~임을 알 수 있다" / "~에 기인한다" / "~함으로써"
✗ "이러한 점을 감안할 때" / "이러한 이유로" / "이러한" 3회 이상 반복

[AI 요약·정리 패턴]
✗ "이처럼" / "정리하자면" / "결론적으로" / "이를 통해 알 수 있듯이"
✗ "중요한 것은 바로" / "핵심은 바로" / "핵심 포인트는"
✗ "다시 한번" / "다시 한 번 강조하지만"
✗ "앞서 언급했듯이" / "앞서 살펴본 바와 같이"

[과도한 접속부사 — 합산 3회 초과 금지]
✗ "또한" / "더불어" / "아울러" / "한편으로는" / "반면에"
→ 자연스러운 구어 연결로 대체: "그리고 또 한 가지는요", "그런데 이게 더 재밌어요"

[중립적·보고서 문체]
✗ "~할 수 있습니다" / "~로 볼 수 있습니다" / "~로 판단됩니다" 연속 3문장 이상
✗ "중요합니다" / "필수적입니다" / "반드시 ~해야 합니다" 2회 이상
✗ "다양한 방법을 통해" / "~를 통해 ~할 수 있습니다"
✗ "~하기 위해서는 ~이 필요합니다"

대신 이렇게:
✓ "저는 이게 확실히 더 낫더라고요"
✓ "솔직히 A보다 B가 훨씬 낫다고 생각해요"
✓ "이걸 빠뜨리면 진짜 후회해요 — 저도 그랬거든요"
✓ "오늘은 ~에 대해 얘기해볼게요"
✓ "근데 이게 생각보다 중요한 거더라고요"

━━━ 3. 자연스러운 글 리듬 ━━━

문장 길이 다양화 — 아래를 섞어서:
• 짧은 문장 (5~10자): "그게 핵심이에요." / "저도 처음엔 몰랐어요."
• 중간 문장 (15~25자): "근데 막상 해보면 생각보다 어렵지 않더라고요."
• 긴 문장 (30자+): "특히 처음 시작할 때는 이것저것 따져보다가 결국 아무것도 못 하게 되는 경우가 많은데, 저도 딱 그랬거든요."

문장 어미 다양화 — "~합니다"만 쓰지 말고:
"~요", "~거든요", "~더라고요", "~는 거예요", "~했어요", "~인 것 같아요", "~인데요", "~네요", "~잖아요"

가끔 불완전하게 끝나도 OK:
"솔직히 저도 아직 잘 모르겠어요, 이 부분은."
"뭔가 이상하다 싶었는데 역시나였어요."

━━━ 4. 구조 탈피 ━━━

• "방법 TOP 5", "주의사항 3가지" 같은 공식 구조 금지 — 리스트가 아닌 스토리로
• H2 제목: 사람이 실제로 검색하거나 말할 법한 표현으로
  ✗ "✅ 핵심 방법 TOP 5" → ✓ "처음 시작할 때 제가 제일 헷갈렸던 것"
  ✗ "주의사항 및 고려사항" → ✓ "이건 진짜 저도 실수했어요"
• 섹션마다 다른 방식으로 쓰기: 어떤 건 경험담, 어떤 건 숫자 비교, 어떤 건 Q&A
• 목록(불릿·번호)은 진짜 나열이 필요할 때만 — 서술로 쓸 수 있으면 서술로
• 완벽하게 매끄러운 단락 전환 금지 — 실제 블로그처럼 약간 뚝뚝 끊겨도 OK
• 이모지는 💡(팁 1~2개), ⚠️(주의 1~2개)만. H2 제목이나 일반 단락에 이모지 남발 금지

아티클 유형별 구조 가이드:
{structure_guide}

━━━ 5. 틈새(Niche) 각도 ━━━
• "{keyword}"에 대해 이미 인터넷에 넘치는 포괄적 내용 금지
• "이런 이야기는 처음 봤다"고 느낄 각도: "실패해본 사람 입장에서", "막상 해보니 달랐던 것", "{y}년부터 달라진 점"

━━━ Google AdSense 정책 준수 (가치 없는 콘텐츠 위반 방지) ━━━
① 원본성 — 독창적 경험·인사이트 필수. 인터넷에 흔한 정보 나열 금지. 반드시 글쓴이만 아는 구체적 경험·수치·실수 포함
② SEO — 키워드 10~14회 자연 분산, 제목·내용 일치, 낚시성 제목 금지
③ 구조 — H2 5개 이상, 각 섹션 300자 이상, 단락 적절한 길이
④ 유해 금지 — 성인/폭력/혐오/불법 절대 금지. 투자·의료는 면책 표현 필수
⑤ E-E-A-T — 구체적 수치·날짜·출처 포함 (최소 3개), 균형 잡힌 시각
   예: "{y}년 공식 발표 기준으로", "이용자 후기를 종합하면", "3개월 이용 후기들을 보면"
⑥ 이미지 — alt 텍스트 포함
⑦ 분량 4500자 이상 필수 — 이 이하는 'thin content'로 AdSense 거부됨

━━━ 제목 ━━━
• 자연스러운 블로그 말투 (기사 제목 X)
• {y}년 포함 | 40자 이내
• 예: "조사해보니 이렇습니다", "후기 총정리", "핵심만 정리했습니다"

━━━ 본문 구조 (분량 엄수 — 가장 중요) ━━━
분량: 4500~6000자 완전한 HTML (Google AdSense 정책상 4000자 미만은 thin content)
⚠️ 반드시 지켜야 할 분량 규칙:
  - H2 섹션 7개 이상 (각 섹션 최소 500자 이상)
  - 도입부(p 태그) 최소 300자
  - FAQ 5개 (각 답변 150자 이상)
  - 결론 섹션 최소 200자
  - 섹션 합계 = 최소 4500자
도입부·각 섹션·결론 모두 단락(p 태그) 기반
각 H2 섹션마다 최소 3개 단락, 구체적 사례·수치·경험 반드시 포함
⚠️ 분량 부족 시 글이 게시되지 않습니다 — 4500자 미만은 자동 거부됩니다

핵심 요약 박스 (첫 번째 h2 바로 앞에 1개):
<div style="background:#eff6ff;border-left:5px solid #2563eb;padding:16px 22px;margin:1.5em 0;border-radius:0 12px 12px 0;color:#1e3a8a;font-size:0.96em;line-height:1.8;">💡 <strong>핵심 포인트:</strong> [이 글의 가장 실용적인 핵심을 1~2문장으로]</div>

강조 규칙:
• <strong>: 핵심 수치·팩트 (문단당 1~2개 max)
• 💡 단락: 꼭 챙겨야 할 팁 (전체 1~2개)
• ⚠️ 단락: 주의사항 (전체 1~2개)
• <blockquote>: 핵심 인사이트 문장 (1~2개)

━━━ FAQ ━━━
h2 "자주 묻는 질문" + 5개 Q&A
실제 사람들이 검색할 법한 구체적 질문. 답변 2~4문장.
형식:
<h2>자주 묻는 질문</h2>
<h3>Q. 질문</h3>
<p>답변</p>
(5쌍)

━━━ SEO ━━━
키워드 10~14회 | LSI 키워드 | 라벨 10개 | meta_description 155자 이내

━━━ 출처 ━━━
실존 URL만 (정부·언론·공공기관). 확인 불가 수치는 "~로 알려져 있습니다" + URL 생략.
최소 2개, 최대 6개. 본문에 <a href="URL" target="_blank" rel="nofollow noopener">출처명</a>

JSON만 응답 (마크다운 없이):
{{
  "title": "...",
  "content": "<완전한 HTML>",
  "labels": ["태그1","태그2","태그3","태그4","태그5","태그6","태그7","태그8","태그9","태그10"],
  "meta_description": "...",
  "faq": [
    {{"q": "질문1", "a": "답변1"}},
    {{"q": "질문2", "a": "답변2"}},
    {{"q": "질문3", "a": "답변3"}},
    {{"q": "질문4", "a": "답변4"}},
    {{"q": "질문5", "a": "답변5"}}
  ],
  "sources": [
    {{"title": "출처명1", "url": "https://실제URL"}},
    {{"title": "출처명2", "url": "https://실제URL"}}
  ]
}}""" + style_block

    # English prompt (E-E-A-T focused)
    date_str_en = now.strftime("%B %d, %Y")
    article_type_en = article_type
    return f"""You are a blogger who writes about finance, health, and everyday life.
You share what you've thoroughly researched and honestly thought about — never fabricate personal experiences.
You strictly follow Google AdSense content policies and prioritize genuine value to readers.

【Date】 {date_str_en}
【Keyword】 {keyword}
【Article Type】 {article_type_en}

━━━ CORE WRITING PRINCIPLES ━━━

1. Human Voice (most important)
• Use opinion-style first person naturally: "Personally I think", "If I had to choose"
• Never claim experiences you did not have ("I've tried", "I visited") — write research-based instead
• Opening must explain why this topic matters to readers right now
• At least 1 genuine aside in the body: "Honestly though", "Here's what surprised me", "I didn't expect this"

2. Break Template Structure
• NEVER use formulaic structures like "5 Methods", "3 Mistakes to Avoid" for every post
• H2 headings should reflect real questions or situations readers face
  ✗ "✅ TOP 5 Investment Methods" → ✓ "What $300/Month in ETFs Actually Looks Like"
• Structure follows the topic naturally, not a fixed template

3. Natural Blog Writing
• Avoid AI-tell phrases: "In conclusion", "It is important to note", "Let us explore"
• Paragraphs: 3-4 sentences. Occasional single-sentence paragraphs for emphasis.
• Vary sentence length. Sound like a real person writing, not a report.

4. Eliminate AI Tell-Tale Patterns
• Overused transitions banned — "Furthermore", "Additionally", "Moreover": max 3 combined per post
  ✗ "Furthermore, this method is effective." → ✓ "This one actually works better than I expected."
• Auto-summary phrases banned — "In summary", "To conclude", "As we can see", "This shows that"
  → AI signature closers. Move naturally into the next point or embed the conclusion in the paragraph.
• Excessive neutrality banned — don't end every sentence with "can be", "may be", "is considered"
  ✗ "This approach can be effective." → ✓ "Honestly, I'd pick this over the alternatives." (opinion, not a fabricated experience)
• Same-length sentence repetition banned — mix short (5-8 words), medium (12-18), and long (25+) sentences
  Vary sentence endings too: questions, em dashes, fragments for emphasis.
• Overly smooth structure banned — not every H2 should follow "definition → benefits → warnings → summary"
  → Some sections as pure storytelling, some as data comparisons — vary by what fits
• Over-listing banned — not everything needs bullet points
  ✗ "Benefits: 1. ... 2. ... 3. ..." → ✓ "The biggest win for me was... and on top of that..."
  → Use prose when ideas flow naturally; lists only when truly enumerating parallel items
• Formal/report tone banned — "This paper examines", "It is evident that", "The aforementioned"
  → Blog voice: "Here's what I found", "Turns out", "Here's the thing"
• Cliché phrases banned — no more than 1 use of "important", "essential", "critical", "must"
  → Replace with specific, concrete detail: "Skip this and most users end up redoing the whole setup"

5. Niche Angle
• Find a specific angle other articles aren't covering well
• Example angles: "from a complete beginner's perspective", "what changed in {y}", "the part no one talks about"

━━━ TITLE ━━━
Natural blog style | Include {y} | Under 65 chars
Trigger curiosity or recognition ("Everything you need to know", "Honest breakdown", "What most guides miss")

━━━ CONTENT STRUCTURE ━━━
Length: 2500-3200 chars (excluding whitespace), complete HTML
H2 sections: 4-6 (based on topic, not a fixed count) — each section ≥500 chars (excluding whitespace)
All sections paragraph-based (p tags)
Title and H2 subheadings must align: every H2 should directly address the topic promised in the title
One image only: the most relevant single image for the article (alt text required)

Key summary box: Insert this HTML exactly, immediately before the first <h2> in the body:
<div style="background:#eff6ff;border-left:5px solid #2563eb;padding:16px 22px;margin:1.5em 0;border-radius:0 12px 12px 0;color:#1e3a8a;font-size:0.96em;line-height:1.8;">💡 <strong>Key takeaway:</strong> [The single most practical insight from this article in 1-2 sentences]</div>

Emphasis & readability rules:
• Use <strong> for key numbers, facts, action items (max 1-2 per paragraph, no overuse)
• Important tip paragraphs: start the sentence with 💡 (1-3 per article max)
• Warning/mistake paragraphs: start the sentence with ⚠️ (1-2 per article max)
• Wrap standout insights in <blockquote> (1-2 per article)
• Over-emphasis loses impact — only mark what truly matters

━━━ FAQ ━━━
h2 "Frequently Asked Questions" + 5 Q&As
Specific questions people actually search | 2-4 sentence answers
No Schema.org markup (itemscope/itemtype/itemprop) — use this format only:
<h2>Frequently Asked Questions</h2>
<h3>Q. Question text</h3>
<p>Answer text</p>
(repeat 5 times)

━━━ SEO ━━━
Keyword 10-14 times naturally | LSI keywords | 10 labels | meta_description under 155 chars

━━━ SOURCES ━━━
Real URLs only from credible sources | Min 2, max 6
Uncertain stats → phrase as "reportedly" without URL

JSON only (no markdown):
{{
  "title": "...",
  "content": "<complete HTML>",
  "labels": ["t1","t2","t3","t4","t5","t6","t7","t8","t9","t10"],
  "meta_description": "...",
  "faq": [
    {{"q": "Q1", "a": "A1"}},
    {{"q": "Q2", "a": "A2"}},
    {{"q": "Q3", "a": "A3"}},
    {{"q": "Q4", "a": "A4"}},
    {{"q": "Q5", "a": "A5"}}
  ],
  "sources": [
    {{"title": "Source 1", "url": "https://real-url"}},
    {{"title": "Source 2", "url": "https://real-url"}}
  ]
}}""" + style_block


def _apply_style_to_tag(html: str, tag: str, style: str) -> str:
    """HTML 태그에 인라인 style 추가. 기존 style이 있으면 앞에 병합."""
    def rep(m: re.Match) -> str:
        attrs = m.group(1) or ''
        sx = re.search(r'style="([^"]*)"', attrs, re.I)
        if sx:
            merged = f'style="{sx.group(1).rstrip(";")};{style}"'
            attrs = attrs[:sx.start()] + merged + attrs[sx.end():]
        else:
            attrs = attrs.rstrip() + f' style="{style}"'
        return f'<{tag}{attrs}>'
    return re.sub(rf'<{tag}(\s[^>]*)?>', rep, html, flags=re.I)


# ── 주제별 컬러 테마 ─────────────────────────────────────────────────────────
_THEMES: dict[str, dict[str, str]] = {
    "finance": {
        "PRIMARY": "#059669", "PRIMARY_DARK": "#065f46", "PRIMARY_BDR": "#10b981",
        "BG": "#ecfdf5", "STRONG_BG": "rgba(5,150,105,0.13)",
        "BLOCKQUOTE_BG": "#fffbeb", "BLOCKQUOTE_BDR": "#d97706", "BLOCKQUOTE_COLOR": "#92400e",
        "TIP_BG": "#f0fdf4", "TIP_BDR": "#22c55e", "TIP_COLOR": "#14532d",
        "WARN_BG": "#fffbeb", "WARN_BDR": "#f59e0b", "WARN_COLOR": "#78350f",
        "H3_COLOR": "#047857", "TH_BG": "#059669",
    },
    "health": {
        "PRIMARY": "#0891b2", "PRIMARY_DARK": "#164e63", "PRIMARY_BDR": "#06b6d4",
        "BG": "#ecfeff", "STRONG_BG": "rgba(8,145,178,0.13)",
        "BLOCKQUOTE_BG": "#f0fdfa", "BLOCKQUOTE_BDR": "#14b8a6", "BLOCKQUOTE_COLOR": "#134e4a",
        "TIP_BG": "#ecfeff", "TIP_BDR": "#06b6d4", "TIP_COLOR": "#164e63",
        "WARN_BG": "#fff7ed", "WARN_BDR": "#f97316", "WARN_COLOR": "#7c2d12",
        "H3_COLOR": "#0e7490", "TH_BG": "#0891b2",
    },
    "drama": {
        "PRIMARY": "#7c3aed", "PRIMARY_DARK": "#4c1d95", "PRIMARY_BDR": "#8b5cf6",
        "BG": "#faf5ff", "STRONG_BG": "rgba(124,58,237,0.1)",
        "BLOCKQUOTE_BG": "#fdf2f8", "BLOCKQUOTE_BDR": "#ec4899", "BLOCKQUOTE_COLOR": "#831843",
        "TIP_BG": "#faf5ff", "TIP_BDR": "#8b5cf6", "TIP_COLOR": "#4c1d95",
        "WARN_BG": "#fff1f2", "WARN_BDR": "#fb7185", "WARN_COLOR": "#881337",
        "H3_COLOR": "#6d28d9", "TH_BG": "#7c3aed",
    },
    "travel": {
        "PRIMARY": "#0369a1", "PRIMARY_DARK": "#0c4a6e", "PRIMARY_BDR": "#0ea5e9",
        "BG": "#f0f9ff", "STRONG_BG": "rgba(3,105,161,0.11)",
        "BLOCKQUOTE_BG": "#ecfdf5", "BLOCKQUOTE_BDR": "#10b981", "BLOCKQUOTE_COLOR": "#065f46",
        "TIP_BG": "#f0f9ff", "TIP_BDR": "#0ea5e9", "TIP_COLOR": "#0c4a6e",
        "WARN_BG": "#fffbeb", "WARN_BDR": "#f59e0b", "WARN_COLOR": "#78350f",
        "H3_COLOR": "#0369a1", "TH_BG": "#0369a1",
    },
    "sports": {
        "PRIMARY": "#dc2626", "PRIMARY_DARK": "#7f1d1d", "PRIMARY_BDR": "#ef4444",
        "BG": "#fff1f2", "STRONG_BG": "rgba(220,38,38,0.1)",
        "BLOCKQUOTE_BG": "#fef3c7", "BLOCKQUOTE_BDR": "#f59e0b", "BLOCKQUOTE_COLOR": "#78350f",
        "TIP_BG": "#fff1f2", "TIP_BDR": "#ef4444", "TIP_COLOR": "#7f1d1d",
        "WARN_BG": "#fffbeb", "WARN_BDR": "#d97706", "WARN_COLOR": "#92400e",
        "H3_COLOR": "#b91c1c", "TH_BG": "#dc2626",
    },
    "default": {
        "PRIMARY": "#1d4ed8", "PRIMARY_DARK": "#1e3a8a", "PRIMARY_BDR": "#2563eb",
        "BG": "#eff6ff", "STRONG_BG": "rgba(29,78,216,0.1)",
        "BLOCKQUOTE_BG": "#fffbeb", "BLOCKQUOTE_BDR": "#d97706", "BLOCKQUOTE_COLOR": "#78350f",
        "TIP_BG": "#eff6ff", "TIP_BDR": "#2563eb", "TIP_COLOR": "#1e3a8a",
        "WARN_BG": "#fffbeb", "WARN_BDR": "#d97706", "WARN_COLOR": "#92400e",
        "H3_COLOR": "#7c3aed", "TH_BG": "#1d4ed8",
    },
}

_FINANCE_KW = {"재테크","투자","주식","펀드","etf","부동산","절세","저축","금융",
               "연금","적금","대출","금리","경제","세금","월세","전세","청약","재정",
               "배당","코인","가상화폐","포트폴리오","절약","용돈","가계부"}
_HEALTH_KW  = {"건강","다이어트","운동","의료","병원","영양","질병","약","치료",
               "헬스","요가","필라테스","수면","스트레스","피부","탈모","체중",
               "면역","혈압","당뇨","근육","칼로리","단백질","식단","비타민"}
_DRAMA_KW   = {"드라마","영화","넷플릭스","티빙","쿠팡플레이","왓챠","ott","음악",
               "연예","아이돌","가수","배우","예능","웹툰","애니","시즌","결말"}
_TRAVEL_KW  = {"여행","관광","투어","코스","명소","숙소","호텔","맛집","공항",
               "비자","패키지","자유여행","배낭","현지","국내여행","해외여행",
               "제주","부산","오사카","방콕","다낭","유럽","괌","하와이"}
_SPORTS_KW  = {"축구","야구","농구","테니스","골프","k리그","kbo","nba","epl","선수",
               "감독","스포츠","마라톤","트레킹","등산","러닝","수영","자전거",
               "손흥민","류현진","경기","승리","패배","득점","순위","직관"}


_LEGAL_KW = {"법률", "민법", "형법", "법원", "계약", "소송", "판결", "권리",
             "임대차", "약관", "분쟁", "상속", "이혼", "고소", "변호사"}


def _assess_risk_level(keyword: str) -> str:
    """키워드의 YMYL(돈·건강·법률) 위험도를 분류합니다.

    high   — 금융·투자 / 건강·의료 / 법률 (잘못된 정보가 독자에게 실질 피해)
    medium — 그 외 정보성 주제 (구매 결정·생활 정보 등)
    low    — 여행·드라마·연예·스포츠 등 엔터테인먼트
    """
    kw = keyword.lower()
    if any(w in kw for w in _FINANCE_KW | _HEALTH_KW | _LEGAL_KW):
        return "high"
    if any(w in kw for w in _DRAMA_KW | _TRAVEL_KW | _SPORTS_KW):
        return "low"
    return "medium"


def _detect_theme(keyword: str, article_type: str) -> dict:
    """키워드·아티클 유형으로 최적 컬러 테마를 반환합니다."""
    kw = keyword.lower()
    if any(w in kw for w in _FINANCE_KW):
        return _THEMES["finance"]
    if any(w in kw for w in _HEALTH_KW):
        return _THEMES["health"]
    if any(w in kw for w in _DRAMA_KW) or article_type == "drama_review":
        return _THEMES["drama"]
    if any(w in kw for w in _TRAVEL_KW) or article_type == "travel_guide":
        return _THEMES["travel"]
    if any(w in kw for w in _SPORTS_KW) or article_type == "sports_review":
        return _THEMES["sports"]
    return _THEMES["default"]


def _retheme_summary_box(html: str, theme: dict) -> str:
    """Claude 프롬프트에서 생성된 핵심 요약 박스의 고정 색상을 현재 테마로 교체."""
    # 원본 패턴: background:#eff6ff;border-left:5px solid #2563eb;...color:#1e3a8a
    html = re.sub(
        r'background:#eff6ff;(border-left:5px solid )#2563eb;'
        r'(padding:[^;]+;margin:[^;]+;border-radius:[^;]+;)color:#1e3a8a;',
        lambda m: (
            f'background:{theme["BG"]};{m.group(1)}{theme["PRIMARY_BDR"]};'
            f'{m.group(2)}color:{theme["PRIMARY_DARK"]};'
        ),
        html,
    )
    return html


_TIP_EMOJIS  = {"💡", "📌", "🔑", "✅", "🔥", "💰", "📊", "ℹ️", "👉", "🎯"}
_WARN_EMOJIS = {"⚠️", "🚨", "❌", "🛑", "🔴"}


def _style_callout_paragraphs(html: str, theme: dict) -> str:
    """💡/⚠️ 등 이모지로 시작하는 <p>를 주제 컬러 callout 박스로 변환합니다."""

    def _make_box(callout_type: str) -> str:
        if callout_type == "warn":
            return (
                f"background:{theme['WARN_BG']};border-left:4px solid {theme['WARN_BDR']};"
                f"padding:14px 20px;margin:1.3em 0;border-radius:0 10px 10px 0;"
                f"color:{theme['WARN_COLOR']};font-size:0.95em;line-height:1.85;"
            )
        return (
            f"background:{theme['TIP_BG']};border-left:4px solid {theme['TIP_BDR']};"
            f"padding:14px 20px;margin:1.3em 0;border-radius:0 10px 10px 0;"
            f"color:{theme['TIP_COLOR']};font-size:0.95em;line-height:1.85;"
        )

    def replace_p(m: re.Match) -> str:
        open_tag = m.group(1)
        content  = m.group(2)

        text_start = re.sub(r'<[^>]+>', '', content).lstrip()

        ctype = None
        for em in _WARN_EMOJIS:
            if text_start.startswith(em):
                ctype = "warn"; break
        if ctype is None:
            for em in _TIP_EMOJIS:
                if text_start.startswith(em):
                    ctype = "tip"; break

        if ctype is None:
            return m.group(0)

        box_style = _make_box(ctype)
        sx = re.search(r'style="([^"]*)"', open_tag, re.I)
        if sx:
            merged = sx.group(1).rstrip(";") + ";" + box_style
            new_open = open_tag[:sx.start()] + f'style="{merged}"' + open_tag[sx.end():]
        else:
            new_open = open_tag.rstrip(">").rstrip() + f' style="{box_style}">'

        return f'{new_open}{content}</p>'

    return re.sub(r'(<p(?:\s[^>]*)?>)(.*?)</p>', replace_p, html, flags=re.I | re.DOTALL)


def _faq_to_cards(content: str) -> str:
    """
    FAQ h2 섹션 아래의 h3(질문)+p(답변) 쌍을 시각적 카드로 변환.
    h3 태그를 기준으로 분리하므로 Schema.org div 중첩도 처리 가능.
    """
    faq_h2 = re.search(
        r'(<h2[^>]*>[^<]*(?:자주\s*묻는\s*질문|Frequently Asked Questions|FAQ)[^<]*</h2>)',
        content, re.I,
    )
    if not faq_h2:
        return content

    pre  = content[:faq_h2.start()]
    h2   = faq_h2.group(1)
    rest = content[faq_h2.end():]

    end_m = re.search(r'<h2[\s>]|</article>', rest, re.I)
    faq_body  = rest[:end_m.start()] if end_m else rest
    post_body = rest[end_m.start():] if end_m else ''

    card_style = (
        "background:#f8fafc;border-radius:12px;"
        "padding:20px 24px;margin:14px 0;"
        "border:1px solid #e5e7eb;"
        "box-shadow:0 2px 8px rgba(0,0,0,0.06);"
    )
    q_style = "font-weight:700;color:#1d4ed8;margin:0 0 10px;font-size:1.02em;"
    a_style = "color:#374151;margin:0;line-height:1.85;"

    pieces = re.split(r'(<h3[^>]*>.*?</h3>)', faq_body, flags=re.I | re.DOTALL)
    cards = []
    i = 1
    while i < len(pieces):
        h3_tag  = pieces[i]
        q_text  = re.sub(r'^Q[.：]\s*', '', re.sub(r'<[^>]+>', '', h3_tag).strip())
        q_safe  = _html_esc.escape(q_text)

        following = pieces[i + 1] if i + 1 < len(pieces) else ''
        p_m = re.search(r'<p[^>]*>(.*?)</p>', following, re.I | re.DOTALL)
        a_inner = p_m.group(1).strip() if p_m else ''

        if q_text:
            cards.append(
                f'<div style="{card_style}">'
                f'<p style="{q_style}">Q. {q_safe}</p>'
                f'<p style="{a_style}">{a_inner}</p>'
                f'</div>'
            )
        i += 2

    faq_rebuilt = '\n'.join(cards) if cards else faq_body
    return pre + h2 + '\n' + faq_rebuilt + '\n' + post_body


def _apply_design(html: str, keyword: str = "", article_type: str = "analysis") -> str:
    """
    Claude 생성 HTML에 Blogger 호환 인라인 스타일 비주얼 디자인 적용.
    Blogger는 <style> 블록을 무시하므로 모든 스타일은 인라인으로 처리.
    keyword·article_type으로 주제별 컬러 테마 자동 선택.
    """
    if not html:
        return html

    theme  = _detect_theme(keyword, article_type)
    PRIMARY     = theme["PRIMARY"]
    PRIMARY_BDR = theme["PRIMARY_BDR"]
    PRIMARY_DARK = theme["PRIMARY_DARK"]
    BG          = theme["BG"]
    STRONG_BG   = theme["STRONG_BG"]
    H3_COLOR    = theme["H3_COLOR"]
    TH_BG       = theme["TH_BG"]
    BLOCKQUOTE_BG  = theme["BLOCKQUOTE_BG"]
    BLOCKQUOTE_BDR = theme["BLOCKQUOTE_BDR"]
    BLOCKQUOTE_CLR = theme["BLOCKQUOTE_COLOR"]

    TEXT   = "#374151"
    DARK   = "#111827"
    BORDER = "#e5e7eb"

    st = _apply_style_to_tag

    # article 루트: 폰트 + 기본 가독성
    html = st(html, 'article',
        f"font-family:'Noto Sans KR','Apple SD Gothic Neo','맑은 고딕',sans-serif;"
        f"font-size:16px;line-height:1.9;color:{TEXT};word-break:keep-all;"
    )

    # H2: 주제 컬러 left-border + 연한 그라디언트 배경
    html = st(html, 'h2',
        f"font-size:1.42em;font-weight:800;color:{DARK};"
        f"border-left:5px solid {PRIMARY_BDR};"
        f"padding:12px 0 12px 18px;margin:2.8em 0 1.1em;"
        f"background:linear-gradient(90deg,{BG},transparent);"
        f"border-radius:0 10px 10px 0;line-height:1.4;"
    )

    # H3: 주제 컬러 + 하단 점선
    html = st(html, 'h3',
        f"font-size:1.12em;font-weight:700;color:{H3_COLOR};"
        f"margin:1.8em 0 0.6em;padding-bottom:4px;"
        f"border-bottom:2px solid {BG};"
    )

    # P: 가독성 최적화
    html = st(html, 'p', f"margin:0 0 1.2em;line-height:1.9;color:{TEXT};")

    # Strong: 주제 컬러 + 배경 하이라이트(마커 효과)
    html = st(html, 'strong',
        f"color:{PRIMARY};font-weight:700;"
        f"background:{STRONG_BG};padding:1px 4px;border-radius:3px;"
    )

    # Em: 주제 컬러 이탤릭 강조
    html = st(html, 'em',
        f"color:{PRIMARY_DARK};font-style:italic;font-weight:500;"
    )

    # 목록
    html = st(html, 'ul', f"margin:0.5em 0 1.3em 0;padding-left:1.4em;color:{TEXT};")
    html = st(html, 'ol', f"margin:0.5em 0 1.3em 0;padding-left:1.6em;color:{TEXT};")
    html = st(html, 'li', "margin-bottom:0.55em;line-height:1.8;")

    # Blockquote: 주제 컬러 left-border + 배경
    html = st(html, 'blockquote',
        f"margin:1.5em 0;padding:16px 22px;"
        f"border-left:4px solid {BLOCKQUOTE_BDR};background:{BLOCKQUOTE_BG};"
        f"border-radius:0 10px 10px 0;color:{BLOCKQUOTE_CLR};"
        f"font-style:italic;font-size:0.97em;line-height:1.85;"
    )

    # Table: 깔끔한 박스
    html = st(html, 'table',
        f"width:100%;border-collapse:collapse;margin:1.5em 0;"
        f"font-size:0.95em;box-shadow:0 2px 8px rgba(0,0,0,0.07);"
    )
    html = st(html, 'th',
        f"background:{TH_BG};color:#fff;"
        f"padding:11px 14px;text-align:left;font-weight:600;"
    )
    html = st(html, 'td',
        f"padding:10px 14px;border-bottom:1px solid {BORDER};"
        f"color:{TEXT};vertical-align:top;"
    )

    # FAQ 섹션을 카드 스타일로 변환
    html = _faq_to_cards(html)

    # 이모지 callout 박스 (💡팁 / ⚠️주의 단락 자동 스타일)
    html = _style_callout_paragraphs(html, theme)

    # 핵심 요약 박스 색상을 현재 테마로 교체
    html = _retheme_summary_box(html, theme)

    return html


def _parse_response(raw: str) -> dict | None:
    """Claude 응답 텍스트에서 JSON을 파싱합니다."""
    text = raw.strip()

    # 코드블록 마커 제거 (```json ... ``` 또는 ``` ... ```)
    if text.startswith("```"):
        first_nl = text.find("\n")
        text = text[first_nl + 1:] if first_nl != -1 else text[3:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3].rstrip()

    # 첫 { ~ 마지막 } 추출
    start = text.find("{")
    if start == -1:
        logger.error(f"JSON 구조 없음 — 응답 앞 200자: {raw[:200]}")
        return None

    end = text.rfind("}")
    if end == -1 or end <= start:
        logger.warning("JSON 잘림 감지 — json_repair 시도")
        json_str = text[start:]  # closing } 없음, json_repair에 전달
    else:
        json_str = text[start:end + 1]
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        try:
            from json_repair import repair_json
            repaired = repair_json(json_str)
            if not repaired or not repaired.strip():
                logger.error("JSON 복구 실패: 복구 후 빈 결과")
                return None
            result = json.loads(repaired)
            if not isinstance(result, dict):
                logger.error(f"JSON 복구 후 dict가 아닌 타입 반환: {type(result)}")
                return None
            logger.warning("JSON 자동 복구 후 파싱 성공")
            return result
        except Exception as e:
            logger.error(f"JSON 복구 실패: {e} — 앞 300자: {json_str[:300]}")
            return None


_KO_STOPWORDS = {
    # 조사/어미/의존명사/지시어
    "이것", "그것", "저것", "이런", "그런", "저런", "이때", "그때", "모든", "여러",
    "어떤", "많은", "위한", "통한", "대한", "있는", "없는", "하는", "되는",
    "있어", "있다", "없다", "한다", "된다", "합니다", "합니다", "됩니다", "있습니다",
    "하면", "되면", "이며", "으로", "에서", "에게", "부터", "까지", "라고", "라는",
    "것은", "것을", "것이", "것도", "것과", "것만", "것으로", "통해", "때문", "위해",
    "하고", "하며", "하여", "하지", "보다", "같은", "같이", "때문", "경우", "정도",
}


def _extract_section_queries(html: str, keyword: str) -> list[str]:
    """H2 섹션 제목 + 본문 핵심 명사를 결합해 이미지 검색 쿼리 목록을 반환합니다."""
    from collections import Counter
    queries = [keyword]  # 첫 이미지: 도입부 → 메인 키워드

    # 키워드 구성 단어 (중복 추가 방지)
    kw_words = set(re.findall(r'[가-힣]{2,}|[A-Za-z]{3,}', keyword.lower()))

    # H2 기준으로 섹션 분리
    sections = re.split(r'(?=<h2[\s>])', html, flags=re.IGNORECASE)

    for section in sections[1:7]:  # 최대 6개 섹션
        h2_m = re.match(r'<h2[^>]*>(.*?)</h2>', section, re.IGNORECASE | re.DOTALL)
        if not h2_m:
            continue

        # 1) 제목 정제 (이모지·번호·특수문자 제거)
        heading = re.sub(r'<[^>]+>', '', h2_m.group(1)).strip()
        heading = re.sub(r'[^\w\s가-힣]', ' ', heading)   # 이모지·특수문자 제거
        heading = re.sub(r'^\s*\d+\s*', '', heading)       # 앞 번호 제거
        heading = re.sub(r'\s+', ' ', heading).strip()

        # 제목에서 키워드 단어와 겹치는 부분 제거 (중복 쿼리 방지)
        heading_words = heading.split()
        deduped = [w for w in heading_words if w.lower() not in kw_words]
        heading_clean = " ".join(deduped).strip()[:40]
        if not heading_clean or len(heading_clean) < 2:
            continue

        # 2) 본문 첫 단락에서 핵심 단어 추출
        body = section[h2_m.end():]
        p_m = re.search(r'<p[^>]*>(.*?)</p>', body, re.IGNORECASE | re.DOTALL)
        extra_terms = ""
        if p_m:
            p_text = re.sub(r'<[^>]+>', '', p_m.group(1))[:200]

            # 영문 대문자 약어 (ETF, GDP 등) — 최우선
            acronyms = re.findall(r'[A-Z][A-Z0-9&]{1,9}', p_text)
            filtered_en = [a for a in dict.fromkeys(acronyms) if a.lower() not in kw_words]

            # 한국어 핵심 명사 (2~4자, 스톱워드·키워드 단어 제외, 빈도순)
            ko_words = re.findall(r'[가-힣]{2,4}', p_text)
            filtered_ko = [
                w for w in ko_words
                if w not in _KO_STOPWORDS and w.lower() not in kw_words
            ]
            top_ko = [w for w, _ in Counter(filtered_ko).most_common(5)]

            # 우선순위: 영문 약어 → 한국어 명사 (합쳐서 최대 2개)
            extra_parts: list[str] = []
            for term in filtered_en + top_ko:
                if term not in extra_parts:
                    extra_parts.append(term)
                if len(extra_parts) == 2:
                    break
            extra_terms = " ".join(extra_parts)

        # 이미지 검색용 쿼리: 키워드 핵심 명사(최대 2개) + 섹션 핵심어
        # — 문장형 긴 쿼리는 네이버/DDG에서 결과 0건이 되므로 명사 조합으로 축약
        from image_fetcher import _core_terms
        kw_core = " ".join(_core_terms(keyword, 2))
        heading_core = " ".join(_core_terms(heading_clean, 2))
        parts = [p for p in (kw_core, heading_core, extra_terms) if p]
        query = " ".join(dict.fromkeys(" ".join(parts).split()))  # 단어 중복 제거
        queries.append(query[:50])

    # 첫 쿼리(메인 키워드)도 핵심 명사로 축약
    from image_fetcher import _core_terms as _ct
    queries[0] = " ".join(_ct(keyword, 3)) or keyword
    return queries[:4]


def _word_count(html: str) -> int:
    """HTML 태그 제거 후 글자 수를 반환합니다."""
    text = re.sub(r"<[^>]+>", "", html)
    return len(re.sub(r"\s+", "", text))


def _content_preview(html: str, chars: int = 200) -> str:
    """HTML 태그 제거 후 미리보기 텍스트를 반환합니다."""
    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:chars] + ("..." if len(text) > chars else "")


_TRUSTED_DOMAINS = re.compile(
    r'https?://(?:www\.)?([\w\-]+\.(?:go\.kr|ac\.kr|or\.kr|re\.kr|'
    r'gov|edu|org|com|net|io|co\.kr|kr|us|uk|de|fr|jp|'
    r'bbc\.co\.uk|reuters\.com|ap\.org|bloomberg\.com|'
    r'naver\.com|daum\.net|yna\.co\.kr|chosun\.com|joins\.com|'
    r'hani\.co\.kr|mk\.co\.kr|hankyung\.com|etnews\.com|'
    r'imf\.org|worldbank\.org|oecd\.org|who\.int|un\.org|'
    r'kosis\.kr|kostat\.go\.kr|bok\.or\.kr|fss\.or\.kr|'
    r'kftc\.or\.kr|mcst\.go\.kr|mof\.go\.kr|mohw\.go\.kr))',
    re.IGNORECASE,
)

_URL_PATTERN = re.compile(
    r'^https?://[^\s/$.?#].[^\s]*$', re.IGNORECASE
)


def _validate_sources(sources: list) -> list:
    """출처 목록에서 형식이 유효한 URL만 유지합니다.
    완전히 임의로 생성된 것으로 보이는 URL은 제거합니다."""
    valid = []
    for s in sources:
        if not isinstance(s, dict):
            continue
        url = s.get("url", "").strip()
        title = s.get("title", "").strip()
        if not url or not title:
            continue
        # 기본 URL 형식 검증
        if not _URL_PATTERN.match(url):
            logger.debug(f"출처 제거 (형식 오류): {url}")
            continue
        # 플레이스홀더 패턴 제거 ("실제존재하는URL", "example.com" 등)
        lower = url.lower()
        if any(x in lower for x in ("example.com", "실제존재", "your-", "placeholder", "xxx")):
            logger.debug(f"출처 제거 (플레이스홀더): {url}")
            continue
        valid.append({"title": title, "url": url})
    if len(sources) != len(valid):
        removed = len(sources) - len(valid)
        logger.info(f"출처 검증: {len(valid)}개 유효 / {removed}개 제거")
    return valid


def _build_series_prompt(keyword: str, traffic: str, series_context: dict, blog_config: dict | None = None) -> str:
    """시리즈 포스트용 프롬프트 — 블로그 주제별 분기"""
    from datetime import datetime
    blog_id = (blog_config or {}).get("id", "")
    # 실제 경험 자료 유무에 따른 문체 규칙 (가짜 체험담 방지)
    style_block = _experience_style_block(keyword, blog_id)
    if blog_id == "blog2":
        return _build_series_prompt_it(keyword, traffic, series_context, blog_config) + style_block
    if blog_id == "blog3":
        return _build_series_prompt_finance(keyword, traffic, series_context, blog_config) + style_block
    # blog1 또는 미지정
    return _build_series_prompt_general(keyword, traffic, series_context, blog_config) + style_block


def _series_common_vars(keyword: str, series_context: dict):
    """시리즈 프롬프트 공통 변수를 반환합니다."""
    from datetime import datetime
    now = datetime.now()
    series_title = series_context.get("series_title", "")
    episode = series_context.get("episode", 1)
    total = series_context.get("total_episodes", 1)
    focus = series_context.get("focus", "")
    title_hint = series_context.get("title", "")
    series_label = series_context.get("series_label", "")
    all_eps = series_context.get("episodes", [])
    other_eps = [ep for ep in all_eps if ep.get("episode") != episode]
    other_list = "\n".join([f"  • {ep['episode']}편: {ep.get('title', '')}" for ep in other_eps])
    return (now.year, now.strftime("%Y년 %m월 %d일"),
            series_title, episode, total, focus, title_hint, series_label, other_list)


def _build_series_prompt_general(keyword: str, traffic: str, series_context: dict, blog_config: dict | None = None) -> str:
    """blog1 / 기본 — 여행·드라마·연예·K-POP 시리즈 프롬프트 (개인 경험 스타일)"""
    from datetime import datetime
    now = datetime.now()
    y = now.year
    date_str = now.strftime("%Y년 %m월 %d일")

    series_title = series_context.get("series_title", "")
    episode = series_context.get("episode", 1)
    total = series_context.get("total_episodes", 1)
    focus = series_context.get("focus", "")
    title_hint = series_context.get("title", "")
    series_label = series_context.get("series_label", "")
    all_eps = series_context.get("episodes", [])
    other_eps = [ep for ep in all_eps if ep.get("episode") != episode]
    other_list = "\n".join(
        [f"  • {ep['episode']}편: {ep.get('title', '')}" for ep in other_eps]
    )

    article_type = _detect_article_type(keyword)
    structure_guide = _STRUCTURE_GUIDE.get(article_type, _STRUCTURE_GUIDE["analysis"])
    blog_topic_hint = _build_blog_topic_hint(blog_config)

    # 드라마·영화 시리즈일 때 실제 리뷰 데이터 수집
    drama_ref_section = ""
    if article_type == "drama_review":
        drama_ref_section = _fetch_drama_references(keyword)
        if drama_ref_section:
            logger.info(f"[시리즈] 드라마/영화 참고 리뷰 데이터 수집 완료: '{keyword}'")

    if BLOG_LANGUAGE == "ko":
        return f"""당신은 "{series_title}" 시리즈를 깊이 공부하고 조사하면서 한 편씩 정리해 올리는 블로거입니다.
글쓰기 전문가가 아니라 완벽하지 않아도 됩니다. 구글 AdSense 정책을 완전히 준수합니다.

【현재 날짜】 {date_str}
【시리즈】 "{series_title}" — 총 {total}편 중 {episode}번째
【이 편 초점】 {focus}
【키워드】 {keyword}
【아티클 유형】 {article_type}{blog_topic_hint}

━━━ 시리즈 연결 방식 ━━━

다른 편 목록:
{other_list}

• 도입부: 이 시리즈를 쓰게 된 계기 또는 이전 편 흐름 자연스럽게 언급
• 본문에서 다른 편을 1~2회 언급 ("1편에서도 얘기했지만", "다음 편에서 자세히 다룰게요")
• 이 편만 읽어도 완결되는 독립적 글
• 제목 힌트 "{title_hint}"를 더 구체적이고 검색하고 싶게 다듬어 사용

━━━ 1. 인간적인 목소리 ━━━

• "저는", "제가", "솔직히" 등 1인칭 자연스럽게 사용
• 도입부: 이 편 주제를 직접 겪은 상황으로 시작
• 확신이 없는 부분은 솔직하게: "이게 맞는 건지 저도 100%는 모르겠지만요"
• 독자에게 말 걸기: "혹시 이런 경험 있으세요?" 1~2회

━━━ 2. 절대 쓰지 말아야 할 표현 ━━━

[관료·번역투]
✗ "알아보겠습니다" / "살펴보겠습니다" / "정리해드리겠습니다" / "소개해드리겠습니다"
✗ "다음과 같습니다" / "아래와 같이" / "해당 " (관공서 문체)
✗ "~에 대하여" / "~임을 알 수 있다" / "~에 기인한다" / "~함으로써"
✗ "이러한 이유로" / "이러한 점에서" / "이러한" 3회 이상

[AI 요약·정리 패턴]
✗ "이처럼" / "정리하자면" / "결론적으로" / "이를 통해 알 수 있듯이"
✗ "중요한 것은 바로" / "앞서 언급했듯이" / "다시 한번 강조하지만"

[남발 금지 (합산 3회 초과 금지)]
✗ "또한" / "더불어" / "아울러" / "한편으로는" / "반면에"

[중립·보고서 문체]
✗ "~할 수 있습니다" / "~로 볼 수 있습니다" 연속 3문장 이상
✗ "중요합니다" / "필수적입니다" 2회 이상
✗ "다양한 방법을 통해" / "~하기 위해서는 ~이 필요합니다"

대신:
✓ "저는 이게 확실히 더 낫더라고요"
✓ "이걸 빠뜨리면 진짜 후회해요 — 저도 그랬거든요"
✓ "오늘은 ~에 대해 얘기해볼게요"

━━━ 3. 자연스러운 글 리듬 ━━━

• 짧은 문장 ("그게 핵심이에요.") + 중간 문장 + 긴 문장 섞기
• 어미 다양화: "~요", "~거든요", "~더라고요", "~는 거예요", "~인데요", "~잖아요"
• 완벽하게 매끄러운 단락 전환 금지 — 약간 뚝뚝 끊겨도 OK
• 이모지는 💡(팁 1~2개), ⚠️(주의 1~2개)만. H2 제목이나 일반 단락 이모지 금지

━━━ 4. 구조 탈피 ━━━
• "방법 TOP 5", "주의사항 3가지" 같은 공식 구조 금지
• H2 제목은 실제 검색할 법한 상황·질문 중심으로
• 섹션마다 다른 방식: 어떤 건 경험담, 어떤 건 숫자 비교, 어떤 건 Q&A
• 목록은 진짜 나열이 필요할 때만
• 유형별 구조 가이드:
{structure_guide}

━━━ Google AdSense 2025 정책 준수 (가치 없는 콘텐츠 위반 방지) ━━━
① 원본성·품질 — 독창적 경험·인사이트 필수. 인터넷에 흔한 정보 나열 금지. 글쓴이만 아는 구체적 경험·수치·실수 포함
② SEO 최적화 — 키워드 자연 분산, 제목·내용 일치
③ 구조·가독성 — H2 5개 이상, 각 섹션 300자 이상, 목차 포함
④ 광고 배치 — 광고 4개 이하, 콘텐츠 충분, 흐름 방해 금지
⑤ 유해·금지 — 성인/폭력/혐오/불법 절대 금지 (위반 시 즉시 거부)
   투자·의료 주장은 반드시 면책 표현 포함
⑥ E-E-A-T — 구체적 수치·날짜·출처 포함 (최소 3개), 균형 잡힌 시각
   예: "{y}년 공식 발표 기준으로", "이용자 후기를 종합하면", "○개월 이용 후기들을 보면"
⑦ 이미지 — alt 텍스트 모든 이미지에 포함
⑧ AI 의심도 — 위 4번 AI 상투어 규칙 철저 준수
⑨ 분량 4500자 이상 필수 — 이 이하는 'thin content'로 AdSense 거부됨

━━━ 제목 규칙 ━━━
• "[{episode}편]"으로 시작
• 자연스러운 블로그 제목 | {y}년 포함 | 40자 이내

━━━ 본문 구조 (분량 엄수 — 가장 중요) ━━━
분량: 4500~6000자 완전한 HTML (Google AdSense 정책상 4000자 미만은 thin content)
⚠️ 반드시 지켜야 할 분량 규칙:
  - H2 섹션 7개 이상 (각 섹션 최소 500자 이상)
  - 도입부(p 태그) 최소 300자
  - FAQ 5개 (각 답변 150자 이상)
  - 결론 섹션 최소 200자
  - 섹션 합계 = 최소 4500자
각 H2 섹션마다 최소 3개 단락, 구체적 사례·수치·경험 반드시 포함
⚠️ 분량 부족 시 글이 게시되지 않습니다 — 4500자 미만은 자동 거부됩니다

━━━ 강조 & 가독성 ━━━
• 핵심 수치·팩트·행동 지침은 <strong>으로 강조 (문단당 1~2개, 남용 금지)
• 독자가 꼭 챙겨야 할 팁 단락: 문장 맨 앞에 💡 배치 (글 전체에서 1~3개)
• 중요 주의사항 단락: 문장 맨 앞에 ⚠️ 배치 (1~2개)
• 핵심 인사이트는 <blockquote>로 감싸기 (1~2개)

━━━ FAQ ━━━
h2 "자주 묻는 질문" + 5개 / 구체적이고 실질적인 질문·답변

━━━ SEO ━━━
키워드 10~14회 | LSI 키워드 | 라벨 10개 (반드시 "{series_label}" 포함) | meta_description 155자 이내
• meta_description 155자 이내

━━━ 출처 링크 ━━━
• 실존하는 공신력 있는 URL만
• 확인 불가 통계는 출처 생략
• 최소 2개, 최대 6개
{drama_ref_section}
JSON만 응답 (마크다운 없이):
{{
  "title": "[{episode}편] ...",
  "content": "<완전한 HTML>",
  "labels": ["{series_label}","태그2","태그3","태그4","태그5","태그6","태그7","태그8","태그9","태그10"],
  "meta_description": "...",
  "faq": [{{"q":"...","a":"..."}},...],
  "sources": [{{"title":"...","url":"..."}}]
}}"""

    other_list_en = "\n".join([f"  • Part {ep['episode']}: {ep.get('title','')}" for ep in other_eps])
    return f"""You are an expert blogger providing genuinely useful information to readers.
Follow Google AdSense content policies. Reader trust is top priority.

【Date】 {now.strftime("%B %d, %Y")}
【Series】 "{series_title}" — Part {episode} of {total}
【Episode Focus】 {focus}
Keyword: {keyword} | Traffic: {traffic}

━━━ SERIES RULES ━━━
Other parts:
{other_list_en}

• This episode must be self-contained and valuable alone
• Naturally mention other parts 1-2 times to encourage series reading

━━━ TITLE ━━━
• Start with "[Part {episode}]" (e.g., "[Part 1] 2026...")
• Include numbers and {y} | Under 65 chars | No sensationalism

━━━ CONTENT STRUCTURE ━━━
Length: 2800-3500 words, complete HTML
Intro (300w): reader problem + episode value + 1-line series intro

6 H2 sections (400-450w each):
1. "📊 {keyword} Stats & Data ({y})"
2. "✅ {focus} TOP 5 Methods"
3. "💡 Real Case Studies"
4. "⚠️ 3 Mistakes to Avoid"
5. "🔥 {y} Trends & Updates"
6. "💰 Action Steps & What's Next"

FAQ (h2 "Frequently Asked Questions"): 5 Q&As
Conclusion (200w): summary + encourage reading next part

━━━ CONTENT QUALITY ━━━
• Each H2: actionable, specific info
• Stats: verifiable only; estimates say "approximately"
• <strong> key concepts | Bullet/numbered lists

━━━ SEO ━━━
• Keyword 10-14 times | LSI keywords throughout
• 10 labels — must include "{series_label}"
• meta_description under 155 chars

━━━ SOURCES ━━━
• Real URLs from credible sources only | Min 2, max 6

JSON only:
{{
  "title": "[Part {episode}] ...",
  "content": "<complete HTML>",
  "labels": ["{series_label}","tag2","tag3","tag4","tag5","tag6","tag7","tag8","tag9","tag10"],
  "meta_description": "...",
  "faq": [{{"q":"...","a":"..."}},...],
  "sources": [{{"title":"...","url":"..."}}]
}}"""


# ── blog2 IT 시리즈 프롬프트 ──────────────────────────────────────────────────

def _build_series_prompt_it(keyword: str, traffic: str, series_context: dict, blog_config: dict | None = None) -> str:
    """blog2 IT 시리즈 전용 프롬프트 — 리뷰·벤치마크 종합 분석 관점"""
    from datetime import datetime
    now = datetime.now()
    y, date_str = now.year, now.strftime("%Y년 %m월 %d일")
    series_title = series_context.get("series_title", "")
    episode = series_context.get("episode", 1)
    total = series_context.get("total_episodes", 1)
    focus = series_context.get("focus", "")
    title_hint = series_context.get("title", "")
    series_label = series_context.get("series_label", "")
    all_eps = series_context.get("episodes", [])
    other_list = "\n".join(
        [f"  • {ep['episode']}편: {ep.get('title', '')}"
         for ep in all_eps if ep.get("episode") != episode]
    )
    return f"""당신은 IT 기기와 앱 정보를 깊이 조사하고 리뷰를 종합해 정리하는 블로거입니다.
"{series_title}" 시리즈를 조사한 내용 기준으로 한 편씩 정리해 올리는 중입니다.
광고·홍보 느낌은 절대 없어야 합니다. 불편한 점도 솔직하게 작성하세요.

【현재 날짜】 {date_str}
【시리즈】 "{series_title}" — 총 {total}편 중 {episode}번째
【이 편 초점】 {focus}
【키워드】 {keyword}

━━━ 시리즈 연결 방식 ━━━
다른 편 목록:
{other_list}

• 도입부: 이 기술/제품을 왜 써보게 됐는지 또는 이전 편과의 연결 자연스럽게 언급
• 본문에서 다른 편을 1~2회 언급 ("1편에서 초기 설정 얘기했는데", "다음 편에서 비교해볼게요")
• 이 편만 읽어도 완결되는 독립적 글
• 제목 힌트 "{title_hint}"를 더 구체적이고 IT 검색에 적합하게 다듬어 사용

━━━ IT 블로그 글쓰기 원칙 ━━━

• 공개된 벤치마크·리뷰 수치 제시 (배터리 몇 분, 속도 몇 Mbps, 처리 시간 등 — 출처 기반)
• 장점 3개 언급 시 반드시 단점·아쉬운 점 1개 이상 포함
• 타 제품/서비스와 구체적 비교 환영 (단, 공정하게)
• "광고 아님" 느낌 주는 표현: "후기들을 보면", "개인적으로는", "솔직히 말하면"
• 공식 사이트 또는 제조사 발표 수치 인용 시 출처 명시

━━━ 절대 쓰지 말아야 할 표현 ━━━
✗ "최고의 제품입니다" / "강력 추천" / "놀라운 성능"
✗ "혁신적인" / "게임 체인저" (과장 표현)
✗ "알아보겠습니다" / "살펴보겠습니다" / "정리해드리겠습니다"

━━━ 글 구조 ━━━
• H2 소제목 4~6개 (각 500자 이상, 공백 제외)
• 도입: 테스트 배경·동기 (200자)
• 요약 박스: 이 편 핵심 테스트 결과 3줄 (HTML 박스)
• 본문: 테스트 과정·결과·비교
• 이미지 1장 (테스트 화면 또는 제품 관련 이미지)
• FAQ 3개 (실제 IT 사용자가 궁금해하는 질문)
• 결론: 이 제품/기술의 추천 대상 명확히

⚠️ 분량: 최소 2,500자 이상(공백 제외)
⚠️ 투자 조언·수익 보장 표현 사용 금지
⚠️ HTML만 출력, 마크다운 사용 금지

다음 JSON 형식으로만 응답하세요:
{{
  "title": "제목 (40자 이내, IT 검색 최적화, {y}년 포함 권장)",
  "content": "<완성된 HTML 본문>",
  "labels": ["{series_label}","IT","AI","스마트폰","앱","기술","테크","리뷰","사용기","비교"],
  "meta_description": "검색 결과 요약 (155자 이내, 구체적 정보 강조)",
  "faq": [{{"q":"IT 사용자 질문","a":"조사 자료 기반 답변"}}],
  "sources": [{{"title":"제조사 또는 공식 발표 출처","url":"https://..."}}]
}}"""


# ── blog3 금융 시리즈 프롬프트 ────────────────────────────────────────────────

def _build_series_prompt_finance(keyword: str, traffic: str, series_context: dict, blog_config: dict | None = None) -> str:
    """blog3 금융·정부지원 시리즈 전용 프롬프트 — 개인 경험 기반 실용 금융 정보"""
    from datetime import datetime
    now = datetime.now()
    y, date_str = now.year, now.strftime("%Y년 %m월 %d일")
    series_title = series_context.get("series_title", "")
    episode = series_context.get("episode", 1)
    total = series_context.get("total_episodes", 1)
    focus = series_context.get("focus", "")
    title_hint = series_context.get("title", "")
    series_label = series_context.get("series_label", "")
    all_eps = series_context.get("episodes", [])
    other_list = "\n".join(
        [f"  • {ep['episode']}편: {ep.get('title', '')}"
         for ep in all_eps if ep.get("episode") != episode]
    )
    return f"""당신은 금융과 정부지원 정책을 깊이 공부하고 조사해 정리하는 블로거입니다.
"{series_title}" 시리즈를 조사한 내용 기준으로 한 편씩 정리해 올리는 중입니다.
투자 전문가가 아니라 완벽하지 않아도 됩니다. 구글 AdSense 정책을 완전히 준수합니다.

【현재 날짜】 {date_str}
【시리즈】 "{series_title}" — 총 {total}편 중 {episode}번째
【이 편 초점】 {focus}
【키워드】 {keyword}

━━━ 시리즈 연결 방식 ━━━
다른 편 목록:
{other_list}

• 도입부: 이 금융/정책 주제를 알아보게 된 계기 또는 이전 편 흐름 자연스럽게 언급
• 본문에서 다른 편을 1~2회 언급 ("1편에서 자격 조건 얘기했는데", "다음 편에서 신청 과정 알려드릴게요")
• 이 편만 읽어도 완결되는 독립적 글
• 제목 힌트 "{title_hint}"를 더 구체적이고 금융 검색에 적합하게 다듬어 사용

━━━ 금융 블로그 글쓰기 원칙 ━━━

• 공신력 있는 출처 필수 인용 (기획재정부·금융위원회·국세청·금융감독원·복지로·고용24)
• 금액·날짜·자격 조건 등 수치는 반드시 출처와 함께 제시
• 독자가 바로 활용할 수 있는 단계별 가이드 포함
• "처음엔 헷갈리기 쉬운데", "신청자 후기를 보면" 등 독자 상황 공감 표현 사용

━━━ 절대 쓰지 말아야 할 표현 ━━━
✗ "투자를 권유합니다" / "수익이 보장됩니다" / "반드시 오릅니다"
✗ 특정 금융상품·주식 매수·매도 유도 표현
✗ "알아보겠습니다" / "살펴보겠습니다" / "정리해드리겠습니다"

━━━ 글 구조 ━━━
• H2 소제목 4~6개 (각 500자 이상, 공백 제외)
• 도입: 이 정보를 알아보게 된 실생활 계기 (200자)
• 요약 박스: 이 편 핵심 정보 3줄 (HTML 박스, ⚠️ 투자 조언 아님 명시)
• 본문: 자격 조건·신청 방법·주의사항·실계산 예시
• 이미지 1장 (금융 관련)
• 면책 문구: "본 글은 개인적인 경험과 공개된 정보를 바탕으로 작성된 것으로, 전문적인 금융 조언이 아닙니다. 중요한 금융 결정은 전문가와 상담하시기 바랍니다."
• FAQ 3개 (독자가 실제로 궁금해하는 자격·신청 관련 질문)
• 결론: 이 제도의 대상자와 주의사항 명확히

⚠️ 분량: 최소 2,500자 이상(공백 제외)
⚠️ 투자 권유·수익 보장 표현 절대 금지
⚠️ HTML만 출력, 마크다운 사용 금지

다음 JSON 형식으로만 응답하세요:
{{
  "title": "제목 (40자 이내, 금융 검색 최적화, {y}년 기준 포함 권장)",
  "content": "<완성된 HTML 본문 + 면책 문구 포함>",
  "labels": ["{series_label}","금융","경제","정부지원","세금","절세","재테크","복지","시책","정책"],
  "meta_description": "검색 결과 요약 (155자 이내, 실용 정보 강조, 투자 조언 아님 명시)",
  "faq": [{{"q":"독자 금융 질문","a":"공신력 있는 정보 기반 답변"}}],
  "sources": [{{"title":"기획재정부·금융위 등 공식 출처명","url":"https://..."}}]
}}"""


def generate_series_post(keyword: str, traffic: str = "N/A", series_context: dict | None = None, blog_config: dict | None = None) -> dict | None:
    """시리즈 포스트를 생성합니다."""
    if not series_context:
        return generate_post(keyword, traffic, blog_config)

    # episode 는 반드시 int — 기본값 "?" 는 build_series_nav에서 TypeError 유발
    _ep_raw = series_context.get("episode", 1)
    try:
        episode = int(_ep_raw)
    except (TypeError, ValueError):
        episode = 1
    total = series_context.get("total_episodes", "?")
    logger.info(f"시리즈 포스트 생성: '{keyword}' ({episode}/{total}편)")
    # 글 작성 전 자료 조사 — 검증된 자료팩만 사실 근거로 사용
    from evidence_builder import format_evidence_for_prompt
    evidence_pack = _run_research(keyword)
    prompt = _build_series_prompt(keyword, traffic, series_context, blog_config) + format_evidence_for_prompt(evidence_pack)
    is_blog1 = blog_config and blog_config.get("id") == "blog1"
    ai_provider = _resolve_ai_provider(blog_config)

    prev_wc = 0
    for attempt in range(3):
        try:
            from datetime import datetime as _dt
            _now = _dt.now()
            blog_lang = (blog_config or {}).get("language", BLOG_LANGUAGE)
            if is_blog1:
                _sys = (
                    f"현재 날짜: {_now.strftime('%Y년 %m월 %d일')}. "
                    "당신은 관심 주제를 깊이 조사하고 공부해서 솔직하게 정리해 올리는 블로거입니다. 하지 않은 경험을 한 것처럼 쓰지 않습니다. "
                    "구글 애드센스 정책을 완전히 준수하며, AI가 쓴 것처럼 보이지 않는 자연스러운 한국어 문체로 작성합니다. "
                    "독자에게 실질적인 도움이 되는 정보를 제공하는 것이 최우선입니다. "
                    "JSON만 응답하세요."
                )
            elif blog_lang == "ko":
                _sys = (
                    f"현재 날짜: {_now.strftime('%Y년 %m월 %d일')}. "
                    "당신은 신뢰할 수 있는 정보를 조사·정리해 솔직하게 글을 쓰는 블로거입니다. 하지 않은 경험을 한 것처럼 쓰지 않습니다. "
                    "AI가 쓴 것처럼 보이지 않게, 사람 냄새 나는 자연스러운 한국어 블로그 글을 씁니다. "
                    "JSON만 응답하세요."
                )
            else:
                _sys = (
                    f"Current date: {_now.strftime('%B %d, %Y')}. "
                    "You are a blogger who writes well-researched, trustworthy posts. Never fabricate personal experiences. "
                    "Write naturally, like a real person — not an AI report. JSON only."
                )
            escalation = _retry_escalation_note(attempt, prev_wc)
            logger.info(f"  AI 제공자: {ai_provider.upper()} (시도 {attempt + 1}/3)")
            raw = _ai_generate(_sys, prompt + escalation, ai_provider).strip()
            if not raw:
                logger.warning(f"{ai_provider.upper()} 응답 없음 — 재시도")
                if attempt < 2:
                    time.sleep(2)
                    continue
                return None
            post_data = _parse_response(raw)
            if post_data is None:
                if attempt < 2:
                    logger.warning(f"JSON 파싱 실패 — 재시도 {attempt + 1}/3")
                    prev_wc = -1  # 파싱 실패 센티널
                    time.sleep(2)
                    continue
                return None

            post_data["keyword"] = keyword
            post_data["article_type"] = _detect_article_type(keyword)
            post_data["risk_level"] = _assess_risk_level(keyword)
            # 표준 스키마: tags는 labels의 별칭 (내부 링크·대시보드 공용)
            post_data["tags"] = list(post_data.get("labels", []) or [])
            post_data["series_id"] = series_context.get("series_id", "")
            post_data["episode"] = episode

            content_html = post_data.get("content", "")
            post_data["word_count"] = _word_count(content_html)
            post_data["content_preview"] = _content_preview(content_html)

            prev_wc = post_data["word_count"]
            if not content_html.strip() or post_data["word_count"] < 2500:
                if attempt < 2:
                    logger.warning(f"컨텐츠 너무 짧음({post_data['word_count']}자, 최소 2500자) — 재시도 {attempt + 1}/3")
                    time.sleep(3)
                    continue
                if post_data["word_count"] < 500:
                    logger.error(f"컨텐츠 생성 실패: {post_data['word_count']}자 — thin content 방지를 위해 게시 거부")
                    return None
                logger.warning(f"최소 분량 미달({post_data['word_count']}자) — 재시도 소진, 해당 분량으로 진행")

            if not isinstance(post_data.get("sources"), list):
                post_data["sources"] = []
            else:
                post_data["sources"] = _validate_sources(post_data["sources"])

            # 자료팩 출처를 sources에 병합 (검증된 출처 우선)
            _merge_evidence(post_data, evidence_pack)

            # 게시 전 팩트체크 — 이미지 삽입 전에 실행 (이미지 HTML 훼손 방지)
            _fact_check_content(post_data, keyword, evidence_pack)

            section_queries = _extract_section_queries(post_data["content"], keyword)
            plain_text = _content_preview(post_data.get("content", ""), chars=600)
            images = fetch_images_for_queries(
                section_queries[:1],
                naver_client_id=os.getenv("NAVER_CLIENT_ID", ""),
                naver_client_secret=os.getenv("NAVER_CLIENT_SECRET", ""),
                pixabay_api_key=os.getenv("PIXABAY_API_KEY", ""),
                article_plain_text=plain_text,
                keyword=keyword,
            )
            images = images[:1]
            if images:
                post_data["content"] = inject_images_into_content(post_data["content"], images, keyword)
                post_data["images_inserted"] = len(images)
            else:
                post_data["images_inserted"] = 0

            # 인라인 스타일 비주얼 디자인 적용 (주제별 컬러 테마)
            post_data["content"] = _apply_design(
                post_data["content"], keyword, _detect_article_type(keyword)
            )

            # 쿠팡파트너스 추천 상품 섹션 삽입 (AdSense 자동 광고와 겹치지 않게 맨 하단 고정)
            post_data["content"] = inject_affiliate_section(
                post_data["content"], keyword, blog_config
            )

            logger.info(
                f"시리즈 포스트 생성 완료: '{post_data.get('title', '?')}' "
                f"({post_data['word_count']}자, 이미지 {post_data['images_inserted']}개)"
            )
            return post_data

        except anthropic.APIStatusError as e:
            if attempt < 2 and e.status_code in (429, 529):
                wait = 8 * (2 ** attempt)
                logger.warning(f"API 과부하 — {wait}s 재시도")
                time.sleep(wait)
            else:
                logger.error(f"Claude API 오류: {e}")
                return None
        except Exception as e:
            logger.error(f"시리즈 포스트 생성 오류: {e}", exc_info=True)
            return None
    return None


def _merge_evidence(post_data: dict, evidence_pack: dict | None) -> None:
    """자료팩의 검증된 출처를 post_data sources 앞쪽에 병합하고 통계를 기록합니다."""
    if not evidence_pack:
        post_data["evidence"] = {"used": False, "facts": 0, "verified": 0}
        return
    facts = evidence_pack.get("facts") or []
    verified = [f for f in facts if f.get("verified")]
    ev_sources = []
    seen = set()
    for f in (verified or facts):
        url = f.get("source_url", "")
        if url and url not in seen:
            seen.add(url)
            ev_sources.append({"title": f.get("source_title") or url, "url": url})
    existing = [s for s in (post_data.get("sources") or [])
                if isinstance(s, dict) and s.get("url") not in seen]
    post_data["sources"] = (ev_sources + existing)[:6]
    post_data["evidence"] = {"used": True, "facts": len(facts), "verified": len(verified)}


def _fact_check_content(post_data: dict, keyword: str, evidence_pack: dict | None = None) -> None:
    """
    게시 전 팩트체크 — 본문의 수치·날짜·통계·기관명 주장 중 의심스러운 것을
    Claude로 검증하고, 본문에서 원문이 그대로 발견되는 경우 수정을 적용합니다.
    결과는 post_data['fact_check']에 기록됩니다. 오류 시 게시를 막지 않습니다.
    환경변수 FACT_CHECK=false 로 비활성화할 수 있습니다.
    """
    if os.getenv("FACT_CHECK", "true").lower() != "true":
        post_data["fact_check"] = {"checked": False, "reason": "disabled"}
        return
    try:
        content_html = post_data.get("content", "")
        plain = re.sub(r"<[^>]+>", " ", content_html)
        plain = re.sub(r"\s+", " ", plain).strip()[:3500]
        if len(plain) < 300:
            post_data["fact_check"] = {"checked": False, "reason": "too_short"}
            return

        from datetime import datetime as _dt
        today = _dt.now().strftime("%Y년 %m월 %d일")

        # 실제 경험 자료가 있으면 그 범위 내 경험담은 허용, 없으면 체험 주장도 검사 대상
        exp = _match_experience(keyword)
        post_data["experience_used"] = bool(exp)
        if exp:
            exp_rule = (
                "⑤글쓴이의 실제 경험 자료 범위를 벗어난 1인칭 체험 주장. "
                f"실제 경험 자료: {str(exp.get('summary', ''))[:200]} — 이 범위 안의 경험담은 허용하세요. "
            )
        else:
            exp_rule = (
                "⑤근거 자료 없는 1인칭 체험 주장(예: '직접 써봤다', '다녀왔다', '투자해봤다', "
                "'치료를 받아봤다', '실제 수익 공개') — 조사형 표현으로 교체하세요. "
            )

        # 자료팩이 있으면 팩트체커가 그 기준으로 수치·날짜를 대조
        pack_rule = ""
        pack_facts = (evidence_pack or {}).get("facts") or []
        if pack_facts:
            facts_brief = " / ".join(f.get("claim", "")[:80] for f in pack_facts[:8])
            pack_rule = (
                "⑥검증된 자료팩과 모순되거나 자료팩에 없는 구체적 수치·정책 내용. "
                f"자료팩: {facts_brief} "
            )

        fc_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        raw = claude_generate(
            fc_client,
            model=CLAUDE_MODEL,
            max_tokens=800,
            max_continues=1,
            system=(
                f"현재 날짜: {today}. 당신은 블로그 글의 팩트체커입니다. "
                "본문에서 사실 오류 가능성이 높은 주장만 찾으세요: "
                "①검증 불가능한 구체적 수치·통계(예: '국민 67%가'), ②잘못된 날짜/연도, "
                "③존재하지 않는 제도·기관·상품명, ④과장된 단정(예: '무조건', '100%'), "
                + exp_rule + pack_rule +
                "의견·판단형 1인칭('개인적으로는', '제 생각에는')은 문제 삼지 마세요. JSON만 응답하세요."
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"주제: {keyword}\n본문:\n{plain}\n\n"
                    '다음 JSON 형식으로만 답하세요:\n'
                    '{"issues": [{"quote": "본문에서 그대로 복사한 문제 구절(20자 이내)", '
                    '"problem": "무엇이 문제인지", "fix": "안전하게 고친 표현"}], '
                    '"verdict": "pass 또는 warn"}\n'
                    "문제가 없으면 issues를 빈 배열로, verdict를 pass로 하세요. 이슈는 최대 5개."
                ),
            }],
        )
        raw = raw.strip()
        parsed = _parse_response(raw)
        result = parsed if parsed and "issues" in parsed else {"issues": [], "verdict": "pass"}

        def _safe_replace(html_text: str, quote: str, fix: str) -> str | None:
            """태그 내부(속성/스타일)가 아닌 텍스트 위치에서만 치환합니다.
            공백·태그 차이로 직접 매칭이 실패하면 공백 유연 정규식으로 재시도.
            치환 실패 시 None."""
            if len(quote) < 6:
                return None  # '100%' 같은 짧은 인용은 스타일 훼손 위험 — 건너뜀

            def _in_tag(pos: int) -> bool:
                lt = html_text.rfind("<", 0, pos)
                gt = html_text.rfind(">", 0, pos)
                return lt > gt  # 직전 '<'가 '>'보다 뒤 = 태그 내부

            # ① 직접 매칭 (태그 밖 첫 위치)
            start = 0
            while True:
                pos = html_text.find(quote, start)
                if pos == -1:
                    break
                if not _in_tag(pos):
                    return html_text[:pos] + fix + html_text[pos + len(quote):]
                start = pos + 1
            # ② 공백 유연 정규식 (plain은 \s+ 정규화되어 있어 HTML과 어긋날 수 있음)
            pattern = re.escape(quote).replace(r"\ ", r"\s+")
            for m2 in re.finditer(pattern, html_text):
                if not _in_tag(m2.start()):
                    return html_text[:m2.start()] + fix + html_text[m2.end():]
            return None

        applied = 0
        issue_records = []
        for issue in result.get("issues", [])[:5]:
            quote, fix = issue.get("quote", ""), issue.get("fix", "")
            fixed = False
            if quote and fix:
                replaced = _safe_replace(content_html, quote, fix)
                if replaced is not None:
                    content_html = replaced
                    applied += 1
                    fixed = True
            issue_records.append({"problem": issue.get("problem", ""), "fixed": fixed})
        if applied:
            post_data["content"] = content_html

        post_data["fact_check"] = {
            "checked": True,
            "verdict": result.get("verdict", "pass"),
            "issues_found": len(result.get("issues", [])),
            "fixes_applied": applied,
            "issues": issue_records,
        }
        if result.get("issues"):
            logger.info(
                f"팩트체크: 이슈 {len(result['issues'])}건 발견, {applied}건 자동 수정 적용"
            )
        else:
            logger.info("팩트체크: 통과")
    except Exception as e:
        logger.warning(f"팩트체크 실패 (게시는 계속 진행): {e}")
        post_data["fact_check"] = {"checked": False, "reason": str(e)[:100]}


def _retry_escalation_note(attempt: int, prev_wc: int) -> str:
    """재시도 시 분량 부족 피드백 메시지를 반환합니다."""
    if attempt == 0 or prev_wc <= 0:
        return ""
    needed = max(0, 2500 - prev_wc)
    needed_str = f"지금 {needed}자가 더 필요합니다 — 각 섹션을 더 길고 구체적으로 작성하세요\n" if needed > 0 else "분량은 충분하지만 구조를 개선하세요\n"
    return (
        f"\n\n⚠️⚠️⚠️ [재시도 {attempt}/2] 이전 응답이 {prev_wc}자로 너무 짧았습니다.\n"
        "이번에는 반드시 다음을 지키세요:\n"
        f"  - H2 섹션마다 최소 500자(공백 제외)\n"
        f"  - 도입부 최소 300자 (경험담으로 풍부하게)\n"
        f"  - FAQ 각 답변 150자 이상\n"
        f"  - 전체 content 필드 텍스트 기준 2500자 이상(공백 제외)\n"
        f"  - {needed_str}"
        "⚠️⚠️⚠️\n"
    )


def _run_research(keyword: str) -> dict | None:
    """글 작성 전 자료 조사 파이프라인 실행 → 검증된 자료팩 반환.

    RESEARCH_ENGINE=false로 비활성화 가능. 실패해도 글 생성은 계속되며,
    자료팩이 없으면 프롬프트에 '검증 불가 수치 작성 금지' 폴백 규칙이 들어갑니다.
    """
    if os.getenv("RESEARCH_ENGINE", "true").strip().lower() not in ("true", "1", "yes"):
        return None
    try:
        from research_collector import collect_research
        from evidence_builder import build_evidence_pack, save_evidence_pack
        from source_validator import validate_pack
        research = collect_research(keyword)
        if not research.get("materials"):
            return None
        pack = build_evidence_pack(research)
        if not pack.get("facts"):
            return None
        pack = validate_pack(pack)
        save_evidence_pack(pack)
        return pack
    except Exception as exc:
        logger.warning(f"자료 조사 실패 (글 생성은 계속): {exc}")
        return None


def generate_post(keyword: str, traffic: str = "N/A", blog_config: dict | None = None) -> dict | None:
    """Claude API로 포스트 생성 후 이미지를 자동 삽입합니다. 실패 시 최대 2회 재시도."""
    logger.info(f"포스트 생성 중: '{keyword}'")

    # 글 작성 전 자료 조사 — 검증된 자료팩만 사실 근거로 사용
    from evidence_builder import format_evidence_for_prompt
    evidence_pack = _run_research(keyword)
    prompt = _build_prompt(keyword, traffic, blog_config) + format_evidence_for_prompt(evidence_pack)

    is_blog1 = blog_config and blog_config.get("id") == "blog1"
    ai_provider = _resolve_ai_provider(blog_config)
    prev_wc = 0
    for attempt in range(3):
        try:
            from datetime import datetime as _dt
            _now = _dt.now()
            blog_lang = (blog_config or {}).get("language", BLOG_LANGUAGE)
            if is_blog1:
                _sys = (
                    f"현재 날짜: {_now.strftime('%Y년 %m월 %d일')}. "
                    "당신은 관심 주제를 깊이 조사하고 공부해서 솔직하게 정리해 올리는 블로거입니다. 하지 않은 경험을 한 것처럼 쓰지 않습니다. "
                    "구글 애드센스 정책을 완전히 준수하며, AI가 쓴 것처럼 보이지 않는 자연스러운 한국어 문체로 작성합니다. "
                    "독자에게 실질적인 도움이 되는 정보를 제공하는 것이 최우선입니다. "
                    "JSON만 응답하세요."
                )
            elif blog_lang == "ko":
                _sys = (
                    f"현재 날짜: {_now.strftime('%Y년 %m월 %d일')}. "
                    "당신은 신뢰할 수 있는 정보를 조사·정리해 솔직하게 글을 쓰는 블로거입니다. 하지 않은 경험을 한 것처럼 쓰지 않습니다. "
                    "AI가 쓴 것처럼 보이지 않게, 사람 냄새 나는 자연스러운 한국어 블로그 글을 씁니다. "
                    "지식 학습 시점 이후의 사건은 '최근 동향에 따르면' 등으로 처리하세요. "
                    "JSON만 응답하세요."
                )
            else:
                _sys = (
                    f"Current date: {_now.strftime('%B %d, %Y')}. "
                    "You are a blogger who writes well-researched, trustworthy posts. Never fabricate personal experiences. "
                    "Write naturally, like a real person — not an AI report. "
                    "For events after your knowledge cutoff, use 'according to recent trends'. "
                    "JSON only."
                )
            escalation = _retry_escalation_note(attempt, prev_wc)
            logger.info(f"  AI 제공자: {ai_provider.upper()} (시도 {attempt + 1}/3)")
            raw = _ai_generate(_sys, prompt + escalation, ai_provider).strip()
            if not raw:
                logger.error(f"{ai_provider.upper()} 응답 없음 또는 max_tokens로 잘림")
                if attempt < 2:
                    time.sleep(2)
                    continue
                return None
            post_data = _parse_response(raw)

            if post_data is None:
                if attempt < 2:
                    logger.warning(f"JSON 파싱 실패 — 재시도 {attempt + 1}/3")
                    prev_wc = -1  # 파싱 실패 센티널 — escalation note 생략 구분용
                    time.sleep(2)
                    continue
                return None

            post_data["keyword"] = keyword
            post_data["article_type"] = _detect_article_type(keyword)
            post_data["risk_level"] = _assess_risk_level(keyword)
            # 표준 스키마: tags는 labels의 별칭 (내부 링크·대시보드 공용)
            post_data["tags"] = list(post_data.get("labels", []) or [])

            # 글자 수 및 미리보기 추가
            content_html = post_data.get("content", "")
            post_data["word_count"] = _word_count(content_html)
            post_data["content_preview"] = _content_preview(content_html)

            # 컨텐츠 유효성 검사 — AdSense thin content 방지 (최소 2500자)
            prev_wc = post_data["word_count"]
            if not content_html.strip() or post_data["word_count"] < 2500:
                if attempt < 2:
                    logger.warning(f"컨텐츠 너무 짧음({post_data['word_count']}자, 최소 2500자) — 재시도 {attempt + 1}/3")
                    time.sleep(3)
                    continue
                if post_data["word_count"] < 500:
                    logger.error(f"컨텐츠 생성 실패: {post_data['word_count']}자 — thin content 방지를 위해 게시 거부")
                    return None
                logger.warning(f"최소 분량 미달({post_data['word_count']}자) — 재시도 소진, 해당 분량으로 진행")

            # sources 필드 유효성 검증 (hallucinated URL 필터링)
            if not isinstance(post_data.get("sources"), list):
                post_data["sources"] = []
                logger.warning("sources 필드 누락 또는 잘못된 형식 — 초기화")
            else:
                post_data["sources"] = _validate_sources(post_data["sources"])
                if not post_data["sources"]:
                    logger.warning("sources 필드: 유효한 출처 없음 — 전부 제거됨")

            # 자료팩 출처를 sources에 병합 (검증된 출처 우선)
            _merge_evidence(post_data, evidence_pack)

            # 게시 전 팩트체크 — 이미지 삽입 전에 실행 (이미지 HTML 훼손 방지)
            _fact_check_content(post_data, keyword, evidence_pack)

            # 섹션별 이미지 검색 & 삽입 (관련성 검증 포함) — 1장만
            section_queries = _extract_section_queries(post_data.get("content", ""), keyword)
            logger.info(f"섹션별 이미지 검색: {section_queries[:1]}")
            plain_text = _content_preview(post_data.get("content", ""), chars=600)
            images = fetch_images_for_queries(
                section_queries[:1],
                naver_client_id=os.getenv("NAVER_CLIENT_ID", ""),
                naver_client_secret=os.getenv("NAVER_CLIENT_SECRET", ""),
                pixabay_api_key=os.getenv("PIXABAY_API_KEY", ""),
                article_plain_text=plain_text,
                keyword=keyword,
            )
            images = images[:1]
            if images:
                post_data["content"] = inject_images_into_content(
                    post_data["content"], images, keyword
                )
                post_data["images_inserted"] = len(images)
                logger.info(f"이미지 {len(images)}개 본문 삽입 완료")
            else:
                post_data["images_inserted"] = 0
                logger.warning("글 내용과 맞는 이미지 없음 — 텍스트만으로 업로드 진행")

            # 인라인 스타일 비주얼 디자인 적용 (주제별 컬러 테마)
            post_data["content"] = _apply_design(
                post_data["content"], keyword, _detect_article_type(keyword)
            )

            # 쿠팡파트너스 추천 상품 섹션 삽입 (AdSense 자동 광고와 겹치지 않게 맨 하단 고정)
            post_data["content"] = inject_affiliate_section(
                post_data["content"], keyword, blog_config
            )

            logger.info(
                f"포스트 생성 완료: '{post_data.get('title', '?')}' "
                f"({post_data['word_count']}자, 이미지 {post_data['images_inserted']}개)"
            )
            return post_data

        except anthropic.APIStatusError as e:
            if attempt < 2 and e.status_code in (429, 529):
                wait = 8 * (2 ** attempt)
                logger.warning(f"API 과부하 — {wait}s 후 재시도 ({attempt + 1}/2)")
                time.sleep(wait)
            else:
                logger.error(f"Claude API 오류: {e}")
                return None
        except anthropic.APIError as e:
            logger.error(f"Claude API 오류: {e}")
            return None
        except Exception as e:
            logger.error(f"포스트 생성 오류: {e}", exc_info=True)
            return None

    return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = generate_post("재테크 방법", "100K+")
    if result:
        print(f"제목: {result['title']}")
        print(f"라벨: {result['labels']}")
        print(f"글자 수: {result.get('word_count', 0)}자")
        print(f"이미지: {result.get('images_inserted', 0)}개")
        print(f"FAQ: {len(result.get('faq', []))}개")
        print(f"미리보기: {result.get('content_preview', '')[:100]}")

