import fs from 'fs'
import path from 'path'
import { ADSENSE_CPC } from '../scrapers/keyword-analyzer.js'
import { logger } from './logger.js'

const ANALYTICS_FILE = path.resolve('./output/analytics.json')

/**
 * AdSense 예상 수익 추정 (CPC × CTR × 예상 PV)
 */
export function estimateAdSenseEarnings(posts) {
  const estimates = posts.map(post => {
    const category = post.adsenseCategory
    const cpc = (category && ADSENSE_CPC[category]?.cpc) || 0.5
    const baseTraffic = estimateBaseTraffic(post)
    const ctr = 0.025
    const pageRPM = cpc * ctr * 1000
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
  existing.runs = [entry, ...(existing.runs || [])].slice(0, 90)
  existing.totalPosts = (existing.totalPosts || 0) + entry.postsGenerated
  existing.totalEstimatedRevenue = Math.round(
    ((existing.totalEstimatedRevenue || 0) + (earningsEstimate?.summary?.estimatedDailyRevenue || 0)) * 100
  ) / 100
  saveAnalytics(existing)
  return entry
}

export function printEarningsReport(earningsEstimate) {
  if (!earningsEstimate) return
  const { summary, posts } = earningsEstimate
  logger.info('\n' + '═'.repeat(55))
  logger.info('💰 AdSense 예상 수익 리포트')
  logger.info('═'.repeat(55))
  logger.info(`  포스트 수:      ${summary.totalPosts}개`)
  logger.info(`  평균 CPC:       $${summary.avgCPC}`)
  logger.info(`  오늘 예상:      $${summary.estimatedDailyRevenue}`)
  logger.info(`  월간 예상:      $${summary.estimatedMonthlyRevenue}`)
  logger.info(`  연간 예상:      $${summary.estimatedYearlyRevenue}`)
  logger.info('─'.repeat(55))
  posts.forEach(p => {
    logger.info(`  [${p.category}] ${p.keyword}`)
    logger.info(`    CPC: $${p.estimatedCPC} | PV: ${p.estimatedDailyPV} | 일수익: $${p.estimatedDailyRevenue}`)
  })
  logger.info('═'.repeat(55))
  logger.info('* CTR 2.5% 기준 추정치')
}

function estimateBaseTraffic(post) {
  const mult = post.trendDirection === 'rising' ? 3.0 : post.trendDirection === 'stable' ? 1.5 : 0.8
  const base = Math.round((post.naverAvgRatio || 10) / 100 * 500 * mult)
  return Math.max(base, 50)
}

function summarizePlatforms(posts) {
  const r = { blogger: 0, instagram: 0, threads: 0, tiktok: 0 }
  posts.forEach(p => {
    if (p.blogger?.url) r.blogger++
    if (p.instagram?.url) r.instagram++
    if (p.threads?.url) r.threads++
    if (p.tiktok?.publishId) r.tiktok++
  })
  return r
}

function loadAnalytics() {
  try { if (fs.existsSync(ANALYTICS_FILE)) return JSON.parse(fs.readFileSync(ANALYTICS_FILE, 'utf-8')) } catch {}
  return { runs: [], totalPosts: 0, totalEstimatedRevenue: 0 }
}

function saveAnalytics(data) {
  const dir = path.dirname(ANALYTICS_FILE)
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true })
  fs.writeFileSync(ANALYTICS_FILE, JSON.stringify(data, null, 2), 'utf-8')
}
