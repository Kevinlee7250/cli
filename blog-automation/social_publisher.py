"""소셜 미디어 콘텐츠 생성 및 게시 모듈

지원 플랫폼:
  - Instagram  (Graph API v21.0)
  - Threads    (Meta Threads API v1.0)
  - TikTok     (스크립트·해시태그 저장 — 영상 파일 별도 제작 필요)

모든 API 키는 환경변수로 관리하며, 미설정 시 해당 플랫폼 게시를 건너뜁니다.
콘텐츠 생성(Claude API)은 크리덴셜 여부와 무관하게 항상 실행됩니다.
"""

import json
import logging
import os
import re
import time

import requests

from config import ANTHROPIC_API_KEY, CLAUDE_MODEL

logger = logging.getLogger(__name__)

# ── 소셜 미디어 크리덴셜 (환경변수에서 로드) ─────────────────────────────────
INSTAGRAM_ACCESS_TOKEN  = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
INSTAGRAM_ACCOUNT_ID    = os.getenv("INSTAGRAM_ACCOUNT_ID", "")
THREADS_ACCESS_TOKEN    = os.getenv("THREADS_ACCESS_TOKEN", "")
THREADS_USER_ID         = os.getenv("THREADS_USER_ID", "")
THREADS_HANDLE          = os.getenv("THREADS_HANDLE", "")   # @없이 핸들 ex) myaccount
IMGBB_API_KEY           = os.getenv("IMGBB_API_KEY", "")    # Instagram 이미지 호스팅 (선택)

OPTIMAL_POSTING_TIMES = {
    "instagram": ["07:00", "12:00", "18:00", "21:00"],
    "threads":   ["08:00", "13:00", "19:00", "22:00"],
    "tiktok":    ["07:00", "12:00", "17:00", "20:00", "23:00"],
}

# ── 카테고리별 해시태그 프리셋 ────────────────────────────────────────────────
_CAT_HASHTAGS: dict[str, list[str]] = {
    "금융":  ["#재테크", "#주식", "#ETF", "#투자", "#경제", "#금융", "#돈관리", "#자산관리", "#주식투자", "#코인"],
    "부동산": ["#부동산", "#아파트", "#청약", "#부동산투자", "#전세", "#부동산정보", "#내집마련", "#분양", "#주택", "#갭투자"],
    "건강":  ["#건강", "#다이어트", "#운동", "#건강관리", "#헬스", "#건강식품", "#영양", "#면역력", "#피부관리", "#요가"],
    "기술":  ["#IT", "#AI", "#기술", "#디지털", "#챗GPT", "#인공지능", "#코딩", "#스마트폰", "#앱", "#테크"],
    "여행":  ["#여행", "#국내여행", "#여행스타그램", "#해외여행", "#여행추천", "#여행지", "#여행일상", "#여행사진", "#맛집", "#호텔"],
    "스포츠": ["#스포츠", "#축구", "#야구", "#운동", "#스포츠뉴스", "#농구", "#테니스", "#골프", "#경기결과", "#스포츠팬"],
    "교육":  ["#공부", "#자기계발", "#교육", "#학습", "#영어공부", "#자격증", "#취업", "#스터디", "#공부스타그램", "#합격"],
    "쇼핑":  ["#쇼핑", "#할인", "#리뷰", "#추천", "#제품리뷰", "#핫딜", "#쇼핑추천", "#구매후기", "#패션", "#가성비"],
    "법률":  ["#법률", "#생활법률", "#법", "#법률정보", "#권리", "#계약", "#법률상담", "#소송", "#변호사", "#법률팁"],
}
_DEFAULT_HASHTAGS = ["#정보", "#블로그", "#일상", "#꿀팁", "#유용한정보"]


# ─────────────────────────────────────────────────────────────────────────────
# 콘텐츠 생성
# ─────────────────────────────────────────────────────────────────────────────

