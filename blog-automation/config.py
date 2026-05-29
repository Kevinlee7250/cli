import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
BLOGGER_CLIENT_ID = os.getenv("BLOGGER_CLIENT_ID", "")
BLOGGER_CLIENT_SECRET = os.getenv("BLOGGER_CLIENT_SECRET", "")
BLOGGER_BLOG_ID = os.getenv("BLOGGER_BLOG_ID", "")
BLOGGER_REFRESH_TOKEN = os.getenv("BLOGGER_REFRESH_TOKEN", "")

# 블로그 설정
BLOG_LANGUAGE = os.getenv("BLOG_LANGUAGE", "ko")  # ko or en
POSTS_PER_RUN = int(os.getenv("POSTS_PER_RUN", "1"))
TREND_COUNTRY = os.getenv("TREND_COUNTRY", "KR")  # KR, US, JP 등
POST_STATUS = os.getenv("POST_STATUS", "live")  # live or draft

# Claude 모델
CLAUDE_MODEL = "claude-sonnet-4-6"

# 스케줄 (cron 형식)
SCHEDULE_CRON = os.getenv("SCHEDULE_CRON", "0 9 * * *")  # 매일 오전 9시
