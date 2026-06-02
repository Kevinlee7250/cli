#!/usr/bin/env node
/**
 * 블로그 자동화 시스템 메인 오케스트레이터 v2
 *
 * 실행 방법:
 *   node src/index.js              # 즉시 실행 (게시 포함)
 *   node src/index.js --once       # 1회 실행 후 종료
 *   node src/index.js --preview    # 게시 없이 미리보기 리포트만 생성
 *   node src/index.js --schedule   # 스케줄러 모드 (cron)
 *   node src/index.js --draft      # Blogger 임시저장 + SNS 게시 안함
 */

import cron from 'node-cron'
import { config, validateConfig } from './config.js'
import { logger } from './utils/logger.js'
import { savePost, saveSocialContent, saveRunHistory } from './utils/storage.js'
import { estimateAdSenseEarnings, recordRunStats, printEarningsReport } from './utils/analytics.js'
import { generatePreviewReport } from './utils/preview-report.js'
import { analyzeHotKeywords } from './scrapers/keyword-analyzer.js'
import { generateBlogPost } from './generators/blog-content.js'
import { generateSocialContent, getNextOptimalPostingTime } from './generators/social-content.js'
import { generateThumbnail, generateVerticalThumbnail } from './generators/thumbnail.js'
import { publishToBlogger } from './publishers/blogger.js'
import { publishToInstagram } from './publishers/instagram.js'
import { publishToThreads } from './publishers/threads.js'
import { publishToTikTok } from './publishers/tiktok.js'

const args = process.argv.slice(2)
const isScheduleMode = args.includes('--schedule')
const isPreviewMode = args.includes('--preview')
const isDraftMode = args.includes('--draft')

/**
 * 메인 파이프라인 v2
 * 1. 키워드 수집 & AdSense 점수 분석
 * 2. 블로그 포스트 생성 (FAQ + 구조화 데이터)
 * 3. 썸네일 생성 (가로 + 세로, 트렌드 배지 포함)
 * 4. SNS 콘텐츠 생성 (최적 타이밍 포함)
 * 5. AdSense 예상 수익 계산
 * 6. [--preview] 미리보기 HTML 생성 또는 [기본] 플랫폼 게시
 */
