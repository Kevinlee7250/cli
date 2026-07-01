"""블로그 포스트 생성 — AdSense 최적화 + 이미지 자동 삽입 + 재시도 로직"""

import html as _html_esc
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


def _detect_article_type(keyword: str) -> str:
    """키워드 기반 아티클 유형 감지"""
    kw = keyword.lower()
    # 드라마 리뷰 — 가장 먼저 체크 (리뷰 타입과 겹치지 않게)
    if any(w in kw for w in ["드라마", "시즌", "넷플릭스", "티빙", "쿠팡플레이", "ott", "왓챠",
                              "결말 해석", "등장인물", "ost 추천", "명장면"]):
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
- 도입부: 나도 처음엔 이걸 몰라서 고생했다는 실제 경험 언급
- 본문: "직접 해보니 이랬어요" 식의 경험 기반 단계별 설명
- 섹션 제목: 실제로 하다 보면 마주치는 상황 중심 (예: "처음 시작할 때 가장 헷갈렸던 것")
- 중간에 "근데 사실 이게 제일 중요해요" 같은 사적인 코멘트 포함
- 마지막: 내가 해보고 느낀 솔직한 총평""",

    "review": """
- 도입부: 왜 직접 써봤는지 계기 설명 (광고 아님, 진짜 써본 것)
- 본문: 장점 → 단점 → 의외로 좋았던 점 → 이런 사람에게 맞다/안 맞다
- "기대했던 것 vs 실제로 써보니" 대비 구조 포함
- 솔직한 불만이나 아쉬운 점도 명확히 표현
- 마지막: 재구매/재사용 의향 + 어떤 독자에게 추천""",

    "comparison": """
- 도입부: 나도 어떤 걸 선택해야 할지 고민해봤던 상황 공유
- 본문: 직접 비교해본 기준 설명 → 항목별 비교 → 상황별 추천
- "처음엔 A가 나을 것 같았는데 실제론 B가 더 좋더라" 식의 반전 포함
- 표(table)나 항목 비교 위주의 구조 (독자가 빠르게 파악할 수 있게)
- 결론: "나라면 이런 상황엔 A, 저런 상황엔 B를 선택할 것" 같은 개인 의견""",

    "explainer": """
- 도입부: 이 개념을 처음 접했을 때 내가 어떻게 이해했는지
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
- 도입부: 이 드라마를 보게 된 계기와 첫 화 보고 나서의 솔직한 첫인상 (광고 아닌 진짜 시청자 감상)
- 본문 구성 (편의 focus에 따라 선택):
  • 소개 편: 줄거리 요약(스포 최소화) + 장르·분위기 소개 + 어떤 사람에게 맞는지
  • 인물 편: 주인공 감정선·성장 + 조연 캐릭터 분석 + 배우 연기력 솔직 평가 + 케미
  • 명장면 편: 인상 깊었던 장면·대사 + "이 장면에서 진짜 소름 돋았어요" 같은 구체적 감상
  • 결말 편: 결말 총평(스포 주의 경고 포함) + OST 추천 + 비슷한 드라마 추천 + 별점
- 감상 표현은 독자와 함께 이야기하는 구어체: "저는 이 부분에서 울었어요", "이건 좀 아쉬웠거든요"
- 과도한 칭찬이나 홍보성 표현 금지 — 아쉬운 점도 솔직하게
- 마지막: "이런 취향이면 강추 / 이런 취향이면 비추" 식의 명확한 추천 기준""",

    "travel_guide": """
- 도입부: 이 여행지를 선택하게 된 계기 + 출발 전 기대했던 것과 현실 비교 예고
- 본문 구성:
  • 실제 여행 경비 공개 (교통·숙소·식비·관광비 항목별 현실 숫자)
  • 현지에서 직접 해보고 "이건 몰랐던 것" 또는 "이건 생각보다 좋았던 것"
  • 숨은 명소·맛집 — 포털에 안 나오는 로컬 스팟 위주
  • 가면 안 되는 시간대·시즌 또는 주의사항 (경험 기반)
- "유명 블로그에서 추천한 곳인데 실제로 가보니..." 같은 반전 경험 포함
- 마지막: 이 여행지가 어떤 사람에게 맞는지 명확한 추천 기준""",

    "sports_review": """
