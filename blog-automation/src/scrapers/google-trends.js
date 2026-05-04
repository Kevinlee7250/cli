import axios from 'axios'
import * as cheerio from 'cheerio'
import { config } from '../config.js'
import { logger } from '../utils/logger.js'

const TRENDING_RSS = {
  KR: 'https://trends.google.com/trends/trendingsearches/daily/rss?geo=KR',
  US: 'https://trends.google.com/trends/trendingsearches/daily/rss?geo=US',
  JP: 'https://trends.google.com/trends/trendingsearches/daily/rss?geo=JP',
}

/**
 * Google Trends 일간 트렌딩 키워드 수집
 * @returns {Promise<Array<{keyword: string, traffic: string, relatedQueries: string[]}>>}
 */
export async function fetchGoogleTrends(limit = 10) {
  const country = config.google.country || 'KR'
  const rssUrl = TRENDING_RSS[country] || TRENDING_RSS.KR

  logger.info(`Google Trends 수집 중... (국가: ${country})`)

  try {
    const response = await axios.get(rssUrl, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        Accept: 'application/rss+xml, text/xml',
      },
      timeout: 15000,
    })

    const $ = cheerio.load(response.data, { xmlMode: true })
    const trends = []

    $('item').each((i, el) => {
      if (i >= limit) return false

      const keyword = $(el).find('title').first().text().trim()
      const traffic = $(el).find('ht\\:approx_traffic').text().trim() ||
                      $(el).find('approx_traffic').text().trim() || '알 수 없음'

      const relatedQueries = []
      $(el).find('ht\\:related_queries a, related_queries a').each((_, q) => {
        relatedQueries.push($(q).text().trim())
      })

      const newsItems = []
      $(el).find('ht\\:news_item_title, news_item_title').each((_, n) => {
        newsItems.push($(n).text().trim())
      })

      if (keyword) {
        trends.push({ keyword, traffic, relatedQueries, newsItems })
      }
    })

    logger.info(`Google Trends ${trends.length}개 키워드 수집 완료`)
    return trends
  } catch (err) {
    logger.warn(`Google Trends 수집 실패: ${err.message}. 폴백 키워드를 사용합니다.`)
    return getFallbackKeywords()
  }
}

/**
 * Google Trends 실시간 트렌드 (JSON API)
 * 대안 엔드포인트 사용
 */
export async function fetchGoogleRealtimeTrends(limit = 10) {
  logger.info('Google 실시간 트렌드 수집 중...')
  try {
    const url = `https://trends.google.com/trends/api/realtimetrends?hl=ko&tz=-540&cat=all&fi=0&fs=0&geo=${config.google.country || 'KR'}&ri=300&rs=20&sort=0`
    const response = await axios.get(url, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        Referer: 'https://trends.google.com/',
      },
      timeout: 15000,
    })

    // Google은 응답 앞에 ")]}',\n" 같은 보호 문자를 붙임
    const jsonText = response.data.replace(/^\)\]\}',\n/, '').trim()
    const data = JSON.parse(jsonText)

    const trends = []
    const stories = data?.storySummaries?.trendingStories || []

    for (const story of stories.slice(0, limit)) {
      const keyword = story.title || story.entityNames?.[0] || ''
      if (keyword) {
        trends.push({
          keyword,
          traffic: story.formattedTraffic || '급상승',
          relatedQueries: story.entityNames?.slice(1) || [],
          newsItems: story.articles?.map(a => a.title).slice(0, 3) || [],
        })
      }
    }

    logger.info(`Google 실시간 트렌드 ${trends.length}개 수집 완료`)
    return trends.length > 0 ? trends : getFallbackKeywords()
  } catch (err) {
    logger.warn(`Google 실시간 트렌드 수집 실패: ${err.message}`)
    return getFallbackKeywords()
  }
}

/**
 * 네트워크 오류 시 사용할 폴백 키워드 (최신 트렌드 기반 샘플)
 */
function getFallbackKeywords() {
  const today = new Date()
  const month = today.getMonth() + 1

  const seasonal = {
    1: ['설날 선물', '겨울 여행', '새해 다이어트'],
    2: ['발렌타인데이', '봄 준비', '입학 준비'],
    3: ['봄 여행', '벚꽃 명소', '새학기'],
    4: ['황사 마스크', '봄 패션', '캠핑'],
    5: ['어버이날 선물', '어린이날', '황금연휴'],
    6: ['여름 준비', '에어컨 청소', '여름 옷'],
    7: ['휴가 여행', '피서지', '여름 음식'],
    8: ['광복절', '여름 방학', '해수욕장'],
    9: ['추석 선물', '가을 여행', '단풍 명소'],
    10: ['핼러윈', '가을 패션', '독감 예방'],
    11: ['수능', '블랙프라이데이', '겨울 준비'],
    12: ['크리스마스 선물', '연말 정산', '송년회'],
  }

  return (seasonal[month] || seasonal[1]).map(keyword => ({
    keyword,
    traffic: '시즌 인기',
    relatedQueries: [],
    newsItems: [],
  }))
}
