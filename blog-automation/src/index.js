#!/usr/bin/env node
/**
 * 블로그 자동화 시스템 메인 오케스트레이터
 *
 * 실행 방법:
 *   node src/index.js --once      # 즉시 1회 실행
 *   node src/index.js --schedule  # 스케줄러 실행 (기본: 매일 오전 8시)
 *   node src/index.js             # 즉시 실행 후 종료
 */

import cron from 'node-cron'
import { config, validateConfig } from './config.js'
import { logger } from './utils/logger.js'
import { savePost, saveSocialContent, saveRunHistory } from './utils/storage.js'
import { analyzeHotKeywords } from './scrapers/keyword-analyzer.js'
import { generateBlogPost } from './generators/blog-content.js'
import { generateSocialContent } from './generators/social-content.js'
import { generateThumbnail, generateVerticalThumbnail } from './generators/thumbnail.js'
import { publishToBlogger } from './publishers/blogger.js'
import { publishToInstagram } from './publishers/instagram.js'
import { publishToThreads } from './publishers/threads.js'
import { publishToTikTok } from './publishers/tiktok.js'

const args = process.argv.slice(2)
const isScheduleMode = args.includes('--schedule')
const isOnceMode = args.includes('--once') || !isScheduleMode

/**
 * 메인 자동화 파이프라인
 * 1. 키워드 수집 및 분석
 * 2. 블로그 포스트 생성
 * 3. 썸네일 생성 (가로 + 세로)
 * 4. SNS 콘텐츠 생성
 * 5. 각 플랫폼 게시
 */
async function runAutomation() {
  const runStart = Date.now()
  logger.info('━'.repeat(60))
  logger.info('🚀 블로그 자동화 시스템 실행 시작')
  logger.info(`실행 시각: ${new Date().toLocaleString('ko-KR')}`)
  logger.info('━'.repeat(60))

  const results = {
    date: new Date().toISOString().split('T')[0],
    keywords: [],
    posts: [],
    errors: [],
  }

  try {
    // ── Step 1: 키워드 분석 ──
    logger.info('\n📊 [1/5] 오늘의 핫 키워드 수집 중...')
    const hotKeywords = await analyzeHotKeywords()

    if (!hotKeywords.length) {
      logger.warn('수집된 키워드가 없습니다. 실행을 종료합니다.')
      return results
    }

    results.keywords = hotKeywords.map(k => k.keyword)
    logger.info(`✅ ${hotKeywords.length}개 키워드 분석 완료: ${results.keywords.join(', ')}`)

    // ── 각 키워드별 처리 ──
    for (let i = 0; i < hotKeywords.length; i++) {
      const keywordData = hotKeywords[i]
      const postResult = { keyword: keywordData.keyword, status: 'pending' }

      logger.info(`\n${'─'.repeat(50)}`)
      logger.info(`🔑 키워드 ${i + 1}/${hotKeywords.length}: "${keywordData.keyword}"`)
      logger.info('─'.repeat(50))

      try {
        // ── Step 2: 블로그 포스트 생성 ──
        logger.info('✍️  [2/5] 블로그 포스트 생성 중...')
        const blogPost = await generateBlogPost(keywordData)
        const postPath = savePost(blogPost)
        postResult.blogPost = { title: blogPost.title, savedAt: postPath }

        // ── Step 3: 썸네일 생성 ──
        logger.info('🖼️  [3/5] 썸네일 생성 중...')
        const [thumbnailPath, verticalPath] = await Promise.all([
          generateThumbnail(blogPost).catch(e => {
            logger.warn(`가로 썸네일 생성 실패: ${e.message}`)
            return null
          }),
          generateVerticalThumbnail(blogPost).catch(e => {
            logger.warn(`세로 썸네일 생성 실패: ${e.message}`)
            return null
          }),
        ])
        postResult.thumbnails = { horizontal: thumbnailPath, vertical: verticalPath }

        // ── Step 4: Blogger 게시 ──
        logger.info('📝 [4/5] Google Blogger 게시 중...')
        const bloggerResult = await publishToBlogger(blogPost)
        postResult.blogger = bloggerResult

        const blogUrl = bloggerResult.url || ''

        // ── Step 5: SNS 콘텐츠 생성 ──
        logger.info('📱 [5/5] SNS 콘텐츠 생성 및 게시 중...')
        const socialContent = await generateSocialContent(blogPost, blogUrl)
        saveSocialContent(socialContent, keywordData.keyword)

        // ── 각 SNS 플랫폼 병렬 게시 ──
        const [instaResult, threadsResult, tiktokResult] = await Promise.allSettled([
          publishToInstagram(socialContent, verticalPath || thumbnailPath),
          publishToThreads(socialContent, thumbnailPath ? null : null),
          publishToTikTok(socialContent),
        ])

        postResult.instagram = instaResult.status === 'fulfilled' ? instaResult.value : { error: instaResult.reason?.message }
        postResult.threads = threadsResult.status === 'fulfilled' ? threadsResult.value : { error: threadsResult.reason?.message }
        postResult.tiktok = tiktokResult.status === 'fulfilled' ? tiktokResult.value : { error: tiktokResult.reason?.message }

        postResult.status = 'completed'
        logPostSummary(keywordData.keyword, blogPost, bloggerResult, postResult)
      } catch (err) {
        postResult.status = 'error'
        postResult.error = err.message
        logger.error(`키워드 "${keywordData.keyword}" 처리 오류: ${err.message}`)
        results.errors.push({ keyword: keywordData.keyword, error: err.message })
      }

      results.posts.push(postResult)

      // API 레이트 리밋 대응 딜레이
      if (i < hotKeywords.length - 1) {
        logger.info('⏳ 다음 포스트 준비 중... (5초)')
        await delay(5000)
      }
    }
  } catch (err) {
    logger.error(`자동화 실행 오류: ${err.message}`)
    results.error = err.message
  }

  const duration = ((Date.now() - runStart) / 1000).toFixed(1)
  logger.info('\n' + '━'.repeat(60))
  logger.info('✅ 자동화 실행 완료!')
  logger.info(`소요 시간: ${duration}초`)
  logger.info(`처리된 키워드: ${results.keywords.length}개`)
  logger.info(`성공: ${results.posts.filter(p => p.status === 'completed').length}개`)
  logger.info(`실패: ${results.errors.length}개`)
  logger.info('━'.repeat(60))

  saveRunHistory(results)
  return results
}

