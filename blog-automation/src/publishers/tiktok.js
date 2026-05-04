import axios from 'axios'
import fs from 'fs'
import { config } from '../config.js'
import { logger } from '../utils/logger.js'

const BASE_URL = config.tiktok.apiUrl

/**
 * TikTok에 영상 정보 및 스크립트 업로드
 * TikTok Content Posting API v2 기준
 *
 * 참고: 실제 영상 파일이 없는 경우 스크립트와 썸네일을 로컬에 저장하고
 * 영상 제작 후 수동 업로드하거나 영상 생성 API를 별도로 연동하세요.
 */
export async function publishToTikTok(socialContent, videoPath = null) {
  if (!config.tiktok.accessToken || !config.tiktok.openId) {
    logger.warn('TikTok API 설정이 없습니다. 건너뜁니다.')
    return { skipped: true, reason: 'TIKTOK credentials not configured' }
  }

  const { tiktok } = socialContent
  if (!tiktok) {
    return { skipped: true, reason: 'No TikTok content' }
  }

  logger.info('TikTok에 게시 중...')

  try {
    if (!videoPath || !fs.existsSync(videoPath)) {
      // 영상 파일이 없는 경우: 스크립트 저장 후 안내 반환
      logger.warn('TikTok 영상 파일이 없습니다. 스크립트만 저장합니다.')
      return {
        skipped: true,
        reason: 'Video file not provided',
        script: tiktok.script,
        hashtags: tiktok.hashtags,
        scenes: tiktok.scenes,
        message: '아래 스크립트로 영상을 제작 후 업로드하세요.',
      }
    }

    // Step 1: 업로드 초기화
    const initResponse = await axios.post(
      `${BASE_URL}/post/publish/video/init/`,
      {
        post_info: {
          title: buildTikTokTitle(socialContent),
          privacy_level: 'PUBLIC_TO_EVERYONE',
          disable_duet: false,
          disable_comment: false,
          disable_stitch: false,
          video_cover_timestamp_ms: 1000,
        },
        source_info: {
          source: 'FILE_UPLOAD',
          video_size: fs.statSync(videoPath).size,
          chunk_size: 10 * 1024 * 1024,
          total_chunk_count: 1,
        },
      },
      {
        headers: {
          Authorization: `Bearer ${config.tiktok.accessToken}`,
          'Content-Type': 'application/json; charset=UTF-8',
        },
      },
    )

    const { publish_id, upload_url } = initResponse.data.data

    // Step 2: 영상 업로드
    const videoBuffer = fs.readFileSync(videoPath)
    await axios.put(upload_url, videoBuffer, {
      headers: {
        'Content-Type': 'video/mp4',
        'Content-Range': `bytes 0-${videoBuffer.length - 1}/${videoBuffer.length}`,
      },
    })

    logger.info(`TikTok 업로드 완료: publish_id=${publish_id}`)
    return { publishId: publish_id, status: 'uploaded' }
  } catch (err) {
    const errMsg = err.response?.data?.error?.message || err.message
    logger.error(`TikTok 게시 실패: ${errMsg}`)
    return { error: errMsg }
  }
}

/**
 * TikTok 영상 게시 상태 확인
 */
export async function checkTikTokPublishStatus(publishId) {
  try {
    const response = await axios.post(
      `${BASE_URL}/post/publish/status/fetch/`,
      { publish_id: publishId },
      {
        headers: {
          Authorization: `Bearer ${config.tiktok.accessToken}`,
          'Content-Type': 'application/json',
        },
      },
    )
    return response.data.data
  } catch (err) {
    logger.error(`TikTok 상태 확인 실패: ${err.message}`)
    return null
  }
}

function buildTikTokTitle(socialContent) {
  const { tiktok, keyword } = socialContent
  const hashtags = (tiktok?.hashtags || [])
    .map(t => t.startsWith('#') ? t : `#${t}`)
    .slice(0, 5)
    .join(' ')

  const baseTitle = tiktok?.thumbnailText || `${keyword} 오늘의 핫이슈`
  return `${baseTitle} ${hashtags}`.slice(0, 150)
}
