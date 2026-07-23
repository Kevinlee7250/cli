import axios from 'axios'
import { config } from '../config.js'
import { logger } from '../utils/logger.js'
import { injectAdSenseSlots, buildFAQStructuredData } from '../generators/blog-content.js'

let cachedAccessToken = null
let tokenExpiry = null

async function getAccessToken() {
  if (cachedAccessToken && tokenExpiry && Date.now() < tokenExpiry) {
    return cachedAccessToken
  }
  if (!config.google.refreshToken) {
    throw new Error('Google Refresh Token이 설정되지 않았습니다.')
  }
  const response = await axios.post(config.google.tokenUrl, {
    client_id: config.google.clientId,
    client_secret: config.google.clientSecret,
    refresh_token: config.google.refreshToken,
    grant_type: 'refresh_token',
  })
  cachedAccessToken = response.data.access_token
  tokenExpiry = Date.now() + (response.data.expires_in - 60) * 1000
  return cachedAccessToken
}

/**
 * Google Blogger에 포스트 게시 (v2)
 * 업그레이드: AdSense 4슬롯, FAQ 구조화 데이터, Article 스키마, 사이트맵 핑
 */
export async function publishToBlogger(blogPost, options = {}) {
  const { adClientId = process.env.ADSENSE_CLIENT_ID || 'ca-pub-XXXXXXXXXXXXXXXX', isDraft = false } = options

  if (!config.blogger.blogId) {
    logger.warn('Blogger Blog ID가 없습니다. 건너뜁니다.')
    return { skipped: true, reason: 'BLOGGER_BLOG_ID not configured' }
  }

  logger.info(`Blogger 게시 중: "${blogPost.title}"`)

  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      if (attempt > 1) {
        const wait = attempt * 5000
        logger.info(`Blogger 재시도 ${attempt}/3 (${wait / 1000}초 후)...`)
        await new Promise(r => setTimeout(r, wait))
      }
    const token = await getAccessToken()
    const htmlContent = buildFullHtmlContent(blogPost, adClientId)

    // 라벨: 최대 20개, 각 200자 이하로 제한
    const labels = [
      ...(blogPost.tags || []),
      blogPost.keyword,
      blogPost.adsenseCategory,
    ].filter(Boolean).slice(0, 20).map(l => String(l).slice(0, 200))

    const response = await axios.post(
      `${config.blogger.apiUrl}/blogs/${config.blogger.blogId}/posts`,
      { title: blogPost.title, content: htmlContent, labels },
      {
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        params: { isDraft },
      },
    )

    const result = {
      id: response.data.id,
      url: response.data.url,
      title: response.data.title,
      published: response.data.published,
    }

      logger.info(`Blogger 게시 완료: ${result.url}`)
      return result
    } catch (err) {
      const errData = err.response?.data?.error
      const errMsg = errData?.message || err.message
      const errDetails = errData?.errors ? JSON.stringify(errData.errors) : ''
      if (attempt < 3) {
        logger.warn(`Blogger 게시 오류 (시도 ${attempt}/3): ${errMsg}`)
      } else {
        logger.error(`Blogger 게시 실패: ${errMsg}${errDetails ? ' | ' + errDetails : ''}`)
        return { error: errMsg }
      }
    }
  }
}

/**
 * SEO 완전 최적화 HTML 구성
 * - Article 구조화 데이터 (JSON-LD)
 * - FAQPage 구조화 데이터
 * - AdSense 광고 4슬롯
 * - 내부 링크 섹션
 * - SEO 키워드 메타
 */
function buildFullHtmlContent(blogPost, adClientId) {
  // 1. 광고 슬롯 주입
  const contentWithAds = injectAdSenseSlots(blogPost.content || '', adClientId)

  // 2. Article 구조화 데이터
  const articleSchema = JSON.stringify({
    '@context': 'https://schema.org',
    '@type': 'Article',
    headline: blogPost.title,
    description: blogPost.metaDescription,
    author: { '@type': 'Organization', name: '오늘의 핫이슈' },
    datePublished: blogPost.generatedAt || new Date().toISOString(),
    dateModified: new Date().toISOString(),
    keywords: (blogPost.seoKeywords || []).join(', '),
    ...(blogPost.structuredData || {}),
  }, null, 2)

  // 3. FAQPage 구조화 데이터
  const faqSchema = blogPost.faq?.length
    ? JSON.stringify(buildFAQStructuredData(blogPost.faq), null, 2)
    : null

  // 4. FAQ HTML 섹션
  const faqHtml = blogPost.faq?.length ? `
<div class="faq-section" style="background:#f8f9fa;padding:24px;border-radius:12px;margin:2em 0;">
  <h2>자주 묻는 질문 (FAQ)</h2>
  ${blogPost.faq.map(f => `
  <details style="margin:12px 0;padding:12px;background:#fff;border-radius:8px;">
    <summary style="font-weight:bold;cursor:pointer;">${f.question}</summary>
    <p style="margin-top:8px;color:#444;">${f.answer}</p>
  </details>`).join('\n')}
</div>` : ''

  // 5. 관련 태그 링크
  const tagLinks = (blogPost.tags || [])
    .map(t => `<a href="/search/label/${encodeURIComponent(t)}" style="display:inline-block;margin:4px;padding:6px 14px;background:#e9ecef;border-radius:20px;text-decoration:none;color:#333;font-size:14px;">${t}</a>`)
    .join('')

  return `<!-- SEO: ${(blogPost.seoKeywords || []).join(', ')} -->
<script type="application/ld+json">${articleSchema}</script>
${faqSchema ? `<script type="application/ld+json">${faqSchema}</script>` : ''}

<div class="blog-post-wrap" style="max-width:800px;margin:0 auto;font-family:'Noto Sans KR',sans-serif;line-height:1.8;color:#222;">

${contentWithAds}

${faqHtml}

<hr style="margin:3em 0;border:none;border-top:2px solid #eee;"/>

<div class="post-footer" style="padding:20px 0;">
  <h3 style="font-size:16px;color:#555;">관련 태그</h3>
  <div style="margin-bottom:16px;">${tagLinks}</div>
  <p style="color:#888;font-size:14px;">📌 이 포스트가 도움이 됐다면 북마크해 두세요!</p>
  <p style="color:#888;font-size:13px;">* 본 콘텐츠는 AI가 최신 트렌드를 바탕으로 작성했으며, 투자·의료·법률 등 전문 분야는 반드시 전문가와 상담하세요.</p>
</div>
</div>`
}
