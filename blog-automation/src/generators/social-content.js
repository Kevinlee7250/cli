import Anthropic from '@anthropic-ai/sdk'
import { config } from '../config.js'
import { logger } from '../utils/logger.js'

const client = new Anthropic({ apiKey: config.anthropic.apiKey })

const OPTIMAL_POSTING_TIMES = {
  instagram: ['07:00', '12:00', '18:00', '21:00'],
  threads: ['08:00', '13:00', '19:00', '22:00'],
  tiktok: ['07:00', '12:00', '17:00', '20:00', '23:00'],
}

/**
 * SNS 플랫폼별 최적화 콘텐츠 생성 (v2)
 * Instagram 저장율, Threads 토론유발, TikTok 완시청률 최적화
 */
export async function generateSocialContent(blogPost, blogUrl = '') {
  logger.info(`SNS 콘텐츠 생성 중: "${blogPost.title}"`)

  const trendBadge = blogPost.trendDirection === 'rising' ? '🚀 급상승' : '🔥 핫이슈'
  const faqPreview = (blogPost.faq || []).slice(0, 2).map(f => `Q. ${f.question}`).join('\n')

  const systemPrompt = `당신은 인스타그램, 쓰레드, 틱톡 플랫폼별 바이럴 SNS 콘텐츠 전문가입니다.
알고리즘 최적화, 저장률·공유율 극대화, 블로그 트래픽 유입을 동시에 달성합니다.
- Instagram: 저장(Save) > 공유 > 댓글 > 좋아요 순으로 알고리즘 가중치
- Threads: 토론·의견 유발 콘텐츠 우대
- TikTok: 3초 리텐션, 완시청률, 댓글 유발이 핵심 지표`

  const userPrompt = `다음 블로그 포스트를 기반으로 플랫폼별 최적화 SNS 콘텐츠를 작성해주세요.

**블로그 제목:** ${blogPost.title}
**키워드:** ${blogPost.keyword} (${trendBadge})
**카테고리:** ${blogPost.adsenseCategory || '일반'}
**요약:** ${blogPost.excerpt || blogPost.metaDescription}
**블로그 URL:** ${blogUrl || '[블로그 URL]'}
**FAQ 미리보기:**
${faqPreview || '없음'}
**태그:** ${(blogPost.tags || []).join(', ')}

**[인스타그램]**
- 첫 2줄: 스크롤 멈추게 하는 후킹 (숫자 또는 충격 사실)
- "저장 필수 🔖" 문구 포함 (저장율 알고리즘 최우선)
- 정보 리스트 5-7개 (번호 + 이모지)
- 스토리 하이라이트 제목 제안 (5자 이내)
- 해시태그: 인기태그 10개 + 중간태그 10개 + 니치태그 5개

**[쓰레드]**
- 5개 연속 스레드 (1/5 ~ 5/5)
- 1번: 충격적 사실/통계
- 5번: 결론 + 블로그 링크 + 의견 요청
- 해시태그 5개

**[틱톡]**
- 60초 영상 스크립트
- 씬별: 0-3초 후킹 / 3-15초 문제 / 15-35초 해결 / 35-50초 결론 / 50-60초 CTA
- 각 씬: 자막 텍스트 + 카메라 연출 + 효과음
- 배경음악 장르 추천
- 해시태그 10개 (FYP 포함)

**응답 형식 (JSON):**
\`\`\`json
{
  "instagram": {
    "caption": "전체 캡션",
    "hookLine": "첫 후킹 문장",
    "storyHighlightTitle": "하이라이트 제목",
    "hashtags": { "popular": [], "medium": [], "niche": [] },
    "bestPostingTimes": ["07:00", "12:00", "21:00"]
  },
  "threads": {
    "posts": [
      { "order": 1, "label": "1/5", "content": "내용" },
      { "order": 2, "label": "2/5", "content": "내용" },
      { "order": 3, "label": "3/5", "content": "내용" },
      { "order": 4, "label": "4/5", "content": "내용" },
      { "order": 5, "label": "5/5", "content": "마지막 + CTA" }
    ],
    "hashtags": ["태그1", "태그2", "태그3", "태그4", "태그5"],
    "engagementQuestion": "댓글 유발 질문",
    "bestPostingTimes": ["08:00", "19:00"]
  },
  "tiktok": {
    "title": "영상 제목",
    "scenes": [
      { "time": "0-3초", "text": "자막", "direction": "연출", "sound": "효과음" },
      { "time": "3-15초", "text": "자막", "direction": "연출", "sound": "효과음" },
      { "time": "15-35초", "text": "자막", "direction": "연출", "sound": "효과음" },
      { "time": "35-50초", "text": "자막", "direction": "연출", "sound": "효과음" },
      { "time": "50-60초", "text": "CTA", "direction": "연출", "sound": "효과음" }
    ],
    "fullScript": "전체 낭독 스크립트",
    "thumbnailText": "썸네일 텍스트",
    "commentBait": "댓글 유발 질문",
    "hashtags": ["fyp", "foryou", "태그3"],
    "backgroundMusic": { "genre": "장르", "mood": "분위기" },
    "bestPostingTimes": ["07:00", "20:00", "23:00"]
  },
  "keyword": "${blogPost.keyword}",
  "date": "${new Date().toISOString().split('T')[0]}",
  "trendDirection": "${blogPost.trendDirection || 'stable'}"
}
\`\`\``

  try {
    const response = await client.messages.create({
      model: config.anthropic.model,
      max_tokens: 10000,
      system: systemPrompt,
      messages: [{ role: 'user', content: userPrompt }],
    })

    const text = response.content[0].text
    const socialContent = extractJSON(text)

    if (!socialContent.instagram?.bestPostingTimes) {
      socialContent.instagram = socialContent.instagram || {}
      socialContent.instagram.bestPostingTimes = OPTIMAL_POSTING_TIMES.instagram
    }

    logger.info(`SNS 콘텐츠 생성 완료: Instagram + Threads(5개) + TikTok(${socialContent.tiktok?.scenes?.length || 5}씬)`)
    return socialContent
  } catch (err) {
    logger.error(`SNS 콘텐츠 생성 실패: ${err.message}`)
    throw err
  }
}

