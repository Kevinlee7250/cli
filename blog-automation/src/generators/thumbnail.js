import { createCanvas } from 'canvas'
import fs from 'fs'
import path from 'path'
import { config } from '../config.js'
import { logger } from '../utils/logger.js'

const { width, height, outputDir } = config.thumbnail

// 업그레이드된 디자인 테마 (6종)
const THEMES = [
  {
    name: 'dark-blue',
    bg: { type: 'gradient', colors: ['#0a0e27', '#111936', '#0f3460'] },
    accent: '#e94560', accent2: '#ff6b6b',
    text: '#ffffff', subText: '#a8b2d8',
    badgeBg: '#e94560',
  },
  {
    name: 'neon-green',
    bg: { type: 'gradient', colors: ['#030303', '#0a1a0a', '#0d2b12'] },
    accent: '#00ff88', accent2: '#00cc66',
    text: '#ffffff', subText: '#88ccaa',
    badgeBg: '#00cc66',
  },
  {
    name: 'fire-orange',
    bg: { type: 'gradient', colors: ['#1a0500', '#2d0e00', '#4a1800'] },
    accent: '#ff6b35', accent2: '#ff9500',
    text: '#ffffff', subText: '#ffcc99',
    badgeBg: '#ff6b35',
  },
  {
    name: 'royal-purple',
    bg: { type: 'gradient', colors: ['#0a0a1a', '#150d33', '#2d1b69'] },
    accent: '#c77dff', accent2: '#9d4edd',
    text: '#ffffff', subText: '#c0b3e8',
    badgeBg: '#9d4edd',
  },
  {
    name: 'clean-red',
    bg: { type: 'solid', color: '#1a1a1a' },
    accent: '#ff3333', accent2: '#ff6666',
    text: '#ffffff', subText: '#cccccc',
    badgeBg: '#ff3333',
  },
  {
    name: 'gold-dark',
    bg: { type: 'gradient', colors: ['#111100', '#1a1500', '#2a2000'] },
    accent: '#ffd700', accent2: '#ffaa00',
    text: '#ffffff', subText: '#ffe066',
    badgeBg: '#cc9900',
  },
]

/**
 * 블로그/YouTube용 가로형 썸네일 생성 (1280×720) — v2
 * 업그레이드: 트렌드 순위 배지, 상승 인디케이터, 뉴스 개수 배지
 */
export async function generateThumbnail(blogPost, outputPath = null) {
  ensureDir(outputDir)

  const theme = THEMES[Math.floor(Math.random() * THEMES.length)]
  const canvas = createCanvas(width, height)
  const ctx = canvas.getContext('2d')

  drawBackground(ctx, theme, width, height)
  drawGridPattern(ctx, theme, width, height)
  drawTopAccentLine(ctx, theme, width)
  drawCornerDecorations(ctx, theme, width, height)

  // 트렌드 배지 (좌상단)
  drawTrendBadge(ctx, theme, blogPost)

  // 날짜 + 뉴스 카운트 (우상단)
  drawTopRight(ctx, theme, blogPost, width)

  // 카테고리 레이블
  if (blogPost.adsenseCategory) {
    drawCategoryLabel(ctx, theme, blogPost.adsenseCategory, width)
  }

  // 메인 제목
  drawTitle(ctx, theme, blogPost.title, width, height)

  // 하단 메타 바
  drawBottomBar(ctx, theme, blogPost, width, height)

  const filename = outputPath || path.join(
    outputDir,
    `${blogPost.date || today()}_${sanitize(blogPost.keyword || 'post')}.png`,
  )

  fs.writeFileSync(filename, canvas.toBuffer('image/png'))
  logger.info(`가로 썸네일 생성: ${filename}`)
  return filename
}

/**
 * Instagram/TikTok용 세로형 썸네일 (1080×1920) — v2
 * 업그레이드: 3단 구성 + 트렌드 화살표 + CTA 버튼 강화
 */
