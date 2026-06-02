import Anthropic from '@anthropic-ai/sdk'
import { config } from '../config.js'
import { logger } from '../utils/logger.js'

const client = new Anthropic({ apiKey: config.anthropic.apiKey })

/**
 * Claude AI로 SEO + AdSense 최적화 블로그 포스트 생성 (v2)
 * 업그레이드: FAQ 섹션(추천 스니펫), 구조화 데이터, 4-슬롯 광고 배치, 내부 링크
 */
export async function generateBlogPost(keywordData) {
  const { keyword, relatedQueries = [], newsContext = [], newsItems = [], adsenseCategory, estimatedCPC, trendDirection } = keywordData

  logger.info(`블로그 포스트 생성 중: "${keyword}" (카테고리: ${adsenseCategory || '일반'}, CPC: $${estimatedCPC || 0.5})`)

  const newsSnippet = [...newsContext, ...newsItems.map(t => ({ title: t }))]
    .slice(0, 5)
    .map(n => `- ${n.title}${n.description ? ': ' + n.description.slice(0, 100) : ''}`)
    .join('\n')

  const relatedStr = relatedQueries.slice(0, 8).join(', ')
  const trendBadge = trendDirection === 'rising' ? '🚀 급상승 중' : trendDirection === 'falling' ? '📉 하락 중' : '📊 안정적'

  const systemPrompt = `당신은 구글 애드센스 수익화에 최적화된 한국어 블로그 포스트를 작성하는 전문 SEO 콘텐츠 전략가입니다.
다음 원칙을 철저히 따릅니다:
- E-E-A-T (경험, 전문성, 권위, 신뢰성) 기준 충족
- FAQ 섹션으로 구글 추천 스니펫(Featured Snippet) 타겟팅
- 키워드 밀도 2-3% 유지, 자연스럽게 삽입
- H2/H3 계층 구조로 가독성과 크롤러 최적화
- 독자 체류 시간 최대화를 위한 정보 밀도 높은 서술
- 광고 클릭을 유도하는 콘텐츠 흐름 설계
- 최소 2000자 이상의 풍부한 본문`

  const userPrompt = `다음 키워드로 구글 애드센스 수익화에 최적화된 블로그 포스트를 작성해주세요.

**메인 키워드:** ${keyword}
**트렌드:** ${trendBadge}
**AdSense 카테고리:** ${adsenseCategory || '일반'} (예상 CPC: $${estimatedCPC || 0.5})
**연관 키워드:** ${relatedStr || '없음'}
**최신 뉴스 컨텍스트:**
${newsSnippet || '일반적인 최신 정보를 활용하여 작성'}

**반드시 포함할 구조:**
1. **후킹 제목** (숫자+감성어 포함, 예: "2026년 AI로 월 300만원? 현실적인 7가지 방법")
2. **메타 설명** (155자 내외, 클릭 유도 문구 포함)
3. **URL 슬러그** (영문 소문자, 하이픈 구분)
4. **서론** (문제 공감 → 해결 기대감 → 이 글의 가치, 200자+)
5. **본문 H2 섹션 최소 5개** (각 300자+):
   - 섹션마다 연관 키워드 자연 삽입
   - 리스트, 표, 강조 텍스트 활용
   - 실용적 데이터와 수치 포함
   - [광고슬롯1] 두 번째 H2 이후 삽입 위치 표시
   - [광고슬롯2] 본문 중간 삽입 위치 표시
6. **FAQ 섹션** (Q&A 형식 5개 — 구글 추천 스니펫 타겟):
   - 독자가 실제로 궁금해할 질문
   - 40-60자 이내 명확한 답변
7. **결론** (요약 + CTA: "지금 바로 시작하세요", 구독 유도)
8. **구조화 데이터** (JSON-LD Article 스키마)
9. **SEO 태그** 7-12개

**응답 형식 (JSON):**
\`\`\`json
{
  "title": "후킹 제목",
  "metaDescription": "메타 설명 (155자)",
  "slug": "url-slug",
  "tags": ["태그1", "태그2"],
  "category": "${adsenseCategory || '일반'}",
  "content": "완성된 HTML 본문 ([광고슬롯1], [광고슬롯2] 위치 마커 포함)",
  "faq": [
    { "question": "질문1?", "answer": "답변1" },
    { "question": "질문2?", "answer": "답변2" },
    { "question": "질문3?", "answer": "답변3" },
    { "question": "질문4?", "answer": "답변4" },
    { "question": "질문5?", "answer": "답변5" }
  ],
  "structuredData": { "@context": "...", 구조화데이터JSON },
  "excerpt": "포스트 요약 (300자)",
  "seoKeywords": ["키워드1", "키워드2"],
  "readingTime": "예상 읽기 시간 (분)",
  "wordCount": 예상글자수
}
\`\`\``

  try {
    const response = await client.messages.create({
      model: config.anthropic.model,
      max_tokens: 6000,
      system: systemPrompt,
      messages: [{ role: 'user', content: userPrompt }],
    })

    const text = response.content[0].text
    const jsonMatch = text.match(/```json\n([\s\S]*?)\n```/) || text.match(/(\{[\s\S]*\})/s)
    const jsonStr = jsonMatch ? (jsonMatch[1] || jsonMatch[0]) : text

    const post = JSON.parse(jsonStr)
    post.keyword = keyword
    post.date = new Date().toISOString().split('T')[0]
    post.generatedAt = new Date().toISOString()
    post.trendDirection = trendDirection
    post.adsenseCategory = adsenseCategory
    post.estimatedCPC = estimatedCPC

    logger.info(`블로그 포스트 생성 완료: "${post.title}" (${post.wordCount || '?'}자, FAQ ${post.faq?.length || 0}개)`)
    return post
  } catch (err) {
    logger.error(`블로그 포스트 생성 실패 (${keyword}): ${err.message}`)
    throw err
  }
}

