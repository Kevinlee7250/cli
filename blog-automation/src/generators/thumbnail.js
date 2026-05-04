import { createCanvas, registerFont } from 'canvas'
import fs from 'fs'
import path from 'path'
import { config } from '../config.js'
import { logger } from '../utils/logger.js'

const { width, height, outputDir } = config.thumbnail

// 썸네일 디자인 테마 모음
const THEMES = [
  {
    name: 'gradient-blue',
    bg: { type: 'gradient', colors: ['#1a1a2e', '#16213e', '#0f3460'] },
    accent: '#e94560',
    text: '#ffffff',
    subText: '#a8b2d8',
  },
  {
    name: 'gradient-green',
    bg: { type: 'gradient', colors: ['#0a0a0a', '#1a2a1a', '#0d3318'] },
    accent: '#00ff88',
    text: '#ffffff',
    subText: '#88ccaa',
  },
  {
    name: 'gradient-orange',
    bg: { type: 'gradient', colors: ['#1a0a00', '#2d1500', '#4a2000'] },
    accent: '#ff6b35',
    text: '#ffffff',
    subText: '#ffcc99',
  },
  {
    name: 'gradient-purple',
    bg: { type: 'gradient', colors: ['#0d0d1a', '#1a1133', '#2d1b69'] },
    accent: '#c77dff',
    text: '#ffffff',
    subText: '#c0b3e8',
  },
  {
    name: 'clean-white',
    bg: { type: 'solid', color: '#f8f9fa' },
    accent: '#e63946',
    text: '#212529',
    subText: '#495057',
  },
]

/**
 * 블로그 포스트용 썸네일 생성 (1280x720 기본)
 * @param {Object} blogPost - 블로그 포스트 데이터
 * @param {string} outputPath - 저장 경로 (선택)
 * @returns {Promise<string>} 저장된 파일 경로
 */
export async function generateThumbnail(blogPost, outputPath = null) {
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true })
  }

  const theme = THEMES[Math.floor(Math.random() * THEMES.length)]
  const canvas = createCanvas(width, height)
  const ctx = canvas.getContext('2d')

  // 배경 렌더링
  drawBackground(ctx, theme)

  // 장식 요소
  drawDecorations(ctx, theme)

  // 키워드 배지
  if (blogPost.keyword) {
    drawKeywordBadge(ctx, blogPost.keyword, theme)
  }

  // 메인 제목
  drawTitle(ctx, blogPost.title, theme)

  // 하단 메타 정보
  drawMeta(ctx, blogPost, theme)

  // 브랜딩 워터마크
  drawWatermark(ctx, theme)

  const filename = outputPath || path.join(
    outputDir,
    `${blogPost.date || new Date().toISOString().split('T')[0]}_${sanitize(blogPost.keyword || 'post')}.png`,
  )

  const buffer = canvas.toBuffer('image/png')
  fs.writeFileSync(filename, buffer)
  logger.info(`썸네일 생성 완료: ${filename}`)
  return filename
}

/**
 * Instagram / TikTok용 세로형 썸네일 (1080x1920)
 */
export async function generateVerticalThumbnail(blogPost, outputPath = null) {
  const vWidth = 1080
  const vHeight = 1920

  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true })
  }

  const theme = THEMES[Math.floor(Math.random() * THEMES.length)]
  const canvas = createCanvas(vWidth, vHeight)
  const ctx = canvas.getContext('2d')

  drawBackgroundCustom(ctx, theme, vWidth, vHeight)
  drawDecorationsVertical(ctx, theme, vWidth, vHeight)

  // 상단 후킹 텍스트
  ctx.fillStyle = theme.accent
  ctx.font = 'bold 60px sans-serif'
  ctx.textAlign = 'center'
  wrapText(ctx, '📢 지금 핫한 이슈', vWidth / 2, 300, vWidth - 120, 70)

  // 키워드 강조
  if (blogPost.keyword) {
    ctx.fillStyle = theme.accent
    ctx.font = 'bold 80px sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText(`#${blogPost.keyword}`, vWidth / 2, 500)
  }

  // 제목
  ctx.fillStyle = theme.text
  ctx.font = 'bold 65px sans-serif'
  ctx.textAlign = 'center'
  wrapText(ctx, blogPost.title, vWidth / 2, 700, vWidth - 100, 80)

  // 하단 CTA
  drawCTABox(ctx, theme, vWidth, vHeight)

  const filename = outputPath || path.join(
    outputDir,
    `${blogPost.date || new Date().toISOString().split('T')[0]}_${sanitize(blogPost.keyword || 'post')}_vertical.png`,
  )

  const buffer = canvas.toBuffer('image/png')
  fs.writeFileSync(filename, buffer)
  logger.info(`세로 썸네일 생성 완료: ${filename}`)
  return filename
}

// ──────────────────────────── 내부 렌더링 함수 ────────────────────────────

