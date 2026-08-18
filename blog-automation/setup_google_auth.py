"""Google 인증 한 번에 끝내기 — 준비 확인 → 발급 → 검증까지.

브라우저에서 "허용"을 누르는 것만 사람이 하고, 나머지는 이 스크립트가 합니다.

기존 get_refresh_token.py는 토큰을 받아 출력하는 데서 끝났습니다. 그런데
2026-08-18 점검에서 드러난 문제는 "토큰을 받았지만 권한이 모자랐다"는 것이었고,
그 사실이 몇 달 뒤 사이트맵 403으로만 드러났습니다. 그래서 이 스크립트는
받은 직후에 권한을 검증하고, 모자라면 그 자리에서 알려줍니다.

하는 일:
  1) 사전 점검 — client id/secret, 8080 포트, 리디렉션 URI 안내
  2) 브라우저 동의 → 인증 코드 수신 → 토큰 교환
  3) 발급된 권한 검증 (webmasters 쓰기 권한이 실제로 붙었는지)
  4) Search Console 속성 목록을 실제로 조회해 연결 확인
  5) 다음 할 일 안내 (GitHub Secrets 등록, 이전 토큰 취소)

⚠️ 반드시 로컬에서 실행하세요. 이 저장소는 공개 포크이므로 GitHub Actions에서
   토큰을 교환하면 값이 그대로 노출됩니다.

Usage:
  cd blog-automation
  export GOOGLE_CLIENT_ID='...'
  export GOOGLE_CLIENT_SECRET='...'
  python setup_google_auth.py
  python setup_google_auth.py --save-env    # 로컬 .env에도 저장 (git 무시됨)
"""

import argparse
import json
import os
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

REDIRECT_URI = "http://localhost:8080"
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GSC_SITES_API = "https://www.googleapis.com/webmasters/v3/sites"

BLOGGER = "https://www.googleapis.com/auth/blogger"
WEBMASTERS = "https://www.googleapis.com/auth/webmasters"          # 쓰기 포함
ADSENSE = "https://www.googleapis.com/auth/adsense.readonly"
SCOPES = [BLOGGER, WEBMASTERS, ADSENSE]

# 없으면 무엇이 망가지는지 — 검증 실패 시 그대로 보여줍니다
_SCOPE_PURPOSE = {
    BLOGGER: "글 발행·수정",
    WEBMASTERS: "사이트맵 제출·색인 요청 (읽기 전용이면 403)",
    ADSENSE: "실제 수익 조회 (AdSense 승인 후 사용)",
}

_result: dict = {}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
        _result["code"] = params.get("code", "")
        _result["error"] = params.get("error", "")
        ok = bool(_result["code"])
        body = (
            "<h2>인증 완료 — 이 창을 닫고 터미널로 돌아가세요.</h2>"
            if ok else
            f"<h2>인증이 취소되었거나 실패했습니다: {_result['error']}</h2>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, *args):
        pass


def _port_is_free(port: int = 8080) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("localhost", port))
            return True
        except OSError:
            return False


def _mask(value: str) -> str:
    """값을 알아볼 수 있을 만큼만 보여줍니다 (전체 노출 금지)."""
    if len(value) <= 12:
        return value[:4] + "…" + f" (길이 {len(value)})"
    return f"{value[:12]}…{value[-6:]} (길이 {len(value)})"


