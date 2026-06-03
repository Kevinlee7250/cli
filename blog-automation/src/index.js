#!/usr/bin/env node
/**
 * 블로그 자동화 시스템 메인 오케스트레이터 v2
 *
 * node src/index.js              # 즉시 실행 (게시)
 * node src/index.js --preview    # 미리보기 리포트만
 * node src/index.js --draft      # Blogger 임시저장 + SNS 건너뜀
 * node src/index.js --schedule   # 스케줄러 모드
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
import { factCheckBlogPost } from './generators/fact-checker.js'

const args = process.argv.slice(2)
const isScheduleMode = args.includes('--schedule')
const isPreviewMode = args.includes('--preview')
const isDraftMode = args.includes('--draft')

async function runAutomation() {
  const runStart = Date.now()
  const modeLabel = isPreviewMode ? '[미리보기]' : isDraftMode ? '[임시저장]' : '[게시]'

  logger.info('━'.repeat(62))
  logger.info(`🚀 블로그 자동화 시스템 v2 ${modeLabel} — ${new Date().toLocaleString('ko-KR')}`)
  logger.info('━'.repeat(62))

  const results = {
    date: new Date().toISOString().split('T')[0],
    mode: isPreviewMode ? 'preview' : isDraftMode ? 'draft' : 'publish',
    keywords: [], posts: [], errors: [], earningsEstimate: null,
  }

  try {
    logger.info('\n📊 [1/6] 오늘의 핫 키워드 수집 & AdSense 분석 중...')
    const hotKeywords = await analyzeHotKeywords()
    if (!hotKeywords.length) { logger.warn('수집된 키워드가 없습니다.'); return results }
    results.keywords = hotKeywords.map(k => k.keyword)

    for (let i = 0; i < hotKeywords.length; i++) {
      const keywordData = { ...hotKeywords[i], rank: i + 1 }
      const postResult = { keyword: keywordData.keyword, status: 'pending' }

      logger.info(`\n${'─'.repeat(50)}`)
      logger.info(`🔑 [${i + 1}/${hotKeywords.length}] "${keywordData.keyword}" | 트렌드: ${keywordData.trendDirection === 'rising' ? '🚀 급상승' : '📊 안정'} | CPC: $${keywordData.estimatedCPC || 0.5}`)

      try {
        logger.info('✍️  [2/7] 블로그 포스트 생성 중...')
        const rawPost = { ...await generateBlogPost(keywordData), rank: i + 1 }

        logger.info('🔍 [3/7] 팩트체크 중...')
        const blogPost = await factCheckBlogPost(rawPost)
        savePost(blogPost)
        postResult.blogPost = { title: blogPost.title, wordCount: blogPost.wordCount, faqCount: blogPost.faq?.length || 0, factCheck: blogPost.factCheck }

        logger.info('🖼️  [4/7] 썸네일 생성 중...')
        const [thumbnailPath, verticalPath] = await Promise.allSettled([
          generateThumbnail(blogPost),
          generateVerticalThumbnail(blogPost),
        ]).then(res => res.map(r => r.status === 'fulfilled' ? r.value : null))
        postResult.thumbnails = { horizontal: thumbnailPath, vertical: verticalPath }

        logger.info('📱 [5/7] SNS 콘텐츠 생성 중...')
        const socialContent = await generateSocialContent(blogPost, '')
        saveSocialContent(socialContent, keywordData.keyword)
        postResult.socialContent = socialContent
        logger.info(`   IG 최적 게시: ${getNextOptimalPostingTime('instagram')} | TikTok: ${getNextOptimalPostingTime('tiktok')}`)

        logger.info('💰 [6/7] AdSense 수익 추정 중...')
        const postEarnings = estimateAdSenseEarnings([{ ...blogPost, naverAvgRatio: keywordData.naverAvgRatio }])
        postResult.earnings = postEarnings.posts[0]

        if (isPreviewMode) {
          logger.info('👁️  [7/7] 미리보기 모드 — 게시 건너뜀')
          postResult.status = 'preview'
        } else {
          logger.info('🚀 [7/7] 플랫폼 게시 중...')
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
      if (i < hotKeywords.length - 1) { logger.info('⏳ 5초 대기...'); await delay(5000) }
    }

    const completedPosts = results.posts.filter(p => p.blogPost).map(p => ({
      keyword: p.keyword, adsenseCategory: p.blogPost?.adsenseCategory,
      trendDirection: p.blogPost?.trendDirection,
      naverAvgRatio: hotKeywords.find(k => k.keyword === p.keyword)?.naverAvgRatio,
      estimatedCPC: p.earnings?.estimatedCPC,
    }))
    if (completedPosts.length) {
      results.earningsEstimate = estimateAdSenseEarnings(completedPosts)
      printEarningsReport(results.earningsEstimate)
    }

    if (isPreviewMode) {
      const reportPath = generatePreviewReport(results)
      logger.info(`\n📄 미리보기 리포트: ${reportPath}`)
    }
  } catch (err) {
    logger.error(`자동화 실행 오류: ${err.message}`)
    results.error = err.message
  }

  const duration = ((Date.now() - runStart) / 1000).toFixed(1)
  logger.info('\n' + '━'.repeat(62))
  logger.info(`✅ 완료! ${duration}초 | 성공: ${results.posts.filter(p => ['completed', 'preview'].includes(p.status)).length}/${results.posts.length}`)
  logger.info('━'.repeat(62))

  saveRunHistory(results)
  if (results.earningsEstimate) recordRunStats(results, results.earningsEstimate)
  return results
}

async function publishWithRetry(fn, maxRetries = 3) {
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try { return await fn() } catch (err) {
      if (attempt === maxRetries) return { error: err.message }
      const waitMs = 2000 * Math.pow(2, attempt - 1)
      logger.warn(`게시 실패 (시도 ${attempt}/${maxRetries}), ${waitMs / 1000}초 후 재시도`)
      await delay(waitMs)
    }
  }
}

function logPostSummary(keyword, blogPost, r) {
  logger.info(`\n✅ "${keyword}" 완료:`)
  const fc = blogPost.factCheck
  const fcLabel = fc ? (fc.issueCount > 0 ? ` | 팩트수정 ${fc.issueCount}건` : ' | 팩트✅') : ''
  logger.info(`   📄 ${blogPost.title} | FAQ: ${blogPost.faq?.length || 0}개 | ${blogPost.wordCount || '?'}자${fcLabel}`)
  if (r.blogger?.url) logger.info(`   🔗 ${r.blogger.url}`)
  if (r.instagram?.url) logger.info(`   📸 ${r.instagram.url}`)
  if (r.threads?.url) logger.info(`   🧵 ${r.threads.url}`)
  if (r.tiktok?.publishId) logger.info(`   🎵 TikTok 업로드 완료`)
  if (r.earnings) logger.info(`   💰 일 수익: $${r.earnings.estimatedDailyRevenue}`)
}

function delay(ms) { return new Promise(resolve => setTimeout(resolve, ms)) }

async function main() {
  try { validateConfig() } catch (err) { logger.error(`설정 오류: ${err.message}`); process.exit(1) }

  if (isScheduleMode) {
    logger.info(`📅 스케줄러: ${config.schedule.cron} (KST)`)
    cron.schedule(config.schedule.cron, () => {
      runAutomation().catch(err => logger.error(`스케줄 오류: ${err.message}`))
    }, { timezone: 'Asia/Seoul' })
  } else {
    await runAutomation()
    process.exit(0)
  }
}

main().catch(err => { logger.error(`오류: ${err.message}`); process.exit(1) })
