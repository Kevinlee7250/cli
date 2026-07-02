import axios from 'axios'
import FormData from 'form-data'
import fs from 'fs'
import { config } from '../config.js'
import { logger } from '../utils/logger.js'
import { formatInstagramCaption } from '../generators/social-content.js'

const BASE_URL = config.instagram.apiUrl

/**
 * 인스타그램에 이미지 + 캡션 게시
 * Instagram Graph API v21.0 기준
 * @param {Object} socialContent - SNS 콘텐츠 데이터
 * @param {string} thumbnailPath - 썸네일 이미지 경로
 * @param {string} imagePublicUrl - 공개 접근 가능한 이미지 URL (Instagram API 요구사항)
 * @returns {Promise<Object>}
 */
export async function publishToInstagram(socialContent, thumbnailPath, imagePublicUrl = null) {
  if (!config.instagram.accessToken || !config.instagram.accountId) {
    logger.warn('Instagram API 설정이 없습니다. 건너뜁니다.')
    return { skipped: true, reason: 'INSTAGRAM credentials not configured' }
  }

  logger.info('Instagram에 게시 중...')

  try {
    const caption = formatInstagramCaption(socialContent)

    // Step 1: 미디어 컨테이너 생성
    let finalImageUrl = imagePublicUrl
    if (!finalImageUrl && thumbnailPath) {
      const imgbbKey = process.env.IMGBB_API_KEY
      if (imgbbKey) {
        finalImageUrl = await uploadImageToImgBB(thumbnailPath)
      } else {
        logger.warn('IMGBB_API_KEY 미설정 — 이미지 없이 텍스트만 게시합니다.')
      }
    }

    const mediaParams = { caption, access_token: config.instagram.accessToken }
    if (finalImageUrl) {
      mediaParams.image_url = finalImageUrl
      mediaParams.media_type = 'IMAGE'
    } else {
      mediaParams.media_type = 'TEXT'
    }

    const containerResponse = await axios.post(
      `${BASE_URL}/${config.instagram.accountId}/media`,
      null,
      { params: mediaParams },
    )

    const creationId = containerResponse.data.id
    logger.info(`Instagram 미디어 컨테이너 생성: ${creationId}`)

    // Step 2: 컨테이너 상태 확인 (최대 30초 대기)
    await waitForContainerReady(creationId)

    // Step 3: 게시 실행
    const publishResponse = await axios.post(
      `${BASE_URL}/${config.instagram.accountId}/media_publish`,
      null,
      {
        params: {
          creation_id: creationId,
          access_token: config.instagram.accessToken,
        },
      },
    )

    const mediaId = publishResponse.data.id
    const postUrl = `https://www.instagram.com/p/${mediaId}/`

    logger.info(`Instagram 게시 완료: ${postUrl}`)
    return { id: mediaId, url: postUrl }
  } catch (err) {
    const errMsg = err.response?.data?.error?.message || err.message
    logger.error(`Instagram 게시 실패: ${errMsg}`)
    return { error: errMsg }
  }
}

/**
 * 미디어 컨테이너 준비 상태 대기
 */
async function waitForContainerReady(creationId, maxWait = 30000) {
  const start = Date.now()
  while (Date.now() - start < maxWait) {
    const response = await axios.get(`${BASE_URL}/${creationId}`, {
      params: {
        fields: 'status_code',
        access_token: config.instagram.accessToken,
      },
    })

    const status = response.data.status_code
    if (status === 'FINISHED') return
    if (status === 'ERROR') throw new Error('Instagram 미디어 처리 오류')

    await delay(3000)
  }
  throw new Error('Instagram 미디어 처리 시간 초과')
}

/**
 * ImgBB에 이미지 업로드 (Instagram API는 공개 URL 필요)
 * 실제 서비스에서는 S3, GCS 등 클라우드 스토리지 사용 권장
 */
async function uploadImageToImgBB(imagePath) {
  const imgbbKey = process.env.IMGBB_API_KEY
  if (!imgbbKey) {
    throw new Error('이미지 공개 URL이 필요합니다. IMGBB_API_KEY 또는 imagePublicUrl을 설정하세요.')
  }

  const imageData = fs.readFileSync(imagePath)
  const base64 = imageData.toString('base64')

  const formData = new FormData()
  formData.append('image', base64)

  const response = await axios.post(`https://api.imgbb.com/1/upload?key=${imgbbKey}`, formData, {
    headers: formData.getHeaders(),
  })

  return response.data.data.url
}

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}
