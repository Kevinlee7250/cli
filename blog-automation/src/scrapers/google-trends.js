import axios from 'axios'
import * as cheerio from 'cheerio'
import Anthropic from '@anthropic-ai/sdk'
import { config } from '../config.js'
import { logger } from '../utils/logger.js'

const client = new Anthropic({ apiKey: config.anthropic.apiKey })

const TRENDING_RSS = {
  KR: 'https://trends.google.com/trends/trendingsearches/daily/rss?geo=KR',
  US: 'https://trends.google.com/trends/trendingsearches/daily/rss?geo=US',
  JP: 'https://trends.google.com/trends/trendingsearches/daily/rss?geo=JP',
}

/**
 * Google News RSS로 오늘의 핫이슈 수집 후 Claude가 블로그 키워드 Top3 선정
 */
export async function fetchTodayHotTopics(count = 3) {
  const today = new Date().toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric' })
  logger.info(`오늘(${today}) 핫이슈 수집 중... (Google News RSS)`)

  let headlines = []

  // 1) Google News 한국 Top Stories RSS
  try {
    const res = await axios.get('https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko', {
      headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36' },
      timeout: 12000,
    })
    const $ = cheerio.load(res.data, { xmlMode: true })
    $('item').each((i, el) => {
      if (i >= 30) return false
      const title = $(el).find('title').first().text().replace(/\s*-\s*[^-]+$/, '').trim()
      const pubDate = $(el).find('pubDate').text().trim()
      if (title) headlines.push({ title, pubDate })
    })
    logger.info(`Google News ${headlines.length}개 헤드라인 수집 완료`)
  } catch (err) {
    logger.warn(`Google News RSS 실패: ${err.message}`)
  }

  // 2) Naver News 폴백 (헤드라인이 적으면 추가)
  if (headlines.length < 10 && config.naver.clientId) {
    try {
      const res = await axios.get('https://openapi.naver.com/v1/search/news.json', {
        params: { query: '오늘 이슈', display: 20, sort: 'date' },
        headers: {
          'X-Naver-Client-Id': config.naver.clientId,
          'X-Naver-Client-Secret': config.naver.clientSecret,
        },
        timeout: 8000,
      })
      const items = (res.data.items || []).map(i => ({
        title: i.title.replace(/<[^>]*>/g, ''),
        pubDate: i.pubDate,
      }))
      headlines = [...headlines, ...items]
      logger.info(`Naver 뉴스 ${items.length}개 추가`)
    } catch {}
  }

  if (headlines.length === 0) {
    logger.warn('외부 뉴스 수집 불가 → Claude 지식 기반 오늘의 키워드 생성')
    return generateKeywordsWithClaude(count)
  }

  // 3) Claude로 오늘의 핫이슈 Top3 블로그 키워드 선정
  logger.info(`Claude가 ${headlines.length}개 헤드라인에서 블로그 키워드 Top${count} 선정 중...`)
  try {
    const headlineText = headlines.slice(0, 25).map((h, i) => `${i + 1}. ${h.title}`).join('\n')
    const response = await client.messages.create({
      model: config.anthropic.model,
      max_tokens: 1000,
      messages: [{
        role: 'user',
        content: `오늘(${today}) 뉴스 헤드라인 목록입니다:
${headlineText}

위 헤드라인에서 한국 독자가 관심 가질 블로그 포스트 키워드 상위 ${count}개를 선정하세요.
조건: ① 구글 AdSense CPC가 높을 것 ② 검색량이 많을 것 ③ 실제 오늘 이슈와 연관

아래 JSON 형식으로만 응답하세요:
{
  "keywords": [
    { "keyword": "키워드1", "reason": "선정 이유", "newsTitle": "관련 헤드라인", "adsenseCategory": "카테고리" },
    { "keyword": "키워드2", "reason": "선정 이유", "newsTitle": "관련 헤드라인", "adsenseCategory": "카테고리" },
    { "keyword": "키워드3", "reason": "선정 이유", "newsTitle": "관련 헤드라인", "adsenseCategory": "카테고리" }
  ]
}`,
      }],
    })

    const { jsonrepair } = await import('jsonrepair')
    const text = response.content[0].text
    const jsonStart = text.indexOf('{')
    const jsonEnd = text.lastIndexOf('}')
    const parsed = JSON.parse(jsonrepair(text.slice(jsonStart, jsonEnd + 1)))

    const result = (parsed.keywords || []).slice(0, count).map(k => ({
      keyword: k.keyword,
      traffic: '오늘 핫이슈',
      relatedQueries: [k.newsTitle].filter(Boolean),
      newsItems: [k.newsTitle].filter(Boolean),
      newsContext: [{ title: k.newsTitle, description: k.reason }].filter(h => h.title),
      adsenseCategory: k.adsenseCategory || null,
      trendDirection: 'rising',
    }))

    logger.info(`오늘의 핫이슈 Top${result.length} 선정 완료:`)
    result.forEach((k, i) => logger.info(`  ${i + 1}. ${k.keyword} (${k.adsenseCategory || '일반'})`))
    return result
  } catch (err) {
    logger.warn(`Claude 키워드 선정 실패: ${err.message} → 헤드라인 직접 사용`)
    return headlines.slice(0, count).map(h => ({
      keyword: h.title.slice(0, 20),
      traffic: '오늘 이슈',
      relatedQueries: [],
      newsItems: [h.title],
      newsContext: [{ title: h.title }],
      trendDirection: 'rising',
    }))
  }
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
 * Claude 지식 기반 오늘의 핫 키워드 생성 (외부 RSS 불가 시 폴백)
 */
async function generateKeywordsWithClaude(count = 3) {
  const today = new Date().toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric' })
  const dayOfWeek = new Date().toLocaleDateString('ko-KR', { weekday: 'long' })
  logger.info(`Claude 지식 기반 오늘(${today}) 핫 키워드 ${count}개 생성 중...`)

  try {
    const response = await client.messages.create({
      model: config.anthropic.model,
      max_tokens: 1500,
      messages: [{
        role: 'user',
        content: `오늘은 ${today} (${dayOfWeek})입니다.

한국에서 오늘 날짜 기준으로 가장 핫한 이슈·키워드 상위 ${count}개를 선정해주세요.
계절, 시사, 경제, 문화, 스포츠, 정치, 사회 이슈를 종합적으로 고려하세요.

조건:
① 오늘 날짜(${today})와 관련성이 높을 것
② 구글 AdSense CPC가 높은 카테고리 우선 (법률 > 부동산 > 금융 > 건강 > 기술 > 교육)
③ 한국 독자가 검색할 가능성이 높을 것
④ 블로그 포스트 작성에 적합한 주제일 것

아래 JSON 형식으로만 응답하세요:
{
  "keywords": [
    { "keyword": "키워드1", "reason": "선정 이유 (날짜·시사 연관성)", "newsTitle": "예상 관련 뉴스 헤드라인", "adsenseCategory": "카테고리" },
    { "keyword": "키워드2", "reason": "선정 이유", "newsTitle": "예상 관련 뉴스 헤드라인", "adsenseCategory": "카테고리" },
    { "keyword": "키워드3", "reason": "선정 이유", "newsTitle": "예상 관련 뉴스 헤드라인", "adsenseCategory": "카테고리" }
  ]
}`,
      }],
    })

    const { jsonrepair } = await import('jsonrepair')
    const text = response.content[0].text
    const jsonStart = text.indexOf('{')
    const jsonEnd = text.lastIndexOf('}')
    const parsed = JSON.parse(jsonrepair(text.slice(jsonStart, jsonEnd + 1)))

    const result = (parsed.keywords || []).slice(0, count).map(k => ({
      keyword: k.keyword,
      traffic: '오늘 핫이슈',
      relatedQueries: [k.newsTitle].filter(Boolean),
      newsItems: [k.newsTitle].filter(Boolean),
      newsContext: [{ title: k.newsTitle, description: k.reason }].filter(h => h.title),
      adsenseCategory: k.adsenseCategory || null,
      trendDirection: 'rising',
    }))

    logger.info(`Claude 지식 기반 키워드 ${result.length}개 생성 완료:`)
    result.forEach((k, i) => logger.info(`  ${i + 1}. ${k.keyword} (${k.adsenseCategory || '일반'})`))
    return result
  } catch (err) {
    logger.warn(`Claude 키워드 생성 실패: ${err.message} → 시즌 폴백 사용`)
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
