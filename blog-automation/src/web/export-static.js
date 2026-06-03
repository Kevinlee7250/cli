/**
 * 정적 GitHub Pages 대시보드용 데이터 익스포트
 * 실행 후 docs/data/ 에 JSON 파일들이 생성됩니다.
 */
import { readFileSync, writeFileSync, readdirSync, existsSync, mkdirSync, statSync } from 'fs'
import { join, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT = join(__dirname, '../../..')
const OUTPUT = join(ROOT, 'blog-automation/output')
const DOCS_DATA = join(ROOT, 'docs/data')

function readJSON(path) {
  try { return JSON.parse(readFileSync(path, 'utf8')) } catch { return null }
}

function ensureDir(dir) {
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true })
}

function loadRuns() {
  const analytics = readJSON(join(OUTPUT, 'analytics.json'))
  if (analytics?.runs?.length) return analytics.runs.map(r => ({ ...r, runAt: r.runAt || r.savedAt }))
  const raw = readJSON(join(OUTPUT, 'run-history.json'))
  const runs = Array.isArray(raw) ? raw : (raw?.runs || [])
  return runs.map(r => ({ ...r, runAt: r.runAt || r.savedAt }))
}

export function exportStaticData() {
  ensureDir(DOCS_DATA)

  // 1. Posts
  const postDir = join(OUTPUT, 'posts')
  const posts = []
  if (existsSync(postDir)) {
    readdirSync(postDir)
      .filter(f => f.endsWith('.json'))
      .sort().reverse()
      .forEach(f => {
        try {
          const d = JSON.parse(readFileSync(join(postDir, f), 'utf8'))
          posts.push({
            id: f.replace('.json', ''),
            title: d.title || '',
            keyword: d.keyword || '',
            date: d.date || f.slice(0, 10),
            wordCount: d.wordCount || 0,
            faqCount: (d.faq || []).length,
            adsenseCategory: d.adsenseCategory || '일반',
            estimatedCPC: d.estimatedCPC || 0.5,
            trendDirection: d.trendDirection || 'stable',
            factCheck: d.factCheck || null,
            metaDescription: d.metaDescription || '',
            tags: d.tags || [],
            faq: (d.faq || []).slice(0, 10),
            contentPreview: (d.content || '').replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').slice(0, 600),
          })
        } catch {}
      })
  }
  writeFileSync(join(DOCS_DATA, 'posts.json'), JSON.stringify(posts, null, 2))

  // 2. Social index
  const socialDir = join(OUTPUT, 'social')
  const social = []
  if (existsSync(socialDir)) {
    readdirSync(socialDir)
      .filter(f => f.endsWith('.json'))
      .sort().reverse()
      .forEach(f => {
        try {
          const d = JSON.parse(readFileSync(join(socialDir, f), 'utf8'))
          social.push({
            id: f.replace('.json', ''),
            date: f.slice(0, 10),
            keyword: d.keyword || f.slice(11).replace('_social.json', '').replace(/_/g, ' '),
            instagram: d.instagram ? {
              caption: d.instagram.caption || '',
              hookLine: d.instagram.hookLine || '',
              hashtags: d.instagram.hashtags || {},
              bestPostingTimes: d.instagram.bestPostingTimes || [],
              storyHighlightTitle: d.instagram.storyHighlightTitle || '',
            } : null,
            threads: d.threads ? {
              posts: (d.threads.posts || []).slice(0, 5),
              hashtags: d.threads.hashtags || [],
              engagementQuestion: d.threads.engagementQuestion || '',
              bestPostingTimes: d.threads.bestPostingTimes || [],
            } : null,
            tiktok: d.tiktok ? {
              title: d.tiktok.title || '',
              scenes: (d.tiktok.scenes || []).slice(0, 5),
              hashtags: d.tiktok.hashtags || [],
              commentBait: d.tiktok.commentBait || '',
              backgroundMusic: d.tiktok.backgroundMusic || null,
              bestPostingTimes: d.tiktok.bestPostingTimes || [],
            } : null,
          })
        } catch {}
      })
  }
  writeFileSync(join(DOCS_DATA, 'social.json'), JSON.stringify(social, null, 2))

  // 3. Runs + Analytics
  const runs = loadRuns()
  writeFileSync(join(DOCS_DATA, 'runs.json'), JSON.stringify(runs, null, 2))

  const analyticsRaw = readJSON(join(OUTPUT, 'analytics.json')) || {}
  const analytics = {
    totalPosts: analyticsRaw.totalPosts || posts.length,
    totalEstimatedRevenue: analyticsRaw.totalEstimatedRevenue || 0,
    runs: runs.slice(0, 30),
  }
  writeFileSync(join(DOCS_DATA, 'analytics.json'), JSON.stringify(analytics, null, 2))

  // 4. Meta (export timestamp, counts)
  const meta = {
    exportedAt: new Date().toISOString(),
    totalPosts: posts.length,
    totalRuns: runs.length,
    totalSocial: social.length,
    lastRunAt: runs[0]?.runAt || null,
    lastKeywords: runs[0]?.keywords || [],
    bloggerTotal: runs.reduce((s, r) => s + (r.platforms?.blogger || 0), 0),
    totalRevenue: analytics.totalEstimatedRevenue,
    repoUrl: 'https://github.com/kevinlee7250/cli',
    actionsUrl: 'https://github.com/kevinlee7250/cli/actions',
  }
  writeFileSync(join(DOCS_DATA, 'meta.json'), JSON.stringify(meta, null, 2))

  console.log(`✅ 정적 데이터 익스포트 완료:`)
  console.log(`   포스트 ${posts.length}개 · 실행이력 ${runs.length}개 · SNS ${social.length}개`)
  console.log(`   → ${DOCS_DATA}`)

  return meta
}

// 직접 실행 시
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  exportStaticData()
}
