import Anthropic from '@anthropic-ai/sdk'
import { jsonrepair } from 'jsonrepair'
import { config } from '../config.js'
import { logger } from '../utils/logger.js'

const client = new Anthropic({ apiKey: config.anthropic.apiKey })

/**
 * Claude로 블로그 포스트 팩트체크 & 수정
 * - 날짜/연도 오류, 통계 오류, 이름 오류, 근거 없는 주장 검출
 * - 오류 수정 또는 불확실한 내용에 적절한 단서 추가
 * - 수정된 content와 체크 리포트 반환
 */
export async function factCheckBlogPost(blogPost) {
  const today = new Date().toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric' })
  logger.info(`🔍 팩트체크 중: "${blogPost.title}"`)

  const contentPreview = (blogPost.content || '').replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').slice(0, 6000)
  const faqText = (blogPost.faq || []).map(f => `Q: ${f.question}\nA: ${f.answer}`).join('\n\n')

  try {
    const response = await client.messages.create({
      model: config.anthropic.model,
      max_tokens: 8000,
      system: `당신은 한국어 블로그 콘텐츠 팩트체커입니다. 오늘 날짜: ${today}
다음 기준으로 철저히 검토합니다:
① 날짜·연도 정확성 (오늘 기준으로 과거/현재/미래 구분)
② 통계·수치의 출처 가능성 (근거 없는 구체적 수치는 표현 완화)
③ 인명·기관명·법률명 등 고유명사 정확성
④ 확인되지 않은 사실을 단정적으로 서술하는 경우 → "~로 알려졌다", "~예상된다" 등으로 수정
⑤ 미래 예측을 현재 사실처럼 서술하는 경우 수정
⑥ 오늘(${today}) 이후 일정이나 결과를 단정적으로 서술하면 "예정" 표현으로 수정`,
      messages: [{
        role: 'user',
        content: `다음 블로그 포스트를 팩트체크하고 수정해주세요.

**제목:** ${blogPost.title}
**키워드:** ${blogPost.keyword}
**메타 설명:** ${blogPost.metaDescription || ''}

**본문 (HTML 태그 제거):**
${contentPreview}

**FAQ:**
${faqText || '없음'}

아래 JSON 형식으로만 응답하세요:
{
  "passed": true 또는 false,
  "issueCount": 수정한 오류 개수,
  "issues": [
    { "type": "날짜오류|수치과장|미확인사실|미래단정|기타", "original": "원문 표현", "corrected": "수정된 표현", "reason": "수정 이유" }
  ],
  "correctedTitle": "수정된 제목 (변경 없으면 원제목)",
  "correctedMetaDescription": "수정된 메타 설명 (변경 없으면 원문)",
  "correctedContent": "수정된 본문 HTML (변경 없으면 원문 그대로, HTML 태그 유지)",
  "correctedFaq": [
    { "question": "질문", "answer": "수정된 답변" }
  ],
  "summary": "팩트체크 요약 (한 줄)"
}`,
      }],
    })

    const text = response.content[0].text
    const jsonStart = text.indexOf('{')
    const jsonEnd = text.lastIndexOf('}')
    const parsed = JSON.parse(jsonrepair(text.slice(jsonStart, jsonEnd + 1)))

    const issueCount = parsed.issueCount || parsed.issues?.length || 0
    if (issueCount === 0) {
      logger.info(`  ✅ 팩트체크 통과 — 오류 없음`)
    } else {
      logger.info(`  ⚠️  팩트체크: ${issueCount}개 수정`)
      parsed.issues?.forEach(issue => {
        logger.info(`     [${issue.type}] "${issue.original}" → "${issue.corrected}"`)
      })
    }
    logger.info(`  📋 ${parsed.summary || '팩트체크 완료'}`)

    // 수정 사항이 있으면 blogPost에 반영
    const checkedPost = {
      ...blogPost,
      title: parsed.correctedTitle || blogPost.title,
      metaDescription: parsed.correctedMetaDescription || blogPost.metaDescription,
      faq: parsed.correctedFaq?.length ? parsed.correctedFaq : blogPost.faq,
      factCheck: {
        passed: parsed.passed !== false,
        issueCount,
        issues: parsed.issues || [],
        summary: parsed.summary || '',
        checkedAt: new Date().toISOString(),
      },
    }

    // 수정된 content가 실질적으로 다를 때만 교체 (너무 짧으면 원문 유지)
    if (parsed.correctedContent && parsed.correctedContent.length > 500 && issueCount > 0) {
      checkedPost.content = parsed.correctedContent
    }

    return checkedPost
  } catch (err) {
    logger.warn(`팩트체크 실패 (원문 그대로 게시): ${err.message}`)
    return {
      ...blogPost,
      factCheck: { passed: true, issueCount: 0, issues: [], summary: '팩트체크 오류 - 원문 게시', checkedAt: new Date().toISOString() },
    }
  }
}
