import Anthropic from '@anthropic-ai/sdk'
import { config } from '../config.js'
import { logger } from '../utils/logger.js'

const client = new Anthropic({ apiKey: config.anthropic.apiKey })

/**
 * Claude API를 사용하여 SEO + AdSense 최적화 블로그 포스트 생성
 * @param {Object} keywordData - 키워드 분석 데이터
 * @returns {Promise<Object>} 완성된 블로그 포스트
 */
export async function generateBlogPost(keywordData) {
  const { keyword, relatedQueries = [], newsContext = [], newsItems = [] } = keywordData

  logger.info(`블로그 포스트 생성 중: "${keyword}"`)

  const newsSnippet = [...newsContext, ...newsItems.map(t => ({ title: t }))]
    .slice(0, 5)
    .map(n => `- ${n.title}${n.description ? ': ' + n.description.slice(0, 100) : ''}`)
    .join('\n')

  const relatedStr = relatedQueries.slice(0, 8).join(', ')

  const systemPrompt = `당신은 구글 애드센스 수익화에 최적화된 한국어 블로그 포스트를 작성하는 전문 콘텐츠 크리에이터입니다.
SEO 최적화, 독자 참여, 광고 수익 극대화를 위한 글쓰기 전문가로서:
- 키워드 밀도를 자연스럽게 유지 (2-3%)
- 풍부한 정보와 실용적인 내용으로 체류 시간 증가
- 명확한 구조로 가독성 극대화
- 독자의 궁금증을 유발하는 흥미로운 서술
- 최소 1500자 이상의 충실한 내용`

  const userPrompt = `다음 키워드로 구글 애드센스 수익화에 최적화된 블로그 포스트를 작성해주세요.

**메인 키워드:** ${keyword}
**연관 키워드:** ${relatedStr || '없음'}
**최신 뉴스 컨텍스트:**
${newsSnippet || '일반 최신 정보를 바탕으로 작성'}

**작성 요구사항:**
1. 제목: 클릭을 유도하는 후킹 제목 (숫자, 감성어 포함)
2. 메타 설명: 150자 내외의 SEO 메타 설명
3. 서론: 독자의 공감을 이끄는 도입부 (200자 이상)
4. 본문: 최소 4개의 H2 섹션, 각 섹션 300자 이상
   - 실용적인 정보, 팁, 데이터 포함
   - 연관 키워드 자연스럽게 삽입
   - 리스트, 표 등 다양한 포맷 활용
5. 결론: 행동 유도 문구(CTA) 포함
6. SEO 태그: 5-10개의 관련 태그

**응답 형식 (JSON):**
\`\`\`json
{
  "title": "SEO 최적화 제목",
  "metaDescription": "메타 설명",
  "slug": "url-friendly-slug",
  "tags": ["태그1", "태그2"],
  "content": "HTML 형식의 완성된 블로그 본문",
  "excerpt": "포스트 요약 (300자)",
  "seoKeywords": ["키워드1", "키워드2"],
  "readingTime": "예상 읽기 시간 (분)"
}
\`\`\``

  try {
    const response = await client.messages.create({
      model: config.anthropic.model,
      max_tokens: 4096,
      system: systemPrompt,
      messages: [{ role: 'user', content: userPrompt }],
    })

    const text = response.content[0].text
    const jsonMatch = text.match(/```json\n([\s\S]*?)\n```/) || text.match(/\{[\s\S]*\}/)
    const jsonStr = jsonMatch ? (jsonMatch[1] || jsonMatch[0]) : text

    const post = JSON.parse(jsonStr)
    post.keyword = keyword
    post.date = new Date().toISOString().split('T')[0]
    post.generatedAt = new Date().toISOString()

    logger.info(`블로그 포스트 생성 완료: "${post.title}"`)
    return post
  } catch (err) {
    logger.error(`블로그 포스트 생성 실패 (${keyword}): ${err.message}`)
    throw err
  }
}

/**
 * 여러 키워드에 대한 블로그 포스트를 순차 생성 (API 레이트 리밋 대응)
 */
export async function generateMultiplePosts(keywordDataList) {
  const posts = []
  for (const keywordData of keywordDataList) {
    try {
      const post = await generateBlogPost(keywordData)
      posts.push(post)
      // API 부하 방지를 위한 딜레이
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
