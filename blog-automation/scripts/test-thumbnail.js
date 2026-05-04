#!/usr/bin/env node
/**
 * 썸네일 생성 테스트 스크립트
 * 실행: node scripts/test-thumbnail.js
 */
import 'dotenv/config'
import { generateThumbnail, generateVerticalThumbnail } from '../src/generators/thumbnail.js'
import { logger } from '../src/utils/logger.js'

const testPost = {
  title: process.argv[2] || '2026년 인공지능으로 월 500만원 버는 5가지 방법',
  keyword: '인공지능 부업',
  date: new Date().toISOString().split('T')[0],
  readingTime: '7분',
  tags: ['인공지능', 'AI', '부업', '재테크'],
}

logger.info('썸네일 생성 테스트 중...')

try {
  const [horizontal, vertical] = await Promise.all([
    generateThumbnail(testPost),
    generateVerticalThumbnail(testPost),
  ])

  logger.info(`\n✅ 썸네일 생성 완료:`)
  logger.info(`  가로 (1280x720): ${horizontal}`)
  logger.info(`  세로 (1080x1920): ${vertical}`)
  logger.info('\n썸네일 파일을 확인하세요.')
} catch (err) {
  logger.error(`썸네일 생성 실패: ${err.message}`)
  logger.info('\n참고: canvas 패키지가 설치되지 않은 경우 "npm install" 을 먼저 실행하세요.')
  process.exit(1)
}
