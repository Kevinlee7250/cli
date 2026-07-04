"""
GSC CTR 낮은 포스트 자동 리라이팅 (주 1회 실행 권장)

흐름:
  1. GSC 쿼리 데이터에서 노출>=10 && CTR<3% 쿼리 추출
  2. docs/data/posts.json에서 해당 쿼리와 키워드/태그가 겹치는 포스트 매칭
  3. Blogger API bypath 로 포스트 ID 조회
  4. Claude (claude-haiku-4-5) 로 클릭 유발 제목 3안 생성 → 1안 적용
  5. Blogger PATCH API 로 제목 업데이트 + docs/data/posts.json 갱신
  6. 결과 요약 리포트 출력

실행:
  python gsc_optimizer.py              # 최대 5개 포스트 최적화
  python gsc_optimizer.py --dry        # 제목 후보만 출력 (실제 업데이트 없음)
  python gsc_optimizer.py --limit 10   # 처리 포스트 수 변경
"""

import argparse
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import anthropic
import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("gsc_optimizer")

# ──────────────────────────────────────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────────────────────────────────────
GSC_API_BASE   = "https://searchconsole.googleapis.com/webmasters/v3"
BLOGGER_BASE   = "https://www.googleapis.com/blogger/v3"
TOKEN_URL      = "https://oauth2.googleapis.com/token"
POSTS_JSON     = Path(__file__).parent.parent / "docs" / "data" / "posts.json"
OPT_LOG        = Path(__file__).parent / "logs" / "gsc_optimized.json"
MAX_PER_RUN    = 5     # 기본 처리 한도 (API 과부하 방지)
IMPRESSION_MIN = 10    # 최소 노출 수
CTR_THRESHOLD  = 3.0   # % (이 값 미만이면 최적화 대상)


# ──────────────────────────────────────────────────────────────────────────────
# 인증
# ──────────────────────────────────────────────────────────────────────────────

def _google_token() -> str | None:
    """Google OAuth2 refresh_token -> access_token"""
    client_id     = os.getenv("GOOGLE_CLIENT_ID") or os.getenv("BLOGGER_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET") or os.getenv("BLOGGER_CLIENT_SECRET", "")
    refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN") or os.getenv("BLOGGER_REFRESH_TOKEN", "")
    if not (client_id and client_secret and refresh_token):
        logger.error("Google OAuth 환경변수 누락 (GOOGLE_CLIENT_ID / SECRET / REFRESH_TOKEN)")
        return None
    resp = requests.post(TOKEN_URL, data={
        "client_id":     client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type":    "refresh_token",
    }, timeout=15)
    if resp.status_code == 200:
        return resp.json().get("access_token")
    logger.error(f"토큰 발급 실패: {resp.status_code} {resp.text[:200]}")
    return None


# ──────────────────────────────────────────────────────────────────────────────
# GSC — 저성과 쿼리 추출
# ──────────────────────────────────────────────────────────────────────────────

def fetch_low_ctr_queries(token: str, days: int = 30, site_url: str = "") -> list[dict]:
    """
    GSC 쿼리 데이터에서 노출 >= IMPRESSION_MIN & CTR < CTR_THRESHOLD% 쿼리를 반환.
    반환 형식: [{"query": str, "impressions": int, "ctr": float, "position": float}, ...]
    site_url 미지정 시 전역 GSC_SITE_URL을 사용합니다.
    """
    site_url = site_url or os.getenv("GSC_SITE_URL", "")
    if not site_url:
        logger.error("GSC_SITE_URL 환경변수 미설정")
        return []

    end_date   = datetime.now() - timedelta(days=3)
    start_date = end_date - timedelta(days=days)

    payload = {
        "startDate":  start_date.strftime("%Y-%m-%d"),
        "endDate":    end_date.strftime("%Y-%m-%d"),
        "dimensions": ["query"],
        "rowLimit":   500,
        "orderBy":    [{"fieldName": "impressions", "sortOrder": "DESCENDING"}],
    }
    encoded = requests.utils.quote(site_url, safe="")
    url = f"{GSC_API_BASE}/sites/{encoded}/searchAnalytics/query"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
    except requests.exceptions.RequestException as e:
        logger.error(f"GSC API 오류: {e}")
        return []

    if resp.status_code != 200:
        logger.error(f"GSC API 실패: {resp.status_code} {resp.text[:300]}")
        return []

    rows = resp.json().get("rows", [])
    low_ctr = []
    for r in rows:
        impressions = int(r.get("impressions", 0))
        ctr_pct     = round(r.get("ctr", 0) * 100, 2)  # 0~1 -> 0~100%
        position    = round(r.get("position", 0), 1)
        if impressions >= IMPRESSION_MIN and ctr_pct < CTR_THRESHOLD:
            low_ctr.append({
                "query":       r.get("keys", [""])[0],
                "impressions": impressions,
                "ctr":         ctr_pct,
                "position":    position,
            })

    logger.info(f"GSC 저CTR 쿼리 {len(low_ctr)}개 / 전체 {len(rows)}개")
    return low_ctr


