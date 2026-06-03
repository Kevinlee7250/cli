"""블로그 포스트 생성 — AdSense 최적화 + 이미지 자동 삽입"""

import json
import logging
import os
import re

import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, BLOG_LANGUAGE
from image_fetcher import fetch_relevant_images, inject_images_into_content

logger = logging.getLogger(__name__)
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _build_prompt(keyword: str, traffic: str) -> str:
    from datetime import datetime
    y = datetime.now().year
    m = datetime.now().month

    if BLOG_LANGUAGE == "ko":
        return f"""당신은 AdSense 수익 극대화 전문 SEO 블로거입니다.
독자 체류 시간을 최대화하고 광고 클릭률(CTR)을 높이는 포스트를 작성하세요.

키워드: {keyword}
작성 기준: {y}년 {m}월 | 예상 트래픽: {traffic}

━━━ 제목 규칙 ━━━
• 숫자 필수 ("5가지", "87%", "TOP 7", "3배 효과")
• 감정/호기심 유발 단어 ("충격", "비밀", "완벽 정리", "몰랐던")
• {y}년 포함 | 35자 이내 | 구글 클릭률 최대화 형식

━━━ 본문 구조 (AdSense 광고 수익 극대화) ━━━
분량: 2800~3500자 완전한 HTML
도입부(300자): 충격적 첫 문장 + 독자 공감 + 글에서 얻을 것 예고

H2 섹션 6개 (각 400~450자):
1. "📊 {keyword} 현황 및 최신 통계 ({y}년)"
2. "✅ {keyword} 핵심 방법 TOP 5 (전문가 추천)"
3. "💡 실제 사례로 보는 {keyword} 성공 전략"
4. "⚠️ {keyword}할 때 절대 피해야 할 실수 3가지"
5. "🔥 {y}년 최신 트렌드 & 게임체인저 변화"
6. "💰 {keyword}로 수익·효과 극대화하는 법"

FAQ 섹션 (h2 "자주 묻는 질문"): 5개 질문/답변 → Google Featured Snippet 확보
결론(200자): 핵심 요약 + 강력한 CTA

━━━ AdSense CTR 극대화 필수 요소 ━━━
• 각 H2 섹션 첫 문장: 구체적 숫자/통계 포함 (체류 시간↑)
• <strong> 태그: 고CPC 키워드 강조 (광고 관련성↑)
• 섹션 끝마다 "다음 내용이 핵심입니다 👇" 식의 CTA
• 구매·클릭 의도 자극 문장 각 섹션 최소 1개
• 번호 리스트 / 불렛포인트 적극 활용 (스캔 가능 → 체류 시간↑)
• 관련 글 내부 링크 유도 문장 2개 이상

━━━ SEO 최적화 ━━━
• 키워드 10~14회 자연스럽게 (첫 문단·각 H2 제목·결론 필수)
• LSI 연관 키워드를 각 섹션에 자연 배치
• 라벨 10개 (고CPC 키워드 우선)
• meta_description: 클릭 유도 문구, 155자 이내

JSON 형식으로만 응답:
{{
  "title": "...",
  "content": "<완전한 HTML — H2 6개 + FAQ H2 포함>",
  "labels": ["태그1","태그2","태그3","태그4","태그5","태그6","태그7","태그8","태그9","태그10"],
  "meta_description": "...",
  "faq": [
    {{"q": "질문1", "a": "답변1 (두 문장 이상)"}},
    {{"q": "질문2", "a": "답변2"}},
    {{"q": "질문3", "a": "답변3"}},
    {{"q": "질문4", "a": "답변4"}},
    {{"q": "질문5", "a": "답변5"}}
  ]
}}"""

    # English
    return f"""You are an AdSense revenue maximization SEO expert.
Write posts that maximize reader dwell time and ad click-through rate.

Keyword: {keyword} | Reference: {m}/{y} | Traffic: {traffic}

━━━ TITLE ━━━
• Numbers required ("7 Ways", "93%", "TOP 5", "3x faster")
• Power words ("Shocking", "Secret", "Complete Guide", "Hidden")
• Year {y} | Under 65 chars | Maximize Google CTR

━━━ CONTENT STRUCTURE (AdSense Optimized) ━━━
Length: 2800-3500 words, complete HTML
Intro (300w): Shocking sentence + empathy + what reader gets

6 H2 sections (400-450w each):
1. "📊 {keyword} Statistics & Latest Data ({y})"
2. "✅ TOP 5 {keyword} Methods (Expert Picks)"
3. "💡 Real Case Studies: {keyword} Success Stories"
4. "⚠️ 3 Costly Mistakes to Avoid with {keyword}"
5. "🔥 {y} Trends & Game-Changing Updates"
6. "💰 How to Maximize Results with {keyword}"

FAQ section (h2 "Frequently Asked Questions"): 5 Q&As → Featured Snippet
Conclusion (200w): Summary + strong CTA

━━━ ADSENSE CTR MAXIMIZATION ━━━
• H2 opening sentence: specific stats/numbers (dwell time↑)
• <strong> on high-CPC keywords (ad relevance↑)
• End-of-section CTA: "This next part is crucial 👇"
• Purchase/search intent sentences: min 1 per section
• Heavy bullet/numbered lists (scannable → dwell time↑)

━━━ SEO ━━━
• Keyword 10-14 times naturally; LSI keywords throughout
• Labels: 10 high-CPC related keywords
• meta_description: click-bait, under 155 chars

Respond ONLY in this JSON format:
{{
  "title": "...",
  "content": "<complete HTML — 6 H2 + FAQ H2>",
  "labels": ["t1","t2","t3","t4","t5","t6","t7","t8","t9","t10"],
  "meta_description": "...",
  "faq": [
    {{"q": "Q1", "a": "A1 (2+ sentences)"}},
    {{"q": "Q2", "a": "A2"}},
    {{"q": "Q3", "a": "A3"}},
    {{"q": "Q4", "a": "A4"}},
    {{"q": "Q5", "a": "A5"}}
  ]
}}"""


