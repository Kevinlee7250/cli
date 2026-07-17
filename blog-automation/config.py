import json
import logging
import os
from dotenv import load_dotenv

load_dotenv()

_cfg_log = logging.getLogger(__name__)

# Claude API
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")

# OpenAI API
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

# AI 제공자 선택 (전역 기본값 — 블로그별 ai_provider 설정으로 재정의 가능)
# 값: "claude" | "openai"
AI_PROVIDER = os.getenv("AI_PROVIDER", "claude")

# Google Blogger OAuth2 (기본/단일 블로그)
BLOGGER_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
BLOGGER_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
BLOGGER_BLOG_ID = os.getenv("BLOGGER_BLOG_ID", "")
BLOGGER_REFRESH_TOKEN = os.getenv("GOOGLE_REFRESH_TOKEN", "")

# Google AdSense (광고 수익화)
ADSENSE_CLIENT_ID = os.getenv("ADSENSE_CLIENT_ID", "ca-pub-XXXXXXXXXXXXXXXXX")
if ADSENSE_CLIENT_ID == "ca-pub-XXXXXXXXXXXXXXXXX":
    _cfg_log.warning("ADSENSE_CLIENT_ID가 설정되지 않아 플레이스홀더 값이 사용됩니다 — AdSense 광고가 올바르게 표시되지 않습니다")
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
            _cfg_log.warning("BLOGS_CONFIG가 JSON 배열 형식이 아닙니다 — 다중 블로그 설정이 무시됩니다")
            _BLOGS_CONFIG_LIST = []
    except (json.JSONDecodeError, ValueError) as _e:
        _cfg_log.warning(f"BLOGS_CONFIG JSON 파싱 실패 ({_e}) — 다중 블로그 설정이 무시됩니다")
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


