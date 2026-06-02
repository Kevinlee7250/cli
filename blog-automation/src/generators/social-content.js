import Anthropic from '@anthropic-ai/sdk'
import { config } from '../config.js'
import { logger } from '../utils/logger.js'

const client = new Anthropic({ apiKey: config.anthropic.apiKey })

// 플랫폼별 최적 게시 시간 (KST)
const OPTIMAL_POSTING_TIMES = {
  instagram: ['07:00', '12:00', '18:00', '21:00'],
  threads: ['08:00', '13:00', '19:00', '22:00'],
  tiktok: ['07:00', '12:00', '17:00', '20:00', '23:00'],
}

/**
 * 블로그 포스트로부터 SNS 플랫폼별 최적화 콘텐츠 생성 (v2)
 * 업그레이드: 게시 타이밍 추천 + 스토리 하이라이트 + 릴스 전환 전략
 */
export async function generateSocialContent(blogPost, blogUrl = '') {
  logger.info(`SNS 콘텐츠 생성 중: "${blogPost.title}"`)

  const trendBadge = blogPost.trendDirection === 'rising' ? '🚀 급상승' : '🔥 핫이슈'
  const faqPreview = (blogPost.faq || []).slice(0, 2).map(f => `Q. ${f.question}`).join('\n')

  const systemPrompt = `당신은 인스타그램, 쓰레드, 틱톡 플랫폼별 바이럴 SNS 콘텐츠 전문가입니다.
알고리즘 최적화, 저장률·공유율 극대화, 블로그 트래픽 유입을 동시에 달성합니다.
각 플랫폼의 2026년 현재 알고리즘 특성을 반영합니다:
- Instagram: 저장(Save) > 공유 > 댓글 > 좋아요 순으로 알고리즘 가중치
- Threads: 토론·의견 유발 콘텐츠 우대, 링크 외부 유도 허용
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

**[인스타그램] 요구사항:**
- 첫 2줄: 스크롤 멈추게 하는 후킹 (숫자 또는 충격 사실)
- 이모지로 시각적 구분
- "저장 필수 🔖" 문구 반드시 포함 (저장율 알고리즘 최우선)
- 정보 리스트 5-7개 (번호 + 이모지)
- 프로필 링크 유도 멘트
- 스토리 하이라이트 제목 제안 (5자 이내)
- 해시태그: 인기태그 10개 + 중간태그 10개 + 니치태그 5개 (총 25개)

**[쓰레드] 요구사항:**
- 5개 연속 스레드 (1/5 형식)
- 1번: 충격적 사실/통계로 시작
- 2-4번: 핵심 정보 단계별 전개
- 5번: 결론 + 블로그 링크 유도 + 의견 요청 질문
- 해시태그 5개
- 각 스레드 500자 이내

**[틱톡] 요구사항:**
- 총 60초 영상 스크립트
- 씬별 구성 (0-3초 후킹 → 15초 문제 → 30초 해결 → 50초 결론 → 60초 CTA)
- 각 씬: 자막 텍스트 + 카메라 연출 지시 + 효과음/배경음 제안
- "이거 모르면 손해" / "충격주의" 등 후킹 공식 적용
- 댓글 유발 질문 포함
- 해시태그 10개 (FYP 태그 포함)
- 배경음악 장르 추천

**응답 형식 (JSON):**
\`\`\`json
{
  "instagram": {
    "caption": "전체 캡션",
    "hookLine": "첫 후킹 문장 (2줄)",
    "infoList": ["포인트1", "포인트2", "포인트3", "포인트4", "포인트5"],
    "ctaText": "프로필 링크 유도 문구",
    "storyHighlightTitle": "하이라이트 제목",
    "hashtags": {
      "popular": ["인기태그1", "인기태그2"],
      "medium": ["중간태그1", "중간태그2"],
      "niche": ["니치태그1", "니치태그2"]
    },
    "bestPostingTimes": ["07:00", "12:00", "21:00"],
    "savePrompt": "저장 유도 문구"
  },
  "threads": {
    "posts": [
      { "order": 1, "label": "1/5", "content": "첫 번째 스레드" },
      { "order": 2, "label": "2/5", "content": "두 번째 스레드" },
      { "order": 3, "label": "3/5", "content": "세 번째 스레드" },
      { "order": 4, "label": "4/5", "content": "네 번째 스레드" },
      { "order": 5, "label": "5/5", "content": "마지막 + CTA + 질문" }
    ],
    "hashtags": ["해시태그1", "해시태그2", "해시태그3", "해시태그4", "해시태그5"],
    "engagementQuestion": "댓글 유발 질문",
    "bestPostingTimes": ["08:00", "19:00"]
  },
  "tiktok": {
    "title": "영상 제목 (60자)",
    "scenes": [
      { "time": "0-3초", "text": "자막 텍스트", "direction": "카메라 연출", "sound": "효과음" },
      { "time": "3-15초", "text": "자막 텍스트", "direction": "카메라 연출", "sound": "효과음" },
      { "time": "15-35초", "text": "자막 텍스트", "direction": "카메라 연출", "sound": "효과음" },
      { "time": "35-50초", "text": "자막 텍스트", "direction": "카메라 연출", "sound": "효과음" },
      { "time": "50-60초", "text": "CTA 자막", "direction": "카메라 연출", "sound": "효과음" }
    ],
    "fullScript": "전체 낭독 스크립트",
    "thumbnailText": "썸네일 텍스트 (10자)",
    "commentBait": "댓글 유발 질문",
    "hashtags": ["fyp", "foryou", "해시태그3", "해시태그4", "해시태그5"],
    "backgroundMusic": { "genre": "장르", "mood": "분위기", "suggestion": "추천 곡/아티스트" },
    "bestPostingTimes": ["07:00", "20:00", "23:00"]
  },
  "keyword": "${blogPost.keyword}",
  "blogTitle": "${blogPost.title}",
  "date": "${new Date().toISOString().split('T')[0]}",
  "trendDirection": "${blogPost.trendDirection || 'stable'}"
}
\`\`\``

  try {
    const response = await client.messages.create({
      model: config.anthropic.model,
      max_tokens: 5000,
      system: systemPrompt,
      messages: [{ role: 'user', content: userPrompt }],
    })

    const text = response.content[0].text
    const jsonMatch = text.match(/```json\n([\s\S]*?)\n```/) || text.match(/(\{[\s\S]*\})/s)
    const jsonStr = jsonMatch ? (jsonMatch[1] || jsonMatch[0]) : text

    const socialContent = JSON.parse(jsonStr)

    // 게시 타이밍 보완 (API 응답에 없는 경우)
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

/**
 * 인스타그램 캡션 포맷팅 (저장율 최적화)
 */
export function formatInstagramCaption(socialContent) {
  const { instagram } = socialContent
  if (!instagram) return ''

  const allHashtags = [
    ...(instagram.hashtags?.popular || []),
    ...(instagram.hashtags?.medium || []),
    ...(instagram.hashtags?.niche || []),
  ].map(t => t.startsWith('#') ? t : `#${t}`).join(' ')

  // 줄바꿈으로 가독성 향상
  return `${instagram.caption}\n\n💡 도움이 됐다면 저장 🔖 해두세요!\n\n${allHashtags}`
}

/**
 * 쓰레드 포스트 배열 반환 (게시 순서 포함)
 */
export function formatThreadsPosts(socialContent) {
  const { threads } = socialContent
  if (!threads) return []

  const tags = (threads.hashtags || []).map(t => t.startsWith('#') ? t : `#${t}`).join(' ')

  return threads.posts.map((p, i) => ({
    ...p,
    fullContent: i === threads.posts.length - 1
      ? `${p.content}\n\n${tags}`
      : p.content,
  }))
}

/**
 * 다음 최적 게시 시간 계산
 */
export function getNextOptimalPostingTime(platform) {
  const times = OPTIMAL_POSTING_TIMES[platform] || OPTIMAL_POSTING_TIMES.instagram
  const now = new Date()
  const nowMinutes = now.getHours() * 60 + now.getMinutes()

  for (const time of times) {
    const [h, m] = time.split(':').map(Number)
    const timeMinutes = h * 60 + m
    if (timeMinutes > nowMinutes) {
      return time
    }
  }
  // 오늘 남은 시간이 없으면 내일 첫 번째 시간
  return times[0] + ' (내일)'
}