def generate_social_content(post_data: dict, blog_url: str = "") -> dict:
    """Claude API로 Instagram·Threads·TikTok 최적화 콘텐츠를 생성합니다.

    Args:
        post_data: content_generator.generate_post() 반환값
        blog_url:  게시된 블로그 포스트 URL

    Returns:
        social_content dict (instagram/threads/tiktok 필드 포함)
    """
    import anthropic

    keyword   = post_data.get("keyword", "")
    title     = post_data.get("title", "")
    excerpt   = post_data.get("meta_description") or post_data.get("content_preview", "")[:200]
    tags      = post_data.get("labels", [])
    faq       = post_data.get("faq", [])
    category  = post_data.get("adsense_category", "일반")

    faq_preview = "\n".join(f"Q. {q.get('question','')}" for q in faq[:2]) if faq else "없음"
    tag_str     = ", ".join(tags[:10]) if tags else keyword

    # 카테고리별 해시태그 프리셋
    popular_tags = _CAT_HASHTAGS.get(category, _DEFAULT_HASHTAGS)

    system_prompt = (
        "당신은 인스타그램, 쓰레드, 틱톡 플랫폼별 바이럴 SNS 콘텐츠 전문가입니다.\n"
        "알고리즘 최적화, 저장률·공유율 극대화, 블로그 트래픽 유입을 동시에 달성합니다.\n"
        "- Instagram: 저장(Save) > 공유 > 댓글 > 좋아요 순으로 알고리즘 가중치\n"
        "- Threads: 토론·의견 유발 콘텐츠 우대\n"
        "- TikTok: 3초 리텐션, 완시청률, 댓글 유발이 핵심 지표"
    )

    user_prompt = f"""다음 블로그 포스트를 기반으로 플랫폼별 최적화 SNS 콘텐츠를 작성해주세요.

**블로그 제목:** {title}
**키워드:** {keyword}
**카테고리:** {category}
**요약:** {excerpt}
**블로그 URL:** {blog_url or '[블로그 URL]'}
**FAQ 미리보기:**
{faq_preview}
**태그:** {tag_str}

**[인스타그램]**
- 첫 2줄: 스크롤 멈추게 하는 후킹 (숫자 또는 충격 사실)
- "저장 필수 🔖" 문구 포함 (저장율 알고리즘 최우선)
- 정보 리스트 5-7개 (번호 + 이모지)
- 스토리 하이라이트 제목 제안 (5자 이내)
- 해시태그: 인기태그 10개 + 중간태그 10개 + 니치태그 5개

**[쓰레드]**
- 5개 연속 스레드 (1/5 ~ 5/5)
- 1번: 충격적 사실/통계
- 5번: 결론 + 블로그 링크 + 의견 요청
- 참여 유발 질문 (댓글 유도)
- 해시태그 5개

**[틱톡]**
- 60초 영상 스크립트
- 씬별: 0-3초 후킹 / 3-15초 문제 / 15-35초 해결 / 35-50초 결론 / 50-60초 CTA
- 각 씬: 자막 텍스트 + 카메라 연출 + 효과음
- 배경음악 장르 추천
- 해시태그 10개 (fyp 포함)
- 썸네일 텍스트

**응답 형식 (JSON 코드블록):**
```json
{{
  "instagram": {{
    "caption": "전체 캡션 (이모지 포함)",
    "hookLine": "첫 후킹 문장",
    "storyHighlightTitle": "하이라이트 제목(5자)",
    "hashtags": {{
      "popular": ["#해시태그1", "..."],
      "medium":  ["#해시태그1", "..."],
      "niche":   ["#해시태그1", "..."]
    }},
    "bestPostingTimes": ["07:00", "12:00", "21:00"]
  }},
  "threads": {{
    "posts": [
      {{"order":1,"label":"1/5","content":"내용"}},
      {{"order":2,"label":"2/5","content":"내용"}},
      {{"order":3,"label":"3/5","content":"내용"}},
      {{"order":4,"label":"4/5","content":"내용"}},
      {{"order":5,"label":"5/5","content":"마지막 내용 + {blog_url or '[블로그 URL]'}"}}
    ],
    "hashtags": ["#태그1","#태그2","#태그3","#태그4","#태그5"],
    "engagementQuestion": "댓글 유발 질문",
    "bestPostingTimes": ["08:00", "19:00"]
  }},
  "tiktok": {{
    "title": "영상 제목",
    "thumbnailText": "썸네일 문구",
    "scenes": [
      {{"time":"0-3초","text":"자막","direction":"연출","sound":"효과음"}},
      {{"time":"3-15초","text":"자막","direction":"연출","sound":"효과음"}},
      {{"time":"15-35초","text":"자막","direction":"연출","sound":"효과음"}},
      {{"time":"35-50초","text":"자막","direction":"연출","sound":"효과음"}},
      {{"time":"50-60초","text":"CTA","direction":"연출","sound":"효과음"}}
    ],
    "fullScript": "전체 낭독 스크립트",
    "commentBait": "댓글 유발 질문",
    "hashtags": ["#fyp","#foryou","#태그3","#태그4","#태그5"],
    "backgroundMusic": {{"genre":"장르","mood":"분위기"}},
    "bestPostingTimes": ["07:00","20:00","23:00"]
  }},
  "keyword": "{keyword}",
  "trendDirection": "stable"
}}
```"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=8000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = resp.content[0].text
        data = _extract_json(raw)

        # bestPostingTimes 기본값 보장
        if not data.get("instagram", {}).get("bestPostingTimes"):
            data.setdefault("instagram", {})["bestPostingTimes"] = OPTIMAL_POSTING_TIMES["instagram"]
        if not data.get("threads", {}).get("bestPostingTimes"):
            data.setdefault("threads", {})["bestPostingTimes"] = OPTIMAL_POSTING_TIMES["threads"]
        if not data.get("tiktok", {}).get("bestPostingTimes"):
            data.setdefault("tiktok", {})["bestPostingTimes"] = OPTIMAL_POSTING_TIMES["tiktok"]

        logger.info(
            f"소셜 콘텐츠 생성 완료: IG + Threads({len(data.get('threads',{}).get('posts',[]))}개) "
            f"+ TikTok({len(data.get('tiktok',{}).get('scenes',[]))}씬)"
        )
        return data

    except Exception as exc:
        logger.error(f"소셜 콘텐츠 생성 실패: {exc}")
        # 폴백: 기본 템플릿 반환
        return _fallback_social_content(post_data, blog_url, popular_tags)


def _fallback_social_content(post_data: dict, blog_url: str, popular_tags: list) -> dict:
    """Claude API 실패 시 기본 템플릿으로 소셜 콘텐츠 생성."""
    keyword  = post_data.get("keyword", "")
    title    = post_data.get("title", "")
    kw_slug  = re.sub(r"[^가-힣a-zA-Z0-9]", "", keyword)
    caption  = f"{title}\n\n💡 {keyword}에 대한 핵심 정보를 정리했습니다.\n\n저장 필수 🔖\n\n{' '.join(popular_tags)}"

    return {
        "instagram": {
            "caption": caption,
            "hookLine": title[:60],
            "storyHighlightTitle": keyword[:5],
            "hashtags": {
                "popular": popular_tags,
                "medium":  [f"#{kw_slug}"] if kw_slug else [],
                "niche":   [],
            },
            "bestPostingTimes": OPTIMAL_POSTING_TIMES["instagram"],
        },
        "threads": {
            "posts": [
                {"order": 1, "label": "1/5", "content": f"📌 {keyword} — 꼭 알아야 할 핵심 정보"},
                {"order": 2, "label": "2/5", "content": f"📊 오늘 포스팅 주제: {title}"},
                {"order": 3, "label": "3/5", "content": "🔍 자세한 내용은 블로그에서 확인하세요."},
                {"order": 4, "label": "4/5", "content": f"💡 {keyword} 관련 궁금한 점이 있으신가요?"},
                {"order": 5, "label": "5/5", "content": f"🔗 전체 글 읽기: {blog_url or '[블로그 URL]'}\n\n여러분의 생각은 어떠신가요? 댓글로 알려주세요 💬"},
            ],
            "hashtags": popular_tags[:5],
            "engagementQuestion": f"{keyword}에 대해 어떻게 생각하시나요?",
            "bestPostingTimes": OPTIMAL_POSTING_TIMES["threads"],
        },
        "tiktok": {
            "title": f"{keyword} 핵심 정리 60초",
            "thumbnailText": keyword[:20],
            "scenes": [
                {"time": "0-3초",  "text": f"⚡ {keyword} 모르면 손해!",         "direction": "화면 클로즈업", "sound": "알림음"},
                {"time": "3-15초", "text": "이걸 모르는 분들이 너무 많아요",       "direction": "정면 촬영",     "sound": "배경음악"},
                {"time": "15-35초","text": "핵심 내용 3가지",                      "direction": "텍스트 슬라이드","sound": "배경음악"},
                {"time": "35-50초","text": f"{keyword} 이렇게 활용하세요",          "direction": "인포그래픽",    "sound": "배경음악"},
                {"time": "50-60초","text": f"더 자세한 내용 → 링크 클릭! {blog_url or ''}","direction": "CTA 화면","sound": "효과음"},
            ],
            "fullScript": f"{keyword}에 대한 핵심 정보입니다. 자세한 내용은 블로그 링크를 확인하세요.",
            "commentBait": f"{keyword} 관련 경험이 있으신 분? 댓글로 공유해주세요!",
            "hashtags": ["#fyp", "#foryou", "#정보", "#꿀팁"] + popular_tags[:3],
            "backgroundMusic": {"genre": "팝", "mood": "경쾌한"},
            "bestPostingTimes": OPTIMAL_POSTING_TIMES["tiktok"],
        },
        "keyword": keyword,
        "trendDirection": "stable",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Instagram 게시
# ─────────────────────────────────────────────────────────────────────────────

def publish_instagram(social_content: dict, image_url: str | None = None) -> dict:
    """Instagram Graph API v21.0으로 이미지+캡션 게시.

    Args:
        social_content: generate_social_content() 반환값
        image_url:      공개 접근 가능한 이미지 URL (None이면 텍스트만)

    Returns:
        {"id": ..., "url": ...} 또는 {"skipped": True} 또는 {"error": ...}
    """
    if not INSTAGRAM_ACCESS_TOKEN or not INSTAGRAM_ACCOUNT_ID:
        logger.info("Instagram 크리덴셜 미설정 — 건너뜀 (INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_ACCOUNT_ID 필요)")
        return {"skipped": True, "reason": "credentials_not_configured"}

    ig      = social_content.get("instagram", {})
    caption = _format_instagram_caption(ig)
    base    = f"https://graph.instagram.com/v21.0/{INSTAGRAM_ACCOUNT_ID}"

    try:
        # Step 1: 미디어 컨테이너 생성
        params: dict = {"caption": caption, "access_token": INSTAGRAM_ACCESS_TOKEN}
        if image_url:
            params["image_url"] = image_url
            params["media_type"] = "IMAGE"
        else:
            params["media_type"] = "TEXT"

        r = requests.post(f"{base}/media", params=params, timeout=30)
        r.raise_for_status()
        creation_id = r.json()["id"]
        logger.info(f"Instagram 미디어 컨테이너 생성: {creation_id}")

        # Step 2: 컨테이너 준비 대기 (최대 30초)
        _wait_instagram_container(creation_id, timeout=30)

        # Step 3: 게시
        r2 = requests.post(
            f"{base}/media_publish",
            params={"creation_id": creation_id, "access_token": INSTAGRAM_ACCESS_TOKEN},
            timeout=30,
        )
        r2.raise_for_status()
        media_id = r2.json()["id"]
        url = f"https://www.instagram.com/p/{media_id}/"
        logger.info(f"Instagram 게시 완료: {url}")
        return {"id": media_id, "url": url}

    except Exception as exc:
        msg = getattr(exc, "response", None)
        msg = msg.json().get("error", {}).get("message", str(exc)) if msg is not None else str(exc)
        logger.error(f"Instagram 게시 실패: {msg}")
        return {"error": msg}


def _wait_instagram_container(creation_id: str, timeout: int = 30) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(
            f"https://graph.instagram.com/v21.0/{creation_id}",
            params={"fields": "status_code", "access_token": INSTAGRAM_ACCESS_TOKEN},
            timeout=15,
        )
        status = r.json().get("status_code", "")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError("Instagram 미디어 처리 오류")
        time.sleep(3)
    raise TimeoutError("Instagram 미디어 처리 시간 초과")


def _format_instagram_caption(ig: dict) -> str:
    hashtags = (
        (ig.get("hashtags", {}).get("popular") or [])
        + (ig.get("hashtags", {}).get("medium") or [])
        + (ig.get("hashtags", {}).get("niche") or [])
    )
    tag_str = " ".join(t if t.startswith("#") else f"#{t}" for t in hashtags)
    caption = ig.get("caption", "")
    return f"{caption}\n\n💡 도움이 됐다면 저장 🔖 해두세요!\n\n{tag_str}".strip()


# ─────────────────────────────────────────────────────────────────────────────
# Threads 게시
# ─────────────────────────────────────────────────────────────────────────────

def publish_threads(social_content: dict, image_url: str | None = None) -> dict:
    """Meta Threads API v1.0으로 연속 스레드(5개) 게시.

    Args:
        social_content: generate_social_content() 반환값
        image_url:      첫 포스트에 첨부할 이미지 URL (선택)

    Returns:
        {"ids": [...], "url": ...} 또는 {"skipped": True} 또는 {"error": ...}
    """
    if not THREADS_ACCESS_TOKEN or not THREADS_USER_ID:
        logger.info("Threads 크리덴셜 미설정 — 건너뜀 (THREADS_ACCESS_TOKEN, THREADS_USER_ID 필요)")
        return {"skipped": True, "reason": "credentials_not_configured"}

    th      = social_content.get("threads", {})
    posts   = th.get("posts", [])
    tags    = th.get("hashtags", [])
    base    = f"https://graph.threads.net/v1.0/{THREADS_USER_ID}"

    if not posts:
        return {"skipped": True, "reason": "no_content"}

    published_ids: list[str] = []
    reply_to_id: str | None  = None

    try:
        for i, post in enumerate(posts):
            is_first = (i == 0)
            # 마지막 포스트에 해시태그 추가
            is_last  = (i == len(posts) - 1)
            tag_str  = " ".join(t if t.startswith("#") else f"#{t}" for t in tags)
            content  = post.get("content", "")
            if is_last and tag_str:
                content = f"{content}\n\n{tag_str}"

            params: dict = {"text": content, "access_token": THREADS_ACCESS_TOKEN}
            if is_first and image_url:
                params["media_type"] = "IMAGE"
                params["image_url"]  = image_url
            else:
                params["media_type"] = "TEXT"
            if reply_to_id:
                params["reply_to_id"] = reply_to_id

            # Step 1: 컨테이너 생성
            r = requests.post(f"{base}/threads", params=params, timeout=30)
            r.raise_for_status()
            container_id = r.json()["id"]

            time.sleep(2)

            # Step 2: 게시
            r2 = requests.post(
                f"{base}/threads_publish",
                params={"creation_id": container_id, "access_token": THREADS_ACCESS_TOKEN},
                timeout=30,
            )
            r2.raise_for_status()
            media_id = r2.json()["id"]
            published_ids.append(media_id)
            reply_to_id = media_id

            logger.info(f"Threads {i + 1}/{len(posts)} 게시 완료: {media_id}")
            if i < len(posts) - 1:
                time.sleep(3)

        handle  = THREADS_HANDLE or "me"
        post_url = f"https://www.threads.net/@{handle}/post/{published_ids[0]}"
        logger.info(f"Threads 전체 게시 완료: {len(published_ids)}개")
        return {"ids": published_ids, "url": post_url}

    except Exception as exc:
        msg = getattr(exc, "response", None)
        msg = msg.json().get("error", {}).get("message", str(exc)) if msg is not None else str(exc)
        logger.error(f"Threads 게시 실패: {msg}")
        return {"error": msg}


# ─────────────────────────────────────────────────────────────────────────────
# TikTok (스크립트 저장)
# ─────────────────────────────────────────────────────────────────────────────

def save_tiktok_script(social_content: dict, keyword: str, output_dir: str = "./output/tiktok") -> dict:
    """TikTok 스크립트를 JSON 파일로 저장합니다.
    실제 영상 파일이 없으므로 스크립트만 저장하고 수동 제작을 안내합니다.
    """
    tt = social_content.get("tiktok", {})
    if not tt:
        return {"skipped": True}

    os.makedirs(output_dir, exist_ok=True)
    from datetime import datetime
    date_str  = datetime.now().strftime("%Y-%m-%d")
    slug      = re.sub(r"[^가-힣a-zA-Z0-9]", "", keyword)[:30]
    filename  = f"{date_str}_{slug}_tiktok.json"
    filepath  = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump({"keyword": keyword, "date": date_str, **tt}, f, ensure_ascii=False, indent=2)

    logger.info(f"TikTok 스크립트 저장: {filepath}")
    logger.info(f"  📽 영상 제목: {tt.get('title', '')}")
    logger.info(f"  🎵 배경음악: {tt.get('backgroundMusic', {}).get('genre', '')} — {tt.get('backgroundMusic', {}).get('mood', '')}")
    logger.info(f"  📝 씬 수: {len(tt.get('scenes', []))}개")

    return {"saved": True, "path": filepath, "title": tt.get("title", ""), "scenes": len(tt.get("scenes", []))}


# ─────────────────────────────────────────────────────────────────────────────
# 통합 게시 함수
# ─────────────────────────────────────────────────────────────────────────────

def publish_all(post_data: dict, blog_url: str = "", image_url: str | None = None) -> dict:
    """소셜 콘텐츠 생성 후 설정된 플랫폼에 게시합니다.

    Args:
        post_data:  generate_post() 반환값
        blog_url:   Blogger 게시 URL
        image_url:  Instagram/Threads에 첨부할 이미지 공개 URL (선택)

    Returns:
        {
            "socialContent": {...},
            "instagram": {...},
            "threads": {...},
            "tiktok": {...},
        }
    """
    keyword = post_data.get("keyword", "")
    logger.info(f"[소셜] '{keyword}' 콘텐츠 생성 중...")

    social_content = generate_social_content(post_data, blog_url)

    results: dict = {"socialContent": social_content}

    # Instagram
    results["instagram"] = publish_instagram(social_content, image_url)

    # Threads
    results["threads"] = publish_threads(social_content, image_url)

    # TikTok (스크립트 저장)
    results["tiktok"] = save_tiktok_script(social_content, keyword)

    _log_results(keyword, results)
    return results


def _log_results(keyword: str, results: dict) -> None:
    ig = results.get("instagram", {})
    th = results.get("threads", {})
    tt = results.get("tiktok", {})

    if ig.get("url"):
        logger.info(f"  📸 Instagram: {ig['url']}")
    elif ig.get("skipped"):
        logger.info(f"  📸 Instagram: 건너뜀 ({ig.get('reason','')})")
    elif ig.get("error"):
        logger.warning(f"  📸 Instagram 실패: {ig['error']}")

    if th.get("url"):
        logger.info(f"  🧵 Threads: {th['url']}")
    elif th.get("skipped"):
        logger.info(f"  🧵 Threads: 건너뜀 ({th.get('reason','')})")
    elif th.get("error"):
        logger.warning(f"  🧵 Threads 실패: {th['error']}")

    if tt.get("saved"):
        logger.info(f"  🎵 TikTok 스크립트 저장: {tt.get('path','')}")


# ─────────────────────────────────────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    """LLM 응답에서 JSON 객체를 추출합니다."""
    # ```json 코드블록 우선
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # 중괄호 depth 탐색
    start = text.find("{")
    if start != -1:
        depth, in_str, escape = 0, False, False
        for i, ch in enumerate(text[start:], start):
            if escape:
                escape = False
                continue
            if ch == "\\" and in_str:
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch in "{[":
                depth += 1
            elif ch in "}]":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start: i + 1])
                    except json.JSONDecodeError:
                        break

    raise ValueError("응답에서 JSON을 찾을 수 없습니다")
