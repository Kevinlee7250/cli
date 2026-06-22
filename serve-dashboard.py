#!/usr/bin/env python3
"""
블로그 자동화 대시보드 로컬 서버
실행: python3 serve-dashboard.py
"""
import http.server
import os
import platform
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

PORT = 8787
DOCS_DIR = Path(__file__).parent / "docs"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DOCS_DIR), **kwargs)

    def log_message(self, fmt, *args):
        # Only log non-asset requests
        path = args[0] if args else ''
        if not any(path.endswith(ext) for ext in ['.json', '.js', '.css', '.ico', '.png']):
            print(f"  [{self.log_date_time_string()}] {fmt % args}")

    def end_headers(self):
        # Allow CORS for local fetch requests
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        super().end_headers()


def open_browser(url: str):
    """OS별 Chrome 또는 기본 브라우저로 URL 열기"""
    time.sleep(0.8)
    system = platform.system()

    # Try Chrome first
    chrome_paths = {
        'Darwin': [
            '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
            '/Applications/Chromium.app/Contents/MacOS/Chromium',
        ],
        'Windows': [
            r'C:\Program Files\Google\Chrome\Application\chrome.exe',
            r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
        ],
        'Linux': ['google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser'],
    }

    paths = chrome_paths.get(system, [])
    for chrome in paths:
        try:
            if system == 'Linux':
                result = subprocess.run(['which', chrome], capture_output=True, text=True)
                if result.returncode == 0:
                    subprocess.Popen([chrome, url])
                    return
            elif os.path.exists(chrome):
                subprocess.Popen([chrome, url])
                return
        except Exception:
            continue

    # Fallback: default browser
    webbrowser.open(url)


def main():
    if not DOCS_DIR.exists():
        print(f"❌ docs/ 폴더를 찾을 수 없습니다: {DOCS_DIR}")
        sys.exit(1)

    if not (DOCS_DIR / 'index.html').exists():
        print(f"❌ docs/index.html 파일이 없습니다.")
        sys.exit(1)

    url = f"http://localhost:{PORT}"
    print("=" * 52)
    print("  🤖 블로그 자동화 대시보드 로컬 서버")
    print("=" * 52)
    print(f"  📊 URL   : {url}")
    print(f"  📁 경로  : {DOCS_DIR}")
    print(f"  🔄 데이터: {DOCS_DIR / 'data'}")
    print("-" * 52)
    print("  Ctrl+C 로 종료")
    print("=" * 52)

    # Open browser in background thread
    threading.Thread(target=open_browser, args=(url,), daemon=True).start()

    try:
        with http.server.HTTPServer(('', PORT), Handler) as httpd:
            print(f"\n  ✅ 서버 시작됨 → 크롬에서 {url} 열기...\n")
            httpd.serve_forever()
    except OSError as e:
        if 'Address already in use' in str(e):
            print(f"\n❌ 포트 {PORT}가 사용 중입니다.")
            print(f"   다른 터미널에서 이미 실행 중이거나:")
            print(f"   lsof -ti:{PORT} | xargs kill -9  # 기존 프로세스 종료")
        else:
            print(f"\n❌ 서버 오류: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n  👋 서버 종료")


if __name__ == '__main__':
    main()
