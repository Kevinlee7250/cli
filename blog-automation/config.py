import json
import os
from dotenv import load_dotenv

load_dotenv()

# Claude API
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")

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
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "")   # https://pixabay.com/api/docs/
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

# ── 소셜 미디어 크리덴셜 ────────────────────────────────────────────────────────
# Instagram Graph API (미설정 시 게시 건너뜀)
INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
INSTAGRAM_ACCOUNT_ID   = os.getenv("INSTAGRAM_ACCOUNT_ID", "")

# Threads API (미설정 시 게시 건너뜀)
THREADS_ACCESS_TOKEN = os.getenv("THREADS_ACCESS_TOKEN", "")
THREADS_USER_ID      = os.getenv("THREADS_USER_ID", "")
THREADS_HANDLE       = os.getenv("THREADS_HANDLE", "")   # @ 없이 핸들명 ex) myaccount

# ImgBB (Instagram 이미지 호스팅 — 선택, 미설정 시 텍스트만 게시)
IMGBB_API_KEY = os.getenv("IMGBB_API_KEY", "")

# 소셜 미디어 자동 게시 (false = 콘텐츠만 생성, 게시는 건너뜀)
SOCIAL_AUTO_PUBLISH = os.getenv("SOCIAL_AUTO_PUBLISH", "false").lower() in ("true", "1", "yes")

# AdSense 정책 자동 검증
ADSENSE_VALIDATION = os.getenv("ADSENSE_VALIDATION", "true").lower() in ("true", "1", "yes")
try:
    ADSENSE_MIN_SCORE = max(0, min(int(os.getenv("ADSENSE_MIN_SCORE", "80").strip()), 100))
except (ValueError, TypeError):
    ADSENSE_MIN_SCORE = 80

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


def claude_text(message) -> str:
    """Claude 응답에서 text 블록을 추출합니다.

    claude-sonnet-5부터는 thinking 파라미터를 생략하면 adaptive thinking이
    기본으로 켜져 응답 첫 블록이 thinking 블록이 됩니다. content[0].text를
    직접 읽으면 깨지므로 반드시 이 헬퍼로 text 블록을 찾아야 합니다.
    """
    for block in getattr(message, "content", None) or []:
        if getattr(block, "type", "") == "text":
            text = getattr(block, "text", "")
            if text:
                return text
    return ""


def claude_generate(client, *, max_continues: int = 2, **kwargs) -> str:
    """max_tokens로 잘린 응답을 이어쓰기로 완성해 전체 텍스트를 반환합니다.

    claude-sonnet-5는 adaptive thinking이 기본으로 켜져 thinking 토큰도
    max_tokens 예산에서 차감됩니다. 생각이 길어진 요청은 본문이 중간에
    잘리며 stop_reason이 "max_tokens"가 됩니다. 잘림을 감지하면 이전
    응답 블록을 그대로 되돌려주고(같은 모델에서는 thinking 블록을 수정
    없이 전달해야 함) 끊긴 지점부터 이어쓰게 합니다.

    이어쓰기 후에도 잘려 있으면 빈 문자열을 반환해 호출부의 재시도
    루프가 처음부터 다시 생성하도록 합니다 (잘린 글 게시 방지).
    """
    messages = list(kwargs.pop("messages"))
    message = client.messages.create(messages=messages, **kwargs)
    parts = [claude_text(message)]
    for _ in range(max_continues):
        if getattr(message, "stop_reason", "") != "max_tokens":
            break
        import logging
        logging.getLogger(__name__).warning("응답이 max_tokens로 잘림 — 이어쓰기 요청")
        messages = messages + [
            {"role": "assistant", "content": message.content},
            {"role": "user", "content": (
                "응답이 토큰 한도로 잘렸습니다. 끊긴 지점부터 정확히 이어서 계속 작성하세요. "
                "이미 출력한 내용을 반복하거나 서두를 붙이지 말고, 잘린 문자 바로 다음부터 출력하세요."
            )},
        ]
        message = client.messages.create(messages=messages, **kwargs)
        parts.append(claude_text(message))
    if getattr(message, "stop_reason", "") == "max_tokens":
        return ""
    return "".join(parts)


_BLOGS_REGISTRY_FILE = os.path.join(os.path.dirname(__file__), "blogs.json")


def _default_blog() -> dict:
    return {
        "id": "blog1",
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


def _load_registry_configs() -> dict:
    """blogs.json 레지스트리를 {id: config} dict로 로드합니다."""
    if not os.path.exists(_BLOGS_REGISTRY_FILE):
        return {}
    try:
        with open(_BLOGS_REGISTRY_FILE, encoding="utf-8") as f:
            registry = json.load(f)
        if not isinstance(registry, list):
            return {}
        result = {}
        for b in registry:
            if not b.get("enabled", True):
                continue
            bid = b.get("id", "blog1")
            result[bid] = {
                "id": bid,
                "name": b.get("name") or BLOG_NAME,
                "blog_id": b.get("blog_id") or BLOGGER_BLOG_ID,
                "client_id": BLOGGER_CLIENT_ID,
                "client_secret": BLOGGER_CLIENT_SECRET,
                "refresh_token": BLOGGER_REFRESH_TOKEN,
                "adsense_client_id": b.get("adsense_client_id") or ADSENSE_CLIENT_ID,
                "adsense_slot_ids": b.get("adsense_slot_ids") or ADSENSE_SLOT_IDS,
                "adsense_mode": b.get("adsense_mode") or ADSENSE_MODE,
                "language": b.get("language", BLOG_LANGUAGE),
                "post_status": b.get("post_status", POST_STATUS),
                "topics": b.get("topics", []),
                "naver_api_queries": b.get("naver_api_queries", []),
                "gsc_site_url": b.get("gsc_site_url") or GSC_SITE_URL,
                "enabled": True,
            }
        return result
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"blogs.json 로드 실패 — 레지스트리 블로그 비활성화: {e}")
        return {}


def get_blog_configs() -> list[dict]:
    """활성화된 블로그 설정 목록을 반환합니다.

    우선순위:
    1. BLOGS_CONFIG 환경변수 + blogs.json 병합
       — BLOGS_CONFIG 항목이 동일 id blogs.json 항목보다 우선
       — blogs.json에만 있는 블로그(blog2·blog3 등)도 포함
    2. blogs.json 레지스트리만 사용
    3. 단일 블로그 폴백
    """
    registry = _load_registry_configs()

    # 1) BLOGS_CONFIG 환경변수 — blogs.json과 병합 (env 항목이 우선)
    if _BLOGS_CONFIG_LIST:
        merged = dict(registry)  # blogs.json 기반
        for b in _BLOGS_CONFIG_LIST:
            if not b.get("enabled", True):
                continue
            # id가 없거나 'default'인 항목은 blog1로 간주
            # (별개 블로그로 병합되어 blog1이 두 번 실행되는 것 방지)
            if not b.get("id") or b.get("id") == "default":
                import logging
                logging.getLogger(__name__).warning(
                    f"BLOGS_CONFIG 항목 id={b.get('id')!r} → 'blog1'로 간주합니다 — Secret에 id: \"blog1\"을 설정하세요."
                )
                b = {**b, "id": "blog1"}
            merged[b["id"]] = b  # BLOGS_CONFIG 항목이 덮어씀
        if merged:
            return list(merged.values())

    # 2) blogs.json 레지스트리만 사용
    if registry:
        return list(registry.values())

    # 3) 단일 블로그 폴백
    return [_default_blog()]


