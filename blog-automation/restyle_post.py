"""포스트 디자인 스타일만 교체 (내용 변경 없음)

새 디자인(파랑 계열)이 적용된 게시글을 원래 디자인(회색/파랑 #4a90e2)으로
내용 손상 없이 CSS 문자열 치환만으로 되돌립니다.

Usage:
  python restyle_post.py --blog-url <블로거_포스트_URL>
"""

import argparse
import json
import logging
import os
import re
import sys

import requests
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"


# ── 디자인 치환 맵 ────────────────────────────────────────────────────────────
# (구 디자인 → 원래 디자인) CSS 패턴을 직접 교체
STYLE_REPLACEMENTS = [
    # 목차 박스
    (
        r'background:#eff6ff;border-left:5px solid #2563eb;border-radius:0 12px 12px 0;'
        r'padding:20px 24px;margin:2em 0;',
        'background:#f8f9fa;border-left:4px solid #4a90e2;border-radius:8px;'
        'padding:20px 24px;margin:2em 0;max-width:680px;',
    ),
    # 목차 제목
    (
        r'font-weight:800;font-size:15px;margin:0 0 12px;color:#1e3a8a;',
        'font-weight:700;font-size:16px;margin:0 0 12px;',
    ),
    # 목차 목록
    (
        r'margin:0;padding-left:22px;line-height:2\.1;color:#374151;',
        'margin:0;padding-left:20px;line-height:2;',
    ),
    # 목차 링크
    (
        r'color:#1d4ed8;text-decoration:none;font-weight:500;',
        'color:#4a90e2;text-decoration:none;',
    ),
    # 태그 클라우드 링크
    (
        r'display:inline-block;margin:4px 3px;padding:6px 16px;'
        r'background:#eff6ff;border-radius:20px;text-decoration:none;'
        r'color:#1d4ed8;font-size:13px;font-weight:500;border:1px solid #bfdbfe;',
        'display:inline-block;margin:4px;padding:5px 14px;'
        'background:#e8f0fe;border-radius:20px;text-decoration:none;'
        'color:#1a73e8;font-size:13px;',
    ),
    # 태그 섹션 컨테이너
    (
        r'margin:2\.5em 0;padding:20px 24px;'
        r'background:#f8fafc;border-radius:12px;border:1px solid #e5e7eb;',
        'margin:2.5em 0;padding:20px;background:#f8f9fa;border-radius:10px;',
    ),
    # 태그 섹션 제목
    (
        r'font-weight:700;margin:0 0 12px;color:#374151;',
        'font-weight:700;margin:0 0 10px;',
    ),
    # 출처 섹션 컨테이너
    (
        r'margin:2\.5em 0;padding:20px 24px;'
        r'background:#f8fafc;border-radius:12px;border:1px solid #e5e7eb;',
        'margin:2.5em 0;padding:20px 24px;background:#f1f3f4;'
        'border-radius:10px;border-left:4px solid #5f6368;',
    ),
    # 출처 제목
    (
        r'font-weight:700;font-size:15px;margin:0 0 12px;color:#374151;',
        'font-weight:700;font-size:15px;margin:0 0 10px;',
    ),
    # 출처 목록
    (
        r'margin:0;padding-left:22px;line-height:2;font-size:14px;color:#374151;',
        'margin:0;padding-left:20px;line-height:1.9;font-size:14px;',
    ),
    # 출처 링크 색상
    (
        r'color:#1d4ed8;text-decoration:none;',
        'color:#1a73e8;text-decoration:none;',
    ),
    # 푸터 (면책 박스)
    (
        r'margin-top:3em;padding:18px 22px;'
        r'background:#fffbeb;border-radius:0 12px 12px 0;'
        r'border-left:4px solid #d97706;',
        'margin-top:3em;padding:18px 20px;background:#fff3cd;border-radius:10px;'
        'border-left:4px solid #ffc107;',
    ),
    # 푸터 텍스트
    (
        r'font-size:13px;color:#78350f;margin:0;line-height:1\.8;',
        'font-size:13px;color:#666;margin:0;',
    ),
    # 외부 wrapper — max-width + font
    (
        r"max-width:780px;margin:0 auto;padding:8px 4px;"
        r"font-family:'Noto Sans KR','Apple SD Gothic Neo','맑은 고딕',sans-serif;"
        r"font-size:16px;line-height:1\.9;color:#374151;word-break:keep-all;",
        "max-width:800px;margin:0 auto;"
        "font-family:'Noto Sans KR',sans-serif;line-height:1.9;color:#222;",
    ),
]


def _get_blog_config(blog_url: str) -> dict:
    """blog_url 도메인에 맞는 BLOGS_CONFIG 항목을 반환합니다."""
    from urllib.parse import urlparse
    domain = urlparse(blog_url).netloc.lower()
    raw = os.getenv("BLOGS_CONFIG", "")
    if raw:
        try:
            for b in json.loads(raw):
                # BLOGS_CONFIG 필드: 'url' (대시보드 saveBlogModal 기준)
                home = b.get("url", "").lower().strip("/")
                if home and (domain in home or home in domain):
                    return b
        except Exception as e:
            logger.error(f"BLOGS_CONFIG 파싱 오류: {e}")
    return {}


