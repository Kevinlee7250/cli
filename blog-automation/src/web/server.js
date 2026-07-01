import express from 'express'
import { createReadStream, readFileSync, writeFileSync, existsSync, readdirSync, statSync } from 'fs'
import { join, dirname, basename } from 'path'
import { fileURLToPath } from 'url'
import { spawn } from 'child_process'
import { config } from '../config.js'

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT = join(__dirname, '../..')
const OUTPUT = join(ROOT, 'output')
// Python dashboard_exporter가 내보내는 docs/data 디렉토리 (GitHub Pages용 + 서버 겸용)
const DOCS_DATA = join(ROOT, '..', 'docs', 'data')
const LOGS = join(ROOT, 'logs/automation.log')

const app = express()
app.use(express.json())
app.use(express.static(join(__dirname, 'public')))

// ── Helpers ──────────────────────────────────────────────────────────────────

function readJSON(path) {
  try { return JSON.parse(readFileSync(path, 'utf8')) } catch { return null }
}

function listJSONDir(dir) {
  if (!existsSync(dir)) return []
  return readdirSync(dir)
    .filter(f => f.endsWith('.json'))
    .map(f => ({ file: f, ...statSync(join(dir, f)) }))
    .sort((a, b) => b.mtimeMs - a.mtimeMs)
}

function mask(str) {
  if (!str) return '미설정'
  return str.slice(0, 6) + '••••••••' + str.slice(-4)
}

// ── API: Status ───────────────────────────────────────────────────────────────

function loadRuns() {
  // Prefer docs/data/runs.json (written by dashboard_exporter.py — includes blogId/blogName)
  const docsRuns = readJSON(join(DOCS_DATA, 'runs.json'))
  if (Array.isArray(docsRuns) && docsRuns.length) {
    return docsRuns.map(r => ({ ...r, runAt: r.runAt || r.savedAt }))
  }
  // Fallback: analytics.json
  const analytics = readJSON(join(OUTPUT, 'analytics.json'))
  if (analytics?.runs?.length) {
    return analytics.runs.map(r => ({ ...r, runAt: r.runAt || r.savedAt }))
  }
  // Fallback: run-history.json
  const raw = readJSON(join(OUTPUT, 'run-history.json'))
  const runs = Array.isArray(raw) ? raw : (raw?.runs || [])
  return runs.map(r => ({ ...r, runAt: r.runAt || r.savedAt }))
}

app.get('/api/status', (req, res) => {
  // Prefer docs/data/meta.json (written by dashboard_exporter.py)
  const meta = readJSON(join(DOCS_DATA, 'meta.json')) || {}
  const analytics = readJSON(join(OUTPUT, 'analytics.json')) || {}
  const runs = loadRuns()
  const posts = listJSONDir(join(OUTPUT, 'posts'))
  const lastRun = runs[0] || null
  const today = new Date().toISOString().split('T')[0]

  res.json({
    totalPosts: meta.totalPosts || analytics.totalPosts || posts.length,
    totalRevenue: meta.totalEstimatedRevenue || analytics.totalEstimatedRevenue || 0,
    lastRunAt: lastRun?.savedAt || lastRun?.runAt || null,
    lastRunKeywords: lastRun?.keywords || [],
    bloggerPosts: runs.reduce((s, r) => s + (r.platforms?.blogger || 0), 0),
    runCount: runs.length,
    postsToday: runs.filter(r => r.date === today).length,
  })
})

// ── API: Blogs ────────────────────────────────────────────────────────────────

app.get('/api/blogs', (req, res) => {
  // docs/data/blogs.json written by dashboard_exporter.py; fallback to blogs.json in project root
  const data = readJSON(join(DOCS_DATA, 'blogs.json'))
    || readJSON(join(ROOT, 'blogs.json'))
    || []
  res.json(data)
})

// ── API: Posts ────────────────────────────────────────────────────────────────