- 도입부: 이 경기/선수/팀을 응원·관심 갖게 된 계기 (팬 시점 or 분석가 시점)
- 본문 구성:
  • 최근 성적·경기 결과 요약 (수치 기반 — 득점·순위·승률 등)
  • 핵심 포인트 분석: "이 부분이 승패를 갈랐다고 생각해요"
  • 선수·전술·팀 운영 관련 솔직한 평가 (과도한 찬양 금지)
  • 앞으로의 전망 — 명확한 개인 의견 포함 ("제 예상엔...")
- 직관 경험이 있으면 분위기·관람 팁 추가
- 마지막: 이 팀/선수/종목에 처음 관심 갖는 독자에게 입문 팁""",
}


def _build_prompt(keyword: str, traffic: str) -> str:
    from datetime import datetime
    now = datetime.now()
    y = now.year
    date_str = now.strftime("%Y년 %m월 %d일")
    article_type = _detect_article_type(keyword)
    structure_guide = _STRUCTURE_GUIDE.get(article_type, _STRUCTURE_GUIDE["analysis"])

    if BLOG_LANGUAGE == "ko":
        return f"""당신은 30대 직장인 블로거입니다.
재테크·건강·생활 정보를 직접 경험하고 공부한 후 솔직하게 정리해서 쓰는 스타일입니다.
검색으로 찾은 정보를 나열하는 게 아니라, 직접 경험하고 생각한 것을 자기 언어로 풀어씁니다.
구글 AdSense 정책을 완전히 준수하며 독자에게 진짜 도움이 되는 글을 씁니다.

【현재 날짜】 {date_str}
【키워드】 {keyword}
【아티클 유형】 {article_type}

━━━ 글쓰기 핵심 원칙 ━━━

1. 인간적인 목소리 (가장 중요)
• "저는", "제가", "제 경험상", "제 생각엔" 등 1인칭을 자연스럽게 사용
• 도입부에 반드시 이 주제와 관련된 개인적 경험·계기·고민을 1~2문단 포함
• 본문 중 최소 1곳에 "솔직히 말하면", "근데 이게 중요한 거예요", "의외로" 같은
  진심 어린 코멘트 삽입

2. 구조 탈피 — 주제에 맞는 자연스러운 흐름
• 모든 글에 "방법 TOP 5", "주의사항 3가지" 같은 공식 구조 금지
• H2 제목도 사람이 실제로 검색할 법한 자연스러운 질문/상황 중심으로
  예) ✗ "✅ ETF 핵심 방법 TOP 5" → ✓ "월 30만 원으로 ETF 시작하는 현실적인 방법"
• 아래 아티클 유형별 구조 가이드를 따르세요:
{structure_guide}

3. 자연스러운 한국어 블로그 문체
• 번역투/AI 투 문장 절대 금지:
  ✗ "~에 대해 알아보도록 하겠습니다"
  ✗ "~에 대한 것들을 살펴보면"
  ✗ "다양한 방법을 통해"
  ✗ "중요한 것은 바로"
  ✗ "이러한 점을 감안할 때"
  ✓ "오늘은 ~에 대해 얘기해볼게요"
  ✓ "~인데, 실제로 해보니까"
  ✓ "솔직히 저도 처음엔 몰랐어요"
• 문단은 3~4문장. 너무 긴 문단 금지.
• 가끔 짧은 한 문장 문단도 OK ("그게 핵심이에요.")

4. AI 상투어 패턴 완전 제거 (독자가 AI 티를 못 느끼게)
• 접속부사 남발 금지 — "또한", "더불어", "아울러"를 한 글에서 합산 3회 이하로 제한
  → 대신 문장을 자연스럽게 이어주는 구어체 연결 사용:
    ✗ "또한, 이 방법은 효과적입니다" → ✓ "이 방법도 생각보다 잘 돼요"
• 자동요약 문구 금지 — "이처럼", "정리하자면", "결론적으로", "이를 통해 알 수 있듯이"
  → AI가 단락을 마무리하는 패턴. 다음 문단으로 자연스럽게 이어가거나 결론을 섹션 안에 녹일 것
• 과도한 중립성·객관적 어투 탈피 — 모든 문장을 "~할 수 있습니다", "~로 볼 수 있습니다"로 끝내지 말 것
  ✗ "이 방법은 효과적일 수 있습니다" → ✓ "저는 이게 확실히 더 낫더라고요"
  → 개인 의견은 명확하게: "솔직히 A보다 B가 훨씬 낫다고 생각해요"
