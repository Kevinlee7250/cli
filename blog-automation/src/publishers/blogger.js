import axios from 'axios'
import { config } from '../config.js'
import { logger } from '../utils/logger.js'

let cachedAccessToken = null
let tokenExpiry = null

/**
 * Google OAuth2 Access Token 갱신
 */
async function getAccessToken() {
  if (cachedAccessToken && tokenExpiry && Date.now() < tokenExpiry) {
    return cachedAccessToken
  }

  if (!config.google.refreshToken) {
    throw new Error('Google Refresh Token이 설정되지 않았습니다.')
  }

  try {
    const response = await axios.post(config.google.tokenUrl, {
      client_id: config.google.clientId,
      client_secret: config.google.clientSecret,
      refresh_token: config.google.refreshToken,
      grant_type: 'refresh_token',
    })

    cachedAccessToken = response.data.access_token
    tokenExpiry = Date.now() + (response.data.expires_in - 60) * 1000
    return cachedAccessToken
  } catch (err) {
    throw new Error(`Access Token 갱신 실패: ${err.response?.data?.error_description || err.message}`)
  }
}

/**
 * 구글 블로거에 포스트 게시
 * @param {Object} blogPost - 블로그 포스트 데이터
 * @returns {Promise<{url: string, id: string}>}
 */
export async function publishToBlogger(blogPost) {
  if (!config.blogger.blogId) {
    logger.warn('Blogger Blog ID가 설정되지 않았습니다. 건너뜁니다.')
    return { skipped: true, reason: 'BLOGGER_BLOG_ID not configured' }
  }

  logger.info(`Blogger에 포스트 게시 중: "${blogPost.title}"`)

  try {
    const token = await getAccessToken()

    const labels = [
      ...(blogPost.tags || []),
      blogPost.keyword,
    ].filter(Boolean)

    const postBody = {
      title: blogPost.title,
      content: buildHtmlContent(blogPost),
      labels,
    }

    const response = await axios.post(
      `${config.blogger.apiUrl}/blogs/${config.blogger.blogId}/posts`,
      postBody,
      {
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        params: { isDraft: false },
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
    const errMsg = err.response?.data?.error?.message || err.message
    logger.error(`Blogger 게시 실패: ${errMsg}`)
    return { error: errMsg }
  }
}

/**
 * HTML 콘텐츠 구성 (AdSense 광고 슬롯 포함)
 */
function buildHtmlContent(blogPost) {
  const adSenseScript = `<!-- Google AdSense -->
<ins class="adsbygoogle"
     style="display:block"
     data-ad-client="ca-pub-XXXXXXXXXXXXXXXX"
     data-ad-slot="XXXXXXXXXX"
     data-ad-format="auto"
     data-full-width-responsive="true"></ins>
<script>(adsbygoogle = window.adsbygoogle || []).push({});</script>`

  const seoMeta = `<!-- SEO 키워드: ${(blogPost.seoKeywords || []).join(', ')} -->`

  // 본문 중간에 광고 삽입 (2000자 기준)
  let content = blogPost.content || ''
  const midPoint = Math.floor(content.length / 2)
  const insertIdx = content.indexOf('</p>', midPoint)
  if (insertIdx > 0) {
    content = content.slice(0, insertIdx + 4) + '\n' + adSenseScript + '\n' + content.slice(insertIdx + 4)
  }

  return `${seoMeta}
<div class="blog-post-container">
${content}

${adSenseScript}

<hr/>
<div class="post-footer">
  <p><strong>관련 키워드:</strong> ${(blogPost.tags || []).map(t => `<a href="/search/label/${encodeURIComponent(t)}">${t}</a>`).join(', ')}</p>
  <p><em>이 포스트가 도움이 되셨다면 공유해주세요!</em></p>
</div>
</div>`
}