async function runAutomation() {
  const runStart = Date.now()
  const modeLabel = isPreviewMode ? '[미리보기 모드]' : isDraftMode ? '[임시저장 모드]' : '[게시 모드]'

  logger.info('━'.repeat(62))
  logger.info(`🚀 블로그 자동화 시스템 v2 시작 ${modeLabel}`)
  logger.info(`실행 시각: ${new Date().toLocaleString('ko-KR')}`)
  logger.info('━'.repeat(62))

  const results = {
    date: new Date().toISOString().split('T')[0],
    mode: isPreviewMode ? 'preview' : isDraftMode ? 'draft' : 'publish',
    keywords: [],
    posts: [],
    errors: [],
    earningsEstimate: null,
  }

  try {
    // ── Step 1: 키워드 분석 ──
    logger.info('\n📊 [1/6] 오늘의 핫 키워드 수집 & AdSense 분석 중...')
    const hotKeywords = await analyzeHotKeywords()

    if (!hotKeywords.length) {
      logger.warn('수집된 키워드가 없습니다.')
      return results
    }

    results.keywords = hotKeywords.map(k => k.keyword)

    // ── 키워드별 처리 ──
    for (let i = 0; i < hotKeywords.length; i++) {
      const keywordData = { ...hotKeywords[i], rank: i + 1 }
      const postResult = { keyword: keywordData.keyword, status: 'pending' }

      logger.info(`\n${'─'.repeat(50)}`)
      logger.info(`🔑 [${i + 1}/${hotKeywords.length}] "${keywordData.keyword}" (점수: ${keywordData.score})`)
      logger.info(`   트렌드: ${keywordData.trendDirection === 'rising' ? '🚀 급상승' : '📊 안정'} | CPC: $${keywordData.estimatedCPC || 0.5}`)

      try {
        // ── Step 2: 블로그 포스트 생성 ──
        logger.info('\n✍️  [2/6] 블로그 포스트 생성 중...')
        const blogPost = { ...await generateBlogPost(keywordData), rank: i + 1 }
        savePost(blogPost)
        postResult.blogPost = { title: blogPost.title, wordCount: blogPost.wordCount, faqCount: blogPost.faq?.length || 0 }

        // ── Step 3: 썸네일 생성 ──
        logger.info('🖼️  [3/6] 썸네일 생성 중...')
        const [thumbnailPath, verticalPath] = await Promise.allSettled([
          generateThumbnail(blogPost),
          generateVerticalThumbnail(blogPost),
        ]).then(res => res.map(r => r.status === 'fulfilled' ? r.value : null))

        postResult.thumbnails = { horizontal: thumbnailPath, vertical: verticalPath }

        // ── Step 4: SNS 콘텐츠 생성 ──
        logger.info('📱 [4/6] SNS 콘텐츠 생성 중...')
        const socialContent = await generateSocialContent(blogPost, '')
        saveSocialContent(socialContent, keywordData.keyword)
        postResult.socialContent = socialContent

        // 최적 게시 시간 안내
        const igTime = getNextOptimalPostingTime('instagram')
        const ttTime = getNextOptimalPostingTime('tiktok')
        logger.info(`   Instagram 다음 게시 적기: ${igTime} | TikTok: ${ttTime}`)

        // ── Step 5: AdSense 수익 추정 ──
        logger.info('💰 [5/6] AdSense 수익 추정 중...')
        const postEarnings = estimateAdSenseEarnings([{ ...blogPost, naverAvgRatio: keywordData.naverAvgRatio }])
        postResult.earnings = postEarnings.posts[0]

        // ── Step 6: 게시 or 미리보기 ──
        if (isPreviewMode) {
          logger.info('👁️  [6/6] 미리보기 모드 — 실제 게시를 건너뜁니다.')
          postResult.status = 'preview'
        } else {
          logger.info('🚀 [6/6] 플랫폼 게시 중...')
          const blogUrl = await publishWithRetry(() => publishToBlogger(blogPost, { isDraft: isDraftMode }))
          postResult.blogger = blogUrl

          if (!isDraftMode) {
            const [instaResult, threadsResult, tiktokResult] = await Promise.allSettled([
              publishWithRetry(() => publishToInstagram(socialContent, verticalPath || thumbnailPath)),
              publishWithRetry(() => publishToThreads(socialContent)),
              publishWithRetry(() => publishToTikTok(socialContent)),
            ])
            postResult.instagram = instaResult.status === 'fulfilled' ? instaResult.value : { error: instaResult.reason?.message }
            postResult.threads = threadsResult.status === 'fulfilled' ? threadsResult.value : { error: threadsResult.reason?.message }
            postResult.tiktok = tiktokResult.status === 'fulfilled' ? tiktokResult.value : { error: tiktokResult.reason?.message }
          }

          postResult.status = 'completed'
          logPostSummary(keywordData.keyword, blogPost, postResult)
        }
      } catch (err) {
        postResult.status = 'error'
        postResult.error = err.message
        logger.error(`"${keywordData.keyword}" 처리 오류: ${err.message}`)
        results.errors.push({ keyword: keywordData.keyword, error: err.message })
      }

      results.posts.push(postResult)

      if (i < hotKeywords.length - 1) {
        logger.info('⏳ 다음 처리까지 5초 대기...')
        await delay(5000)
      }
    }

    // ── 전체 수익 추정 ──
    const completedPosts = results.posts
      .filter(p => p.blogPost)
      .map(p => ({
        keyword: p.keyword,
        adsenseCategory: p.blogPost?.adsenseCategory,
        trendDirection: p.blogPost?.trendDirection,
        naverAvgRatio: hotKeywords.find(k => k.keyword === p.keyword)?.naverAvgRatio,
        estimatedCPC: p.earnings?.estimatedCPC,
      }))

    if (completedPosts.length) {
      results.earningsEstimate = estimateAdSenseEarnings(completedPosts)
      printEarningsReport(results.earningsEstimate)
    }

    // ── 미리보기 리포트 생성 ──
    if (isPreviewMode) {
      const reportPath = generatePreviewReport(results)
      logger.info(`\n📄 미리보기 리포트: ${reportPath}`)
      logger.info('브라우저에서 열어 검토 후, --once 옵션으로 실제 게시하세요.')
    }
  } catch (err) {
    logger.error(`자동화 실행 오류: ${err.message}`)
    results.error = err.message
  }

  const duration = ((Date.now() - runStart) / 1000).toFixed(1)
  logger.info('\n' + '━'.repeat(62))
  logger.info('✅ 자동화 완료!')
  logger.info(`소요 시간: ${duration}초 | 성공: ${results.posts.filter(p => p.status === 'completed' || p.status === 'preview').length}/${results.posts.length}개`)
  logger.info('━'.repeat(62))

  saveRunHistory(results)

  if (results.earningsEstimate) {
    recordRunStats(results, results.earningsEstimate)
  }

  return results
}

/**
 * API 호출 실패 시 지수 백오프 재시도 (최대 3회)
 */
async function publishWithRetry(fn, maxRetries = 3) {
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      return await fn()
    } catch (err) {
      if (attempt === maxRetries) return { error: err.message }
      const waitMs = 2000 * Math.pow(2, attempt - 1)
      logger.warn(`게시 실패 (시도 ${attempt}/${maxRetries}), ${waitMs / 1000}초 후 재시도: ${err.message}`)
      await delay(waitMs)
    }
  }
}

function logPostSummary(keyword, blogPost, postResult) {
  logger.info(`\n✅ "${keyword}" 완료:`)
  logger.info(`   📄 제목: ${blogPost.title}`)
  logger.info(`   📊 FAQ: ${blogPost.faq?.length || 0}개 | 글자수: ${blogPost.wordCount || '?'}자`)
  if (postResult.blogger?.url) logger.info(`   🔗 Blogger: ${postResult.blogger.url}`)
  if (postResult.instagram?.url) logger.info(`   📸 Instagram: ${postResult.instagram.url}`)
  if (postResult.threads?.url) logger.info(`   🧵 Threads: ${postResult.threads.url}`)
  if (postResult.tiktok?.publishId) logger.info(`   🎵 TikTok: 업로드 완료`)
  if (postResult.thumbnails?.horizontal) logger.info(`   🖼️  썸네일: ${postResult.thumbnails.horizontal}`)
  if (postResult.earnings) logger.info(`   💰 예상 일 수익: $${postResult.earnings.estimatedDailyRevenue}`)
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
    logger.info(`📅 스케줄러 모드: ${config.schedule.cron} (KST)`)
    logger.info('   Ctrl+C 로 종료')
    cron.schedule(config.schedule.cron, () => {
      logger.info('⏰ 스케줄 실행 시작')
      runAutomation().catch(err => logger.error(`스케줄 실행 오류: ${err.message}`))
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