• 같은 길이 문장 반복 금지 — 짧은 문장(5~10자)·중간(15~25자)·긴 문장(30자+)을 섞어 리듬감 만들기
  → 문장 끝 처리도 "~요", "~다", "~네요", "~거든요" 다양하게
• 과도하게 매끄러운 구조 금지 — 모든 H2 섹션이 "정의 → 특징 → 장점 → 주의사항 → 요약" 패턴 반복 금지
  → 어떤 섹션은 경험담으로만, 어떤 섹션은 숫자 비교로만 써도 OK
• 목록화 남발 금지 — 모든 내용을 불릿/번호 리스트로 만들지 말 것
  ✗ "장점: ① ... ② ... ③ ..." → ✓ "이게 제일 좋았던 점인데, ... 그다음으로는 ..."
  → 서술로 충분히 표현 가능한 내용은 단락으로 쓰기. 리스트는 진짜 나열이 필요할 때만
• 딱딱한 격식체·보고서 문체 금지:
  ✗ "~에 대하여 살펴보겠습니다" ✗ "~임을 알 수 있다" ✗ "~에 기인한다"
  → 블로그 구어체: "~얘기해볼게요", "~그러더라고요", "~생각해봤어요"
• 클리셰 표현 반복 금지 — "중요합니다", "필수적입니다", "반드시 ~해야 합니다"를 2회 이상 쓰지 말 것
  → 구체적 이유나 경험으로 대체: "이걸 빠뜨리면 나중에 진짜 후회해요 — 저도 그랬거든요"

5. 특정 틈새(Niche) 공략
• "{keyword}"와 관련해서 인터넷에 이미 넘치는 포괄적 내용 금지
• 독자가 "이런 구체적인 얘기는 처음 봤다"고 느낄 각도로 접근
• 예: "직장인이 점심시간에 할 수 있는", "실패해본 사람 입장에서", "2025년 기준으로 달라진 점"

━━━ Google AdSense 2025 정책 준수 (자동 검증 대상) ━━━
글 완성 후 아래 8개 항목을 자동으로 검증합니다. 처음부터 충족되게 작성하세요:

① 원본성·품질 — 정보 나열 금지, 독창적 경험·인사이트 반드시 포함, 2500자 이상
② SEO 최적화 — 키워드 자연 분산 (20회 미만), 제목과 내용 일치, 낚시성 제목 금지
③ 구조·가독성 — H2 헤딩 4개 이상, 단락 지나치게 길지 않게, 목차 포함
④ 광고 배치 — 광고 4개 이하, 콘텐츠 충분히 있을 것, 광고가 내용 흐름 방해 금지
⑤ 유해·금지 콘텐츠 — 성인/폭력/혐오/불법/도박/약물/무기 절대 금지 (위반 시 즉시 거부)
   투자·의료 주장은 반드시 면책 표현 포함 ("~에 따르면", "전문가 상담 권장")
⑥ E-E-A-T — 1인칭 경험 서술 포함, 출처 최소 2개 인용, 균형 잡힌 시각 유지
⑦ 이미지 정책 — alt 텍스트 모든 이미지에 포함, 저작권 침해 이미지 금지
⑧ AI 의심도 최소화 — 위 4번(AI 상투어 패턴) 규칙 철저 준수

━━━ 제목 규칙 ━━━
• 자연스러운 블로그 제목 스타일 (포털 기사 제목 X)
• 숫자는 있으면 좋지만 강제 아님 | {y}년 포함 | 40자 이내
• 독자의 실제 궁금증을 건드리는 표현 ("저도 해봤는데", "직접 비교해봤어요", "솔직 후기")

━━━ 본문 구조 ━━━
분량: 2800~3500자 완전한 HTML
H2 섹션: 4~6개 (주제에 따라 자유롭게, 공식 개수 없음)
도입부·각 섹션·결론 모두 단락(p 태그) 기반으로 작성

핵심 요약 박스: 본문 첫 번째 <h2> 태그 바로 앞에 아래 HTML 그대로 1개 삽입:
<div style="background:#eff6ff;border-left:5px solid #2563eb;padding:16px 22px;margin:1.5em 0;border-radius:0 12px 12px 0;color:#1e3a8a;font-size:0.96em;line-height:1.8;">💡 <strong>핵심 포인트:</strong> [이 글의 가장 실용적인 핵심을 1~2문장으로]</div>