def _record_token_usage(model: str, input_tokens: int, output_tokens: int) -> None:
    """토큰 사용량을 logs/ai_usage.json에 누적 기록합니다."""
    import datetime
    import sys
    if "pytest" in sys.modules:  # 테스트의 mock 호출이 실사용 통계를 오염시키지 않도록
        return
    usage_file = os.path.join(os.path.dirname(__file__), "logs", "ai_usage.json")
    os.makedirs(os.path.dirname(usage_file), exist_ok=True)
    try:
        with open(usage_file, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {"daily": {}, "monthly": {}, "total": {"input_tokens": 0, "output_tokens": 0, "calls": 0}, "model": model}

    now = datetime.datetime.utcnow()
    day_key = now.strftime("%Y-%m-%d")
    month_key = now.strftime("%Y-%m")

    for scope_key, scope in [("daily", day_key), ("monthly", month_key)]:
        bucket = data[scope_key].setdefault(scope, {"input_tokens": 0, "output_tokens": 0, "calls": 0})
        bucket["input_tokens"] += input_tokens
        bucket["output_tokens"] += output_tokens
        bucket["calls"] += 1
        bucket["model"] = model

    total = data.setdefault("total", {"input_tokens": 0, "output_tokens": 0, "calls": 0})
    total["input_tokens"] += input_tokens
    total["output_tokens"] += output_tokens
    total["calls"] += 1
    data["model"] = model
    data["last_updated"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    # 오래된 일별 데이터 정리 (90일 초과)
    cutoff = (now - datetime.timedelta(days=90)).strftime("%Y-%m-%d")
    data["daily"] = {k: v for k, v in data["daily"].items() if k >= cutoff}

    try:
        with open(usage_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        _cfg_log.warning(f"ai_usage.json 저장 실패: {e}")


def export_ai_usage_to_docs() -> None:
    """logs/ai_usage.json을 docs/data/ai_usage.json으로 복사합니다."""
    import shutil
    src = os.path.join(os.path.dirname(__file__), "logs", "ai_usage.json")
    dst = os.path.join(os.path.dirname(__file__), "..", "docs", "data", "ai_usage.json")
    dst = os.path.normpath(dst)
    if not os.path.exists(src):
        return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


# Claude 사용 한도 도달 여부 (프로세스 내 공유) — 한 번 감지되면
# 같은 실행의 나머지 호출은 Claude를 건너뛰고 바로 OpenAI 폴백으로 갑니다.
_claude_limit_hit = False


def _is_usage_limit_error(e: Exception) -> bool:
    """Anthropic 사용 한도 오류 판별 (월 지출 한도 도달 시 400으로 반환됨)."""
    msg = str(e).lower()
    return "usage limits" in msg or "regain access" in msg


def _messages_to_text(messages: list) -> list[dict]:
    """Claude 메시지를 OpenAI 형식으로 변환 (content 블록 리스트 → 평문)."""
    converted = []
    for m in messages:
        content = m.get("content", "") if isinstance(m, dict) else ""
        role = m.get("role", "user") if isinstance(m, dict) else "user"
        if isinstance(content, list):
            content = "".join(
                getattr(b, "text", "") or (b.get("text", "") if isinstance(b, dict) else "")
                for b in content
                if getattr(b, "type", None) == "text" or (isinstance(b, dict) and b.get("type") == "text")
            )
        converted.append({"role": role, "content": content})
    return converted


def _openai_fallback(system: str, messages: list, max_tokens: int, temperature: float) -> str:
    """Claude 한도 도달 시 OpenAI로 동일 요청을 수행합니다. 미설정 시 빈 문자열."""
    if not OPENAI_API_KEY:
        _cfg_log.error("Claude 사용 한도 도달 + OPENAI_API_KEY 미설정 — 폴백 불가")
        return ""
    try:
        from openai import OpenAI
    except ImportError:
        _cfg_log.error("Claude 사용 한도 도달 + openai 패키지 미설치 — 폴백 불가")
        return ""
    _cfg_log.warning(f"Claude 사용 한도 도달 — OpenAI({OPENAI_MODEL})로 자동 폴백")
    client = OpenAI(api_key=OPENAI_API_KEY)
    return gpt_generate(
        client,
        model=OPENAI_MODEL,
        system=system,
        messages=_messages_to_text(messages),
        max_tokens=min(max_tokens, 16000),  # gpt-4o 출력 한도 16384 이내
        temperature=temperature,
    )


def claude_generate(client, *, max_continues: int = 2, **kwargs) -> str:
    """max_tokens로 잘린 응답을 이어쓰기로 완성해 전체 텍스트를 반환합니다.

    claude-sonnet-5는 adaptive thinking이 기본으로 켜져 thinking 토큰도
    max_tokens 예산에서 차감됩니다. 생각이 길어진 요청은 본문이 중간에
    잘리며 stop_reason이 "max_tokens"가 됩니다. 잘림을 감지하면 이전
    응답 블록을 그대로 되돌려주고(같은 모델에서는 thinking 블록을 수정
    없이 전달해야 함) 끊긴 지점부터 이어쓰게 합니다.

    이어쓰기 후에도 잘려 있으면 빈 문자열을 반환해 호출부의 재시도
    루프가 처음부터 다시 생성하도록 합니다 (잘린 글 게시 방지).

    streaming 사용 이유: claude-sonnet-5 + adaptive thinking 조합은 응답에
    10분 이상 걸릴 수 있어 Anthropic SDK가 non-streaming 호출을 거부합니다.
    stream.get_final_message()는 Message 객체를 그대로 반환하므로 기존 로직과
    완전히 호환됩니다.

    Anthropic 사용 한도(월 지출 한도) 오류가 감지되면 OpenAI로 자동 폴백하며,
    이후 같은 프로세스의 모든 호출은 Claude를 건너뛰고 바로 OpenAI를 사용합니다.
    """
    import logging as _logging
    global _claude_limit_hit
    _log = _logging.getLogger(__name__)

    messages = list(kwargs.pop("messages"))
    model = kwargs.get("model", CLAUDE_MODEL)
    _fb_args = (
        kwargs.get("system", ""), messages,
        kwargs.get("max_tokens", 8000), kwargs.get("temperature", 1.0),
    )

    # 이번 실행에서 이미 한도 도달 확인됨 → Claude 호출 없이 바로 폴백
    if _claude_limit_hit:
        return _openai_fallback(*_fb_args)

    try:
        with client.messages.stream(messages=messages, **kwargs) as stream:
            message = stream.get_final_message()
    except Exception as e:
        if _is_usage_limit_error(e):
            _claude_limit_hit = True
            return _openai_fallback(*_fb_args)
        raise

    usage = getattr(message, "usage", None)
    total_in = getattr(usage, "input_tokens", 0) or 0
    total_out = getattr(usage, "output_tokens", 0) or 0

    parts = [claude_text(message)]

    for _ in range(max_continues):
        if getattr(message, "stop_reason", "") != "max_tokens":
            break
        _log.warning("응답이 max_tokens로 잘림 — 이어쓰기 요청")
        messages = messages + [
            {"role": "assistant", "content": message.content},
            {"role": "user", "content": (
                "응답이 토큰 한도로 잘렸습니다. 끊긴 지점부터 정확히 이어서 계속 작성하세요. "
                "이미 출력한 내용을 반복하거나 서두를 붙이지 말고, 잘린 문자 바로 다음부터 출력하세요."
            )},
        ]
        try:
            with client.messages.stream(messages=messages, **kwargs) as stream:
                message = stream.get_final_message()
        except Exception as e:
            if _is_usage_limit_error(e):
                # 이어쓰기 도중 한도 도달 — 부분 결과를 버리고 OpenAI로 전체 재생성
                _claude_limit_hit = True
                return _openai_fallback(*_fb_args)
            raise
        usage = getattr(message, "usage", None)
        total_in += getattr(usage, "input_tokens", 0) or 0
        total_out += getattr(usage, "output_tokens", 0) or 0
        parts.append(claude_text(message))

    try:
        _record_token_usage(model, total_in, total_out)
    except Exception as e:
        _log.warning(f"토큰 사용량 기록 실패: {e}")

    if getattr(message, "stop_reason", "") == "max_tokens":
        return ""
    return "".join(parts)


def gpt_generate(client, *, model: str, system: str, messages: list, max_tokens: int = 8000, temperature: float = 1.0) -> str:
    """OpenAI ChatCompletion API 호출 — Claude claude_generate()와 동일한 인터페이스.

    system + messages 형식으로 GPT를 호출하고 응답 텍스트를 반환합니다.
    API 오류 시 빈 문자열을 반환합니다.
    """
    import logging
    _logger = logging.getLogger(__name__)
    try:
        msgs = [{"role": "system", "content": system}] + list(messages)
        resp = client.chat.completions.create(
            model=model,
            messages=msgs,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        _logger.error(f"OpenAI API 오류: {e}")
        return ""


_BLOGS_REGISTRY_FILE = os.path.join(os.path.dirname(__file__), "blogs.json")
_AUTHOR_PROFILE_FILE = os.path.join(os.path.dirname(__file__), "author_profile.json")


def get_author_profile() -> dict:
    """author_profile.json 로드 — 실제 저자 정보와 경험 목록.

    파일이 없거나 파싱에 실패하면 {} 반환 (모든 글이 조사·분석형으로 작성됨).
    """
    if not os.path.exists(_AUTHOR_PROFILE_FILE):
        return {}
    try:
        with open(_AUTHOR_PROFILE_FILE, encoding="utf-8") as f:
            profile = json.load(f)
        return profile if isinstance(profile, dict) else {}
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"author_profile.json 로드 실패: {e}")
        return {}


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