function logPostSummary(keyword, blogPost, bloggerResult, postResult) {
  logger.info(`\n✅ "${keyword}" 처리 완료:`)
  logger.info(`   📄 제목: ${blogPost.title}`)
  if (bloggerResult.url) logger.info(`   🔗 Blogger: ${bloggerResult.url}`)
  if (postResult.instagram?.url) logger.info(`   📸 Instagram: ${postResult.instagram.url}`)
  if (postResult.threads?.url) logger.info(`   🧵 Threads: ${postResult.threads.url}`)
  if (postResult.tiktok?.publishId) logger.info(`   🎵 TikTok: 업로드 완료`)
  if (postResult.thumbnails?.horizontal) logger.info(`   🖼️  썸네일: ${postResult.thumbnails.horizontal}`)
}

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

// ── 진입점 ──
async function main() {
  try {
    validateConfig()
  } catch (err) {
    logger.error(`설정 오류: ${err.message}`)
    process.exit(1)
  }

  if (isScheduleMode) {
    logger.info(`📅 스케줄러 시작: ${config.schedule.cron}`)
    logger.info('   첫 실행은 예약된 시간에 자동으로 진행됩니다.')
    logger.info('   종료하려면 Ctrl+C 를 누르세요.')

    cron.schedule(config.schedule.cron, async () => {
      logger.info('⏰ 스케줄 실행 시작')
      await runAutomation()
    }, { timezone: 'Asia/Seoul' })
  } else {
    await runAutomation()
    process.exit(0)
  }
}

main().catch(err => {
  logger.error(`예상치 못한 오류: ${err.message}`)
  process.exit(1)
})