강조 & 가독성 규칙:
• 핵심 수치·팩트·행동 지침은 <strong>으로 강조 (문단당 1~2개, 남용 금지)
• 독자가 꼭 챙겨야 할 팁 단락: 문장 맨 앞에 💡 배치 (글 전체에서 1~3개)
• 중요 주의사항·실수 패턴 단락: 문장 맨 앞에 ⚠️ 배치 (글 전체에서 1~2개)
• 핵심 인사이트나 인상적인 문장은 <blockquote>로 감싸기 (1~2개)
• 과도한 강조는 오히려 효과 없음 — 진짜 중요한 것만 강조

━━━ FAQ ━━━
• h2 제목 "자주 묻는 질문" 아래 5개
• 실제로 사람들이 검색할 법한 구체적 질문 (너무 일반적인 질문 금지)
• 답변은 2~4문장, 단정적이고 실질적으로
• Schema.org 마크업(itemscope/itemtype/itemprop) 사용 금지 — 아래 형식으로만:
  <h2>자주 묻는 질문</h2>
  <h3>Q. 질문 텍스트</h3>
  <p>답변 텍스트</p>
  (5쌍 반복)

━━━ SEO ━━━
• 키워드 10~14회 자연스럽게 (강제 반복 느낌 금지)
• LSI 연관 키워드 각 섹션에 배치
• 라벨 10개 (실제 이 글과 관련된 것만)
• meta_description: 독자가 클릭하고 싶게 만드는 한 문장, 155자 이내

━━━ 출처 ━━━
• 실존하는 공신력 있는 URL만 (정부·공공기관·주요 언론)
• 확인 불가 수치는 "~로 알려져 있습니다" 등으로 표현하고 URL 생략
• 최소 2개, 최대 6개
• 본문 HTML에 <a href="URL" target="_blank" rel="nofollow noopener">출처명</a>

JSON 형식으로만 응답 (마크다운 없이):
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

    # English prompt (E-E-A-T focused)
    date_str_en = now.strftime("%B %d, %Y")
    article_type_en = article_type
    return f"""You are a personal blogger in your 30s who writes about finance, health, and everyday life.
You share what you've personally experienced, researched, and honestly thought about — not just information gathered from web searches.
You strictly follow Google AdSense content policies and prioritize genuine value to readers.

【Date】 {date_str_en}
【Keyword】 {keyword}
【Article Type】 {article_type_en}

━━━ CORE WRITING PRINCIPLES ━━━

1. Human Voice (most important)
• Use first person naturally: "I've tried", "In my experience", "Personally I think"
• Opening must include a personal anecdote or why you got interested in this topic
• At least 1 genuine aside in the body: "Honestly though", "Here's what surprised me", "I didn't expect this"

2. Break Template Structure
• NEVER use formulaic structures like "5 Methods", "3 Mistakes to Avoid" for every post
• H2 headings should reflect real questions or situations readers face
  ✗ "✅ TOP 5 Investment Methods" → ✓ "What I Actually Did With $300/Month in ETFs"
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
  ✗ "This approach can be effective." → ✓ "Honestly, I'd pick this over the alternatives."
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
  → Replace with specific experience: "Skip this and you'll regret it — learned that the hard way"

5. Niche Angle
• Find a specific angle other articles aren't covering well
• Example angles: "from a beginner's perspective after failing twice", "what changed in {y}", "the part no one talks about"

━━━ TITLE ━━━
Natural blog style | Include {y} | Under 65 chars
Trigger curiosity or recognition ("I tested this", "Honest review", "What I wish I knew")

━━━ CONTENT STRUCTURE ━━━
Length: 2800-3500 chars, complete HTML
H2 sections: 4-6 (based on topic, not a fixed count)
All sections paragraph-based (p tags)

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
}}"""


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

        query = f"{keyword} {heading_clean}".strip()
        if extra_terms:
            query = f"{query} {extra_terms}".strip()
        queries.append(query[:65])

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