def _validate_credentials(client_id: str, client_secret: str) -> tuple[str, str]:
    """자격증명 형식을 확인합니다.

    형식이 틀리면 구글은 "401 invalid_client"만 돌려주고 이유를 말해주지 않아,
    자리표시자를 그대로 넣었는지 따옴표가 섞였는지 알 수 없습니다.
    브라우저를 열기 전에 여기서 걸러냅니다.
    """
    # cmd에서 set X="값" 으로 넣으면 따옴표까지 값에 포함됨
    stripped_id = client_id.strip().strip('"').strip("'")
    stripped_secret = client_secret.strip().strip('"').strip("'")
    if stripped_id != client_id or stripped_secret != client_secret:
        print("\n⚠️ 값에 따옴표가 섞여 있어 제거했습니다.")
        print("   (cmd의 set은 따옴표를 값의 일부로 취급합니다 — set X=값 형태로 넣으세요)")
        client_id, client_secret = stripped_id, stripped_secret

    problems = []
    if not client_id.endswith(".apps.googleusercontent.com"):
        problems.append(
            "GOOGLE_CLIENT_ID가 '.apps.googleusercontent.com'으로 끝나지 않습니다"
        )
    if not client_secret.startswith("GOCSPX-"):
        # 예전에 발급된 시크릿은 다른 형식일 수 있어 경고만 합니다
        print("\n⚠️ GOOGLE_CLIENT_SECRET이 'GOCSPX-'로 시작하지 않습니다 "
              "(오래된 클라이언트라면 정상일 수 있습니다)")
    if any(ord(c) > 127 for c in client_id):
        problems.append("GOOGLE_CLIENT_ID에 한글이 들어 있습니다 — 안내문을 그대로 붙여넣지 않았는지 확인하세요")

    print("\n[자격증명 확인]")
    print(f"    client_id     : {_mask(client_id)}")
    print(f"    client_secret : {_mask(client_secret)}")

    if problems:
        print("\n❌ 이 값으로는 구글이 '401 invalid_client'를 돌려줍니다:")
        for p in problems:
            print(f"    · {p}")
        print("\n   https://console.cloud.google.com/apis/credentials 에서")
        print("   OAuth 2.0 클라이언트 ID 항목을 열어 값을 다시 복사하세요.")
        sys.exit(1)

    return client_id, client_secret


def preflight() -> tuple[str, str]:
    """자격증명과 실행 환경을 확인합니다. 실패하면 종료."""
    print("=" * 64)
    print("  Google 인증 설정 (로컬 전용)")
    print("=" * 64)

    if os.getenv("GITHUB_ACTIONS") == "true":
        print("\n❌ GitHub Actions에서는 실행할 수 없습니다.")
        print("   이 저장소는 공개 포크라 토큰이 로그·아티팩트로 노출됩니다.")
        sys.exit(1)

    client_id = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()
    if not client_id:
        client_id = input("GOOGLE_CLIENT_ID: ").strip()
    if not client_secret:
        client_secret = input("GOOGLE_CLIENT_SECRET: ").strip()
    if not (client_id and client_secret):
        print("\n❌ client id/secret이 없으면 진행할 수 없습니다.")
        sys.exit(1)

    client_id, client_secret = _validate_credentials(client_id, client_secret)

    if not _port_is_free():
        print("\n❌ 8080 포트를 다른 프로그램이 쓰고 있습니다.")
        print("   해당 프로그램을 종료한 뒤 다시 실행하세요.")
        sys.exit(1)

    print("\n[사전 확인] Google Cloud Console에 아래 리디렉션 URI가 등록돼 있어야 합니다:")
    print(f"    {REDIRECT_URI}")
    print("    (API 및 서비스 → 사용자 인증 정보 → 해당 OAuth 클라이언트 → 승인된 리디렉션 URI)")
    print("\n[요청할 권한]")
    for s in SCOPES:
        print(f"    · {s.rsplit('/', 1)[-1]:<22} {_SCOPE_PURPOSE[s]}")
    print("\n동의 화면에서 Search Console 항목이 '보기 및 관리'인지 꼭 확인하세요.")
    print("'보기'만 있으면 사이트맵 제출이 또 403으로 실패합니다.")
    input("\n준비되면 Enter를 눌러 브라우저를 엽니다... ")
    return client_id, client_secret


