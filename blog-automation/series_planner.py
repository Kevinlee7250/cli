"""시리즈 포스트 자동 기획 — 큰 주제를 N편으로 분할, 내부 링크 연결"""

import json
import logging
import os
import uuid
from datetime import datetime

import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, BLOG_LANGUAGE

logger = logging.getLogger(__name__)

SERIES_FILE = os.path.join(os.path.dirname(__file__), "logs", "series.json")
_MAX_SERIES = 50


# ─────────────────────────────────────────────
# I/O
# ─────────────────────────────────────────────

def load_series() -> list:
    try:
        with open(SERIES_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


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
# 기획
# ─────────────────────────────────────────────

def plan_series(keyword: str, count: int = 4) -> dict | None:
    """Claude AI로 시리즈 기획안을 생성합니다."""
    count = max(2, min(count, 5))
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        now = datetime.now()
        y = now.year
        date_str = now.strftime("%Y년 %m월 %d일") if BLOG_LANGUAGE == "ko" else now.strftime("%B %d, %Y")

        if BLOG_LANGUAGE == "ko":
            prompt = f"""오늘: {date_str}
주제 키워드: {keyword}
시리즈 편수: {count}편

이 주제로 {count}편짜리 블로그 시리즈를 기획하세요.

조건:
- 편 1: 개요·입문 (처음 접하는 독자 대상)
- 편 2~{count - 1}: 심화 내용 (구체적 방법, 사례, 전략)
- 편 {count}: 실전 총정리 (바로 적용 가능한 액션 플랜)
- 각 편은 독립적으로 읽어도 충분한 가치가 있어야 함
- 각 편 제목: 숫자 포함, {y}년 포함, 35자 이내

JSON만 응답 (마크다운 없이):
{{
  "series_title": "시리즈 전체 제목 (예: 2026년 재테크 완전정복 시리즈)",
  "series_label": "Blogger 라벨 태그 (공백 없음, 하이픈 사용, 예: 재테크-시리즈-2026)",
  "series_description": "시리즈 소개 (100자 이내)",
  "episodes": [
    {{
      "episode": 1,
      "title": "[1편] {y}년 ... (35자 이내, 숫자 포함)",
      "focus": "이 편의 핵심 주제 (30자 이내)",
      "search_keyword": "이 편의 대표 검색 키워드"
    }}
  ]
}}"""
        else:
            prompt = f"""Today: {date_str}
Topic: {keyword}  Episodes: {count}

Plan a {count}-part blog series.
- Part 1: overview/intro for beginners
- Parts 2-{count - 1}: deep dives (methods, case studies, strategies)
- Part {count}: complete action guide

Each part must be valuable standalone. Titles include numbers and {y}, under 65 chars.

JSON only:
{{
  "series_title": "Full series title",
  "series_label": "blogger-label-no-spaces",
  "series_description": "Series description under 150 chars",
  "episodes": [
    {{
      "episode": 1,
      "title": "[Part 1] {y} ... (under 65 chars)",
      "focus": "Core focus of this episode",
      "search_keyword": "primary search keyword"
    }}
  ]
}}"""

        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2000,
            system=(
                f"현재 날짜: {date_str}. JSON만 응답하세요."
                if BLOG_LANGUAGE == "ko"
                else f"Current date: {date_str}. JSON only."
            ),
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        s, e = raw.find("{"), raw.rfind("}")
        if s == -1 or e <= s:
            logger.error(f"시리즈 기획 JSON 파싱 실패: {raw[:300]}")
            return None
        plan = json.loads(raw[s:e + 1])

        plan["series_id"] = str(uuid.uuid4())[:8]
        plan["keyword"] = keyword
        plan["total_episodes"] = len(plan.get("episodes", []))
        plan["created_at"] = datetime.now().isoformat()
        plan["status"] = "planned"

        for ep in plan.get("episodes", []):
            ep.setdefault("status", "pending")
            ep.setdefault("post_id", None)
            ep.setdefault("blogger_url", None)

        logger.info(f"시리즈 기획 완료: '{plan.get('series_title')}' {plan['total_episodes']}편")
        return plan

    except Exception as exc:
        logger.error(f"시리즈 기획 오류: {exc}", exc_info=True)
        return None


# ─────────────────────────────────────────────
# 내비게이션 HTML
# ─────────────────────────────────────────────

def build_series_nav(series_plan: dict, current_episode: int) -> str:
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

    index_link = (
        f'<a href="/search/label/{series_label}" '
        f'style="font-size:12px;color:#1a73e8;text-decoration:none;">📋 시리즈 전체 보기</a>'
        if series_label else ""
    )

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
