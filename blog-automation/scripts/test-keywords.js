#!/usr/bin/env node
/**
 * 키워드 수집 테스트 스크립트
 * 실행: node scripts/test-keywords.js
 */
import 'dotenv/config'
import { analyzeHotKeywords } from '../src/scrapers/keyword-analyzer.js'
import { logger } from '../src/utils/logger.js'

logger.info('키워드 수집 테스트 시작...')

try {
  const keywords = await analyzeHotKeywords()
  logger.info(`\n수집된 키워드 ${keywords.length}개:`)
  keywords.forEach((k, i) => {
    logger.info(`  ${i + 1}. ${k.keyword} (점수: ${k.score}, 트래픽: ${k.traffic})`)
    if (k.relatedQueries?.length) {
      logger.info(`     연관어: ${k.relatedQueries.slice(0, 3).join(', ')}`)
    }
    if (k.newsContext?.length) {
      logger.info(`     뉴스: ${k.newsContext[0]?.title?.slice(0, 60)}...`)
    }
  })
} catch (err) {
  logger.error(`테스트 실패: ${err.message}`)
  process.exit(1)
}