def _build_series_prompt(keyword: str, traffic: str, series_context: dict) -> str:
    """시리즈 포스트용 프롬프트"""
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

    if BLOG_LANGUAGE == "ko":
        return f"""당신은 30대 직장인 블로거입니다.
"{series_title}" 시리즈를 직접 공부하고 경험하면서 편씩 정리해 올리는 중입니다.
구글 AdSense 정책을 완전히 준수하며, 독자에게 진짜 도움이 되는 글을 씁니다.

【현재 날짜】 {date_str}
【시리즈】 "{series_title}" — 총 {total}편 중 {episode}번째
【이 편 초점】 {focus}
【키워드】 {keyword}
【아티클 유형】 {article_type}

━━━ 시리즈 글쓰기 원칙 ━━━

다른 편 목록:
{other_list}

시리즈 연결 방식:
• 도입부에 이 시리즈를 쓰게 된 계기 또는 이전 편에서 이어지는 흐름 자연스럽게 언급
• 본문에서 다른 편을 1~2회 언급 (예: "1편에서도 얘기했지만", "다음 편에서 자세히 다룰 예정이에요")
• 이 편만 읽어도 완결되는 독립적 글
• 제목 힌트 "{title_hint}"를 더 구체적이고 검색하고 싶게 다듬어 사용

━━━ 글쓰기 핵심 원칙 ━━━

1. 인간적인 목소리
• 1인칭 자연스럽게 사용 ("저는", "제가", "제 경험상")
• 도입부: 이 편 주제와 관련된 개인적 경험·고민 1~2문단
• 본문 중 최소 1곳에 솔직한 개인 코멘트 삽입

2. 구조 탈피 — 주제에 맞는 흐름
• "방법 TOP 5", "주의사항 3가지" 같은 공식 구조 금지
• H2 제목은 실제 검색할 법한 상황·질문 중심으로
• 유형별 구조 가이드:
{structure_guide}

3. 자연스러운 블로그 문체
• 번역투/AI 투 표현 금지: "~살펴보도록 하겠습니다", "~에 대한 것들을", "다양한 방법을 통해"
• 블로그 구어체 사용: "오늘은 ~에 대해 얘기해볼게요", "솔직히 저도 처음엔 몰랐어요"
• 짧은 강조 문단 활용 ("그게 핵심이에요.")

4. AI 상투어 패턴 완전 제거 (독자가 AI 티를 못 느끼게)
• 접속부사 남발 금지 — "또한", "더불어", "아울러"를 한 글에서 합산 3회 이하로 제한
  ✗ "또한, 이 방법은 효과적입니다" → ✓ "이 방법도 생각보다 잘 돼요"
• 자동요약 문구 금지 — "이처럼", "정리하자면", "결론적으로", "이를 통해 알 수 있듯이"
  → AI 특유의 단락 마무리 패턴. 자연스럽게 다음 내용으로 이어가거나 결론을 섹션 안에 녹일 것
• 과도한 중립성 탈피 — "~할 수 있습니다", "~로 볼 수 있습니다"만 반복 금지
  ✗ "이 방법은 효과적일 수 있습니다" → ✓ "저는 이게 확실히 더 낫더라고요"
• 같은 길이 문장 반복 금지 — 짧은·중간·긴 문장 섞어 리듬감 만들기
  문장 끝 처리도 "~요", "~다", "~네요", "~거든요" 다양하게
• 과도하게 매끄러운 구조 금지 — 모든 섹션이 "정의→특징→주의→요약" 패턴 반복 금지
• 목록화 남발 금지 — 서술로 충분한 내용은 단락으로. 리스트는 진짜 나열이 필요할 때만
  ✗ "장점: ① ... ② ..." → ✓ "이게 제일 좋았는데, ... 그다음으로는 ..."
• 딱딱한 격식체 금지 — "~에 대하여", "~임을 알 수 있다", "~에 기인한다"
• 클리셰 반복 금지 — "중요합니다", "필수적입니다"를 2회 이상 쓰지 말 것
  → "이걸 빠뜨리면 진짜 후회해요 — 저도 그랬거든요" 같은 경험 기반 표현으로 대체

━━━ Google AdSense 2025 정책 준수 (자동 검증 대상) ━━━
① 원본성·품질 — 독창적 경험·인사이트 필수, 2500자 이상
② SEO 최적화 — 키워드 자연 분산, 제목·내용 일치
③ 구조·가독성 — H2 4개 이상, 단락 적절한 길이, 목차 포함
④ 광고 배치 — 광고 4개 이하, 콘텐츠 충분, 흐름 방해 금지
⑤ 유해·금지 — 성인/폭력/혐오/불법 절대 금지 (위반 시 즉시 거부)
   투자·의료 주장은 반드시 면책 표현 포함
⑥ E-E-A-T — 1인칭 경험 포함, 출처 최소 2개, 균형 잡힌 시각
⑦ 이미지 — alt 텍스트 모든 이미지에 포함
⑧ AI 의심도 — 위 4번 AI 상투어 규칙 철저 준수

━━━ 제목 규칙 ━━━
• "[{episode}편]"으로 시작
• 자연스러운 블로그 제목 | {y}년 포함 | 40자 이내

━━━ 본문 구조 ━━━
분량: 2800~3500자 완전한 HTML
H2 섹션: 4~6개 (주제에 따라 자유롭게)

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


def generate_series_post(keyword: str, traffic: str = "N/A", series_context: dict | None = None) -> dict | None:
    """시리즈 포스트를 생성합니다."""
    if not series_context:
        return generate_post(keyword, traffic)

    # episode 는 반드시 int — 기본값 "?" 는 build_series_nav에서 TypeError 유발
    _ep_raw = series_context.get("episode", 1)
    try:
        episode = int(_ep_raw)
    except (TypeError, ValueError):
        episode = 1
    total = series_context.get("total_episodes", "?")
    logger.info(f"시리즈 포스트 생성: '{keyword}' ({episode}/{total}편)")
    prompt = _build_series_prompt(keyword, traffic, series_context)

    for attempt in range(3):
        try:
            from datetime import datetime as _dt
            _now = _dt.now()
            _sys = (
                f"현재 날짜: {_now.strftime('%Y년 %m월 %d일')}. 이 날짜 기준 최신 정보를 사용하세요. JSON만 응답하세요."
                if BLOG_LANGUAGE == "ko" else
                f"Current date: {_now.strftime('%B %d, %Y')}. JSON only."
            )
            message = _get_client().messages.create(
                model=CLAUDE_MODEL,
                max_tokens=16000,
                system=_sys,
                messages=[{"role": "user", "content": prompt}],
            )
            if not message.content or not hasattr(message.content[0], "text"):
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
            post_data["series_id"] = series_context.get("series_id", "")
            post_data["episode"] = episode

            content_html = post_data.get("content", "")
            post_data["word_count"] = _word_count(content_html)
            post_data["content_preview"] = _content_preview(content_html)

            if not content_html.strip() or post_data["word_count"] < 100:
                if attempt < 2:
                    logger.warning(f"컨텐츠 너무 짧음({post_data['word_count']}자) — 재시도")
                    time.sleep(2)
                    continue
                return None

            if not isinstance(post_data.get("sources"), list):
                post_data["sources"] = []
            else:
                post_data["sources"] = _validate_sources(post_data["sources"])

            section_queries = _extract_section_queries(content_html, keyword)
            plain_text = _content_preview(post_data.get("content", ""), chars=600)
            images = fetch_images_for_queries(
                section_queries,
                naver_client_id=os.getenv("NAVER_CLIENT_ID", ""),
                naver_client_secret=os.getenv("NAVER_CLIENT_SECRET", ""),
                article_plain_text=plain_text,
                keyword=keyword,
            )
            if images:
                post_data["content"] = inject_images_into_content(post_data["content"], images, keyword)
                post_data["images_inserted"] = len(images)
            else:
                post_data["images_inserted"] = 0

            # 인라인 스타일 비주얼 디자인 적용 (주제별 컬러 테마)
            post_data["content"] = _apply_design(
                post_data["content"], keyword, _detect_article_type(keyword)
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

            # sources 필드 유효성 검증 (hallucinated URL 필터링)
            if not isinstance(post_data.get("sources"), list):
                post_data["sources"] = []
                logger.warning("sources 필드 누락 또는 잘못된 형식 — 초기화")
            else:
                post_data["sources"] = _validate_sources(post_data["sources"])
                if not post_data["sources"]:
                    logger.warning("sources 필드: 유효한 출처 없음 — 전부 제거됨")

            # 섹션별 이미지 검색 & 삽입 (관련성 검증 포함)
            section_queries = _extract_section_queries(post_data.get("content", ""), keyword)
            logger.info(f"섹션별 이미지 검색: {section_queries}")
            plain_text = _content_preview(post_data.get("content", ""), chars=600)
            images = fetch_images_for_queries(
                section_queries,
                naver_client_id=os.getenv("NAVER_CLIENT_ID", ""),
                naver_client_secret=os.getenv("NAVER_CLIENT_SECRET", ""),
                article_plain_text=plain_text,
                keyword=keyword,
            )
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
