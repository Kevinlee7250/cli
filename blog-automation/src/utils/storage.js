import fs from 'fs'
import path from 'path'
import { config } from '../config.js'
import { logger } from './logger.js'

function ensureDir(dir) {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true })
  }
}

export function savePost(post) {
  ensureDir(config.output.postsDir)
  const filename = `${post.date}_${sanitizeFilename(post.title)}.json`
  const filepath = path.join(config.output.postsDir, filename)
  fs.writeFileSync(filepath, JSON.stringify(post, null, 2), 'utf-8')
  logger.info(`포스트 저장 완료: ${filepath}`)
  return filepath
}

export function saveSocialContent(content, keyword) {
  ensureDir(config.output.socialDir)
  const filename = `${content.date}_${sanitizeFilename(keyword)}_social.json`
  const filepath = path.join(config.output.socialDir, filename)
  fs.writeFileSync(filepath, JSON.stringify(content, null, 2), 'utf-8')
  logger.info(`SNS 콘텐츠 저장 완료: ${filepath}`)
  return filepath
}

export function loadRunHistory() {
  const historyFile = path.resolve('./output/run-history.json')
  if (!fs.existsSync(historyFile)) return []
  try {
    return JSON.parse(fs.readFileSync(historyFile, 'utf-8'))
  } catch {
    return []
  }
}

export function saveRunHistory(entry) {
  ensureDir('./output')
  const historyFile = path.resolve('./output/run-history.json')
  const history = loadRunHistory()
  history.unshift({ ...entry, savedAt: new Date().toISOString() })
  // 최근 100개만 유지
  const trimmed = history.slice(0, 100)
  fs.writeFileSync(historyFile, JSON.stringify(trimmed, null, 2), 'utf-8')
}

function sanitizeFilename(name) {
  return name
    .replace(/[<>:"/\\|?*]/g, '')
    .replace(/\s+/g, '_')
    .slice(0, 50)
}