# ──────────────────────────────────────────────────────────────────────────────
# posts.json 매칭
# ──────────────────────────────────────────────────────────────────────────────

def load_posts() -> list[dict]:
    """docs/data/posts.json 로드"""
    if not POSTS_JSON.exists():
        logger.warning(f"posts.json 없음: {POSTS_JSON}")
        return []
    with open(POSTS_JSON, encoding="utf-8") as f:
        return json.load(f)


def _already_optimized() -> set[str]:
    """이미 최적화한 포스트 blogUrl 집합 (30일 내 중복 방지)"""
    if not OPT_LOG.exists():
        return set()
    with open(OPT_LOG, encoding="utf-8") as f:
        records = json.load(f)
    cutoff = (datetime.now() - timedelta(days=30)).isoformat()
    return {r["blogUrl"] for r in records if r.get("optimized_at", "") > cutoff}


def match_posts_to_queries(posts: list[dict], queries: list[dict]) -> list[dict]:
    """
    GSC 저CTR 쿼리와 posts.json 의 keyword/tags 를 텍스트 매칭.
    반환: [{"post": {...}, "matched_query": {...}, "match_score": int}, ...] (노출 수 내림차순)
    """
    already_done = _already_optimized()
    matched: dict[str, dict] = {}  # blogUrl -> best match

    for query_data in queries:
        q_words = [w for w in query_data["query"].lower().split() if len(w) >= 2]
        if not q_words:
            continue
        # 쿼리가 수집된 사이트와 같은 블로그의 포스트만 매칭 (블로그 간 교차 오염 방지)
        q_site = (query_data.get("site_url") or "").rstrip("/")

        for post in posts:
            url = post.get("blogUrl", "")
            if not url or url in already_done:
                continue
            if q_site and not url.startswith(q_site):
                continue

            keyword_text = (post.get("keyword", "") or "").lower()
            tags_text    = " ".join(post.get("tags", []) or []).lower()
            title_text   = (post.get("title", "") or "").lower()
            combined     = f"{keyword_text} {title_text} {tags_text}"

            score = sum(1 for w in q_words if w in combined)
            if score < max(1, len(q_words) // 2):
                continue

            if url not in matched or score > matched[url]["match_score"]:
                matched[url] = {
                    "post":          post,
                    "matched_query": query_data,
                    "match_score":   score,
                }

    result = sorted(matched.values(), key=lambda x: x["matched_query"]["impressions"], reverse=True)
    logger.info(f"매칭 포스트 {len(result)}개")
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Blogger API — 포스트 ID 조회 & 제목 업데이트
# ──────────────────────────────────────────────────────────────────────────────

def _blog_id() -> str:
    return os.getenv("BLOGGER_BLOG_ID", "").strip()


def get_post_id_by_url(token: str, blog_url: str, blog_id: str = "") -> str | None:
    """blogUrl 의 path 로 Blogger bypath API 조회 -> post ID 반환.
    blog_id 미지정 시 전역 BLOGGER_BLOG_ID 사용."""
    parsed = re.search(r"blogspot\.com(/.+)", blog_url)
    if not parsed:
        logger.debug(f"blogspot URL 아님, 건너뜀: {blog_url}")
        return None
    path = parsed.group(1).rstrip("/")
    bid  = blog_id or _blog_id()
    if not bid:
        return None
    try:
        resp = requests.get(
            f"{BLOGGER_BASE}/blogs/{bid}/posts/bypath",
            params={"path": path},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json().get("id")
        logger.debug(f"bypath 조회 실패 [{resp.status_code}]: {path}")
    except requests.exceptions.RequestException as e:
        logger.debug(f"bypath 네트워크 오류: {e}")
    return None


def update_blogger_title(token: str, post_id: str, new_title: str, blog_id: str = "") -> bool:
    """Blogger PATCH API 로 제목만 업데이트. blog_id 미지정 시 전역 BLOGGER_BLOG_ID."""
    bid = blog_id or _blog_id()
    if not bid or not post_id:
        return False
    try:
        resp = requests.patch(
            f"{BLOGGER_BASE}/blogs/{bid}/posts/{post_id}",
            json={"title": new_title},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json",
            },
            timeout=15,
        )
        if resp.status_code == 200:
            logger.info(f"  [OK] 제목 업데이트: {new_title[:60]}")
            return True
        logger.warning(f"  [FAIL] 업데이트 실패 [{resp.status_code}]: {resp.text[:200]}")
    except requests.exceptions.RequestException as e:
        logger.warning(f"  [FAIL] 네트워크 오류: {e}")
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Claude — 클릭 유발 제목 생성
# ──────────────────────────────────────────────────────────────────────────────

def _anthropic_client() -> "anthropic.Anthropic | None":
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key or api_key.startswith("sk-ant-xxx"):
        logger.error("ANTHROPIC_API_KEY 미설정")
        return None
    return anthropic.Anthropic(api_key=api_key)


def generate_improved_titles(
    client: "anthropic.Anthropic",
    current_title: str,
    low_ctr_query: str,
    impressions: int,
    position: float,
) -> list[str]:
    """CTR 향상을 위한 개선 제목 3안 생성. 반환: [제목1, 제목2, 제목3]"""
    prompt = f"""당신은 블로그 SEO 전문가입니다.
아래 포스트가 구글 검색 노출은 높지만 클릭률이 낮습니다.

현재 제목: {current_title}
저성과 검색어: {low_ctr_query}
노출 수: {impressions}회 | CTR: 3% 미만 | 평균 순위: {position}위

다음 조건을 지킨 개선 제목 3개를 JSON 배열로 출력하세요:
- 검색어 '{low_ctr_query}'의 핵심 단어 포함 필수
- 클릭 욕구를 자극하는 숫자, 구체성, 감정 어구 활용
  (예: "직장인이 실제 해봤어요", "3가지 핵심", "2026년 최신", "솔직 후기")
- 50자 이내 (한국어 기준)
- 현재 연도(2026) 포함 권장
- 기존 제목과 다른 각도로 접근

출력 형식 (JSON 배열만, 마크다운 없이):
["제목1", "제목2", "제목3"]"""

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        match = re.search(r'\[.*?\]', raw, re.DOTALL)
        if match:
            titles = json.loads(match.group(0))
            return [t.strip() for t in titles if isinstance(t, str) and t.strip()][:3]
    except Exception as e:
        logger.warning(f"제목 생성 오류: {e}")
    return []


# ──────────────────────────────────────────────────────────────────────────────
# 최적화 이력 저장
# ──────────────────────────────────────────────────────────────────────────────

def _save_opt_log(records: list[dict]) -> None:
    OPT_LOG.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict] = []
    if OPT_LOG.exists():
        with open(OPT_LOG, encoding="utf-8") as f:
            existing = json.load(f)
    existing.extend(records)
    with open(OPT_LOG, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


def _update_posts_json(blog_url: str, new_title: str) -> None:
    """posts.json 에서 해당 포스트의 title 필드 갱신"""
    posts = load_posts()
    for p in posts:
        if p.get("blogUrl") == blog_url:
            p["title"] = new_title
            p["optimized_at"] = datetime.now().isoformat()
            break
    with open(POSTS_JSON, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────────────────────────────────────
# 메인 최적화 루프
# ──────────────────────────────────────────────────────────────────────────────

def run_optimization(dry_run: bool = False, limit: int = MAX_PER_RUN) -> dict:
    """
    GSC CTR 최적화 실행.
    dry_run=True 이면 제목 후보만 출력하고 Blogger 업데이트는 하지 않음.
    """
    logger.info("=" * 60)
    logger.info(f"GSC 제목 최적화 시작 {'[DRY RUN]' if dry_run else ''}")
    logger.info("=" * 60)

    token = _google_token()
    if not token:
        return {"optimized": 0, "skipped": 0, "details": [], "error": "토큰 발급 실패"}

    client = _anthropic_client()
    if not client:
        return {"optimized": 0, "skipped": 0, "details": [], "error": "API 키 없음"}

    # 1) GSC 저CTR 쿼리 수집 — 모든 블로그의 GSC 사이트 순회 (중복 URL 제거)
    # site_blog_map: gsc_site_url → Blogger blog_id (제목 PATCH 시 해당 블로그 API 사용)
    site_urls: list[str] = []
    site_blog_map: dict[str, str] = {}
    try:
        from config import get_blog_configs
        for b in get_blog_configs():
            u = b.get("gsc_site_url", "")
            if u and u not in site_urls:
                site_urls.append(u)
                site_blog_map[u.rstrip("/")] = str(b.get("blog_id") or "")
    except Exception as e:
        logger.debug(f"블로그 설정 로드 실패 — 전역 GSC_SITE_URL 사용: {e}")
    if not site_urls:
        site_urls = [os.getenv("GSC_SITE_URL", "")]

    low_ctr_queries: list[dict] = []
    for su in site_urls:
        qs = fetch_low_ctr_queries(token, site_url=su)
        if qs:
            logger.info(f"저CTR 쿼리 {len(qs)}개 수집: {su}")
            for q in qs:
                q["site_url"] = su  # 매칭·업데이트 시 블로그 구분용
            low_ctr_queries.extend(qs)
    if not low_ctr_queries:
        logger.info("저CTR 쿼리 없음 (모두 CTR >= 3%) — 최적화 불필요")
        return {"optimized": 0, "skipped": 0, "details": []}

    # 2) posts.json 매칭
    posts = load_posts()
    if not posts:
        logger.warning("posts.json 비어있음")
        return {"optimized": 0, "skipped": 0, "details": []}

    candidates = match_posts_to_queries(posts, low_ctr_queries)[:limit]
    logger.info(f"최적화 대상: {len(candidates)}개 (한도 {limit}개)")

    optimized = 0
    skipped   = 0
    details   = []

    for idx, item in enumerate(candidates, 1):
        post  = item["post"]
        query = item["matched_query"]
        title = post.get("title", "")
        url   = post.get("blogUrl", "")

        logger.info(f"\n[{idx}/{len(candidates)}] {title[:50]}...")
        logger.info(f"  검색어: '{query['query']}' | 노출: {query['impressions']} | CTR: {query['ctr']}%")

        # 3) Claude로 개선 제목 생성
        new_titles = generate_improved_titles(
            client,
            current_title=title,
            low_ctr_query=query["query"],
            impressions=query["impressions"],
            position=query["position"],
        )
        if not new_titles:
            logger.warning("  제목 생성 실패 — 건너뜀")
            skipped += 1
            continue

        best_title = new_titles[0]
        logger.info(f"  현재  : {title}")
        logger.info(f"  1순위 : {best_title}")
        logger.info(f"  후보  : {new_titles}")

        detail = {
            "blogUrl":        url,
            "original_title": title,
            "new_title":      best_title,
            "candidates":     new_titles,
            "query":          query["query"],
            "impressions":    query["impressions"],
            "ctr":            query["ctr"],
            "optimized_at":   datetime.now().isoformat(),
            "dry_run":        dry_run,
        }

        # 이 포스트가 속한 블로그의 Blogger ID (쿼리 수집 사이트 기준)
        target_blog_id = site_blog_map.get((query.get("site_url") or "").rstrip("/"), "")

        if not dry_run:
            # 4) Blogger 포스트 ID 조회
            post_id = get_post_id_by_url(token, url, blog_id=target_blog_id)
            if not post_id:
                logger.warning("  포스트 ID 조회 실패 — 제목 후보만 저장 (blogspot URL이 아닐 수 있음)")
                detail["blogger_updated"] = False
                detail["skip_reason"]     = "post_id 조회 실패"
                skipped += 1
            else:
                # 5) Blogger 제목 PATCH
                ok = update_blogger_title(token, post_id, best_title, blog_id=target_blog_id)
                detail["blogger_updated"] = ok
                detail["post_id"]         = post_id
                if ok:
                    _update_posts_json(url, best_title)
                    optimized += 1
                else:
                    skipped += 1
        else:
            optimized += 1  # dry run: 성공으로 카운트

        details.append(detail)
        if idx < len(candidates):
            time.sleep(2)  # API 과부하 방지

    if details:
        _save_opt_log(details)

    logger.info("\n" + "=" * 60)
    logger.info(f"최적화 완료: {optimized}개 성공 | {skipped}개 건너뜀 {'[DRY RUN]' if dry_run else ''}")
    logger.info("=" * 60)
    return {"optimized": optimized, "skipped": skipped, "details": details}


# ──────────────────────────────────────────────────────────────────────────────
# CLI 진입점
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GSC CTR 낮은 포스트 제목 자동 최적화")
    parser.add_argument("--dry",   action="store_true", help="제목 후보만 출력, 실제 업데이트 없음")
    parser.add_argument("--limit", type=int, default=MAX_PER_RUN, help=f"처리 포스트 수 (기본값: {MAX_PER_RUN})")
    args = parser.parse_args()

    report = run_optimization(dry_run=args.dry, limit=args.limit)

    print("\n📊 최적화 결과 요약")
    print(f"  성공: {report['optimized']}개")
    print(f"  건너뜀: {report['skipped']}개")
    for d in report.get("details", []):
        flag = "[OK]" if d.get("blogger_updated", args.dry) else "[SKIP]"
        print(f"  {flag} {d['original_title'][:40]}...")
        print(f"       -> {d['new_title']}")
