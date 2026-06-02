"""
GitHub Secrets 자동 등록 스크립트
.env 파일을 읽어서 GitHub Actions Secrets에 자동 등록합니다.
"""
import subprocess, sys
from pathlib import Path

def install(pkg):
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])

try:
    import requests
    from nacl import encoding, public
    import base64
except ImportError:
    print("필요 패키지 설치 중...")
    install("requests")
    install("PyNaCl")
    import requests
    from nacl import encoding, public
    import base64

REPO = "Kevinlee7250/cli"
SECRET_KEYS = [
    "ANTHROPIC_API_KEY",
    "BLOGGER_CLIENT_ID",
    "BLOGGER_CLIENT_SECRET",
    "BLOGGER_BLOG_ID",
    "BLOGGER_REFRESH_TOKEN",
]

def load_env(env_path: str) -> dict:
    values = {}
    with open(env_path, encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                values[k.strip()] = v.strip().strip('"').strip("'")
    return values

def encrypt_secret(public_key_str: str, secret_value: str) -> str:
    key = public.PublicKey(public_key_str.encode("utf-8"), encoding.Base64Encoder)
    box = public.SealedBox(key)
    encrypted = box.encrypt(secret_value.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")

def set_secrets(token: str, secrets: dict):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    r = requests.get(
        f"https://api.github.com/repos/{REPO}/actions/secrets/public-key",
        headers=headers
    )
    if r.status_code != 200:
        print(f"[오류] 공개키 조회 실패: {r.status_code}")
        print("토큰에 'repo' 권한이 있는지 확인하세요.")
        return False

    key_data = r.json()
    pub_key = key_data["key"]
    key_id  = key_data["key_id"]

    for name, value in secrets.items():
        if not value:
            print(f"  [SKIP] {name} (값 없음)")
            continue
        encrypted = encrypt_secret(pub_key, value)
        resp = requests.put(
            f"https://api.github.com/repos/{REPO}/actions/secrets/{name}",
            headers=headers,
            json={"encrypted_value": encrypted, "key_id": key_id}
        )
        if resp.status_code in (201, 204):
            print(f"  [OK] {name}")
        else:
            print(f"  [FAIL] {name}: {resp.status_code}")
    return True

def main():
    print("=" * 50)
    print("  GitHub Secrets 자동 등록")
    print("=" * 50)

    script_dir = Path(__file__).parent
    env_path = script_dir / ".env"
    if not env_path.exists():
        print(f"[오류] .env 파일 없음: {env_path}")
        return

    env = load_env(str(env_path))
    secrets = {k: env.get(k, "") for k in SECRET_KEYS}

    print("\n.env에서 읽은 항목:")
    for k, v in secrets.items():
        masked = v[:6] + "..." if len(v) > 6 else v
        print(f"  {k}: {masked}")

    print()
    print("GitHub Personal Access Token 발급 방법:")
    print("  1. https://github.com/settings/tokens/new 접속")
    print("  2. Note: blog-automation")
    print("  3. Expiration: 30 days")
    print("  4. Scopes: [repo] 전체 체크")
    print("  5. Generate token 후 복사")
    print()
    token = input("GitHub 토큰 입력: ").strip()
    if not token:
        print("취소됨")
        return

    print("\n등록 중...")
    set_secrets(token, secrets)
    print(f"\n완료! 확인: https://github.com/{REPO}/actions")

if __name__ == "__main__":
    main()
