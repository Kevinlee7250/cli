#!/usr/bin/env node
/**
 * AdSense 수익 추정 테스트
 * 실행: node scripts/test-analytics.js
 */
import 'dotenv/config'
import { estimateAdSenseEarnings, printEarningsReport } from '../src/utils/analytics.js'
import { logger } from '../src/utils/logger.js'

const testPosts = [
  {
    keyword: 'AI 재테크',
    title: '챗GPT로 월 300만원? 2026년 AI로 돈 버는 7가지 현실적인 방법',
    adsenseCategory: '기술',
    trendDirection: 'rising',
    naverAvgRatio: 90,
    estimatedCPC: 1.5,
  },
  {
    keyword: 'ETF 투자',
    title: '2026년 ETF 투자 완벽 가이드: 초보도 월 50만원 수익 내는 법',
    adsenseCategory: '금융',
    trendDirection: 'stable',
    naverAvgRatio: 65,
    estimatedCPC: 2.5,
  },
  {
    keyword: '여름 여행 일본',
    title: '2026 여름 일본 여행 완벽 준비: 최저가 항공+호텔 패키지 비교',
    adsenseCategory: '여행',
    trendDirection: 'rising',
    naverAvgRatio: 27,
    estimatedCPC: 1.2,
  },
]

logger.info('AdSense 수익 추정 테스트')
const estimate = estimateAdSenseEarnings(testPosts)
printEarningsReport(estimate)
