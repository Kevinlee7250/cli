"""시리즈 포스트 자동 기획 — 큰 주제를 N편으로 분할, 내부 링크 연결"""

import json
import logging
import os
import re
import uuid
from datetime import datetime

import anthropic

from config import claude_text, ANTHROPIC_API_KEY, CLAUDE_MODEL, BLOG_LANGUAGE

logger = logging.getLogger(__name__)

SERIES_FILE = os.path.join(os.path.dirname(__file__), "logs", "series.json")
_MAX_SERIES = 50

# 블로그별 주제 맵
_BLOG_TOPIC_MAP = {
    "blog1": {"label": "여행·드라마·연예·K-POP", "topics": ["여행", "드라마", "영화", "연예", "K-POP"]},
    "blog2": {"label": "IT·AI·기술", "topics": ["IT", "AI", "기술", "스마트폰", "앱", "테크"]},
    "blog3": {"label": "금융·경제·정부지원", "topics": ["금융", "경제", "정부지원", "세금", "복지", "시책"]},
}


def _get_blog_id(blog_config) -> str:
    return (blog_config or {}).get("id", "")


# ─────────────────────────────────────────────
# I/O
# ─────────────────────────────────────────────

def get_last_series_date(blog_id: str = "") -> datetime | None:
    """가장 최근에 생성된 시리즈의 날짜를 반환합니다 (blog_id 지정 시 해당 블로그만). 없으면 None."""
    for s in load_series():
        if blog_id and s.get("blog_id") and s["blog_id"] != blog_id:
            continue
        created = s.get("created_at")
        if created:
            try:
                return datetime.fromisoformat(created)
            except ValueError:
                continue
    return None


def pick_series_keyword(keywords: list[str], blog_config: dict | None = None) -> str | None:
    """
    키워드 목록 중 블로그 주제에 맞게 시리즈로 확장하기 가장 적합한 키워드 1개를 Claude가 선택합니다.
    모든 키워드가 시리즈 부적합이면 None을 반환합니다.
    """
    if not keywords:
        return None

    blog_id = _get_blog_id(blog_config)
    topic_info = _BLOG_TOPIC_MAP.get(blog_id, {})
    topic_label = topic_info.get("label", "")
    topic_filter = (
        f"\n• 이 블로그 주제({topic_label})와 직접 관련된 키워드를 우선 선택하세요."
        if topic_label else ""
    )

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        kw_list = "\n".join(f"{i + 1}. {kw}" for i, kw in enumerate(keywords))
        prompt = (
            "다음 키워드 목록 중 3~4편 블로그 시리즈로 확장하기 가장 적합한 것 1개를 선택하세요.\n\n"
            "선택 기준:\n"
            "• 한 주제 안에 서로 다른 하위 각도 3개 이상이 나올 수 있는 것\n"
            "• 독자가 여러 편을 이어 읽을 만큼 깊이와 범위가 있는 것\n"
            "• 즉각적인 속보가 아닌 지속 검색 수요가 있는 것\n"
            f"• 모든 키워드가 시리즈로 확장하기 어려우면 'none' 반환{topic_filter}\n\n"
            f"키워드 목록:\n{kw_list}\n\n"
            "번호만 응답 (예: 2) 또는 none:"
        )
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}],
        )
        ans = claude_text(msg).strip().lower()
        if "none" in ans:
            logger.info("시리즈 적합 키워드 없음 — 단독 포스트로 진행")
            return None
        m = re.search(r'\d+', ans)
        if m:
            idx = int(m.group()) - 1
            if 0 <= idx < len(keywords):
                chosen = keywords[idx]
                logger.info(f"자동 시리즈 키워드 선정: '{chosen}'")
                return chosen
    except Exception as e:
        logger.debug(f"시리즈 키워드 자동 선정 실패: {e}")
    return None


