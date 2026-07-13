"""게시 후 성과 추적 자동화 — 포스트 생애주기 상태 판정.

추적 일정:
  7일  — 색인 여부 확인
  14일 — 첫 노출·검색어 확인
  30일 — 제목·도입부·CTR 평가
  60일 — 본문·내부 링크 보강
  90일 — 유지·통합·재작성·비공개 판단

상태: 신규 / 색인 대기 / 성장 중 / 최적화 필요 / 업데이트 필요 / 통합 후보 / 성과 우수

수집 데이터: GSC(페이지별 노출·클릭·CTR·순위), 게시 후 경과일, 제목 변경 이력,
수정 전후 성과(스냅샷 히스토리), 모델 사용 비용 추정.
GA4·AdSense는 API 자격증명(GA4_PROPERTY_ID 등)이 설정되면 확장 가능하도록 자리 확보.

실행: cd blog-automation && python post_lifecycle.py
출력: docs/data/lifecycle.json + logs/lifecycle_history.json
"""
import json
import logging
import os
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_BASE = Path(__file__).parent
REGISTRY_FILE = _BASE / "logs" / "post_registry.json"
HISTORY_FILE = _BASE / "logs" / "lifecycle_history.json"
OUTPUT_FILE = _BASE.parent / "docs" / "data" / "lifecycle.json"

GSC_API_BASE = "https://searchconsole.googleapis.com/webmasters/v3"

# 추적 일정 (게시 후 경과일 → 자동 작업)
CHECK_SCHEDULE = [
    (7,  "색인 여부 확인"),
    (14, "첫 노출·검색어 확인"),
    (30, "제목·도입부·CTR 평가"),
    (60, "본문·내부 링크 보강"),
    (90, "유지·통합·재작성·비공개 판단"),
]

# 상태 판정 임계값
CTR_LOW = 1.5          # % — 30일+ 노출은 있는데 이 미만이면 최적화 필요
IMPRESSIONS_GOOD = 300  # 성과 우수 최소 노출
CLICKS_GOOD = 30        # 성과 우수 최소 클릭
IMPRESSIONS_DEAD = 10   # 90일+ 이 미만이면 통합 후보

# 모델 비용 추정 (USD / 1M tokens) — CLAUDE_MODEL 기준 출력 단가
_MODEL_PRICE_OUT = {
    "claude-sonnet-5": 15.0,
    "claude-sonnet-4-6": 15.0,
    "claude-opus-4-8": 25.0,
    "claude-haiku-4-5": 5.0,
}


# ──────────────────────────────────────────────────────────────────────────────
# 데이터 로드
# ──────────────────────────────────────────────────────────────────────────────

def _load_json(path: Path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _google_token() -> str | None:
    """gsc_optimizer와 동일한 자격증명으로 access token 발급."""
    try:
        from gsc_optimizer import _google_token as _gt
        return _gt()
    except Exception:
        return None


def fetch_page_metrics(token: str, site_url: str, days: int = 28) -> dict[str, dict]:
    """GSC 페이지별 성과 — {url: {clicks, impressions, ctr(%), position}}."""
    if not token or not site_url:
        return {}
    from datetime import timedelta
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    encoded = urllib.parse.quote(site_url, safe="")
    try:
        r = requests.post(
            f"{GSC_API_BASE}/sites/{encoded}/searchAnalytics/query",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "startDate": str(start), "endDate": str(end),
                "dimensions": ["page"], "rowLimit": 500,
            },
            timeout=20,
        )
        if r.status_code != 200:
            logger.warning(f"GSC 페이지 조회 실패 ({site_url}): HTTP {r.status_code}")
            return {}
        out = {}
        for row in r.json().get("rows", []):
            url = row.get("keys", [""])[0]
            out[url.rstrip("/")] = {
                "clicks": row.get("clicks", 0),
                "impressions": row.get("impressions", 0),
                "ctr": round(row.get("ctr", 0) * 100, 2),
                "position": round(row.get("position", 0), 1),
            }
        return out
    except Exception as exc:
        logger.warning(f"GSC 페이지 조회 오류: {exc}")
        return {}


