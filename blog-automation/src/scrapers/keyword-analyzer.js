import { fetchGoogleTrends, fetchGoogleRealtimeTrends } from './google-trends.js'
import { fetchNaverTrends, fetchNaverNews } from './naver-trends.js'
import { logger } from '../utils/logger.js'
import { config } from '../config.js'

/**
 * Google + 네이버 트렌드를 통합 분석하여 AdSense 수익화에 최적화된 키워드 선별
 */
export async function analyzeHotKeywords() {
  logger.info('=== 오늘의 핫 키워드 분석 시작 ===')

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

  // 교차 분석: 두 플랫폼에 모두 등장하는 키워드 우선
  const scored = scoreKeywords(googleKeywords, naverKeywords)

  // 상위 N개 선택
  const topKeywords = scored.slice(0, config.content.postsPerRun)

  // 각 키워드별 뉴스 컨텍스트 수집
  logger.info(`상위 ${topKeywords.length}개 키워드 뉴스 컨텍스트 수집 중...`)
  const enriched = await Promise.all(
    topKeywords.map(async (item) => {
      const news = await fetchNaverNews(item.keyword, 3)
      return { ...item, newsContext: news }
    }),
  )

  logger.info('=== 핫 키워드 분석 완료 ===')
  enriched.forEach((k, i) => {
    logger.info(`  ${i + 1}. ${k.keyword} (점수: ${k.score}, 출처: ${k.sources.join('+')}`)
  })

  return enriched
}

function mergeTrends(googleDaily, googleRealtime) {
  const map = new Map()

  googleDaily.forEach((item, idx) => {
    map.set(item.keyword, {
      keyword: item.keyword,
      traffic: item.traffic,
      relatedQueries: item.relatedQueries,
      newsItems: item.newsItems,
      googleRank: idx + 1,
      sources: ['google-daily'],
    })
  })

  googleRealtime.forEach((item, idx) => {
    if (map.has(item.keyword)) {
      const existing = map.get(item.keyword)
      existing.sources.push('google-realtime')
      existing.googleRealtimeRank = idx + 1
    } else {
      map.set(item.keyword, {
        keyword: item.keyword,
        traffic: item.traffic,
        relatedQueries: item.relatedQueries,
        newsItems: item.newsItems,
        googleRealtimeRank: idx + 1,
        sources: ['google-realtime'],
      })
    }
  })

  return Array.from(map.values())
}

function scoreKeywords(googleKeywords, naverKeywords) {
  const naverSet = new Set(naverKeywords.map(n => n.keyword))

  // AdSense 고가치 카테고리 가중치
  const highValueCategories = {
    금융: ['주식', '코인', '펀드', '보험', '대출', '카드', '금리', '부동산', '청약'],
    건강: ['다이어트', '운동', '영양제', '병원', '의료', '건강', '질병', '치료'],
    기술: ['AI', '인공지능', '스마트폰', '노트북', '게임', '앱', '소프트웨어'],
    여행: ['여행', '항공', '호텔', '숙소', '리조트', '해외여행', '국내여행'],
    교육: ['영어', '자격증', '시험', '취업', '학원', '온라인강의', '코딩'],
    쇼핑: ['할인', '세일', '쿠폰', '가전', '가구', '패션', '명품'],
  }

  const scored = googleKeywords.map(item => {
    let score = 100

    // 구글 순위 점수
    if (item.googleRank) score += (20 - Math.min(item.googleRank, 20)) * 5
    if (item.googleRealtimeRank) score += (20 - Math.min(item.googleRealtimeRank, 20)) * 3

    // 네이버 교차 검증 보너스
    if (naverSet.has(item.keyword)) score += 50

    // 트래픽 점수
    const trafficNum = parseInt((item.traffic || '').replace(/[^0-9]/g, ''), 10) || 0
    if (trafficNum > 1000000) score += 80
    else if (trafficNum > 100000) score += 50
    else if (trafficNum > 10000) score += 30

    // AdSense 고가치 카테고리 보너스
    for (const [, keywords] of Object.entries(highValueCategories)) {
      if (keywords.some(k => item.keyword.includes(k))) {
        score += 40
        break
      }
    }

    // 관련 쿼리 풍부도
    score += Math.min(item.relatedQueries?.length || 0, 5) * 5

    return { ...item, score }
  })

  return scored.sort((a, b) => b.score - a.score)
}