export function formatInstagramCaption(socialContent) {
  const { instagram } = socialContent
  if (!instagram) return ''
  const allHashtags = [
    ...(instagram.hashtags?.popular || []),
    ...(instagram.hashtags?.medium || []),
    ...(instagram.hashtags?.niche || []),
  ].map(t => t.startsWith('#') ? t : `#${t}`).join(' ')
  return `${instagram.caption}\n\n💡 도움이 됐다면 저장 🔖 해두세요!\n\n${allHashtags}`
}

export function formatThreadsPosts(socialContent) {
  const { threads } = socialContent
  if (!threads) return []
  const tags = (threads.hashtags || []).map(t => t.startsWith('#') ? t : `#${t}`).join(' ')
  return threads.posts.map((p, i) => ({
    ...p,
    fullContent: i === threads.posts.length - 1 ? `${p.content}\n\n${tags}` : p.content,
  }))
}

export function getNextOptimalPostingTime(platform) {
  const times = OPTIMAL_POSTING_TIMES[platform] || OPTIMAL_POSTING_TIMES.instagram
  const now = new Date()
  const nowMinutes = now.getHours() * 60 + now.getMinutes()
  for (const time of times) {
    const [h, m] = time.split(':').map(Number)
    if (h * 60 + m > nowMinutes) return time
  }
  return times[0] + ' (내일)'
}

function sanitizeJSON(raw) {
  return raw
    .replace(/['']/g, "'")
    .replace(/[""]/g, '"')
    .replace(/[–—]/g, '-')
    .replace(/\r\n/g, '\n')
}

function extractJSON(text) {
  const codeStart = text.indexOf('```json')
  if (codeStart !== -1) {
    const jsonStart = text.indexOf('{', codeStart)
    const jsonEnd = text.lastIndexOf('}')
    if (jsonStart !== -1 && jsonEnd > jsonStart) {
      const raw = sanitizeJSON(text.slice(jsonStart, jsonEnd + 1))
      try { return JSON.parse(raw) } catch {}
    }
  }
  const start = text.indexOf('{')
  const end = text.lastIndexOf('}')
  if (start !== -1 && end > start) {
    return JSON.parse(sanitizeJSON(text.slice(start, end + 1)))
  }
  throw new Error('응답에서 JSON을 찾을 수 없습니다')
}
