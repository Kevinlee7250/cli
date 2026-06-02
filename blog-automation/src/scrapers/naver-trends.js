import axios from 'axios'
import { config } from '../config.js'
import { logger } from '../utils/logger.js'

/**
 * Google News RSS로 실제 최신 뉴스 수집 (API 키 불필요)
 */
export async function fetchGoogleNews(keyword, count = 5) {
  try {
    const url = `https://news.google.com/rss/search?q=${encodeURIComponent(keyword)}&hl=ko&gl=KR&ceid=KR:ko`
    const res = await axios.get(url, { timeout: 8000 })
    const items = []
    const itemRe = /<item>([\s\S]*?)<\/item>/g
    let m
    while ((m = itemRe.exec(res.data)) !== null && items.length < count) {
      const block = m[1]
      const title = (block.match(/<title><!\[CDATA\[(.*?)\]\]><\/title>/) || block.match(/<title>(.*?)<\/title>/))?.[1] || ''
      const pubDate = (block.match(/<pubDate>(.*?)<\/pubDate>/))?.[1] || ''
      if (title) items.push({ title: title.trim(), pubDate: pubDate.trim() })
    }
    if (items.length > 0) logger.info(`Google 뉴스 ${items.length}건 수집 (${keyword})`)
    return items
  } catch (err) {
    logger.warn(`Google 뉴스 수집 실패 (${keyword}): ${err.message}`)
    return []
  }
}

/**
 * 네이버 DataLab 검색어 트렌드 조회
 * 최근 7일 인기 검색어 키워드를 분석
 */
export async function fetchNaverTrends(keywords = []) {
  if (!config.naver.clientId || !config.naver.clientSecret) {
    logger.warn('네이버 API 키가 설정되지 않았습니다. 네이버 트렌드 수집을 건너뜁니다.')
    return []
  }

  const today = new Date()
  const startDate = new Date(today)
  startDate.setDate(today.getDate() - 7)

  const formatDate = (d) => d.toISOString().split('T')[0]

  // 기본 트렌드 카테고리 그룹
  const defaultGroups = keywords.length > 0
    ? keywords.map(k => ({ groupName: k, keywords: [k] }))
    : [
        { groupName: '경제', keywords: ['주식', '코인', '부동산', '금리'] },
        { groupName: '건강', keywords: ['다이어트', '운동', '영양제', '건강식품'] },
        { groupName: '여행', keywords: ['국내여행', '해외여행', '숙소', '항공권'] },
        { groupName: '패션', keywords: ['옷', '신발', '가방', '코디'] },
        { groupName: '음식', keywords: ['맛집', '배달', '레시피', '음식'] },
      ]

  logger.info('네이버 DataLab 트렌드 수집 중...')

  try {
    const body = {
      startDate: formatDate(startDate),
      endDate: formatDate(today),
      timeUnit: 'date',
      keywordGroups: defaultGroups.slice(0, 5),
    }

    const response = await axios.post(config.naver.datalabUrl, body, {
      headers: {
        'X-Naver-Client-Id': config.naver.clientId,
        'X-Naver-Client-Secret': config.naver.clientSecret,
        'Content-Type': 'application/json',
      },
      timeout: 10000,
    })

    const results = response.data.results || []
    const trends = results.map(r => {
      const data = r.data || []
      const avgRatio = data.length > 0
        ? data.reduce((sum, d) => sum + d.ratio, 0) / data.length
        : 0
      const maxRatio = Math.max(...data.map(d => d.ratio), 0)

      return {
        keyword: r.title,
        avgRatio: Math.round(avgRatio * 10) / 10,
        maxRatio: Math.round(maxRatio * 10) / 10,
        trend: detectTrend(data),
      }
    })

    // 평균 검색 비율 높은 순으로 정렬
    trends.sort((a, b) => b.avgRatio - a.avgRatio)
    logger.info(`네이버 DataLab ${trends.length}개 트렌드 수집 완료`)
    return trends
  } catch (err) {
    logger.warn(`네이버 DataLab 수집 실패: ${err.message}`)
    return []
  }
}

/**
 * 네이버 뉴스 검색으로 키워드별 최신 이슈 수집
 */
export async function fetchNaverNews(keyword, display = 5) {
  if (!config.naver.clientId || !config.naver.clientSecret) return []

  try {
    const response = await axios.get(`${config.naver.searchUrl}/news.json`, {
      params: { query: keyword, display, sort: 'date' },
      headers: {
        'X-Naver-Client-Id': config.naver.clientId,
        'X-Naver-Client-Secret': config.naver.clientSecret,
      },
      timeout: 10000,
    })

    return (response.data.items || []).map(item => ({
      title: stripHtml(item.title),
      description: stripHtml(item.description),
      link: item.link,
      pubDate: item.pubDate,
    }))
  } catch (err) {
    logger.warn(`네이버 뉴스 수집 실패 (${keyword}): ${err.message}`)
    return []
  }
}

/**
 * 네이버 블로그 검색으로 키워드 인기도 파악
 */
export async function fetchNaverBlogPosts(keyword, display = 5) {
  if (!config.naver.clientId || !config.naver.clientSecret) return []

  try {
    const response = await axios.get(`${config.naver.searchUrl}/blog.json`, {
      params: { query: keyword, display, sort: 'date' },
      headers: {
        'X-Naver-Client-Id': config.naver.clientId,
        'X-Naver-Client-Secret': config.naver.clientSecret,
      },
      timeout: 10000,
    })

    return (response.data.items || []).map(item => ({
      title: stripHtml(item.title),
      description: stripHtml(item.description),
      bloggerName: item.bloggername,
      postDate: item.postdate,
    }))
  } catch (err) {
    logger.warn(`네이버 블로그 수집 실패 (${keyword}): ${err.message}`)
    return []
  }
}

function detectTrend(data) {
  if (data.length < 3) return 'stable'
  const recent = data.slice(-3).map(d => d.ratio)
  const earlier = data.slice(0, 3).map(d => d.ratio)
  const recentAvg = recent.reduce((a, b) => a + b, 0) / recent.length
  const earlierAvg = earlier.reduce((a, b) => a + b, 0) / earlier.length
  if (recentAvg > earlierAvg * 1.3) return 'rising'
  if (recentAvg < earlierAvg * 0.7) return 'falling'
  return 'stable'
}

function stripHtml(str) {
  return str.replace(/<[^>]*>/g, '').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').replace(/&quot;/g, '"')
}
