import axios from 'axios'
import { config } from '../config.js'
import { logger } from '../utils/logger.js'
import { formatThreadsPosts } from '../generators/social-content.js'

const BASE_URL = config.threads.apiUrl

/**
 * Threads에 연속 스레드(Thread Chain) 게시
 * Meta Threads API v1.0 기준
 * @param {Object} socialContent - SNS 콘텐츠 데이터
 * @param {string} imagePublicUrl - 첫 포스트에 첨부할 이미지 URL (선택)
 * @returns {Promise<Object>}
 */
export async function publishToThreads(socialContent, imagePublicUrl = null) {
  if (!config.threads.accessToken || !config.threads.userId) {
    logger.warn('Threads API 설정이 없습니다. 건너뜁니다.')
    return { skipped: true, reason: 'THREADS credentials not configured' }
  }

  logger.info('Threads에 게시 중...')

  try {
    const posts = formatThreadsPosts(socialContent)
    if (!posts.length) {
      return { skipped: true, reason: 'No threads content' }
    }

    const publishedIds = []
    let replyToId = null

    for (let i = 0; i < posts.length; i++) {
      const post = posts[i]
      const isFirst = i === 0

      // Step 1: 미디어 컨테이너 생성
      const params = {
        text: post.fullContent,
        access_token: config.threads.accessToken,
      }

      if (isFirst && imagePublicUrl) {
        params.media_type = 'IMAGE'
        params.image_url = imagePublicUrl
      } else {
        params.media_type = 'TEXT'
      }

      if (replyToId) {
        params.reply_to_id = replyToId
      }

      const containerRes = await axios.post(
        `${BASE_URL}/${config.threads.userId}/threads`,
        null,
        { params },
      )

      const containerId = containerRes.data.id

      // Step 2: 게시
      await delay(2000)

      const publishRes = await axios.post(
        `${BASE_URL}/${config.threads.userId}/threads_publish`,
        null,
        {
          params: {
            creation_id: containerId,
            access_token: config.threads.accessToken,
          },
        },
      )

      const mediaId = publishRes.data.id
      publishedIds.push(mediaId)
      replyToId = mediaId

      logger.info(`Threads 포스트 ${i + 1}/${posts.length} 게시 완료: ${mediaId}`)

      // 스레드 간 딜레이
      if (i < posts.length - 1) await delay(3000)
    }

    const firstPostUrl = `https://www.threads.net/@me/post/${publishedIds[0]}`
    logger.info(`Threads 전체 게시 완료: ${publishedIds.length}개 스레드`)
    return { ids: publishedIds, url: firstPostUrl }
  } catch (err) {
    const errMsg = err.response?.data?.error?.message || err.message
    logger.error(`Threads 게시 실패: ${errMsg}`)
    return { error: errMsg }
  }
}

/**
 * 단일 Threads 포스트 게시 (텍스트만)
 */
export async function publishSingleThread(text) {
  if (!config.threads.accessToken || !config.threads.userId) {
    return { skipped: true }
  }

  try {
    const containerRes = await axios.post(
      `${BASE_URL}/${config.threads.userId}/threads`,
      null,
      {
        params: {
          media_type: 'TEXT',
          text,
          access_token: config.threads.accessToken,
        },
      },
    )

    await delay(1500)

    const publishRes = await axios.post(
      `${BASE_URL}/${config.threads.userId}/threads_publish`,
      null,
      {
        params: {
          creation_id: containerRes.data.id,
          access_token: config.threads.accessToken,
        },
      },
    )

    return { id: publishRes.data.id }
  } catch (err) {
    return { error: err.response?.data?.error?.message || err.message }
  }
}

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}
