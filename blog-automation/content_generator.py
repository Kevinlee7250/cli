import anthropic
import logging
import re
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, BLOG_LANGUAGE

logger = logging.getLogger(__name__)
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _build_prompt(keyword: str, traffic: str) -> str:
    from datetime import datetime
    current_year = datetime.now().year
    current_month = datetime.now().month

    if BLOG_LANGUAGE == "ko":
        return f"""당신은 바이럴 콘텐츠 전문가이자 SEO 수익형 블로거입니다.
최신 데이터와 강력한 후킹 요소로 독자를 사로잡는 포스트를 작성하세요.

키워드: {keyword}
작성 기준 시점: {current_year}년 {current_month}월
예상 트래픽: {traffic}

━━━ 제목 규칙 (반드시 준수) ━━━
- 숫자 포함 필수 (예: "5가지", "87%", "3배")
- 충격/호기심 유발 단어 사용 (예: "충격", "비밀", "몰랐던", "드디어", "이유")
- 연도 포함 ({current_year}년)
- 30자 이내

━━━ 후킹 요소 (반드시 포함) ━━━
1. 오프닝 훅: 첫 문장에 충격적인 통계나 반전 질문 (예: "10명 중 9명이 모르는 사실...")
2. 최신 데이터: {current_year}년 기준 구체적 수치/통계/연구결과 인용
3. FOMO 자극: "지금 당장 하지 않으면 손해", "이미 XX만 명이 시작"
4. 공감 유발: 독자의 고민/문제를 정확히 짚는 문장
5. 반전 포인트: 상식과 다른 의외의 정보 1개 이상
6. 리스트 활용: 번호 목록으로 핵심 정보 정리 (스캔 가능하게)
7. 긴급성 강조: "2025년 바뀐 내용", "올해만 적용되는"
8. CTA: 각 섹션 끝에 다음 섹션 읽게 만드는 한 줄

━━━ 본문 구조 ━━━
- 분량: 1800~2500자, HTML 형식
- 도입부(200자): 훅 + 공감 + 이 글에서 얻을 것 예고
- H2 섹션 4개:
  • 섹션1: 최신 현황/통계 (숫자 강조)
  • 섹션2: 핵심 방법/비법 (번호 리스트)
  • 섹션3: 실제 사례/후기 (구체적)
  • 섹션4: 주의사항/실수 (역발상)
- 결론(150자): 요약 + 행동 촉구

━━━ SEO & 수익화 ━━━
- 키워드 자연스럽게 6~10회 포함
- <strong> 태그로 핵심 문구 강조
- 독자의 구매/검색/클릭 의도 자극하는 문장 포함
- 라벨: 연관 키워드 + 트렌드 태그 7개

다음 JSON 형식으로만 응답하세요:
{{
  "title": "...",
  "content": "<html 본문>",
  "labels": ["태그1", "태그2", "태그3", "태그4", "태그5", "태그6", "태그7"],
  "meta_description": "검색 결과 설명 (160자 이내, 키워드+숫자+혜택 포함)"
}}"""
    else:
        return f"""You are a viral content expert and SEO monetization blogger.
Write a post with latest data and powerful hooks that captivates readers instantly.

Keyword: {keyword}
Reference date: {current_month}/{current_year}
Estimated traffic: {traffic}

━━━ TITLE RULES (mandatory) ━━━
- Must include numbers ("7 Ways", "93% of people", "3x faster")
- Use power words ("Shocking", "Secret", "Finally", "Hidden")
- Include year ({current_year})
- Under 70 characters

━━━ HOOK ELEMENTS (all required) ━━━
1. Opening hook: Shocking stat or counter-intuitive question in first sentence
2. Latest data: Cite specific {current_year} statistics/research
3. FOMO trigger: "Already X million people are doing this"
4. Empathy: Pinpoint reader's exact pain point
5. Surprise twist: At least one counter-intuitive insight
6. Scannable lists: Numbered/bulleted key info
7. Urgency: "{current_year} updated", "New this year"
8. CTA: End each section pulling reader to next

━━━ CONTENT STRUCTURE ━━━
- Length: 1800-2500 words, HTML format
- Intro (200w): Hook + empathy + promise
- 4 H2 sections:
  • Section 1: Latest stats/trends (emphasize numbers)
  • Section 2: Core methods (numbered list)
  • Section 3: Real examples/case studies
  • Section 4: Mistakes/warnings (reverse angle)
- Conclusion (150w): Summary + call to action

━━━ SEO & MONETIZATION ━━━
- Keyword 6-10 times naturally
- <strong> tags on key phrases
- Trigger purchase/search/click intent
- Labels: related keywords + trending tags, 7 total

Respond ONLY in this JSON format:
{{
  "title": "...",
  "content": "<html body>",
  "labels": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6", "tag7"],
  "meta_description": "160 chars max, include keyword+number+benefit"
}}"""


def generate_post(keyword: str, traffic: str = "N/A") -> dict | None:
    """Claude API를 사용해 블로그 포스트를 생성합니다."""
    logger.info(f"포스트 생성 중: '{keyword}'")
    prompt = _build_prompt(keyword, traffic)

    try:
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()

        # JSON 블록 추출 (```json ... ``` 래핑 대응)
        json_match = re.search(r"\{[\s\S]*\}", raw)
        if not json_match:
            logger.error("JSON 파싱 실패: 응답에서 JSON을 찾을 수 없음")
            return None

        import json
        post_data = json.loads(json_match.group())
        post_data["keyword"] = keyword
        logger.info(f"포스트 생성 완료: '{post_data.get('title', '제목 없음')}'")
        return post_data

    except anthropic.APIError as e:
        logger.error(f"Claude API 오류: {e}")
        return None
    except Exception as e:
        logger.error(f"포스트 생성 중 오류: {e}")
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = generate_post("재테크 방법", "100K+")
    if result:
        print(f"제목: {result['title']}")
        print(f"라벨: {result['labels']}")
        print(f"설명: {result['meta_description']}")
