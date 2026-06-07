"""블로그 포스트 생성 — AdSense 최적화 + 이미지 자동 삽입 + 재시도 로직"""

import json
import logging
import os
import re
import time

import anthropic

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, BLOG_LANGUAGE
from image_fetcher import fetch_images_for_queries, inject_images_into_content

logger = logging.getLogger(__name__)
_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def _build_prompt(keyword: str, traffic: str) -> str:
    from datetime import datetime
    now = datetime.now()
    y = now.year
    m = now.month
    date_str = now.strftime("%Y년 %m월 %d일")

    if BLOG_LANGUAGE == "ko":
        return f"""당신은 AdSense 수익 극대화 전문 SEO 블로거입니다.
독자 체류 시간을 최대화하고 광고 클릭률(CTR)을 높이는 포스트를 작성하세요.

【현재 시점】 {date_str} — 이 날짜 기준의 최신 정보·트렌드·통계를 반영하여 작성하세요.
키워드: {keyword}
예상 트래픽: {traffic}

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

━━━ 출처 링크 (신뢰도·SEO 강화) ━━━
• 통계·수치를 인용할 때 실제 출처 URL을 sources 배열에 포함
• 공신력 있는 사이트 우선 (정부기관, 학술지, 주요 언론, 공식 기관)
• 최소 3개 이상, 최대 8개
• 본문 HTML에 <a href="URL" target="_blank" rel="nofollow noopener">출처명</a> 형태로 인용 표시

JSON 형식으로만 응답하세요. 마크다운 코드블록(```) 없이 순수 JSON만:
{{
  "title": "...",
  "content": "<완전한 HTML — H2 6개 + FAQ H2 포함, 인용 링크 포함>",
  "labels": ["태그1","태그2","태그3","태그4","태그5","태그6","태그7","태그8","태그9","태그10"],
  "meta_description": "...",
  "faq": [
    {{"q": "질문1", "a": "답변1 (두 문장 이상)"}},
    {{"q": "질문2", "a": "답변2"}},
    {{"q": "질문3", "a": "답변3"}},
    {{"q": "질문4", "a": "답변4"}},
    {{"q": "질문5", "a": "답변5"}}
  ],
  "sources": [
    {{"title": "출처명1", "url": "https://..."}},
    {{"title": "출처명2", "url": "https://..."}}
  ]
}}"""

    date_str_en = now.strftime("%B %d, %Y")
    return f"""You are an AdSense revenue maximization SEO expert.
Write posts that maximize reader dwell time and ad click-through rate.

【Current Date】 {date_str_en} — use this date as reference for all current trends, stats, and information.
Keyword: {keyword} | Traffic: {traffic}

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

━━━ SOURCE LINKS (trust & SEO boost) ━━━
• Include real source URLs in sources array when citing stats/facts
• Prefer authoritative sites (gov, academic, major media, official orgs)
• Min 3, max 8 sources
• In HTML body, mark citations as <a href="URL" target="_blank" rel="nofollow noopener">Source Name</a>

Respond with ONLY raw JSON (no markdown code blocks):
{{
  "title": "...",
  "content": "<complete HTML — 6 H2 + FAQ H2, with citation links>",
  "labels": ["t1","t2","t3","t4","t5","t6","t7","t8","t9","t10"],
  "meta_description": "...",
  "faq": [
    {{"q": "Q1", "a": "A1 (2+ sentences)"}},
    {{"q": "Q2", "a": "A2"}},
    {{"q": "Q3", "a": "A3"}},
    {{"q": "Q4", "a": "A4"}},
    {{"q": "Q5", "a": "A5"}}
  ],
  "sources": [
    {{"title": "Source Name 1", "url": "https://..."}},
    {{"title": "Source Name 2", "url": "https://..."}}
  ]
}}"""


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
            logger.warning("JSON 자동 복구 후 파싱 성공")
            return result
        except Exception as e:
            logger.error(f"JSON 복구 실패: {e} — 앞 300자: {json_str[:300]}")
            return None


_KO_STOPWORDS = {
    # 조사/어미/의존명사/지시어
    "이것", "그것", "저것", "이런", "그런", "저런", "이때", "그때", "모든", "여러",
    "어떤", "이런", "많은", "위한", "통한", "대한", "있는", "없는", "하는", "되는",
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
        heading_clean = " ".join(deduped).strip()[:25]
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

        query = f"{keyword} {heading_clean}".strip()
        if extra_terms:
            query = f"{query} {extra_terms}".strip()
        queries.append(query[:55])

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


def generate_post(keyword: str, traffic: str = "N/A") -> dict | None:
    """Claude API로 포스트 생성 후 이미지를 자동 삽입합니다. 실패 시 최대 2회 재시도."""
    logger.info(f"포스트 생성 중: '{keyword}'")
    prompt = _build_prompt(keyword, traffic)

    for attempt in range(3):
        try:
            from datetime import datetime as _dt
            _now = _dt.now()
            _sys = (
                f"현재 날짜: {_now.strftime('%Y년 %m월 %d일')}. "
                "이 날짜를 기준으로 최신 정보를 사용하세요. "
                "지식 학습 시점 이후의 사건은 '최신 동향에 따르면' 등의 표현으로 처리하세요."
                if BLOG_LANGUAGE == "ko" else
                f"Current date: {_now.strftime('%B %d, %Y')}. "
                "Use this date as your reference. "
                "For events after your knowledge cutoff, use phrasing like 'according to recent trends'."
            )
            message = _get_client().messages.create(
                model=CLAUDE_MODEL,
                max_tokens=16000,
                system=_sys,
                messages=[{"role": "user", "content": prompt}],
            )
            if not message.content or not hasattr(message.content[0], "text"):
                logger.error("Claude 응답 형식 오류: text 콘텐츠 없음")
                if attempt < 2:
                    time.sleep(2)
                    continue
                return None
            raw = message.content[0].text.strip()
            post_data = _parse_response(raw)

            if post_data is None:
                if attempt < 2:
                    logger.warning(f"JSON 파싱 실패 — 재시도 {attempt + 1}/3")
                    time.sleep(2)
                    continue
                return None

            post_data["keyword"] = keyword

            # 글자 수 및 미리보기 추가
            content_html = post_data.get("content", "")
            post_data["word_count"] = _word_count(content_html)
            post_data["content_preview"] = _content_preview(content_html)

            # 컨텐츠 유효성 검사 (json_repair로 복구됐지만 내용이 비어있는 경우 방지)
            if not content_html.strip() or post_data["word_count"] < 100:
                if attempt < 2:
                    logger.warning(f"컨텐츠 비어있음 또는 너무 짧음({post_data['word_count']}자) — 재시도 {attempt + 1}/3")
                    time.sleep(2)
                    continue
                logger.error("컨텐츠 생성 실패: 유효한 내용 없음")
                return None

            # sources 필드 유효성 검증
            if not isinstance(post_data.get("sources"), list):
                post_data["sources"] = []
                logger.warning("sources 필드 누락 또는 잘못된 형식 — 초기화")
            elif not post_data["sources"]:
                logger.warning("sources 필드 비어있음 — 출처 링크 미포함")

            # 섹션별 이미지 검색 & 삽입
            section_queries = _extract_section_queries(post_data.get("content", ""), keyword)
            logger.info(f"섹션별 이미지 검색: {section_queries}")
            images = fetch_images_for_queries(
                section_queries,
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
                post_data["images_inserted"] = 0
                logger.warning("이미지 없음 — 텍스트만으로 업로드 진행")

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