def load_series() -> list:
    try:
        with open(SERIES_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_series_with_blog(series_plan: dict, blog_config: dict | None = None) -> None:
    """blog_id를 태깅하고 저장합니다."""
    blog_id = _get_blog_id(blog_config)
    if blog_id and not series_plan.get("blog_id"):
        series_plan["blog_id"] = blog_id
    save_series(series_plan)


def save_series(series_plan: dict) -> None:
    """시리즈 기획 저장 (series_id 기준 upsert)"""
    os.makedirs(os.path.dirname(SERIES_FILE), exist_ok=True)
    series_list = load_series()
    sid = series_plan.get("series_id")
    for i, s in enumerate(series_list):
        if s.get("series_id") == sid:
            series_list[i] = series_plan
            break
    else:
        series_list.insert(0, series_plan)
    with open(SERIES_FILE, "w", encoding="utf-8") as f:
        json.dump(series_list[:_MAX_SERIES], f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────
# 기획 — 공통 헬퍼
# ─────────────────────────────────────────────

def _finalize_plan(plan: dict, keyword: str, blog_config: dict | None = None) -> dict:
    """series_id·blog_id·메타 필드를 채웁니다."""
    plan["series_id"] = str(uuid.uuid4())[:8]
    plan["keyword"] = keyword
    plan["total_episodes"] = len(plan.get("episodes", []))
    plan["created_at"] = datetime.now().isoformat()
    plan["status"] = "planned"
    blog_id = _get_blog_id(blog_config)
    if blog_id:
        plan["blog_id"] = blog_id
        plan["blog_name"] = (blog_config or {}).get("name", "")
    for ep in plan.get("episodes", []):
        ep.setdefault("status", "pending")
        ep.setdefault("post_id", None)
        ep.setdefault("blogger_url", None)
    return plan


def _call_claude_plan(prompt: str, system: str) -> dict | None:
    """Claude에 기획 프롬프트를 보내고 JSON을 파싱합니다."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2000,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = claude_text(msg).strip()
    s, e = raw.find("{"), raw.rfind("}")
    if s == -1 or e <= s:
        raise ValueError(f"JSON 파싱 실패: {raw[:300]}")
    return json.loads(raw[s:e + 1])


# ─────────────────────────────────────────────
# 기획 — blog1 (여행·드라마·연예·K-POP)
# ─────────────────────────────────────────────

def _plan_blog1_series(keyword: str, count: int, blog_config: dict | None = None) -> dict | None:
    """blog1용 시리즈 기획 — 여행·드라마·연예·K-POP 주제, 개인 경험 공유 스타일."""
    now = datetime.now()
    y = now.year
    date_str = now.strftime("%Y년 %m월 %d일")
    prompt = f"""오늘: {date_str}
주제 키워드: {keyword}
시리즈 편수: {count}편
블로그 주제: 여행, 드라마, 영화, 연예, K-POP

이 주제로 {count}편짜리 블로그 시리즈를 기획하세요.
글쓰기 방향: 정보 나열이 아닌 '직접 경험하고 공부한 사람의 인사이트 공유' 스타일.

시리즈 구조 원칙:
- 편 1: "왜 이 주제를 파게 됐는지" — 입문자 공감형 도입 (계기·실패담·첫 경험)
- 편 2~{count - 1}: 실전 경험 기반 심화 (각자 독립적 주제, 남들이 안 다루는 구체적 각도)
- 편 {count}: 지금까지 배운 것들의 솔직한 총평 + 실전 액션 플랜
- 각 편: 독립적으로 읽어도 완결되는 글, "이 각도는 다른 곳에서 못 봤다"는 느낌
- 제목: 경험·솔직함·구체성 강조 (예: "직접 가봤더니", "이것만은 진짜 주의", "{y}년 현재 기준")
- 제목 40자 이내

JSON만 응답 (마크다운 없이):
{{
  "series_title": "시리즈 전체 제목 (경험 기반, 예: {keyword} 직접 해보고 정리한 시리즈)",
  "series_label": "Blogger 라벨 태그 (공백 없음, 하이픈 사용)",
  "series_description": "시리즈 소개: 어떤 경험을 기반으로 쓰는 시리즈인지 (100자 이내)",
  "episodes": [
    {{
      "episode": 1,
      "title": "[1편] ... (40자 이내, 경험/솔직함 강조)",
      "focus": "이 편의 핵심 — 어떤 경험/인사이트를 공유하는지 (30자 이내)",
      "search_keyword": "이 편의 대표 검색 키워드 (구체적으로)"
    }}
  ]
}}"""
    try:
        plan = _call_claude_plan(prompt, f"현재 날짜: {date_str}. JSON만 응답하세요.")
        plan = _finalize_plan(plan, keyword, blog_config)
        logger.info(f"[blog1] 시리즈 기획 완료: '{plan.get('series_title')}' {plan['total_episodes']}편")
        return plan
    except Exception as exc:
        logger.error(f"[blog1] 시리즈 기획 오류: {exc}", exc_info=True)
        return None


# ─────────────────────────────────────────────
# 기획 — blog2 (IT·AI·기술)
# ─────────────────────────────────────────────

def plan_it_series(keyword: str, count: int = 4, blog_config: dict | None = None) -> dict | None:
    """blog2용 시리즈 기획 — IT·AI·기술 주제, 직접 테스트 경험 기반 스타일."""
    count = max(2, min(count, 5))
    now = datetime.now()
    y = now.year
    date_str = now.strftime("%Y년 %m월 %d일")
    prompt = f"""오늘: {date_str}
주제 키워드: {keyword}
시리즈 편수: {count}편
블로그 주제: IT, AI, 기술, 스마트폰, 앱, 테크

이 IT/기술 주제로 {count}편짜리 블로그 시리즈를 기획하세요.
글쓰기 방향: '직접 써본 IT 사용자의 솔직한 사용기·비교·팁 공유' 스타일.
광고·홍보 느낌 절대 금지. 불편한 점·아쉬운 점도 솔직히 작성.

시리즈 구조 원칙:
- 편 1: "왜 이 기술/제품을 써보게 됐나" — 사용 계기·첫인상 (긍정+부정 균형 있게)
- 편 2~{count - 1}: 실제 사용 경험 심화 — 기능별 상세 테스트, 타 제품 비교, 숨겨진 팁
- 편 {count}: 한 달(또는 장기) 사용 후 솔직한 총평 + 추천 대상 명확히
- 제목: 직접성·구체성 강조 (예: "직접 써봤더니", "실제 성능 테스트", "{y}년 최신 버전")
- 제목 40자 이내

JSON만 응답 (마크다운 없이):
{{
  "series_title": "시리즈 전체 제목 (IT 사용기 기반, 예: {keyword} 직접 써본 사용기 시리즈)",
  "series_label": "Blogger 라벨 태그 (공백 없음, 하이픈 사용, IT 관련)",
  "series_description": "어떤 IT 경험/테스트를 기반으로 쓰는 시리즈인지 (100자 이내)",
  "series_type": "it_review",
  "episodes": [
    {{
      "episode": 1,
      "title": "[1편] ... (40자 이내, 직접 사용/테스트 강조)",
      "focus": "이 편의 핵심 IT 경험/테스트 내용 (30자 이내)",
      "search_keyword": "이 편의 대표 IT 검색 키워드 (구체적인 기능·제품명 포함)"
    }}
  ]
}}"""
    try:
        plan = _call_claude_plan(prompt, f"현재 날짜: {date_str}. JSON만 응답하세요.")
        plan = _finalize_plan(plan, keyword, blog_config)
        logger.info(f"[blog2 IT] 시리즈 기획 완료: '{plan.get('series_title')}' {plan['total_episodes']}편")
        return plan
    except Exception as exc:
        logger.error(f"[blog2 IT] 시리즈 기획 오류: {exc}", exc_info=True)
        return None


# ─────────────────────────────────────────────
# 기획 — blog3 (금융·경제·정부지원)
# ─────────────────────────────────────────────

def plan_finance_series(keyword: str, count: int = 4, blog_config: dict | None = None) -> dict | None:
    """blog3용 시리즈 기획 — 금융·정부지원 주제, 공신력 있는 정보 + 개인 경험 스타일."""
    count = max(2, min(count, 5))
    now = datetime.now()
    y = now.year
    date_str = now.strftime("%Y년 %m월 %d일")
    prompt = f"""오늘: {date_str}
주제 키워드: {keyword}
시리즈 편수: {count}편
블로그 주제: 금융뉴스, 은행·대출, 정부지원시책, 세금·절세, 경제정책

이 금융/정부지원 주제로 {count}편짜리 블로그 시리즈를 기획하세요.
글쓰기 방향: '직접 알아보고 신청/경험한 직장인·개인 투자자 시점의 실용 정보 공유' 스타일.
공신력 있는 출처(기획재정부·금융위원회·국세청·금융감독원 등) 기반. 투자 권유 절대 금지.

시리즈 구조 원칙:
- 편 1: "왜 이걸 알아보기 시작했나" — 실생활 공감 계기 (세금 고지서, 대출 거절, 신청 기회 놓침 등)
- 편 2~{count - 1}: 핵심 정보 심화 — 신청 방법, 자격 조건, 놓치기 쉬운 조항, 실제 계산 예시
- 편 {count}: 직접 신청·경험한 후기 + 주의사항 총정리 + 추천 대상 명확히
- 제목: 실용성·구체성 강조 (예: "직접 신청해봤더니", "자격 조건 총정리", "{y}년 최신 기준")
- 제목 40자 이내
- ※ 투자 조언·수익 보장 표현 사용 금지

JSON만 응답 (마크다운 없이):
{{
  "series_title": "시리즈 전체 제목 (금융 실용 기반, 예: {keyword} 직접 알아본 완전 정리 시리즈)",
  "series_label": "Blogger 라벨 태그 (공백 없음, 하이픈 사용, 금융 관련)",
  "series_description": "어떤 금융/정책 경험을 기반으로 쓰는 시리즈인지 (100자 이내)",
  "series_type": "finance_news",
  "episodes": [
    {{
      "episode": 1,
      "title": "[1편] ... (40자 이내, 실용/경험 강조)",
      "focus": "이 편의 핵심 금융 정보/경험 (30자 이내)",
      "search_keyword": "이 편의 대표 금융 검색 키워드 (구체적 제도·상품명 포함)"
    }}
  ]
}}"""
    try:
        plan = _call_claude_plan(prompt, f"현재 날짜: {date_str}. JSON만 응답하세요.")
        plan = _finalize_plan(plan, keyword, blog_config)
        logger.info(f"[blog3 금융] 시리즈 기획 완료: '{plan.get('series_title')}' {plan['total_episodes']}편")
        return plan
    except Exception as exc:
        logger.error(f"[blog3 금융] 시리즈 기획 오류: {exc}", exc_info=True)
        return None


# ─────────────────────────────────────────────
# 기획 — 일반 (블로그 미지정 또는 영문)
# ─────────────────────────────────────────────

def _plan_general_series(keyword: str, count: int, blog_config: dict | None = None) -> dict | None:
    """일반 시리즈 기획 (blog_id 미지정 또는 영문 블로그)."""
    now = datetime.now()
    y = now.year
    date_str = now.strftime("%Y년 %m월 %d일") if BLOG_LANGUAGE == "ko" else now.strftime("%B %d, %Y")
    if BLOG_LANGUAGE == "ko":
        prompt = f"""오늘: {date_str} / 키워드: {keyword} / 편수: {count}

{count}편 블로그 시리즈 기획 (경험 기반 인사이트 공유 스타일).
편 1: 입문 계기·첫 경험 / 편 2~{count-1}: 실전 심화 / 편 {count}: 총평+액션플랜
제목 40자 이내.

JSON만 응답:
{{"series_title":"","series_label":"","series_description":"","episodes":[{{"episode":1,"title":"","focus":"","search_keyword":""}}]}}"""
    else:
        prompt = f"""Today: {date_str} / Topic: {keyword} / Parts: {count}
Plan a {count}-part series (personal experience angle). Part 1: entry story / Middle: deep dives / Last: honest verdict.
Titles under 65 chars. JSON only:
{{"series_title":"","series_label":"","series_description":"","episodes":[{{"episode":1,"title":"","focus":"","search_keyword":""}}]}}"""
    try:
        system = f"현재 날짜: {date_str}. JSON만 응답." if BLOG_LANGUAGE == "ko" else f"Date: {date_str}. JSON only."
        plan = _call_claude_plan(prompt, system)
        plan = _finalize_plan(plan, keyword, blog_config)
        logger.info(f"시리즈 기획 완료: '{plan.get('series_title')}' {plan['total_episodes']}편")
        return plan
    except Exception as exc:
        logger.error(f"시리즈 기획 오류: {exc}", exc_info=True)
        return None


# ─────────────────────────────────────────────
# 기획 — 라우터 (공개 인터페이스)
# ─────────────────────────────────────────────

def plan_series(keyword: str, count: int = 4, blog_config: dict | None = None) -> dict | None:
    """블로그 주제에 맞는 시리즈 기획안을 생성합니다."""
    count = max(2, min(count, 5))
    blog_id = _get_blog_id(blog_config)
    if blog_id == "blog2":
        return plan_it_series(keyword, count, blog_config)
    if blog_id == "blog3":
        return plan_finance_series(keyword, count, blog_config)
    if blog_id == "blog1":
        return _plan_blog1_series(keyword, count, blog_config)
    return _plan_general_series(keyword, count, blog_config)


# ─────────────────────────────────────────────
# 드라마 리뷰 시리즈 기획
# ─────────────────────────────────────────────

def plan_drama_series(drama_name: str, count: int = 4) -> dict | None:
    """
    인기 드라마 리뷰 특화 시리즈를 기획합니다.
    편 구성: 소개·첫인상 → 인물 분석 → 명장면·반전 → 결말·총평·추천
    """
    count = max(3, min(count, 5))
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        now = datetime.now()
        y = now.year
        date_str = now.strftime("%Y년 %m월 %d일")

        # 편수별 구조 가이드 동적 생성
        mid_eps = ""
        if count >= 4:
            mid_eps = f"\n- 편 3: 중반부 명장면·화제 장면 해석 + 반전 포인트 (스포 주의 안내 포함)"
        if count >= 5:
            mid_eps = mid_eps + f"\n- 편 4: OST 전곡 소개 + 촬영지·배경 이야기 + 제작비화"

        prompt = f"""오늘: {date_str}
드라마: {drama_name}
편수: {count}편

"{drama_name}" 드라마 리뷰 블로그 시리즈를 기획하세요.
관점: 직접 시청한 일반 시청자의 솔직한 감상 — 홍보·광고 아님.

편 구성 원칙:
- 편 1: 첫인상 + 시청 전 알면 좋은 것 (줄거리 스포 최소화, 장르·분위기 위주)
- 편 2: 등장인물 심층 분석 + 배우 연기력 솔직 평가 + 인물 관계도{mid_eps}
- 편 {count}: 결말 종합 총평 (스포 주의 경고 포함) + OST 추천 + 유사 드라마 추천 + 최종 별점
- 각 편은 독립적으로 읽어도 가치 있어야 함
- 제목: 검색 의도 명확하게 (예: "{drama_name} 1화 첫인상 솔직 리뷰", "{drama_name} 등장인물 분석")
- 제목 40자 이내, {y}년 포함

JSON만 응답:
{{
  "series_title": "{drama_name} 드라마 리뷰 시리즈",
  "series_label": "드라마리뷰",
  "drama_label": "{re.sub(r'[^가-힣a-zA-Z0-9]', '-', drama_name)}",
  "series_description": "직접 본 시청자 입장의 {drama_name} 솔직 리뷰 시리즈 (100자 이내)",
  "drama_name": "{drama_name}",
  "episodes": [
    {{
      "episode": 1,
      "title": "[1편] ... (40자 이내, {y} 포함)",
      "focus": "이 편의 핵심 포커스 (30자 이내)",
      "search_keyword": "이 편의 대표 검색 키워드 (드라마명 + 세부 주제)"
    }}
  ]
}}"""

        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2000,
            system=f"현재 날짜: {date_str}. JSON만 응답하세요.",
            messages=[{"role": "user", "content": prompt}],
        )
        raw = claude_text(msg).strip()
        s, e = raw.find("{"), raw.rfind("}")
        if s == -1 or e <= s:
            logger.error(f"드라마 시리즈 기획 JSON 파싱 실패: {raw[:300]}")
            return None
        plan = json.loads(raw[s:e + 1])

        plan["series_id"] = str(uuid.uuid4())[:8]
        plan["keyword"] = drama_name
        plan["total_episodes"] = len(plan.get("episodes", []))
        plan["created_at"] = datetime.now().isoformat()
        plan["status"] = "planned"
        plan["type"] = "drama_review"

        for ep in plan.get("episodes", []):
            ep.setdefault("status", "pending")
            ep.setdefault("post_id", None)
            ep.setdefault("blogger_url", None)

        logger.info(f"드라마 시리즈 기획 완료: '{plan.get('series_title')}' {plan['total_episodes']}편")
        return plan

    except Exception as exc:
        logger.error(f"드라마 시리즈 기획 오류: {exc}", exc_info=True)
        return None


# ─────────────────────────────────────────────
# 내비게이션 HTML
# ─────────────────────────────────────────────

def build_series_nav(series_plan: dict, current_episode: int, blog_url: str = "") -> str:
    """시리즈 내비게이션 + 목차 HTML을 생성합니다."""
    episodes = series_plan.get("episodes", [])
    series_title = series_plan.get("series_title", "")
    series_label = series_plan.get("series_label", "")
    total = series_plan.get("total_episodes", len(episodes))

    toc_items = ""
    for ep in episodes:
        ep_num = ep["episode"]
        ep_title = ep.get("title", f"{ep_num}편")
        ep_url = ep.get("blogger_url")
        is_current = ep_num == current_episode
        is_done = ep.get("status") == "done" and ep_url

        if is_current:
            toc_items += (
                f'<li style="margin:5px 0;font-weight:700;color:#1a73e8;">'
                f'{ep_title} ◀ 현재 글</li>'
            )
        elif is_done:
            toc_items += (
                f'<li style="margin:5px 0;">'
                f'<a href="{ep_url}" style="color:#1a73e8;text-decoration:none;">{ep_title}</a></li>'
            )
        else:
            toc_items += (
                f'<li style="margin:5px 0;color:#999;">'
                f'{ep_title} <span style="font-size:11px;">(업데이트 예정)</span></li>'
            )

    prev_ep = next((ep for ep in episodes if ep["episode"] == current_episode - 1), None)
    next_ep = next((ep for ep in episodes if ep["episode"] == current_episode + 1), None)

    nav_buttons = ""
    if prev_ep or next_ep:
        nav_buttons = '<div style="display:flex;gap:10px;margin-top:14px;flex-wrap:wrap;">'
        if prev_ep and prev_ep.get("blogger_url"):
            nav_buttons += (
                f'<a href="{prev_ep["blogger_url"]}" '
                f'style="flex:1;min-width:200px;padding:11px 14px;background:#f1f3f4;'
                f'border-radius:8px;text-decoration:none;color:#333;font-size:13px;">'
                f'◀ 이전 편<br>'
                f'<strong style="font-size:12px;">{prev_ep.get("title", "")[:30]}</strong></a>'
            )
        if next_ep:
            next_url = next_ep.get("blogger_url") or "#"
            fade = "opacity:0.55;" if not next_ep.get("blogger_url") else ""
            nav_buttons += (
                f'<a href="{next_url}" '
                f'style="flex:1;min-width:200px;padding:11px 14px;background:#e8f0fe;'
                f'border-radius:8px;text-decoration:none;color:#1a73e8;font-size:13px;{fade}">'
                f'다음 편 ▶<br>'
                f'<strong style="font-size:12px;">{next_ep.get("title", "")[:30]}</strong></a>'
            )
        nav_buttons += "</div>"

    if series_label:
        base = blog_url.rstrip("/") if blog_url else ""
        label_url = f"{base}/search/label/{series_label}" if base else f"/search/label/{series_label}"
        index_link = (
            f'<a href="{label_url}" style="font-size:12px;color:#1a73e8;text-decoration:none;">📋 시리즈 전체 보기</a>'
        )
    else:
        index_link = ""

    return (
        f'<div style="background:#f0f4ff;border:1px solid #c5d3f7;border-radius:12px;'
        f'padding:20px 24px;margin:1.5em 0;font-family:\'Noto Sans KR\',sans-serif;">'
        f'<div style="display:flex;justify-content:space-between;align-items:flex-start;'
        f'flex-wrap:wrap;gap:8px;">'
        f'<div><p style="font-weight:700;font-size:15px;margin:0 0 2px;color:#1a73e8;">📚 {series_title}</p>'
        f'<p style="font-size:12px;color:#888;margin:0;">{current_episode}/{total}편 · {index_link}</p></div>'
        f'</div>'
        f'<ol style="margin:12px 0 0;padding-left:18px;font-size:13px;line-height:1.9;">'
        f'{toc_items}</ol>'
        f'{nav_buttons}'
        f'</div>'
    )
