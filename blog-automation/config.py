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
# ADSENSE_MODE: "auto" = Blogger 자동 광고(테마 스크립트), "manual" = 포스트 내 개별 슬롯
ADSENSE_MODE = os.getenv("ADSENSE_MODE", "auto")
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


_BLOGS_REGISTRY_FILE = os.path.join(os.path.dirname(__file__), "blogs.json")


def _default_blog() -> dict:
    return {
        "id": "default",
        "name": BLOG_NAME,
        "blog_id": BLOGGER_BLOG_ID,
        "client_id": BLOGGER_CLIENT_ID,
        "client_secret": BLOGGER_CLIENT_SECRET,
        "refresh_token": BLOGGER_REFRESH_TOKEN,
        "adsense_client_id": ADSENSE_CLIENT_ID,
        "adsense_slot_ids": ADSENSE_SLOT_IDS,
        "adsense_mode": ADSENSE_MODE,
        "language": BLOG_LANGUAGE,
        "post_status": POST_STATUS,
        "enabled": True,
    }


def get_blog_configs() -> list[dict]:
    """활성화된 블로그 설정 목록을 반환합니다.

    우선순위:
    1. BLOGS_CONFIG 환경변수 (JSON 배열) — 모든 자격증명 명시 필요
    2. blogs.json 레지스트리 — blog_id·이름만 관리, OAuth는 공유 Secrets 사용
    3. 단일 블로그 폴백 (기존 방식)
    """
    # 1) BLOGS_CONFIG 환경변수
    if _BLOGS_CONFIG_LIST:
        return [b for b in _BLOGS_CONFIG_LIST if b.get("enabled", True)]

    # 2) blogs.json 레지스트리 (OAuth는 공유 Secrets 자동 주입)
    if os.path.exists(_BLOGS_REGISTRY_FILE):
        try:
            with open(_BLOGS_REGISTRY_FILE, encoding="utf-8") as f:
                registry = json.load(f)
            if isinstance(registry, list) and registry:
                configs = []
                for b in registry:
                    if not b.get("enabled", True):
                        continue
                    configs.append({
                        "id": b.get("id", "blog1"),
                        "name": b.get("name") or BLOG_NAME,
                        # blog_id 미지정 시 기존 단일 Secret 사용
                        "blog_id": b.get("blog_id") or BLOGGER_BLOG_ID,
                        # OAuth·AdSense는 항상 공유 Secrets 사용
                        "client_id": BLOGGER_CLIENT_ID,
                        "client_secret": BLOGGER_CLIENT_SECRET,
                        "refresh_token": BLOGGER_REFRESH_TOKEN,
                        "adsense_client_id": b.get("adsense_client_id") or ADSENSE_CLIENT_ID,
                        "adsense_slot_ids": b.get("adsense_slot_ids") or ADSENSE_SLOT_IDS,
                        "adsense_mode": b.get("adsense_mode") or ADSENSE_MODE,
                        "language": b.get("language", BLOG_LANGUAGE),
                        "post_status": b.get("post_status", POST_STATUS),
                        "enabled": True,
                    })
                if configs:
                    return configs
        except Exception:
            pass

    # 3) 단일 블로그 폴백
    return [_default_blog()]
