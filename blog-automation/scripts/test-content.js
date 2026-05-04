#!/usr/bin/env node
/**
 * 콘텐츠 생성 테스트 스크립트
 * 실행: node scripts/test-content.js
 */
import 'dotenv/config'
import { generateBlogPost } from '../src/generators/blog-content.js'
import { generateSocialContent } from '../src/generators/social-content.js'
import { savePost, saveSocialContent } from '../src/utils/storage.js'
import { logger } from '../src/utils/logger.js'

const testKeyword = {
  keyword: process.argv[2] || '인공지능',
  traffic: '100K+',
  relatedQueries: ['AI 활용', 'ChatGPT', '생성형AI'],
  newsContext: [
    { title: 'AI 기술 급격히 발전, 일상 속 활용 늘어' },
    { title: '인공지능으로 월 100만원 부수입 만드는 방법' },
  ],
}

logger.info(`"${testKeyword.keyword}" 키워드로 콘텐츠 생성 테스트 중...`)

try {
  const blogPost = await generateBlogPost(testKeyword)
  logger.info(`\n✅ 블로그 포스트 생성 완료:`)
  logger.info(`  제목: ${blogPost.title}`)
  logger.info(`  메타: ${blogPost.metaDescription}`)
  logger.info(`  태그: ${blogPost.tags?.join(', ')}`)
  logger.info(`  읽기시간: ${blogPost.readingTime}`)

  const postPath = savePost(blogPost)
  logger.info(`  저장: ${postPath}`)

  const social = await generateSocialContent(blogPost, 'https://yourblog.blogspot.com/test-post')
  logger.info(`\n✅ SNS 콘텐츠 생성 완료:`)
  logger.info(`  Instagram 후킹: ${social.instagram?.hookLine}`)
  logger.info(`  Threads 개수: ${social.threads?.posts?.length}개`)
  logger.info(`  TikTok 씬: ${social.tiktok?.scenes?.length}개`)

  saveSocialContent(social, testKeyword.keyword)
  logger.info('\n테스트 완료! output/ 폴더를 확인하세요.')
} catch (err) {
  logger.error(`테스트 실패: ${err.message}`)
  process.exit(1)
}