def fetch_top_queries_for_page(token: str, site_url: str, page_url: str, days: int = 28) -> list[dict]:
    """특정 페이지의 상위 검색어 (14일 체크: 첫 노출·검색어 확인용)."""
    if not token or not site_url or not page_url:
        return []
    from datetime import timedelta
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    encoded = urllib.parse.quote(site_url, safe="")
    try:
        r = requests.post(
            f"{GSC_API_BASE}/sites/{encoded}/searchAnalytics/query",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "startDate": str(start), "endDate": str(end),
                "dimensions": ["query"], "rowLimit": 5,
                "dimensionFilterGroups": [{"filters": [
                    {"dimension": "page", "operator": "equals", "expression": page_url}
                ]}],
            },
            timeout=20,
        )
        if r.status_code != 200:
            return []
        return [
            {"query": row.get("keys", [""])[0],
             "impressions": row.get("impressions", 0),
             "clicks": row.get("clicks", 0)}
            for row in r.json().get("rows", [])
        ]
    except Exception:
        return []


# ──────────────────────────────────────────────────────────────────────────────
# 상태 판정
# ──────────────────────────────────────────────────────────────────────────────

def days_since(published_at: str) -> int | None:
    if not published_at:
        return None
    try:
        pub = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - pub).days
    except Exception:
        return None


def due_checks(days: int | None) -> list[str]:
    """경과일 기준 도래한 자동 작업 목록."""
    if days is None:
        return []
    return [label for d, label in CHECK_SCHEDULE if days >= d]


def evaluate_status(days: int | None, metrics: dict, prev: dict | None) -> str:
    """생애주기 상태를 판정합니다.

    상태: 신규 / 색인 대기 / 성장 중 / 최적화 필요 / 업데이트 필요 / 통합 후보 / 성과 우수
    """
    if days is None:
        return "신규"
    imp = metrics.get("impressions", 0)
    clicks = metrics.get("clicks", 0)
    ctr = metrics.get("ctr", 0.0)

    # 성과 우수 — 경과일 무관 최우선
    if clicks >= CLICKS_GOOD or (imp >= IMPRESSIONS_GOOD and ctr >= 3.0):
        return "성과 우수"
    if days < 7:
        return "신규"
    if imp == 0:
        # 7일+ 노출 없음 → 색인 대기, 90일 넘도록 없으면 통합 후보
        return "통합 후보" if days >= 90 else "색인 대기"
    if days >= 90 and imp < IMPRESSIONS_DEAD:
        return "통합 후보"
    if days >= 60:
        prev_clicks = (prev or {}).get("clicks")
        declining = prev_clicks is not None and clicks < prev_clicks
        if declining or clicks == 0:
            return "업데이트 필요"
    if days >= 30 and ctr < CTR_LOW:
        return "최적화 필요"
    return "성장 중"


def estimate_model_cost(word_count: int) -> float:
    """모델 사용 비용 추정(USD) — 본문 길이 기반 근사치.

    한국어 1자 ≈ 1.5 토큰, 재시도·팩트체크·이미지 검증 오버헤드 ×2 가정.
    """
    model = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")
    price = _MODEL_PRICE_OUT.get(model, 15.0)
    est_tokens = word_count * 1.5 * 2
    return round(est_tokens / 1_000_000 * price, 4)


# ──────────────────────────────────────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────────────────────────────────────

