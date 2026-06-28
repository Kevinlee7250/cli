import json
import os
from dotenv import load_dotenv

load_dotenv()

# Claude API
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# Google Blogger OAuth2 (기본/단일 블로그)
BLOGGER_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
BLOGGER_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
BLOGGER_BLOG_ID = os.getenv("BLOGGER_BLOG_ID", "")
BLOGGER_REFRESH_TOKEN = os.getenv("GOOGLE_REFRESH_TOKEN", "")

# Google AdSense (광고 수익화)
ADSENSE_CLIENT_ID = os.getenv("ADSENSE_CLIENT_ID", "ca-pub-XXXXXXXXXXXXXXXXX")
_raw_slots = os.getenv("ADSENSE_SLOT_IDS", "")
ADSENSE_SLOT_IDS = [s.strip() for s in _raw_slots.split(",") if s.strip()] or ["0000000000"]

# 네이버 이미지 검색 (이미지 자동 첨부)
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")

# 블로그 설정
BLOG_LANGUAGE = os.getenv("BLOG_LANGUAGE", "ko")   # ko | en
try:
    POSTS_PER_RUN = max(1, min(int((os.getenv("POSTS_PER_RUN") or "1").strip()), 10))
except (ValueError, TypeError):
    POSTS_PER_RUN = 1
TREND_COUNTRY = os.getenv("TREND_COUNTRY", "KR")   # KR | US | JP
POST_STATUS = os.getenv("POST_STATUS", "live")       # live | draft

# 스케줄 (cron 형식: 분 시 * * *)
SCHEDULE_CRON = os.getenv("SCHEDULE_CRON", "0 9 * * *")

# Google Search Console
GSC_SITE_URL = os.getenv("GSC_SITE_URL", "")

# AdSense 정책 자동 검증
ADSENSE_VALIDATION = os.getenv("ADSENSE_VALIDATION", "true").lower() in ("true", "1", "yes")
try:
    ADSENSE_MIN_SCORE = max(0, min(int(os.getenv("ADSENSE_MIN_SCORE", "70").strip()), 100))
except (ValueError, TypeError):
    ADSENSE_MIN_SCORE = 70

# 시리즈 자동화
AUTO_SERIES = os.getenv("AUTO_SERIES", "true").lower() in ("true", "1", "yes")
try:
    AUTO_SERIES_COUNT = max(2, min(int(os.getenv("AUTO_SERIES_COUNT", "3").strip()), 5))
except (ValueError, TypeError):
    AUTO_SERIES_COUNT = 3
try:
    AUTO_SERIES_MIN_DAYS = max(1, int(os.getenv("AUTO_SERIES_MIN_DAYS", "7").strip()))
except (ValueError, TypeError):
    AUTO_SERIES_MIN_DAYS = 7

# ── 다중 블로그 설정 ────────────────────────────────────────────────────────────
# BLOGS_CONFIG: JSON 배열 형식의 블로그 설정 목록
# 예시:
# [
#   {
#     "id": "blog1", "name": "블로그1",
#     "blog_id": "BLOGGER_BLOG_ID_1",
#     "client_id": "CLIENT_ID_1", "client_secret": "SECRET_1",
#     "refresh_token": "REFRESH_TOKEN_1",
#     "adsense_client_id": "ca-pub-XXX", "adsense_slot_ids": ["111","222"],
#     "language": "ko", "post_status": "live", "enabled": true
#   }
# ]
_blogs_config_raw = os.getenv("BLOGS_CONFIG", "")
_BLOGS_CONFIG_LIST: list[dict] = []
if _blogs_config_raw.strip():
    try:
        _BLOGS_CONFIG_LIST = json.loads(_blogs_config_raw)
        if not isinstance(_BLOGS_CONFIG_LIST, list):
            _BLOGS_CONFIG_LIST = []
    except (json.JSONDecodeError, ValueError):
        _BLOGS_CONFIG_LIST = []

# 기본 블로그 이름 (BLOGS_CONFIG 미사용 시 단일 블로그 이름)
BLOG_NAME = os.getenv("BLOG_NAME", "기본 블로그")


def get_blog_configs() -> list[dict]:
    """활성화된 블로그 설정 목록을 반환합니다.
    BLOGS_CONFIG가 설정돼 있으면 해당 목록을 사용하고,
    없으면 기존 단일 블로그 환경 변수로 폴백합니다.
    """
    if _BLOGS_CONFIG_LIST:
        return [b for b in _BLOGS_CONFIG_LIST if b.get("enabled", True)]
    # 단일 블로그 폴백
    return [{
        "id": "default",
        "name": BLOG_NAME,
        "blog_id": BLOGGER_BLOG_ID,
        "client_id": BLOGGER_CLIENT_ID,
        "client_secret": BLOGGER_CLIENT_SECRET,
        "refresh_token": BLOGGER_REFRESH_TOKEN,
        "adsense_client_id": ADSENSE_CLIENT_ID,
        "adsense_slot_ids": ADSENSE_SLOT_IDS,
        "language": BLOG_LANGUAGE,
        "post_status": POST_STATUS,
        "enabled": True,
    }]
