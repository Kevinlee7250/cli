#!/usr/bin/env python3
"""
Blogger API OAuth 인증 설정 도우미
처음 한 번만 실행하면 Refresh Token을 발급받을 수 있습니다.
"""

import json
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import requests
from dotenv import load_dotenv
import os

load_dotenv()

CLIENT_ID = os.getenv("BLOGGER_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("BLOGGER_CLIENT_SECRET", "")
REDIRECT_URI = "http://localhost:8080"
SCOPE = "https://www.googleapis.com/auth/blogger"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"

received_code = None


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global received_code
        params = parse_qs(urlparse(self.path).query)
        if "code" in params:
            received_code = params["code"][0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<h1>인증 완료! 터미널로 돌아가세요.</h1>")
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"<h1>인증 실패</h1>")

    def log_message(self, *args):
        pass


def main():
    if not CLIENT_ID or not CLIENT_SECRET:
        print("[오류] .env 파일에 BLOGGER_CLIENT_ID와 BLOGGER_CLIENT_SECRET을 설정하세요.")
        return

    auth_url = (
        f"{AUTH_URL}?client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={SCOPE}"
        f"&access_type=offline"
        f"&prompt=consent"
    )

    print("브라우저에서 Google 계정 인증을 진행하세요...")
    webbrowser.open(auth_url)

    server = HTTPServer(("localhost", 8080), CallbackHandler)
    print("콜백 대기 중 (localhost:8080)...")
    server.handle_request()

    if not received_code:
        print("[오류] 인증 코드를 받지 못했습니다.")
        return

    resp = requests.post(TOKEN_URL, data={
        "code": received_code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    })

    if resp.status_code == 200:
        tokens = resp.json()
        refresh_token = tokens.get("refresh_token", "")
        print(f"\n✅ 인증 성공!")
        print(f"REFRESH_TOKEN: {refresh_token}")
        print("\n.env 파일에 아래 줄을 추가하세요:")
        print(f'BLOGGER_REFRESH_TOKEN="{refresh_token}"')
    else:
        print(f"[오류] 토큰 발급 실패: {resp.text}")


if __name__ == "__main__":
    main()
