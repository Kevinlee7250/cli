"""
Google OAuth Refresh Token 발급 스크립트
실행: python get_refresh_token.py
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

if not CLIENT_ID or not CLIENT_SECRET:
    print("GOOGLE_CLIENT_ID와 GOOGLE_CLIENT_SECRET을 입력하세요.")
    CLIENT_ID = input("GOOGLE_CLIENT_ID: ").strip()
    CLIENT_SECRET = input("GOOGLE_CLIENT_SECRET: ").strip()
REDIRECT_URI = "http://localhost:8080"
SCOPE = "https://www.googleapis.com/auth/blogger"

_auth_code = None


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        global _auth_code
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
        _auth_code = params.get("code", "")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("<h2>인증 완료! 이 창을 닫아도 됩니다.</h2>".encode("utf-8"))

    def log_message(self, *args):
        pass  # 불필요한 로그 숨김


def main():
    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        + urllib.parse.urlencode({
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
        })
    )

    print("=" * 60)
    print("Google OAuth Refresh Token 발급")
    print("=" * 60)
    print("\n브라우저에서 Google 로그인 후 Blogger 권한을 허용하세요.")
    print("브라우저가 자동으로 열립니다...\n")

    webbrowser.open(auth_url)

    server = HTTPServer(("localhost", 8080), _Handler)
    server.handle_request()  # 1회만 처리

    if not _auth_code:
        print("❌ 인증 코드를 받지 못했습니다.")
        return

    # authorization code → tokens 교환
    data = urllib.parse.urlencode({
        "code": _auth_code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }).encode()

    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            tokens = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"❌ 토큰 교환 실패 (HTTP {e.code}): {body}")
        return
    except Exception as e:
        print(f"❌ 토큰 교환 오류: {e}")
        return

    refresh_token = tokens.get("refresh_token", "")
    if not refresh_token:
        print("❌ Refresh Token을 받지 못했습니다.")
        print("응답:", tokens)
        return

    print("\n" + "=" * 60)
    print("✅ Refresh Token 발급 성공!")
    print("=" * 60)
    print(f"\nGOOGLE_REFRESH_TOKEN={refresh_token}\n")
    print("위 값을 GitHub Secrets에 등록하세요:")
    print("https://github.com/kevinlee7250/cli/settings/secrets/actions")
    print("=" * 60)


if __name__ == "__main__":
    main()