def generate_post(keyword: str, traffic: str = "N/A") -> dict | None:
    """Claude API로 포스트 생성 후 이미지를 자동 삽입합니다."""
    logger.info(f"포스트 생성 중: '{keyword}'")

    try:
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=8192,
            messages=[{"role": "user", "content": _build_prompt(keyword, traffic)}],
        )
        raw = message.content[0].text.strip()

        # 코드블록 마커(```json / ```) 제거 후 첫 { ~ 마지막 } 추출
        text = raw
        if text.startswith("```"):
            text = text[text.find("\n") + 1:] if "\n" in text else text[3:]
            if text.rstrip().endswith("```"):
                text = text.rstrip()[:-3].rstrip()

        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            logger.error(f"JSON 추출 실패 — 응답 앞 200자: {raw[:200]}")
            return None
        json_str = text[start: end + 1]

        try:
            post_data = json.loads(json_str)
        except json.JSONDecodeError:
            # Claude 응답의 이스케이프 누락 등 경미한 JSON 오류 자동 복구
            try:
                from json_repair import repair_json
                post_data = json.loads(repair_json(json_str))
                logger.warning("JSON 자동 복구 후 파싱 성공")
            except Exception as e2:
                logger.error(f"JSON 복구 실패: {e2}")
                return None
        post_data["keyword"] = keyword

        # ── 이미지 검색 & 삽입 ────────────────────────────────────────
        logger.info(f"관련 이미지 검색 중: '{keyword}'")
        images = fetch_relevant_images(
            keyword,
            count=4,
            naver_client_id=os.getenv("NAVER_CLIENT_ID", ""),
            naver_client_secret=os.getenv("NAVER_CLIENT_SECRET", ""),
        )
        if images:
            post_data["content"] = inject_images_into_content(
                post_data["content"], images, keyword
            )
            post_data["images_inserted"] = len(images)
            logger.info(f"이미지 {len(images)}개 본문 삽입 완료")
        else:
            logger.warning("이미지 없음 — 텍스트만으로 업로드 진행")

        logger.info(f"포스트 생성 완료: '{post_data.get('title', '?')}'")
        return post_data

    except anthropic.APIError as e:
        logger.error(f"Claude API 오류: {e}")
        return None
    except Exception as e:
        logger.error(f"포스트 생성 오류: {e}")
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = generate_post("재테크 방법", "100K+")
    if result:
        print(f"제목: {result['title']}")
        print(f"라벨: {result['labels']}")
        print(f"이미지 삽입: {result.get('images_inserted', 0)}개")
        print(f"FAQ: {len(result.get('faq', []))}개")