function drawBackground(ctx, theme) {
  if (theme.bg.type === 'gradient') {
    const grad = ctx.createLinearGradient(0, 0, width, height)
    theme.bg.colors.forEach((color, i) => {
      grad.addColorStop(i / (theme.bg.colors.length - 1), color)
    })
    ctx.fillStyle = grad
  } else {
    ctx.fillStyle = theme.bg.color
  }
  ctx.fillRect(0, 0, width, height)
}

function drawBackgroundCustom(ctx, theme, w, h) {
  if (theme.bg.type === 'gradient') {
    const grad = ctx.createLinearGradient(0, 0, w, h)
    theme.bg.colors.forEach((color, i) => {
      grad.addColorStop(i / (theme.bg.colors.length - 1), color)
    })
    ctx.fillStyle = grad
  } else {
    ctx.fillStyle = theme.bg.color
  }
  ctx.fillRect(0, 0, w, h)
}

function drawDecorations(ctx, theme) {
  // 우상단 원형 장식
  ctx.beginPath()
  ctx.arc(width - 100, -50, 200, 0, Math.PI * 2)
  ctx.fillStyle = theme.accent + '20'
  ctx.fill()

  // 좌하단 원형 장식
  ctx.beginPath()
  ctx.arc(80, height + 30, 160, 0, Math.PI * 2)
  ctx.fillStyle = theme.accent + '15'
  ctx.fill()

  // 상단 강조 라인
  ctx.fillStyle = theme.accent
  ctx.fillRect(0, 0, width, 8)

  // 격자 패턴 (은은하게)
  ctx.strokeStyle = theme.text + '08'
  ctx.lineWidth = 1
  for (let x = 0; x < width; x += 60) {
    ctx.beginPath()
    ctx.moveTo(x, 0)
    ctx.lineTo(x, height)
    ctx.stroke()
  }
  for (let y = 0; y < height; y += 60) {
    ctx.beginPath()
    ctx.moveTo(0, y)
    ctx.lineTo(width, y)
    ctx.stroke()
  }
}

function drawDecorationsVertical(ctx, theme, w, h) {
  ctx.beginPath()
  ctx.arc(w / 2, h - 300, 400, 0, Math.PI * 2)
  ctx.fillStyle = theme.accent + '15'
  ctx.fill()

  ctx.fillStyle = theme.accent
  ctx.fillRect(0, 0, w, 10)
  ctx.fillRect(0, h - 10, w, 10)
}

function drawKeywordBadge(ctx, keyword, theme) {
  const badgeX = 60
  const badgeY = 60
  const text = `# ${keyword}`

  ctx.font = 'bold 28px sans-serif'
  const textWidth = ctx.measureText(text).width

  ctx.fillStyle = theme.accent
  roundRect(ctx, badgeX, badgeY, textWidth + 40, 48, 24)
  ctx.fill()

  ctx.fillStyle = '#ffffff'
  ctx.textAlign = 'left'
  ctx.fillText(text, badgeX + 20, badgeY + 32)
}

function drawTitle(ctx, title, theme) {
  ctx.fillStyle = theme.text
  ctx.textAlign = 'left'

  const maxWidth = width - 120
  const startY = height / 2 - 60

  // 제목이 길면 폰트 크기 자동 조절
  let fontSize = 62
  ctx.font = `bold ${fontSize}px sans-serif`
  while (ctx.measureText(title).width > maxWidth * 1.5 && fontSize > 36) {
    fontSize -= 4
    ctx.font = `bold ${fontSize}px sans-serif`
  }

  wrapText(ctx, title, 60, startY, maxWidth, fontSize + 16)
}

function drawMeta(ctx, blogPost, theme) {
  const y = height - 70
  ctx.fillStyle = theme.subText
  ctx.font = '26px sans-serif'
  ctx.textAlign = 'left'

  const date = blogPost.date || new Date().toISOString().split('T')[0]
  const readTime = blogPost.readingTime || '5분'
  ctx.fillText(`📅 ${date}   🕐 읽기 ${readTime}   ✍️ AI 생성 콘텐츠`, 60, y)
}

function drawWatermark(ctx, theme) {
  ctx.fillStyle = theme.accent + 'cc'
  ctx.font = 'bold 22px sans-serif'
  ctx.textAlign = 'right'
  ctx.fillText('▶ 블로그에서 전체보기', width - 60, height - 30)
}

function drawCTABox(ctx, theme, w, h) {
  ctx.fillStyle = theme.accent
  roundRect(ctx, 60, h - 250, w - 120, 120, 20)
  ctx.fill()

  ctx.fillStyle = '#ffffff'
  ctx.font = 'bold 48px sans-serif'
  ctx.textAlign = 'center'
  ctx.fillText('👉 블로그에서 전체 내용 확인', w / 2, h - 175)
}

function wrapText(ctx, text, x, y, maxWidth, lineHeight) {
  const words = text.split('')
  let line = ''
  let currentY = y

  // 한글은 글자 단위로 줄바꿈
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

function sanitize(str) {
  return str.replace(/[^a-zA-Z0-9가-힣_-]/g, '_').slice(0, 40)
}
