import fs from 'fs'
import path from 'path'
import { config } from '../config.js'
import { logger } from './logger.js'

/**
 * 게시 전 미리보기 HTML 리포트 생성
 * --preview 모드에서 실제 API 호출 없이 콘텐츠를 검토할 수 있습니다
 */
export function generatePreviewReport(results) {
  const reportDir = path.resolve('./output/previews')
  if (!fs.existsSync(reportDir)) fs.mkdirSync(reportDir, { recursive: true })

  const date = new Date().toISOString().split('T')[0]
  const time = new Date().toTimeString().slice(0, 5).replace(':', '')
  const filename = path.join(reportDir, `preview_${date}_${time}.html`)

  const html = buildPreviewHtml(results, date)
  fs.writeFileSync(filename, html, 'utf-8')
  logger.info(`미리보기 리포트 생성: ${filename}`)
  return filename
}

function buildPreviewHtml(results, date) {
  const postCards = results.posts.map((post, i) => {
    if (!post.blogPost) return ''

    const { blogPost, socialContent, thumbnails, earnings } = post

    const instagramPreview = socialContent?.instagram
      ? `<div class="sns-preview instagram">
          <div class="sns-header">📸 Instagram</div>
          <div class="hook">${socialContent.instagram.hookLine || ''}</div>
          <pre class="caption">${(socialContent.instagram.caption || '').slice(0, 300)}...</pre>
          <div class="timing">⏰ 최적 게시: ${(socialContent.instagram.bestPostingTimes || []).join(', ')}</div>
          <div class="hashtags">${getAllHashtags(socialContent.instagram).slice(0, 10).join(' ')}</div>
        </div>`
      : ''

    const threadsPreview = socialContent?.threads
      ? `<div class="sns-preview threads">
          <div class="sns-header">🧵 Threads (${socialContent.threads.posts?.length || 0}개 스레드)</div>
          ${(socialContent.threads.posts || []).slice(0, 2).map(p =>
            `<div class="thread-post"><strong>${p.label}</strong> ${p.content.slice(0, 150)}...</div>`).join('')}
          <div class="timing">⏰ 최적 게시: ${(socialContent.threads.bestPostingTimes || []).join(', ')}</div>
        </div>`
      : ''

    const tiktokPreview = socialContent?.tiktok
      ? `<div class="sns-preview tiktok">
          <div class="sns-header">🎵 TikTok 스크립트</div>
          <div class="tiktok-title">${socialContent.tiktok.title || ''}</div>
          <table class="scenes-table">
            <tr><th>타이밍</th><th>자막</th><th>연출</th></tr>
            ${(socialContent.tiktok.scenes || []).map(s =>
              `<tr><td>${s.time}</td><td>${s.text}</td><td>${s.direction}</td></tr>`).join('')}
          </table>
          <div class="timing">⏰ 최적 게시: ${(socialContent.tiktok.bestPostingTimes || []).join(', ')}</div>
        </div>`
      : ''

    const faqHtml = blogPost.faq?.length
      ? `<div class="faq-preview">
          <h4>FAQ (구글 추천 스니펫 타겟)</h4>
          ${blogPost.faq.map(f => `<div class="faq-item"><strong>Q. ${f.question}</strong><p>A. ${f.answer}</p></div>`).join('')}
        </div>`
      : ''

    const earningsHtml = earnings
      ? `<div class="earnings">
          💰 예상 일 수익: <strong>$${earnings.estimatedDailyRevenue}</strong> |
          월 수익: <strong>$${earnings.estimatedMonthlyRevenue}</strong> |
          CPC: $${earnings.estimatedCPC} | RPM: $${earnings.pageRPM}
        </div>`
      : ''

    return `
<div class="post-card">
  <div class="post-header">
    <span class="rank">#${i + 1}</span>
    <span class="keyword">${blogPost.keyword}</span>
    <span class="category tag">${blogPost.adsenseCategory || '일반'}</span>
    <span class="trend tag ${blogPost.trendDirection}">${
      blogPost.trendDirection === 'rising' ? '🚀 급상승' : blogPost.trendDirection === 'falling' ? '📉 하락' : '📊 안정'
    }</span>
  </div>

  <h2 class="post-title">${blogPost.title}</h2>
  <p class="meta-desc">${blogPost.metaDescription || ''}</p>

  ${earningsHtml}

  <div class="thumbnails">
    ${thumbnails?.horizontal ? `<div class="thumb-label">🖼️ 가로 썸네일: <code>${thumbnails.horizontal}</code></div>` : ''}
    ${thumbnails?.vertical ? `<div class="thumb-label">📱 세로 썸네일: <code>${thumbnails.vertical}</code></div>` : ''}
  </div>

  ${faqHtml}

  <div class="sns-previews">
    ${instagramPreview}
    ${threadsPreview}
    ${tiktokPreview}
  </div>

  <div class="post-tags">
    ${(blogPost.tags || []).map(t => `<span class="tag">${t}</span>`).join('')}
  </div>
</div>`
  }).join('')

  const totalEarnings = results.earningsEstimate?.summary
  const summaryHtml = totalEarnings ? `
<div class="summary-card">
  <h2>💰 AdSense 예상 수익 요약</h2>
  <div class="earnings-grid">
    <div class="e-item"><div class="e-label">오늘 예상</div><div class="e-value">$${totalEarnings.estimatedDailyRevenue}</div></div>
    <div class="e-item"><div class="e-label">월간 예상</div><div class="e-value">$${totalEarnings.estimatedMonthlyRevenue}</div></div>
    <div class="e-item"><div class="e-label">연간 예상</div><div class="e-value">$${totalEarnings.estimatedYearlyRevenue}</div></div>
    <div class="e-item"><div class="e-label">평균 CPC</div><div class="e-value">$${totalEarnings.avgCPC}</div></div>
  </div>
  <p style="color:#888;font-size:13px;margin-top:8px;">* CTR 2.5% 기준 추정치. 실제 수익은 트래픽·광고 단가에 따라 달라집니다.</p>
</div>` : ''

  return `<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>블로그 자동화 미리보기 — ${date}</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Noto Sans KR', sans-serif; background: #0f0f0f; color: #e0e0e0; padding: 20px; }
h1 { color: #fff; margin-bottom: 20px; font-size: 28px; }
.summary-card { background: #1a1a2e; border: 1px solid #333; border-radius: 16px; padding: 24px; margin-bottom: 24px; }
.summary-card h2 { color: #ffd700; margin-bottom: 16px; }
.earnings-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
.e-item { background: #0f0f1a; border-radius: 12px; padding: 16px; text-align: center; }
.e-label { color: #888; font-size: 13px; margin-bottom: 8px; }
.e-value { color: #ffd700; font-size: 28px; font-weight: bold; }
.post-card { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 16px; padding: 24px; margin-bottom: 32px; }
.post-header { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.rank { background: #e94560; color: #fff; font-weight: bold; padding: 4px 14px; border-radius: 20px; font-size: 18px; }
.keyword { font-size: 20px; font-weight: bold; color: #fff; }
.tag { padding: 4px 12px; border-radius: 20px; font-size: 13px; background: #2a2a3a; color: #a0a0c0; }
.tag.rising { background: #003300; color: #00ff88; }
.tag.falling { background: #330000; color: #ff6666; }
.post-title { font-size: 24px; color: #ffffff; margin-bottom: 10px; line-height: 1.4; }
.meta-desc { color: #888; font-size: 14px; margin-bottom: 16px; }
.earnings { background: #111; border-left: 4px solid #ffd700; padding: 12px 16px; border-radius: 4px; margin-bottom: 16px; font-size: 14px; }
.earnings strong { color: #ffd700; }
.thumbnails { margin-bottom: 16px; }
.thumb-label { font-size: 13px; color: #666; margin-bottom: 4px; }
.thumb-label code { color: #00ff88; }
.faq-preview { background: #111; border-radius: 12px; padding: 16px; margin-bottom: 16px; }
.faq-preview h4 { color: #a0a0ff; margin-bottom: 12px; }
.faq-item { margin-bottom: 12px; border-bottom: 1px solid #222; padding-bottom: 10px; }
.faq-item strong { color: #e0e0ff; display: block; margin-bottom: 4px; }
.faq-item p { color: #888; font-size: 14px; }
.sns-previews { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; margin-bottom: 16px; }
.sns-preview { background: #111; border-radius: 12px; padding: 16px; }
.sns-header { font-weight: bold; margin-bottom: 10px; color: #fff; }
.hook { color: #ffd700; font-size: 15px; margin-bottom: 8px; }
.caption { color: #888; font-size: 12px; white-space: pre-wrap; max-height: 120px; overflow: hidden; }
.timing { color: #00ff88; font-size: 12px; margin-top: 8px; }
.hashtags { color: #6688ff; font-size: 12px; margin-top: 6px; }
.thread-post { font-size: 13px; color: #ccc; border-left: 3px solid #6644aa; padding-left: 10px; margin-bottom: 8px; }
.tiktok-title { color: #ff6b6b; font-weight: bold; margin-bottom: 10px; }
.scenes-table { width: 100%; font-size: 12px; border-collapse: collapse; }
.scenes-table th { background: #222; color: #aaa; padding: 6px; text-align: left; }
.scenes-table td { padding: 6px; border-bottom: 1px solid #1a1a1a; color: #ccc; vertical-align: top; }
.post-tags { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.post-tags .tag { background: #1a2a3a; color: #6699cc; }
</style>
</head>
<body>
<h1>🤖 블로그 자동화 미리보기 — ${date}</h1>
<p style="color:#666;margin-bottom:20px;">생성된 ${results.posts?.length || 0}개 포스트 미리보기 (게시 전 검토용)</p>

${summaryHtml}

${postCards}

<div style="color:#444;font-size:12px;margin-top:40px;text-align:center;">
  Blog Automation System v2 | Generated at ${new Date().toLocaleString('ko-KR')}
</div>
</body>
</html>`
}

function getAllHashtags(instagram) {
  return [
    ...(instagram.hashtags?.popular || []),
    ...(instagram.hashtags?.medium || []),
    ...(instagram.hashtags?.niche || []),
  ].map(t => t.startsWith('#') ? t : `#${t}`)
}
