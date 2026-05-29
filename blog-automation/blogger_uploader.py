import requests
import logging
from config import (
    BLOGGER_CLIENT_ID,
    BLOGGER_CLIENT_SECRET,
    BLOGGER_BLOG_ID,
    BLOGGER_REFRESH_TOKEN,
    POST_STATUS,
)

logger = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"


def _get_access_token() -> str | None:
    """Refresh Token으로 Access Token을 발급합니다."""
    resp = requests.post(TOKEN_URL, data={
        "client_id": BLOGGER_CLIENT_ID,
        "client_secret": BLOGGER_CLIENT_SECRET,
        "refresh_token": BLOGGER_REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }, timeout=15)

    if resp.status_code == 200:
        return resp.json().get("access_token")
    logger.error(f"토큰 발급 실패: {resp.status_code} {resp.text}")
    return None


def upload_post(post_data: dict) -> dict | None:
    """Blogger API로 포스트를 업로드합니다."""
    access_token = _get_access_token()
    if not access_token:
        return None

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    payload = {
        "title": post_data["title"],
        "content": post_data["content"],
        "labels": post_data.get("labels", []),
    }

    url = f"{BLOGGER_API_BASE}/blogs/{BLOGGER_BLOG_ID}/posts/"
    params = {"isDraft": POST_STATUS != "live"}

    resp = requests.post(url, json=payload, headers=headers, params=params, timeout=30)

    if resp.status_code in (200, 201):
        result = resp.json()
        logger.info(f"포스트 업로드 성공: {result.get('url', '')}")
        return result
    else:
        logger.error(f"포스트 업로드 실패: {resp.status_code} {resp.text[:300]}")
        return None


def get_blog_info() -> dict | None:
    """블로그 정보를 조회합니다 (연결 테스트용)."""
    access_token = _get_access_token()
    if not access_token:
        return None

    resp = requests.get(
        f"{BLOGGER_API_BASE}/blogs/{BLOGGER_BLOG_ID}",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    if resp.status_code == 200:
        return resp.json()
    logger.error(f"블로그 정보 조회 실패: {resp.status_code}")
    return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    info = get_blog_info()
    if info:
        print(f"블로그 이름: {info.get('name')}")
        print(f"URL: {info.get('url')}")
    else:
        print("블로그 연결 실패. .env 설정을 확인하세요.")