def authorize(client_id: str) -> str:
    """브라우저 동의를 받아 인증 코드를 돌려줍니다."""
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",          # 항상 새 refresh_token을 받기 위해
    })
    print("\n브라우저가 열리지 않으면 아래 주소를 직접 여세요:\n")
    print(url + "\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass

    print("브라우저에서 로그인·동의를 기다리는 중...")
    HTTPServer(("localhost", 8080), _Handler).handle_request()

    if _result.get("error"):
        print(f"\n❌ 인증이 거부되었습니다: {_result['error']}")
        sys.exit(1)
    if not _result.get("code"):
        print("\n❌ 인증 코드를 받지 못했습니다.")
        sys.exit(1)
    return _result["code"]


def exchange(code: str, client_id: str, client_secret: str) -> dict:
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request(
        TOKEN_URL, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"\n❌ 토큰 교환 실패 (HTTP {e.code}): {body[:300]}")
        if "redirect_uri_mismatch" in body:
            print(f"   → Google Cloud Console에 {REDIRECT_URI} 를 추가하세요.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 토큰 교환 오류: {e}")
        sys.exit(1)


def verify_scopes(granted: str) -> list[str]:
    """받은 권한을 확인하고, 빠진 항목을 반환합니다.

    부분 문자열로 비교하면 webmasters.readonly가 webmasters를 포함해
    통과해버리므로 공백으로 쪼개 정확히 일치하는지 봅니다.
    """
    granted_set = set((granted or "").split())
    return [s for s in SCOPES if s not in granted_set]


def verify_live(access_token: str) -> None:
    """실제 API를 호출해 Search Console 연결을 확인합니다 (읽기만)."""
    req = urllib.request.Request(
        GSC_SITES_API, headers={"Authorization": f"Bearer {access_token}"})
    try:
        with urllib.request.urlopen(req) as resp:
            entries = json.loads(resp.read()).get("siteEntry", [])
    except Exception as e:
        print(f"\n⚠️ Search Console 속성 조회 실패 (토큰 자체는 발급됨): {e}")
        return
    if not entries:
        print("\n⚠️ 접근 가능한 Search Console 속성이 없습니다.")
        print("   블로그를 Search Console에 먼저 등록해야 색인이 시작됩니다.")
        return
    print(f"\n[연결 확인] Search Console 속성 {len(entries)}개:")
    for s in entries:
        print(f"    · {s.get('siteUrl', '')}  ({s.get('permissionLevel', '')})")


def save_env(refresh_token: str) -> None:
    """로컬 .env에 저장합니다 (.gitignore로 제외되어 커밋되지 않음)."""
    path = os.path.join(os.path.dirname(__file__), ".env")
    lines = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines()
                     if not ln.startswith("GOOGLE_REFRESH_TOKEN=")]
    lines.append(f'GOOGLE_REFRESH_TOKEN="{refresh_token}"')
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\n💾 {path} 에 저장했습니다 (git이 무시하는 파일입니다)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Google 인증 설정")
    parser.add_argument("--save-env", action="store_true",
                        help="로컬 .env에도 저장 (git에 커밋되지 않음)")
    args = parser.parse_args()

    client_id, client_secret = preflight()
    code = authorize(client_id)
    tokens = exchange(code, client_id, client_secret)

    refresh_token = tokens.get("refresh_token", "")
    if not refresh_token:
        print("\n❌ Refresh Token이 응답에 없습니다.")
        print("   구글 계정 → 보안 → 서드파티 앱 액세스에서 기존 권한을 취소한 뒤 다시 시도하세요.")
        return 1

    missing = verify_scopes(tokens.get("scope", ""))
    if missing:
        print("\n" + "=" * 64)
        print("❌ 권한이 모자란 채로 발급됐습니다 — 이 토큰을 쓰면 안 됩니다.")
        print("=" * 64)
        for s in missing:
            print(f"    빠짐: {s.rsplit('/', 1)[-1]}  → {_SCOPE_PURPOSE[s]}")
        print("\n동의 화면에서 일부 항목의 체크를 해제하면 이렇게 됩니다.")
        print("다시 실행해 모든 항목을 허용해 주세요.")
        return 1

    print("\n" + "=" * 64)
    print("✅ 발급 성공 — 필요한 권한이 모두 붙었습니다")
    print("=" * 64)

    verify_live(tokens.get("access_token", ""))

    if args.save_env:
        save_env(refresh_token)

    print("\n[다음 할 일]")
    print("  1) 아래 값을 GitHub Secrets의 GOOGLE_REFRESH_TOKEN 에 덮어쓰기")
    print("     https://github.com/Kevinlee7250/cli/settings/secrets/actions")
    print("  2) 구글 계정 → 보안 → 서드파티 앱 액세스에서 이전 권한 취소")
    print("     (노출됐을 수 있는 옛 토큰을 무효화하는 유일한 방법입니다)")
    print("  3) 대시보드에서 '구글 색인 점검' 워크플로 실행 → 사이트맵 제출 확인")
    print("\n" + "-" * 64)
    print(f"GOOGLE_REFRESH_TOKEN={refresh_token}")
    print("-" * 64)
    print("⚠️ 이 값은 비밀번호와 같습니다. 채팅·이슈·커밋에 붙여넣지 마세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
