import anthropic
import logging
import re
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, BLOG_LANGUAGE

logger = logging.getLogger(__name__)
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _build_prompt(keyword: str, traffic: str) -> str:
    if BLOG_LANGUAGE == "ko":
        return f"""당신은 구글 애드센스 수익 극대화를 위한 SEO 전문 블로거입니다.
다음 트렌드 키워드로 수익형 블로그 포스트를 작성하세요.

키워드: {keyword}
예상 트래픽: {traffic}

요구사항:
1. 제목: 클릭률 높은 제목 (키워드 포함, 30자 이내)
2. 본문: 1500~2000자, HTML 형식
3. 구조: 도입부 → H2 소제목 3~4개 → 결론
4. SEO: 키워드를 자연스럽게 5~8회 포함
5. 광고 친화적: 독자의 구매/검색 의도 충족
6. 라벨(태그): 관련 키워드 5개

다음 JSON 형식으로만 응답하세요:
{{
  "title": "...",
  "content": "<html 본문>",
  "labels": ["태그1", "태그2", "태그3", "태그4", "태그5"],
  "meta_description": "검색 결과에 표시될 설명 (160자 이내)"
}}"""
    else:
        return f"""You are an SEO expert blogger focused on maximizing Google AdSense revenue.
Write a monetization-focused blog post for the following trending keyword.

Keyword: {keyword}
Estimated traffic: {traffic}

Requirements:
1. Title: High CTR title including keyword (under 70 chars)
2. Content: 1500-2000 words, HTML format
3. Structure: Intro → 3-4 H2 sections → Conclusion
4. SEO: Include keyword naturally 5-8 times
5. Ad-friendly: Address reader purchase/search intent
6. Labels: 5 related keywords

Respond ONLY in this JSON format:
{{
  "title": "...",
  "content": "<html body>",
  "labels": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "meta_description": "Search result description (under 160 chars)"
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