def _get_access_token(blog_config: dict) -> str | None:
    """OAuth2 Refresh Token → Access Token 교환."""
    client_id     = blog_config.get("client_id")     or os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = blog_config.get("client_secret") or os.getenv("GOOGLE_CLIENT_SECRET", "")
    refresh_token = blog_config.get("refresh_token") or os.getenv("GOOGLE_REFRESH_TOKEN", "")
    if not all([client_id, client_secret, refresh_token]):
        return None
    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "grant_type":    "refresh_token",
        "refresh_token": refresh_token,
        "client_id":     client_id,
        "client_secret": client_secret,
    }, timeout=15)
    if resp.status_code == 200:
        return resp.json().get("access_token")
    logger.error(f"토큰 교환 실패: {resp.text[:200]}")
    return None


def _get_post_by_url(blog_url: str, blog_config: dict) -> dict | None:
    """URL에 해당하는 Blogger 포스트 전체 데이터를 반환합니다."""
    from urllib.parse import urlparse
    path = urlparse(blog_url).path
    blog_id = blog_config.get("blog_id") or os.getenv("BLOGGER_BLOG_ID", "")
    if not blog_id:
        logger.error("blog_id가 없습니다. BLOGS_CONFIG 또는 BLOGGER_BLOG_ID를 확인하세요.")
        return None
    access_token = _get_access_token(blog_config)
    if not access_token:
        return None
    resp = requests.get(
        f"{BLOGGER_API_BASE}/blogs/{blog_id}/posts/bypath",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"path": path, "fetchImages": "false"},
        timeout=15,
    )
    if resp.status_code == 200:
        return resp.json()
    logger.error(f"포스트 조회 실패 [{resp.status_code}]: {resp.text[:200]}")
    return None


def _apply_style_replacements(html: str) -> str:
    """디자인 CSS 문자열을 원래 스타일로 치환합니다."""
    for old_pat, new_str in STYLE_REPLACEMENTS:
        html = re.sub(old_pat, new_str, html)
    return html


def restyle(blog_url: str) -> int:
    logger.info(f"=== 디자인 원복 시작: {blog_url} ===")

    # 환경변수 상태 진단
    has_client_id     = bool(os.getenv("GOOGLE_CLIENT_ID"))
    has_client_secret = bool(os.getenv("GOOGLE_CLIENT_SECRET"))
    has_refresh_token = bool(os.getenv("GOOGLE_REFRESH_TOKEN"))
    has_blogger_id    = bool(os.getenv("BLOGGER_BLOG_ID"))
    has_blogs_config  = bool(os.getenv("BLOGS_CONFIG"))
    logger.info(
        f"환경변수 상태: CLIENT_ID={has_client_id} SECRET={has_client_secret} "
        f"REFRESH={has_refresh_token} BLOGGER_ID={has_blogger_id} BLOGS_CONFIG={has_blogs_config}"
    )

    blog_config = _get_blog_config(blog_url)
    if not blog_config:
        logger.warning("BLOGS_CONFIG에서 블로그 설정을 찾지 못했습니다. 기본 환경변수를 사용합니다.")
    else:
        logger.info(f"블로그 설정 확인: id={blog_config.get('id')} blog_id={blog_config.get('blog_id')}")

    post = _get_post_by_url(blog_url, blog_config)
    if not post:
        return 1

    post_id = post.get("id", "")
    title   = post.get("title", "")
    content = post.get("content", "")
    labels  = post.get("labels", [])
    if labels and isinstance(labels[0], dict):
        labels = [l.get("name", "") for l in labels]

    logger.info(f"포스트 조회 성공: [{post_id}] {title}")
    logger.info(f"현재 HTML 길이: {len(content)} chars")

    new_content = _apply_style_replacements(content)

    if new_content == content:
        logger.info("✅ 이미 원래 디자인이거나 변경 대상 패턴을 찾지 못했습니다. 업데이트 불필요.")
        return 0

    changed_count = sum(
        1 for old_pat, _ in STYLE_REPLACEMENTS
        if re.search(old_pat, content)
    )
    logger.info(f"교체된 CSS 패턴: {changed_count}개")

    # Blogger API PUT
    blog_id      = blog_config.get("blog_id") or os.getenv("BLOGGER_BLOG_ID", "")
    access_token = _get_access_token(blog_config)
    if not access_token:
        logger.error("액세스 토큰 없음 — 업데이트 실패")
        return 1

    payload = {"title": title, "content": new_content, "labels": labels}
    resp = requests.put(
        f"{BLOGGER_API_BASE}/blogs/{blog_id}/posts/{post_id}",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json=payload,
        params={"fetchBody": "false"},
        timeout=30,
    )
    if resp.status_code == 200:
        logger.info(f"✅ 포스트 업데이트 성공: {blog_url}")
        return 0
    else:
        logger.error(f"❌ 업데이트 실패 [{resp.status_code}]: {resp.text[:300]}")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="포스트 디자인 원복")
    parser.add_argument("--blog-url", required=True, help="업데이트할 Blogger 포스트 URL")
    args = parser.parse_args()
    return restyle(args.blog_url)


if __name__ == "__main__":
    sys.exit(main())
