import 'dotenv/config'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

export const config = {
  anthropic: {
    apiKey: process.env.ANTHROPIC_API_KEY,
    model: process.env.CLAUDE_MODEL || 'claude-sonnet-4-6',
  },

  naver: {
    clientId: process.env.NAVER_CLIENT_ID,
    clientSecret: process.env.NAVER_CLIENT_SECRET,
    datalabUrl: 'https://openapi.naver.com/v1/datalab/search',
    searchUrl: 'https://openapi.naver.com/v1/search',
  },

  google: {
    clientId: process.env.GOOGLE_CLIENT_ID,
    clientSecret: process.env.GOOGLE_CLIENT_SECRET,
    refreshToken: process.env.GOOGLE_REFRESH_TOKEN,
    tokenUrl: 'https://oauth2.googleapis.com/token',
    trendsUrl: 'https://trends.google.com/trends/trendingsearches/daily/rss',
    country: process.env.TREND_COUNTRY || 'KR',
  },

  blogger: {
    blogId: process.env.BLOGGER_BLOG_ID,
    apiUrl: 'https://www.googleapis.com/blogger/v3',
  },

  instagram: {
    accessToken: process.env.INSTAGRAM_ACCESS_TOKEN,
    accountId: process.env.INSTAGRAM_ACCOUNT_ID,
    apiUrl: 'https://graph.instagram.com/v21.0',
  },

  threads: {
    accessToken: process.env.THREADS_ACCESS_TOKEN,
    userId: process.env.THREADS_USER_ID,
    handle: process.env.THREADS_HANDLE || '',
    apiUrl: 'https://graph.threads.net/v1.0',
  },

  tiktok: {
    accessToken: process.env.TIKTOK_ACCESS_TOKEN,
    openId: process.env.TIKTOK_OPEN_ID,
    apiUrl: 'https://open.tiktokapis.com/v2',
  },

  content: {
    language: process.env.CONTENT_LANGUAGE || 'ko',
    postsPerRun: parseInt(process.env.POSTS_PER_RUN || '3', 10),
  },

  thumbnail: {
    width: parseInt(process.env.THUMBNAIL_WIDTH || '1280', 10),
    height: parseInt(process.env.THUMBNAIL_HEIGHT || '720', 10),
    outputDir: path.resolve(__dirname, '..', process.env.THUMBNAIL_OUTPUT_DIR || './output/thumbnails'),
  },

  schedule: {
    cron: process.env.SCHEDULE_CRON || '0 8 * * *',
  },

  output: {
    postsDir: path.resolve(__dirname, '..', './output/posts'),
    socialDir: path.resolve(__dirname, '..', './output/social'),
    thumbnailsDir: path.resolve(__dirname, '..', './output/thumbnails'),
  },

  log: {
    level: process.env.LOG_LEVEL || 'info',
    file: path.resolve(__dirname, '..', process.env.LOG_FILE || './logs/automation.log'),
  },
}

export function validateConfig() {
  const required = [
    ['ANTHROPIC_API_KEY', config.anthropic.apiKey],
  ]
  const missing = required.filter(([, val]) => !val).map(([key]) => key)
  if (missing.length > 0) {
    throw new Error(`필수 환경 변수가 설정되지 않았습니다: ${missing.join(', ')}\n.env.example 파일을 참고하여 .env 파일을 설정하세요.`)
  }
}
