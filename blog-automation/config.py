import os
from dotenv import load_dotenv

load_dotenv()

# Claude API
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# Google Blogger OAuth2
BLOGGER_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
BLOGGER_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
BLOGGER_BLOG_ID = os.getenv("BLOGGER_BLOG_ID", "")
BLOGGER_REFRESH_TOKEN = os.getenv("GOOGLE_REFRESH_TOKEN", "")

# Google AdSense (광고 수익화)
ADSENSE_CLIENT_ID = os.getenv("ADSENSE_CLIENT_ID", "ca-pub-XXXXXXXXXXXXXXXXX")
# 광고 슬롯 ID 목록 (쉼표 구분 또는 단일값 반복 사용)
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
GSC_SITE_URL = os.getenv("GSC_SITE_URL", "")  # 예: https://hoguwhat1.blogspot.com/