/**
 * HTML 콘텐츠에 AdSense 광고 슬롯 4개 삽입 (상단/중간1/중간2/하단)
 * [광고슬롯1] [광고슬롯2] 마커를 실제 AdSense 코드로 교체
 */
export function injectAdSenseSlots(content, adClientId = 'ca-pub-XXXXXXXXXXXXXXXX') {
  const adTemplate = (slot) => `
<div class="ad-container" style="text-align:center;margin:2em 0;">
<!-- Google AdSense -->
<ins class="adsbygoogle"
     style="display:block"
     data-ad-client="${adClientId}"
     data-ad-slot="${slot}"
     data-ad-format="auto"
     data-full-width-responsive="true"></ins>
<script>(adsbygoogle = window.adsbygoogle || []).push({});</script>
</div>`

  // 상단 광고 (포스트 시작)
  let result = adTemplate('TOP_SLOT_ID') + content

  // 중간 광고 (마커 교체)
  result = result.replace('[광고슬롯1]', adTemplate('MID1_SLOT_ID'))
  result = result.replace('[광고슬롯2]', adTemplate('MID2_SLOT_ID'))

  // 하단 광고 (포스트 끝)
  result = result + adTemplate('BOTTOM_SLOT_ID')

  return result
}

/**
 * FAQ를 JSON-LD FAQPage 스키마로 변환 (구글 추천 스니펫 최적화)
 */
export function buildFAQStructuredData(faqList) {
  return {
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: faqList.map(item => ({
      '@type': 'Question',
      name: item.question,
      acceptedAnswer: {
        '@type': 'Answer',
        text: item.answer,
      },
    })),
  }
}

export async function generateMultiplePosts(keywordDataList) {
  const posts = []
  for (const keywordData of keywordDataList) {
    try {
      const post = await generateBlogPost(keywordData)
      posts.push(post)
      await delay(2000)
    } catch (err) {
      logger.error(`포스트 생성 건너뜀 (${keywordData.keyword}): ${err.message}`)
    }
  }
  return posts
}

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}