export async function generateVerticalThumbnail(blogPost, outputPath = null) {
  const vW = 1080
  const vH = 1920
  ensureDir(outputDir)

  const theme = THEMES[Math.floor(Math.random() * THEMES.length)]
  const canvas = createCanvas(vW, vH)
  const ctx = canvas.getContext('2d')

  drawBackground(ctx, theme, vW, vH)
  drawGridPattern(ctx, theme, vW, vH)

  // 상단 배지 영역 (배경 블록)
  ctx.fillStyle = theme.accent + 'cc'
  ctx.fillRect(0, 0, vW, 160)

  ctx.fillStyle = '#ffffff'
  ctx.font = 'bold 52px sans-serif'
  ctx.textAlign = 'center'
  ctx.fillText(`🔥 ${today()} 오늘의 핫이슈`, vW / 2, 105)

  // 트렌드 화살표 (상승 시)
  if (blogPost.trendDirection === 'rising') {
    drawRisingArrow(ctx, theme, vW, 200)
  }

  // 키워드 강조 블록
  const keyBgY = 220
  ctx.fillStyle = theme.accent
  roundRect(ctx, 60, keyBgY, vW - 120, 120, 20)
  ctx.fill()
  ctx.fillStyle = '#ffffff'
  ctx.font = 'bold 64px sans-serif'
  ctx.textAlign = 'center'
  ctx.fillText(`#${(blogPost.keyword || '').slice(0, 18)}`, vW / 2, keyBgY + 78)

  // 제목 텍스트
  ctx.fillStyle = '#ffffff'
  ctx.font = 'bold 60px sans-serif'
  ctx.textAlign = 'center'
  wrapTextCenter(ctx, blogPost.title, vW / 2, 440, vW - 100, 74)

  // 구분선
  ctx.fillStyle = theme.accent + '88'
  ctx.fillRect(80, 900, vW - 160, 3)

  // 미리보기 포인트 (있는 경우)
  if (blogPost.previewPoints?.length) {
    ctx.fillStyle = theme.subText
    ctx.font = '44px sans-serif'
    ctx.textAlign = 'left'
    blogPost.previewPoints.slice(0, 3).forEach((point, i) => {
      ctx.fillText(`✅ ${point.slice(0, 28)}`, 80, 960 + i * 72)
    })
  } else {
    ctx.fillStyle = theme.subText
    ctx.font = '46px sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText('블로그에서 전체 내용 확인', vW / 2, 980)
    ctx.fillText(`📖 읽기 ${blogPost.readingTime || '5분'}`, vW / 2, 1050)
  }

  // 하단 CTA 버튼
  const ctaY = vH - 300
  ctx.fillStyle = theme.accent
  roundRect(ctx, 60, ctaY, vW - 120, 140, 30)
  ctx.fill()

  ctx.fillStyle = '#ffffff'
  ctx.font = 'bold 54px sans-serif'
  ctx.textAlign = 'center'
  ctx.fillText('👆 프로필 링크로 전체 보기', vW / 2, ctaY + 88)

  // 브랜드 하단
  ctx.fillStyle = theme.accent + '44'
  ctx.fillRect(0, vH - 120, vW, 120)
  ctx.fillStyle = '#ffffff'
  ctx.font = '36px sans-serif'
  ctx.textAlign = 'center'
  ctx.fillText(`${today()} | AI 자동 생성 콘텐츠`, vW / 2, vH - 42)

  const filename = outputPath || path.join(
    outputDir,
    `${blogPost.date || today()}_${sanitize(blogPost.keyword || 'post')}_vertical.png`,
  )

  fs.writeFileSync(filename, canvas.toBuffer('image/png'))
  logger.info(`세로 썸네일 생성: ${filename}`)
  return filename
}

// ─────────────── 내부 렌더링 헬퍼 ───────────────

function drawBackground(ctx, theme, w, h) {
  if (theme.bg.type === 'gradient') {
    const grad = ctx.createLinearGradient(0, 0, w, h)
    theme.bg.colors.forEach((c, i) => grad.addColorStop(i / (theme.bg.colors.length - 1), c))
    ctx.fillStyle = grad
  } else {
    ctx.fillStyle = theme.bg.color
  }
  ctx.fillRect(0, 0, w, h)
}

function drawGridPattern(ctx, theme, w, h) {
  ctx.strokeStyle = theme.text + '08'
  ctx.lineWidth = 1
  for (let x = 0; x < w; x += 60) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke() }
  for (let y = 0; y < h; y += 60) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke() }
}

function drawTopAccentLine(ctx, theme, w) {
  const grad = ctx.createLinearGradient(0, 0, w, 0)
  grad.addColorStop(0, theme.accent)
  grad.addColorStop(0.5, theme.accent2)
  grad.addColorStop(1, theme.accent)
  ctx.fillStyle = grad
  ctx.fillRect(0, 0, w, 10)
}

function drawCornerDecorations(ctx, theme, w, h) {
  ctx.beginPath()
  ctx.arc(w - 80, -40, 220, 0, Math.PI * 2)
  ctx.fillStyle = theme.accent + '18'
  ctx.fill()

  ctx.beginPath()
  ctx.arc(60, h + 20, 170, 0, Math.PI * 2)
  ctx.fillStyle = theme.accent2 + '12'
  ctx.fill()
}