app.get('/api/posts', (req, res) => {
  // Build a lookup from docs/data/posts.json for enriched fields (blogId, blogName, articleType)
  const docsPosts = readJSON(join(DOCS_DATA, 'posts.json')) || []
  const docsMap = {}
  for (const p of docsPosts) {
    if (p.id) docsMap[p.id] = p
  }

  const files = listJSONDir(join(OUTPUT, 'posts'))
  const posts = files.map(({ file }) => {
    const data = readJSON(join(OUTPUT, 'posts', file)) || {}
    const id = file.replace('.json', '')
    const extra = docsMap[id] || {}
    return {
      id,
      title: data.title || file,
      keyword: data.keyword || '',
      date: data.date || file.slice(0, 10),
      wordCount: data.wordCount || 0,
      faqCount: data.faq?.length || 0,
      adsenseCategory: data.adsenseCategory || '일반',
      estimatedCPC: data.estimatedCPC || 0.5,
      trendDirection: data.trendDirection || 'stable',
      factCheck: data.factCheck || null,
      metaDescription: data.metaDescription || '',
      tags: data.tags || [],
      publishStatus: data.publishStatus || 'published',
      bloggerUrl: data.bloggerUrl || null,
      blogId: data.blogId || extra.blogId || '',
      blogName: data.blogName || extra.blogName || '',
      articleType: data.article_type || extra.articleType || '',
    }
  })
  res.json(posts)
})

app.get('/api/posts/:id', (req, res) => {
  const file = join(OUTPUT, 'posts', req.params.id + '.json')
  const data = readJSON(file)
  if (!data) return res.status(404).json({ error: '포스트를 찾을 수 없습니다' })
  res.json(data)
})

app.put('/api/posts/:id', (req, res) => {
  const file = join(OUTPUT, 'posts', req.params.id + '.json')
  const existing = readJSON(file)
  if (!existing) return res.status(404).json({ error: '포스트를 찾을 수 없습니다' })
  const allowed = ['title', 'metaDescription', 'tags', 'content', 'faq']
  const updated = { ...existing }
  for (const key of allowed) {
    if (req.body[key] !== undefined) updated[key] = req.body[key]
  }
  updated.updatedAt = new Date().toISOString()
  try {
    writeFileSync(file, JSON.stringify(updated, null, 2), 'utf-8')
    res.json({ ok: true })
  } catch (err) {
    res.status(500).json({ error: err.message })
  }
})

app.post('/api/posts/:id/publish', async (req, res) => {
  const file = join(OUTPUT, 'posts', req.params.id + '.json')
  const post = readJSON(file)
  if (!post) return res.status(404).json({ error: '포스트를 찾을 수 없습니다' })
  try {
    const { publishToBlogger } = await import('../publishers/blogger.js')
    const result = await publishToBlogger(post, { isDraft: false })
    if (result?.error) return res.status(500).json({ error: result.error })
    post.publishStatus = 'published'
    post.bloggerUrl = result?.url || null
    post.publishedAt = new Date().toISOString()
    writeFileSync(file, JSON.stringify(post, null, 2), 'utf-8')
    res.json({ ok: true, url: result?.url })
  } catch (err) {
    res.status(500).json({ error: err.message })
  }
})

app.delete('/api/posts/:id', (req, res) => {
  const file = join(OUTPUT, 'posts', req.params.id + '.json')
  const post = readJSON(file)
  if (!post) return res.status(404).json({ error: '포스트를 찾을 수 없습니다' })
  post.publishStatus = 'rejected'
  post.rejectedAt = new Date().toISOString()
  try {
    writeFileSync(file, JSON.stringify(post, null, 2), 'utf-8')
    res.json({ ok: true })
  } catch (err) {
    res.status(500).json({ error: err.message })
  }
})

// ── API: Thumbnails ───────────────────────────────────────────────────────────

app.get('/api/thumbnail/:name', (req, res) => {
  const file = join(OUTPUT, 'thumbnails', req.params.name)
  if (!existsSync(file)) return res.status(404).send('Not found')
  res.setHeader('Content-Type', 'image/png')
  createReadStream(file).pipe(res)
})

app.get('/api/thumbnails', (req, res) => {
  const dir = join(OUTPUT, 'thumbnails')
  if (!existsSync(dir)) return res.json([])
  const files = readdirSync(dir).filter(f => f.endsWith('.png') && !f.includes('_vertical'))
  res.json(files)
})

// ── API: Social Content ───────────────────────────────────────────────────────

app.get('/api/social', (req, res) => {
  const files = listJSONDir(join(OUTPUT, 'social'))
  const list = files.map(({ file }) => ({
    id: file.replace('.json', ''),
    date: file.slice(0, 10),
    keyword: file.slice(11).replace('_social.json', '').replace(/_/g, ' '),
  }))
  res.json(list)
})

