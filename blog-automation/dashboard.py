from flask import Flask, jsonify, render_template_string
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

app = Flask(__name__)

LOG_FILE = Path("blog_automation.log")
HISTORY_FILE = Path("posted_keywords.json")

HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>블로그 자동화 대시보드</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }
  header { background: #1e293b; padding: 20px 32px; border-bottom: 1px solid #334155; display: flex; align-items: center; gap: 12px; }
  header h1 { font-size: 1.4rem; font-weight: 700; color: #f8fafc; }
  .badge { background: #22c55e; color: #fff; font-size: 0.7rem; padding: 2px 8px; border-radius: 999px; }
  .badge.off { background: #ef4444; }
  main { padding: 28px 32px; display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; }
  .card { background: #1e293b; border-radius: 12px; padding: 20px; border: 1px solid #334155; }
  .card h2 { font-size: 0.8rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 8px; }
  .card .value { font-size: 2rem; font-weight: 700; color: #f1f5f9; }
  .card .sub { font-size: 0.8rem; color: #64748b; margin-top: 4px; }
  .wide { grid-column: 1 / -1; }
  .log-box { background: #0f172a; border-radius: 8px; padding: 16px; font-family: monospace; font-size: 0.78rem; height: 320px; overflow-y: auto; border: 1px solid #1e293b; }
  .log-line { padding: 2px 0; border-bottom: 1px solid #1e293b22; white-space: pre-wrap; word-break: break-all; }
  .log-line.info { color: #94a3b8; }
  .log-line.warn { color: #fbbf24; }
  .log-line.error { color: #f87171; }
  .log-line.success { color: #34d399; }
  .keywords { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
  .kw-tag { background: #334155; color: #cbd5e1; padding: 4px 10px; border-radius: 6px; font-size: 0.8rem; }
  .schedule { display: flex; gap: 12px; margin-top: 12px; flex-wrap: wrap; }
  .sch-item { background: #334155; border-radius: 8px; padding: 10px 16px; text-align: center; }
  .sch-item .time { font-size: 1.1rem; font-weight: 700; color: #818cf8; }
  .sch-item .label { font-size: 0.7rem; color: #64748b; margin-top: 2px; }
  .btn { background: #6366f1; color: #fff; border: none; padding: 10px 20px; border-radius: 8px; cursor: pointer; font-size: 0.9rem; font-weight: 600; transition: background 0.2s; }
  .btn:hover { background: #4f46e5; }
  .btn:disabled { background: #334155; cursor: not-allowed; }
  .refresh-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
  .last-update { font-size: 0.75rem; color: #475569; }
</style>
</head>
<body>
<header>
  <h1>📊 블로그 자동화 대시보드</h1>
  <span class="badge" id="status-badge">확인 중...</span>
</header>
<main>
  <div class="card">
    <h2>총 발행 포스트</h2>
    <div class="value" id="total-posts">-</div>
    <div class="sub">누적 키워드 수</div>
  </div>
  <div class="card">
    <h2>오늘 발행</h2>
    <div class="value" id="today-posts">-</div>
    <div class="sub" id="today-date">-</div>
  </div>
  <div class="card">
    <h2>마지막 실행</h2>
    <div class="value" style="font-size:1.1rem" id="last-run">-</div>
    <div class="sub" id="last-keyword">-</div>
  </div>
  <div class="card">
    <h2>다음 실행</h2>
    <div class="value" style="font-size:1.1rem" id="next-run">-</div>
    <div class="sub">자동 스케줄</div>
  </div>

  <div class="card wide">
    <h2>스케줄</h2>
    <div class="schedule">
      <div class="sch-item"><div class="time">08:00</div><div class="label">오전</div></div>
      <div class="sch-item"><div class="time">13:00</div><div class="label">오후</div></div>
      <div class="sch-item"><div class="time">18:00</div><div class="label">저녁</div></div>
    </div>
  </div>

  <div class="card wide">
    <h2>발행된 키워드</h2>
    <div class="keywords" id="keywords-list">-</div>
  </div>

  <div class="card wide">
    <div class="refresh-bar">
      <h2>실행 로그</h2>
      <div style="display:flex;gap:8px;align-items:center">
        <span class="last-update" id="last-update"></span>
        <button class="btn" onclick="loadAll()">새로고침</button>
        <button class="btn" id="run-btn" onclick="runNow()">지금 실행</button>
      </div>
    </div>
    <div class="log-box" id="log-box"></div>
  </div>
</main>
<script>
async function loadAll() {
  const [stats, logs] = await Promise.all([
    fetch('/api/stats').then(r => r.json()),
    fetch('/api/logs').then(r => r.json()),
  ]);

  document.getElementById('total-posts').textContent = stats.total;
  document.getElementById('today-posts').textContent = stats.today;
  document.getElementById('today-date').textContent = stats.date;
  document.getElementById('last-run').textContent = stats.last_run || '-';
  document.getElementById('last-keyword').textContent = stats.last_keyword ? '키워드: ' + stats.last_keyword : '';
  document.getElementById('next-run').textContent = stats.next_run || '-';
  document.getElementById('last-update').textContent = '업데이트: ' + new Date().toLocaleTimeString('ko-KR');

  const badge = document.getElementById('status-badge');
  if (stats.running) { badge.textContent = '실행 중'; badge.className = 'badge'; }
  else { badge.textContent = '중지됨'; badge.className = 'badge off'; }

  const kwList = document.getElementById('keywords-list');
  if (stats.keywords.length) {
    kwList.innerHTML = stats.keywords.slice(-20).reverse().map(k => `<span class="kw-tag">${k}</span>`).join('');
  }

  const logBox = document.getElementById('log-box');
  logBox.innerHTML = logs.lines.map(l => {
    let cls = 'info';
    if (l.includes('[WARNING]')) cls = 'warn';
    else if (l.includes('[ERROR]')) cls = 'error';
    else if (l.includes('완료') || l.includes('성공') || l.includes('OK')) cls = 'success';
    return `<div class="log-line ${cls}">${l}</div>`;
  }).join('');
  logBox.scrollTop = logBox.scrollHeight;
}

async function runNow() {
  const btn = document.getElementById('run-btn');
  btn.disabled = true; btn.textContent = '실행 중...';
  await fetch('/api/run', {method: 'POST'});
  setTimeout(() => { btn.disabled = false; btn.textContent = '지금 실행'; loadAll(); }, 5000);
}

loadAll();
setInterval(loadAll, 30000);
</script>
</body>
</html>"""


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/api/stats")
def stats():
    keywords = []
    if HISTORY_FILE.exists():
        keywords = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))

    today = datetime.now().strftime("%Y-%m-%d")
    last_run = "-"
    last_keyword = ""
    today_count = 0

    if LOG_FILE.exists():
        lines = LOG_FILE.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        for line in reversed(lines):
            if "자동 포스팅 시작" in line and last_run == "-":
                last_run = line.split("]")[0].replace("[INFO", "").strip().lstrip("0123456789- :")
                try:
                    last_run = line.split("[INFO]")[1].strip().replace("자동 포스팅 시작: ", "")
                except Exception:
                    pass
            if "업로드 완료" in line:
                try:
                    last_keyword = line.split("]:")[-1].strip()
                except Exception:
                    pass
            if today in line and "업로드 완료" in line:
                today_count += 1

    # 다음 실행 시간 계산
    now = datetime.now()
    schedules = ["08:00", "13:00", "18:00"]
    next_run = "-"
    for t in schedules:
        h, m = map(int, t.split(":"))
        if now.hour < h or (now.hour == h and now.minute < m):
            next_run = f"오늘 {t}"
            break
    if next_run == "-":
        next_run = f"내일 {schedules[0]}"

    # 프로세스 확인
    running = False
    try:
        result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq pythonw.exe"],
                                capture_output=True, text=True)
        running = "pythonw.exe" in result.stdout
    except Exception:
        pass

    return jsonify({
        "total": len(keywords),
        "today": today_count,
        "date": today,
        "keywords": keywords,
        "last_run": last_run,
        "last_keyword": last_keyword,
        "next_run": next_run,
        "running": running,
    })


@app.route("/api/logs")
def logs():
    if not LOG_FILE.exists():
        return jsonify({"lines": ["로그 파일 없음"]})
    lines = LOG_FILE.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    return jsonify({"lines": lines[-100:]})


@app.route("/api/run", methods=["POST"])
def run_now():
    try:
        subprocess.Popen([sys.executable, "main.py", "--once"],
                         creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


if __name__ == "__main__":
    import threading, webbrowser, os

    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]

    def open_chrome():
        import time; time.sleep(1)
        for path in chrome_paths:
            if os.path.exists(path):
                subprocess.Popen([path, "http://localhost:5000"])
                return
        webbrowser.open("http://localhost:5000")

    threading.Thread(target=open_chrome, daemon=True).start()
    print("대시보드 시작: http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
