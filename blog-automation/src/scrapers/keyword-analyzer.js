import { fetchGoogleTrends, fetchGoogleRealtimeTrends, fetchTodayHotTopics } from './google-trends.js'
import { fetchNaverTrends, fetchNaverNews, fetchGoogleNews } from './naver-trends.js'
import { logger } from '../utils/logger.js'
import { config } from '../config.js'

// AdSense CPC 추정치 (카테고리별 클릭당 단가, USD)
export const ADSENSE_CPC = {
  금융: { cpc: 2.5, keywords: ['주식', '코인', '펀드', '보험', '대출', '카드', '금리', '부동산', '청약', 'ETF', '투자'] },
  건강: { cpc: 1.8, keywords: ['다이어트', '운동', '영양제', '병원', '의료', '건강', '질병', '치료', '헬스'] },
  기술: { cpc: 1.5, keywords: ['AI', '인공지능', '스마트폰', '노트북', '게임', '앱', '소프트웨어', '챗GPT', '자동화'] },
  여행: { cpc: 1.2, keywords: ['여행', '항공', '호텔', '숙소', '리조트', '해외여행', '국내여행', '캠핑', '항공권'] },
  교육: { cpc: 1.3, keywords: ['영어', '자격증', '시험', '취업', '학원', '온라인강의', '코딩', '자기계발'] },
  쇼핑: { cpc: 0.9, keywords: ['할인', '세일', '쿠폰', '가전', '가구', '패션', '명품', '브랜드'] },
  부동산: { cpc: 2.8, keywords: ['아파트', '분양', '임대', '전세', '월세', '매매', '청약', '재건축'] },
  법률: { cpc: 3.2, keywords: ['변호사', '소송', '법률', '이혼', '상속', '계약', '손해배상'] },
}

/**
 * Google + 네이버 트렌드 통합 분석
 * 업그레이드: 트렌드 방향성 가중치 + AdSense CPC 추정 + 상승률 보너스
 */
export async function analyzeHotKeywords() {
  logger.info('=== 오늘의 핫 키워드 분석 시작 (v2) ===')

  // 1순위: 오늘 실제 핫이슈 (Google News RSS → Claude 선정)
  const hotTopics = await fetchTodayHotTopics(config.content.postsPerRun)
  if (hotTopics.length >= config.content.postsPerRun) {
    const enriched = await enrichWithAdSense(hotTopics)
    logger.info('=== 핫 키워드 분석 완료 (오늘의 실시간 이슈 기반) ===')
    enriched.forEach((k, i) => {
      const arrow = k.trendDirection === 'rising' ? '🚀' : '📊'
      logger.info(`  ${i + 1}. ${k.keyword} ${arrow} (CPC: $${k.estimatedDailyCPC?.cpc || 0.5} | ${k.adsenseCategory || '일반'})`)
    })
    return enriched
  }

  // 2순위: Google Trends + Naver 통합 분석 (폴백)
  logger.info('핫이슈 수집 부족 — Google Trends + Naver 분석으로 전환')
  const [googleTrends, realtimeTrends, naverTrends] = await Promise.allSettled([
    fetchGoogleTrends(20),
    fetchGoogleRealtimeTrends(20),
    fetchNaverTrends(),
  ])

  const googleKeywords = mergeTrends(
    googleTrends.status === 'fulfilled' ? googleTrends.value : [],
    realtimeTrends.status === 'fulfilled' ? realtimeTrends.value : [],
  )
  const naverKeywords = naverTrends.status === 'fulfilled' ? naverTrends.value : []
  const scored = scoreKeywords(googleKeywords, naverKeywords)
  const topKeywords = scored.slice(0, config.content.postsPerRun)

  logger.info(`상위 ${topKeywords.length}개 키워드 뉴스 컨텍스트 수집 중...`)
  const enriched = await Promise.all(
    topKeywords.map(async (item) => {
      let news = await fetchNaverNews(item.keyword, 5)
      if (news.length === 0) news = await fetchGoogleNews(item.keyword, 5)
      return {
        ...item,
        newsContext: news,
        estimatedDailyCPC: estimateDailyCPC(item),
        trendDirection: item.naverTrend || 'stable',
      }
    }),
  )

  logger.info('=== 핫 키워드 분석 완료 ===')
  enriched.forEach((k, i) => {
    const arrow = k.trendDirection === 'rising' ? '🚀' : k.trendDirection === 'falling' ? '📉' : '📊'
    logger.info(`  ${i + 1}. ${k.keyword} ${arrow} (점수: ${k.score} | CPC: $${k.estimatedDailyCPC?.cpc || 0} | ${k.sources?.join('+') || 'fallback'})`)
  })
  return enriched
}

