import Anthropic from '@anthropic-ai/sdk'
import { config } from '../config.js'
import { logger } from '../utils/logger.js'

const client = new Anthropic({ apiKey: config.anthropic.apiKey })

/**
 * 블로그 포스트로부터 각 SNS 플랫폼별 최적화 콘텐츠 생성
 * Instagram, Threads, TikTok 스크립트를 한 번에 생성
 */
export async function generateSocialContent(blogPost, blogUrl = '') {
  logger.info(`SNS 콘텐츠 생성 중: "${blogPost.title}"`)

  const systemPrompt = `당신은 인스타그램, 쓰레드, 틱톡 플랫폼별 바이럴 SNS 콘텐츠 전문가입니다.
각 플랫폼의 알고리즘과 사용자 행동을 깊이 이해하여 최대 도달률과 블로그 유입을 목표로 합니다.`

  const userPrompt = `다음 블로그 포스트를 기반으로 각 SNS 플랫폼별 최적화 콘텐츠를 생성해주세요.

**블로그 제목:** ${blogPost.title}
**키워드:** ${blogPost.keyword}
**본문 요약:** ${blogPost.excerpt || blogPost.metaDescription}
**블로그 URL:** ${blogUrl || '[블로그 URL]'}
**태그:** ${(blogPost.tags || []).join(', ')}

**플랫폼별 요구사항:**

### 인스타그램
- 첫 2줄이 후킹 포인트 (더 보기 전에 클릭 유도)
- 이모지 적극 활용
- 줄바꿈으로 가독성 향상
- 해시태그 20-30개 (관련 + 인기 태그 혼합)
- 프로필 링크 클릭 유도

### 쓰레드(Threads)
- 짧고 임팩트 있는 문장
- 연속 스레드 형식 (1/5, 2/5...)으로 5개 작성
- 토론을 유발하는 질문으로 마무리
- 해시태그 3-5개만
- 자연스러운 대화체

### 틱톡 스크립트
- 영상 길이: 30-60초 기준
- 후킹 오프닝: "이거 알면 인생 바뀜" 스타일
- 3초 안에 주목을 끄는 시작
- 자막 형식으로 작성 (짧은 문장)
- 영상 구성: 오프닝 → 문제제기 → 해결책 → CTA
- 해시태그 5-10개

**응답 형식 (JSON):**
\`\`\`json
{
  "instagram": {
    "caption": "인스타그램 캡션 전체",
    "hashtags": ["해시태그1", "해시태그2"],
    "hookLine": "첫 후킹 문장",
    "ctaText": "행동 유도 문구"
  },
  "threads": {
    "posts": [
      { "order": 1, "content": "첫 번째 스레드 내용" },
      { "order": 2, "content": "두 번째 스레드 내용" },
      { "order": 3, "content": "세 번째 스레드 내용" },
      { "order": 4, "content": "네 번째 스레드 내용" },
      { "order": 5, "content": "마무리 + CTA" }
    ],
    "hashtags": ["해시태그1", "해시태그2", "해시태그3"]
  },
  "tiktok": {
    "script": "틱톡 영상 전체 스크립트",
    "scenes": [
      { "time": "0-3초", "text": "오프닝", "direction": "카메라 연출 지시" },
      { "time": "3-15초", "text": "본론 1", "direction": "연출 지시" },
      { "time": "15-30초", "text": "핵심 내용", "direction": "연출 지시" },
      { "time": "30-50초", "text": "결론", "direction": "연출 지시" },
      { "time": "50-60초", "text": "CTA", "direction": "연출 지시" }
    ],
    "hashtags": ["해시태그1", "해시태그2"],
    "soundSuggestion": "배경음악 추천",
    "thumbnailText": "틱톡 썸네일 텍스트"
  },
  "keyword": "${blogPost.keyword}",
  "blogTitle": "${blogPost.title}",
  "date": "${new Date().toISOString().split('T')[0]}"
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
    const jsonMatch = text.match(/```json\n([\s\S]*?)\n```/) || text.match(/\{[\s\S]*\}/s)
    const jsonStr = jsonMatch ? (jsonMatch[1] || jsonMatch[0]) : text

    const socialContent = JSON.parse(jsonStr)
    logger.info(`SNS 콘텐츠 생성 완료: Instagram, Threads, TikTok`)
    return socialContent
  } catch (err) {
    logger.error(`SNS 콘텐츠 생성 실패: ${err.message}`)
    throw err
  }
}

/**
 * 인스타그램 캡션 포맷팅 (줄바꿈 + 해시태그 분리)
 */
export function formatInstagramCaption(socialContent) {
  const { instagram } = socialContent
  if (!instagram) return ''
  const tags = instagram.hashtags.map(t => t.startsWith('#') ? t : `#${t}`).join(' ')
  return `${instagram.caption}\n\n${tags}`
}

/**
 * 쓰레드 포스트 배열 반환
 */
export function formatThreadsPosts(socialContent) {
  const { threads } = socialContent
  if (!threads) return []
  const tags = threads.hashtags.map(t => t.startsWith('#') ? t : `#${t}`).join(' ')
  return threads.posts.map((p, i) => ({
    ...p,
    fullContent: i === threads.posts.length - 1
      ? `${p.content}\n\n${tags}`
      : p.content,
  }))
}