app.get('/api/social/:id', (req, res) => {
  const file = join(OUTPUT, 'social', req.params.id + '.json')
  const data = readJSON(file)
  if (!data) return res.status(404).json({ error: '소셜 콘텐츠를 찾을 수 없습니다' })
  res.json(data)
})

// ── API: Run History & Analytics ──────────────────────────────────────────────

app.get('/api/runs', (req, res) => {
  res.json(loadRuns())
})

app.get('/api/analytics', (req, res) => {
  const data = readJSON(join(OUTPUT, 'analytics.json')) || {}
  res.json(data)
})

// ── API: Logs ─────────────────────────────────────────────────────────────────

app.get('/api/logs', (req, res) => {
  if (!existsSync(LOGS)) return res.json({ lines: [] })
  const content = readFileSync(LOGS, 'utf8')
  const lines = content.split('\n').filter(Boolean).slice(-200)
  res.json({ lines })
})

// ── API: Config ───────────────────────────────────────────────────────────────

app.get('/api/config', (req, res) => {
  res.json({
    anthropicKey: mask(config.anthropic.apiKey),
    anthropicModel: config.anthropic.model,
    naverClientId: mask(config.naver.clientId),
    googleClientId: mask(config.google.clientId),
    googleRefreshToken: mask(config.google.refreshToken),
    bloggerBlogId: config.blogger.blogId || '미설정',
    postsPerRun: config.content.postsPerRun,
    scheduleCron: config.schedule?.cron || '0 9 * * *',
    country: config.google.country || 'KR',
  })
})

// ── API: Run Automation (SSE streaming) ───────────────────────────────────────

let runningProcess = null

app.get('/api/run/status', (req, res) => {
  res.json({ running: !!runningProcess })
})

app.post('/api/run', (req, res) => {
  if (runningProcess) return res.status(409).json({ error: '이미 실행 중입니다' })
  const { mode = 'publish' } = req.body
  const args = mode === 'draft' ? ['--draft'] : mode === 'preview' ? ['--preview'] : []

  runningProcess = spawn('node', ['src/index.js', ...args], {
    cwd: ROOT, env: { ...process.env },
  })

  let output = ''
  runningProcess.stdout.on('data', d => { output += d })
  runningProcess.stderr.on('data', d => { output += d })
  runningProcess.on('close', code => {
    runningProcess = null
  })

  res.json({ started: true, mode })
})

app.get('/api/run/stream', (req, res) => {
  res.setHeader('Content-Type', 'text/event-stream')
  res.setHeader('Cache-Control', 'no-cache')
  res.setHeader('Connection', 'keep-alive')
  res.flushHeaders()

  // Tail the log file for live output
  const send = (data) => res.write(`data: ${JSON.stringify(data)}\n\n`)

  send({ type: 'status', running: !!runningProcess })

  if (!existsSync(LOGS)) {
    send({ type: 'error', message: '로그 파일 없음' })
    return res.end()
  }

  // Send last 50 lines immediately
  const content = readFileSync(LOGS, 'utf8')
  const lines = content.split('\n').filter(Boolean).slice(-50)
  lines.forEach(line => send({ type: 'log', line: stripAnsi(line) }))

  // Poll for new lines
  let lastSize = statSync(LOGS).size
  const interval = setInterval(() => {
    try {
      const current = statSync(LOGS).size
      if (current > lastSize) {
        const stream = createReadStream(LOGS, { start: lastSize, end: current })
        let buf = ''
        stream.on('data', d => { buf += d })
        stream.on('end', () => {
          buf.split('\n').filter(Boolean).forEach(line =>
            send({ type: 'log', line: stripAnsi(line) })
          )
        })
        lastSize = current
      }
      send({ type: 'status', running: !!runningProcess })
    } catch {}
  }, 800)

  req.on('close', () => clearInterval(interval))
})

function stripAnsi(str) {
  return str.replace(/\x1B\[[0-9;]*m/g, '')
}

// ── API: Stop run ─────────────────────────────────────────────────────────────

app.post('/api/run/stop', (req, res) => {
  if (!runningProcess) return res.json({ stopped: false })
  runningProcess.kill('SIGTERM')
  runningProcess = null
  res.json({ stopped: true })
})

// ── Start server ──────────────────────────────────────────────────────────────

const PORT = process.env.WEB_PORT || 4000
app.listen(PORT, () => {
  console.log(`\n🌐 블로그 자동화 관리 대시보드`)
  console.log(`   http://localhost:${PORT}\n`)
})