function drawTrendBadge(ctx, theme, post) {
  const trendLabel = post.trendDirection === 'rising' ? '🚀 급상승' : '🔥 HOT'
  const rankText = post.rank ? `#${post.rank} ` : ''
  const badgeText = `${rankText}${trendLabel}`

  ctx.font = 'bold 26px sans-serif'
  const tw = ctx.measureText(badgeText).width

  ctx.fillStyle = theme.badgeBg
  roundRect(ctx, 30, 30, tw + 50, 52, 26)
  ctx.fill()

  ctx.fillStyle = '#ffffff'
  ctx.textAlign = 'left'
  ctx.fillText(badgeText, 55, 65)
}

function drawTopRight(ctx, theme, post, w) {
  ctx.fillStyle = theme.subText
  ctx.font = '24px sans-serif'
  ctx.textAlign = 'right'
  const dateStr = post.date || today()
  const newsCount = post.newsContext?.length || 0
  const infoText = newsCount > 0 ? `📰 관련뉴스 ${newsCount}건 | 📅 ${dateStr}` : `📅 ${dateStr}`
  ctx.fillText(infoText, w - 30, 60)
}

function drawCategoryLabel(ctx, theme, category, w) {
  ctx.fillStyle = theme.accent2 + 'cc'
  ctx.font = 'bold 22px sans-serif'
  ctx.textAlign = 'right'
  ctx.fillText(`[${category}]`, w - 30, 100)
}

function drawTitle(ctx, theme, title, w, h) {
  ctx.fillStyle = theme.text
  ctx.textAlign = 'left'
  const maxW = w - 100
  let fontSize = 64
  ctx.font = `bold ${fontSize}px sans-serif`

  while (ctx.measureText(title).width > maxW * 1.8 && fontSize > 36) {
    fontSize -= 4
    ctx.font = `bold ${fontSize}px sans-serif`
  }

  wrapText(ctx, title, 50, h / 2 - 50, maxW, fontSize + 18)
}

function drawBottomBar(ctx, theme, post, w, h) {
  ctx.fillStyle = '#00000044'
  ctx.fillRect(0, h - 80, w, 80)

  ctx.fillStyle = theme.subText
  ctx.font = '24px sans-serif'
  ctx.textAlign = 'left'
  const readTime = post.readingTime || '5분'
  const cpc = post.estimatedCPC ? `| AdSense: $${post.estimatedCPC}/클릭 ` : ''
  ctx.fillText(`📅 ${post.date || today()}   🕐 ${readTime} 읽기   ${cpc}✍️ AI 생성`, 30, h - 28)

  ctx.fillStyle = theme.accent
  ctx.font = 'bold 22px sans-serif'
  ctx.textAlign = 'right'
  ctx.fillText('▶ 블로그에서 전체보기', w - 30, h - 28)
}

function drawRisingArrow(ctx, theme, w, y) {
  ctx.fillStyle = theme.accent
  ctx.font = 'bold 70px sans-serif'
  ctx.textAlign = 'center'
  ctx.fillText('📈 지금 급상승 중!', w / 2, y)
}

function wrapText(ctx, text, x, y, maxWidth, lineHeight) {
  let line = ''
  let currentY = y
  for (let i = 0; i < text.length; i++) {
    const testLine = line + text[i]
    if (ctx.measureText(testLine).width > maxWidth && line !== '') {
      ctx.fillText(line, x, currentY)
      line = text[i]
      currentY += lineHeight
    } else {
      line = testLine
    }
  }
  if (line) ctx.fillText(line, x, currentY)
}

function wrapTextCenter(ctx, text, cx, y, maxWidth, lineHeight) {
  let line = ''
  let currentY = y
  for (let i = 0; i < text.length; i++) {
    const testLine = line + text[i]
    if (ctx.measureText(testLine).width > maxWidth && line !== '') {
      ctx.fillText(line, cx, currentY)
      line = text[i]
      currentY += lineHeight
    } else {
      line = testLine
    }
  }
  if (line) ctx.fillText(line, cx, currentY)
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.lineTo(x + w - r, y)
  ctx.quadraticCurveTo(x + w, y, x + w, y + r)
  ctx.lineTo(x + w, y + h - r)
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h)
  ctx.lineTo(x + r, y + h)
  ctx.quadraticCurveTo(x, y + h, x, y + h - r)
  ctx.lineTo(x, y + r)
  ctx.quadraticCurveTo(x, y, x + r, y)
  ctx.closePath()
}

function ensureDir(dir) {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true })
}

function today() {
  return new Date().toISOString().split('T')[0]
}

function sanitize(str) {
  return str.replace(/[^a-zA-Z0-9가-힣_-]/g, '_').slice(0, 40)
}