def run() -> dict:
    registry = _load_json(REGISTRY_FILE, [])
    if not registry:
        # 레지스트리가 없으면 대시보드 posts.json 폴백
        posts_json = _load_json(_BASE.parent / "docs" / "data" / "posts.json", [])
        registry = [
            {"post_id": p.get("id", ""), "title": p.get("title", ""),
             "blogId": p.get("blogId", ""), "blogUrl": p.get("blogUrl", ""),
             "publishedAt": p.get("date", ""), "status": "published",
             "wordCount": p.get("wordCount", 0)}
            for p in posts_json
        ]
    published = [p for p in registry if p.get("status") == "published" and p.get("blogUrl")]
    logger.info(f"추적 대상 게시물: {len(published)}개")

    history = _load_json(HISTORY_FILE, {})
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 블로그별 GSC 페이지 데이터 수집
    token = _google_token()
    site_urls = {}
    try:
        from config import get_blog_configs
        for cfg in get_blog_configs():
            if cfg.get("gsc_site_url"):
                site_urls[cfg["id"]] = cfg["gsc_site_url"]
    except Exception:
        pass
    page_metrics: dict[str, dict] = {}
    if token:
        for bid, site in site_urls.items():
            page_metrics.update(fetch_page_metrics(token, site))
    else:
        logger.warning("GSC 토큰 없음 — 노출·클릭 데이터 없이 경과일 기준으로만 판정")

    # 제목 A/B: 변경 후 28일 지난 건 전후 비교 → 하락 시 복원 제안
    try:
        from title_ab_tracker import evaluate_changes
        n = evaluate_changes(page_metrics)
        if n:
            logger.info(f"제목 A/B 평가 완료: {n}건")
    except Exception as exc:
        logger.warning(f"제목 A/B 평가 실패: {exc}")

    results = []
    status_count: dict[str, int] = {}
    for p in published:
        pid = p.get("post_id", "")
        url = (p.get("blogUrl") or "").rstrip("/")
        days = days_since(p.get("publishedAt", ""))
        metrics = page_metrics.get(url, {"clicks": 0, "impressions": 0, "ctr": 0.0, "position": 0.0})

        snapshots = history.get(pid, [])
        prev = snapshots[-1] if snapshots else None
        status = evaluate_status(days, metrics, prev)
        status_count[status] = status_count.get(status, 0) + 1

        # 제목 변경 이력 — 이전 스냅샷과 다르면 기록
        title = p.get("title", "")
        title_history = [s["title"] for s in snapshots if s.get("title")]
        if title and (not title_history or title_history[-1] != title):
            title_history.append(title)

        # 14일 체크: 첫 노출 검색어 (노출이 생긴 포스트만, 토큰 있을 때)
        top_queries = []
        if token and days is not None and days >= 14 and metrics["impressions"] > 0:
            site = site_urls.get(p.get("blogId", ""), "")
            top_queries = fetch_top_queries_for_page(token, site, p.get("blogUrl", ""))

        entry = {
            "post_id": pid,
            "title": title,
            "blogId": p.get("blogId", ""),
            "blogUrl": p.get("blogUrl", ""),
            "publishedAt": p.get("publishedAt", ""),
            "daysSincePublish": days,
            "status": status,
            "dueChecks": due_checks(days),
            "metrics": metrics,
            "topQueries": top_queries,
            "titleHistory": title_history[-5:],
            "prevMetrics": {k: prev[k] for k in ("clicks", "impressions", "ctr") if prev and k in prev} if prev else None,
            "estimatedModelCostUSD": estimate_model_cost(p.get("wordCount", 0)),
            # GA4·AdSense — 자격증명 설정 시 확장 (현재 미연결)
            "ga4": None,
            "adsense": None,
        }
        results.append(entry)

        # 스냅샷 기록 (하루 1회 — 같은 날짜면 갱신)
        snap = {"date": today, "title": title, "status": status, **metrics}
        if snapshots and snapshots[-1].get("date") == today:
            snapshots[-1] = snap
        else:
            snapshots.append(snap)
        history[pid] = snapshots[-24:]  # 최근 24개 스냅샷 유지

    output = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "gscConnected": bool(token),
        "schedule": [{"days": d, "task": t} for d, t in CHECK_SCHEDULE],
        "summary": status_count,
        "posts": sorted(results, key=lambda x: (x["daysSincePublish"] is None, -(x["daysSincePublish"] or 0))),
    }

    os.makedirs(OUTPUT_FILE.parent, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    os.makedirs(HISTORY_FILE.parent, exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    logger.info(f"생애주기 판정 완료: {status_count} → {OUTPUT_FILE}")
    return output


if __name__ == "__main__":
    run()
