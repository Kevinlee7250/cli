import fs from 'fs'
import path from 'path'
import { ADSENSE_CPC } from '../scrapers/keyword-analyzer.js'
import { logger } from './logger.js'

const ANALYTICS_FILE = path.resolve('./output/analytics.json')

/**
 * AdSense 예상 수익 추정
 * 포스트 발행 후 예상 일일/월간 수익을 CPC와 예상 트래픽으로 계산
 */
export function estimateAdSenseEarnings(posts) {
  const estimates = posts.map(post => {
    const category = post.adsenseCategory
    const cpc = (category && ADSENSE_CPC[category]?.cpc) || 0.5

    // 트렌드에 따른 예상 트래픽
    const baseTraffic = estimateBaseTraffic(post)
    const ctr = 0.025 // 평균 CTR 2.5%
    const pageRPM = cpc * ctr * 1000 // 1000 PV당 수익

    return {
      keyword: post.keyword,
      title: post.title,
      category: category || '일반',
      estimatedCPC: cpc,
      estimatedDailyPV: baseTraffic,
      estimatedDailyClicks: Math.round(baseTraffic * ctr),
      estimatedDailyRevenue: Math.round(baseTraffic * ctr * cpc * 100) / 100,
      estimatedMonthlyRevenue: Math.round(baseTraffic * ctr * cpc * 30 * 100) / 100,
      pageRPM: Math.round(pageRPM * 100) / 100,
    }
  })

  const totalDaily = estimates.reduce((sum, e) => sum + e.estimatedDailyRevenue, 0)
  const totalMonthly = estimates.reduce((sum, e) => sum + e.estimatedMonthlyRevenue, 0)

  return {
    posts: estimates,
    summary: {
      totalPosts: posts.length,
      estimatedDailyRevenue: Math.round(totalDaily * 100) / 100,
      estimatedMonthlyRevenue: Math.round(totalMonthly * 100) / 100,
      estimatedYearlyRevenue: Math.round(totalMonthly * 12 * 100) / 100,
      avgCPC: Math.round(estimates.reduce((sum, e) => sum + e.estimatedCPC, 0) / estimates.length * 100) / 100,
      currency: 'USD',
    },
  }
}

/**
 * 실행 기록 저장 및 누적 통계
 */
export function recordRunStats(runResult, earningsEstimate) {
  const existing = loadAnalytics()

  const entry = {
    date: new Date().toISOString().split('T')[0],
    runAt: new Date().toISOString(),
    keywords: runResult.keywords || [],
    postsGenerated: runResult.posts?.filter(p => p.status === 'completed').length || 0,
    errors: runResult.errors?.length || 0,
    earnings: earningsEstimate?.summary || {},
    platforms: summarizePlatforms(runResult.posts || []),
  }

  existing.runs = [entry, ...(existing.runs || [])].slice(0, 90) // 최근 90일 유지
  existing.totalPosts = (existing.totalPosts || 0) + entry.postsGenerated
  existing.totalEstimatedRevenue = Math.round(
    ((existing.totalEstimatedRevenue || 0) + (earningsEstimate?.summary?.estimatedDailyRevenue || 0)) * 100,
  ) / 100

  saveAnalytics(existing)
  return entry
}

/**
 * 성과 리포트 출력
 */
export function printEarningsReport(earningsEstimate) {
  if (!earningsEstimate) return

  const { summary, posts } = earningsEstimate
  logger.info('\n' + '═'.repeat(55))
  logger.info('💰 AdSense 예상 수익 리포트')
  logger.info('═'.repeat(55))
  logger.info(`  포스트 수:       ${summary.totalPosts}개`)
  logger.info(`  평균 CPC:        $${summary.avgCPC}`)
  logger.info(`  오늘 예상 수익:  $${summary.estimatedDailyRevenue}`)
  logger.info(`  월간 예상 수익:  $${summary.estimatedMonthlyRevenue}`)
  logger.info(`  연간 예상 수익:  $${summary.estimatedYearlyRevenue}`)
  logger.info('─'.repeat(55))
  posts.forEach(p => {
    logger.info(`  [${p.category}] ${p.keyword}`)
    logger.info(`    CPC: $${p.estimatedCPC} | 일 PV: ${p.estimatedDailyPV} | 일 수익: $${p.estimatedDailyRevenue}`)
  })
  logger.info('═'.repeat(55))
  logger.info('* 예상치는 평균 CTR 2.5% 기준 추정값입니다.')
}

function estimateBaseTraffic(post) {
  const trendMultiplier = post.trendDirection === 'rising' ? 3.0
    : post.trendDirection === 'stable' ? 1.5 : 0.8

  const naverRatio = post.naverAvgRatio || 10
  const base = Math.round((naverRatio / 100) * 500 * trendMultiplier)
  return Math.max(base, 50)
}

function summarizePlatforms(posts) {
  const result = { blogger: 0, instagram: 0, threads: 0, tiktok: 0 }
  posts.forEach(p => {
    if (p.blogger?.url) result.blogger++
    if (p.instagram?.url) result.instagram++
    if (p.threads?.url) result.threads++
    if (p.tiktok?.publishId) result.tiktok++
  })
  return result
}

function loadAnalytics() {
  try {
    if (fs.existsSync(ANALYTICS_FILE)) {
      return JSON.parse(fs.readFileSync(ANALYTICS_FILE, 'utf-8'))
    }
  } catch {}
  return { runs: [], totalPosts: 0, totalEstimatedRevenue: 0 }
}

function saveAnalytics(data) {
  const dir = path.dirname(ANALYTICS_FILE)
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true })
  fs.writeFileSync(ANALYTICS_FILE, JSON.stringify(data, null, 2), 'utf-8')
}