async function enrichWithAdSense(topics) {
  return topics.map(item => {
    const adsenseInfo = item.adsenseCategory
      ? { category: item.adsenseCategory, cpc: ADSENSE_CPC[item.adsenseCategory]?.cpc || 0.5 }
      : getAdSenseCategory(item.keyword) || { category: '일반', cpc: 0.5 }
    return {
      ...item,
      adsenseCategory: adsenseInfo.category,
      estimatedCPC: adsenseInfo.cpc,
      estimatedDailyCPC: adsenseInfo,
      score: 200,
      sources: ['google-news-hot'],
    }
  })
}

/**
 * 네이버 DataLab 실시간 데이터로 직접 분석 (MCP 연동용)
 */
export function analyzeNaverDatalabResults(datalabResults) {
  if (!datalabResults?.results) return []

  return datalabResults.results.map(r => {
    const data = r.data || []
    const ratios = data.map(d => d.ratio)
    const avgRatio = ratios.reduce((a, b) => a + b, 0) / (ratios.length || 1)
    const maxRatio = Math.max(...ratios, 0)

    const recentAvg = ratios.slice(-3).reduce((a, b) => a + b, 0) / 3
    const prevAvg = ratios.slice(0, -3).reduce((a, b) => a + b, 0) / Math.max(ratios.length - 3, 1)
    const risingRate = prevAvg > 0 ? ((recentAvg - prevAvg) / prevAvg) * 100 : 0
    const trend = risingRate > 30 ? 'rising' : risingRate < -20 ? 'falling' : 'stable'

    return {
      keyword: r.title,
      keywords: r.keywords || [],
      avgRatio: Math.round(avgRatio * 10) / 10,
      maxRatio: Math.round(maxRatio * 10) / 10,
      risingRate: Math.round(risingRate),
      trend,
      data,
    }
  }).sort((a, b) => {
    const scoreA = a.avgRatio * (a.trend === 'rising' ? 1.5 : 1)
    const scoreB = b.avgRatio * (b.trend === 'rising' ? 1.5 : 1)
    return scoreB - scoreA
  })
}

function mergeTrends(googleDaily, googleRealtime) {
  const map = new Map()
  googleDaily.forEach((item, idx) => {
    map.set(item.keyword, {
      keyword: item.keyword, traffic: item.traffic,
      relatedQueries: item.relatedQueries, newsItems: item.newsItems,
      googleRank: idx + 1, sources: ['google-daily'],
    })
  })
  googleRealtime.forEach((item, idx) => {
    if (map.has(item.keyword)) {
      const existing = map.get(item.keyword)
      existing.sources.push('google-realtime')
      existing.googleRealtimeRank = idx + 1
    } else {
      map.set(item.keyword, {
        keyword: item.keyword, traffic: item.traffic,
        relatedQueries: item.relatedQueries, newsItems: item.newsItems,
        googleRealtimeRank: idx + 1, sources: ['google-realtime'],
      })
    }
  })
  return Array.from(map.values())
}

function scoreKeywords(googleKeywords, naverKeywords) {
  const naverMap = new Map(naverKeywords.map(n => [n.keyword, n]))
  const scored = googleKeywords.map(item => {
    let score = 100
    if (item.googleRank) score += (20 - Math.min(item.googleRank, 20)) * 5
    if (item.googleRealtimeRank) score += (20 - Math.min(item.googleRealtimeRank, 20)) * 3
    const naverData = naverMap.get(item.keyword)
    if (naverData) {
      score += 50
      item.naverAvgRatio = naverData.avgRatio
      item.naverTrend = naverData.trend
      if (naverData.trend === 'rising') score += 60
      if (naverData.risingRate > 50) score += 30
    }
    const trafficNum = parseInt((item.traffic || '').replace(/[^0-9]/g, ''), 10) || 0
    if (trafficNum > 1000000) score += 80
    else if (trafficNum > 100000) score += 50
    else if (trafficNum > 10000) score += 30
    const adsenseInfo = getAdSenseCategory(item.keyword)
    if (adsenseInfo) {
      score += Math.round(adsenseInfo.cpc * 20)
      item.adsenseCategory = adsenseInfo.category
      item.estimatedCPC = adsenseInfo.cpc
    }
    score += Math.min(item.relatedQueries?.length || 0, 5) * 5
    return { ...item, score }
  })
  return scored.sort((a, b) => b.score - a.score)
}

function getAdSenseCategory(keyword) {
  for (const [category, info] of Object.entries(ADSENSE_CPC)) {
    if (info.keywords.some(k => keyword.includes(k))) return { category, cpc: info.cpc }
  }
  return null
}

function estimateDailyCPC(item) {
  const category = item.adsenseCategory
  if (!category || !ADSENSE_CPC[category]) return { cpc: 0.5, category: '일반' }
  return { cpc: ADSENSE_CPC[category].cpc, category }
}
