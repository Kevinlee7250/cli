"""
블로그 성과 분석 모듈 — Feature 4: 데이터 기반 의사결정
========================================================
A. Blogger API로 실제 블로그 전체 조회수(30일) 수집
B. GSC 페이지별 클릭/노출/CTR 수집 (dimensions=["page"])
C. 포스트별 추정 조회수 및 실제 수익 재계산
D. S/A/B/C 등급 자동 분류 (C급 = 리라이팅 or 삭제 대상)
E. docs/data/posts.json에 분석 필드 업데이트
F. logs/analytics_report.json에 요약 리포트 저장

등급 기준 (30일 GSC 데이터 기준):
  S: composite_score ≥ 200  — 최상위 성과, 시리즈 확장 권장
  A: composite_score ≥ 50   — 양호, 유지 관리
  B: composite_score ≥ 15   — 기본 성과, 개선 가능
  C: composite_score < 15   — 성과 미흡, 리라이팅/삭제 검토
  (14일 미만 신규 포스트는 자동으로 B 이상 보장)

CLI 사용법:
  python blog_analytics.py              # 전체 분석 + posts.json 업데이트
  python blog_analytics.py --dry        # 미리보기만 (파일 수정 없음)
  python blog_analytics.py --limit 20   # 최신 20개 포스트만 처리
  python blog_analytics.py --report     # 성과 리포트만 출력 (업데이트 없음)
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Optional

import requests

# ──────────────────────────────────────────────────────────────────────────────
# 로거 설정
# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# 경로 상수
# ──────────────────────────────────────────────────────────────────────────────
_DIR = os.path.dirname(__file__)
_POSTS_JSON = os.path.join(_DIR, "..", "docs", "data", "posts.json")
_ANALYTICS_LOG = os.path.join(_DIR, "logs", "analytics_report.json")
_ANALYTICS_EXPORT = os.path.join(_DIR, "..", "docs", "data", "analytics_summary.json")

BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"
GSC_API_BASE = "https://searchconsole.googleapis.com/webmasters/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"

# ──────────────────────────────────────────────────────────────────────────────
# CPC 테이블 (dashboard_exporter._cpc_for_category 와 동기화)
# ──────────────────────────────────────────────────────────────────────────────
_CPC_MAP: dict[str, float] = {
    "법률": 3.2, "부동산": 2.8, "금융": 2.5, "건강": 1.8,
    "기술": 1.5, "교육": 1.3, "여행": 1.2, "스포츠": 1.1, "쇼핑": 0.9,
}
_DEFAULT_CPC = 0.9
_ADSENSE_CTR = 0.025  # AdSense 평균 CTR 2.5%


# ──────────────────────────────────────────────────────────────────────────────
# OAuth 토큰 발급 (Blogger / GSC 공용)
# ──────────────────────────────────────────────────────────────────────────────

def _get_oauth_token(client_id: str, client_secret: str, refresh_token: str) -> Optional[str]:
    """Google OAuth2 refresh_token으로 access_token을 발급합니다."""
    if not client_id or not refresh_token:
        return None
    try:
        resp = requests.post(
            TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json().get("access_token")
        logger.warning(f"OAuth 토큰 발급 실패: HTTP {resp.status_code}")
        return None
    except Exception as exc:
        logger.debug(f"OAuth 토큰 오류: {exc}")
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Feature A: Blogger API 실제 조회수 수집
# ──────────────────────────────────────────────────────────────────────────────

def fetch_blogger_pageviews(blog_id: str, token: str) -> dict[str, int]:
    """
    Blogger API로 블로그 전체 조회수를 수집합니다.
    반환값: {"total_30d": 12345, "total_7d": 3456, "total_1d": 567}
    실패 시 모두 0 반환.
    """
    if not blog_id or not token:
        logger.debug("BLOGGER_BLOG_ID 또는 토큰 없음 — Blogger 조회수 수집 생략")
        return {"total_30d": 0, "total_7d": 0, "total_1d": 0}

    headers = {"Authorization": f"Bearer {token}"}
    result: dict[str, int] = {"total_30d": 0, "total_7d": 0, "total_1d": 0}

    for range_label, key in [("30DAYS", "total_30d"), ("7DAYS", "total_7d"), ("1DAYS", "total_1d")]:
        try:
            url = f"{BLOGGER_API_BASE}/blogs/{blog_id}/pageviews"
            resp = requests.get(
                url,
                headers=headers,
                params={"range": range_label},
                timeout=15,
            )
            if resp.status_code == 200:
                raw = resp.json()
                logger.info(f"Blogger API [{range_label}] 응답: {str(raw)[:300]}")
                counts = raw.get("counts", [])
                for item in counts:
                    if item.get("timeRange") == range_label:
                        result[key] = int(item.get("count", 0))
                        break
            elif resp.status_code == 403:
                logger.warning("Blogger 조회수 API 권한 없음 (블로그 소유자 확인 필요)")
                break
            else:
                logger.warning(f"Blogger 조회수 API [{range_label}]: HTTP {resp.status_code} — {resp.text[:200]}")
        except Exception as exc:
            logger.debug(f"Blogger 조회수 API 오류 [{range_label}]: {exc}")

    logger.info(
        f"Blogger 실제 조회수 — 30일: {result['total_30d']:,} | "
        f"7일: {result['total_7d']:,} | 1일: {result['total_1d']:,}"
    )
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Feature A/B: GSC 페이지별 데이터 수집
# ──────────────────────────────────────────────────────────────────────────────

def fetch_gsc_page_data(
    site_url: str,
    token: str,
    days: int = 30,
    row_limit: int = 500,
) -> dict[str, dict]:
    """
    GSC API에서 페이지(URL)별 클릭/노출/CTR/순위를 수집합니다.
    반환값: {
      "https://blog.com/post1": {"clicks": 5, "impressions": 230, "ctr": 2.17, "position": 8.3},
      ...
    }
    """
    if not site_url or not token:
        return {}

    end_date = datetime.now() - timedelta(days=3)  # GSC는 3일 지연
    start_date = end_date - timedelta(days=days)

    payload = {
        "startDate": start_date.strftime("%Y-%m-%d"),
        "endDate": end_date.strftime("%Y-%m-%d"),
        "dimensions": ["page"],
        "rowLimit": row_limit,
        "orderBy": [{"fieldName": "clicks", "sortOrder": "DESCENDING"}],
    }

    encoded_url = requests.utils.quote(site_url, safe="")
    url = f"{GSC_API_BASE}/sites/{encoded_url}/searchAnalytics/query"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
    except Exception as exc:
        logger.warning(f"GSC 페이지 데이터 요청 실패: {exc}")
        return {}

    if resp.status_code == 403:
        logger.warning("GSC 권한 없음 — Search Console에 사이트 등록 여부 확인")
        return {}
    if resp.status_code != 200:
        logger.debug(f"GSC 페이지 데이터 오류: HTTP {resp.status_code}")
        return {}

    rows = resp.json().get("rows", [])
    page_data: dict[str, dict] = {}
    for row in rows:
        page_url = row.get("keys", [""])[0]
        if page_url:
            page_data[page_url] = {
                "clicks": int(row.get("clicks", 0)),
                "impressions": int(row.get("impressions", 0)),
                "ctr": round(row.get("ctr", 0) * 100, 2),
                "position": round(row.get("position", 0), 1),
            }

    logger.info(f"GSC 페이지별 데이터 수집: {len(page_data)}개 URL")
    return page_data


# ──────────────────────────────────────────────────────────────────────────────
# Feature B/C: 포스트별 추정 조회수 계산
# ──────────────────────────────────────────────────────────────────────────────

def estimate_post_pageviews(
    post_url: str,
    gsc_page_data: dict[str, dict],
    total_blog_views_30d: int,
    total_gsc_clicks: int,
    total_posts: int,
) -> int:
    """
    포스트 1개의 추정 조회수(30일)를 계산합니다.

    공식:
      GSC 데이터 있음: blog_total × (post_clicks / all_clicks)
      GSC 데이터 없음: blog_total / total_posts (균등 배분)
      Blogger API 조회수 없음: GSC 클릭 × 경험적 배율(15배)
    """
    post_gsc = gsc_page_data.get(post_url, {})
    post_clicks = post_gsc.get("clicks", 0)

    if total_blog_views_30d > 0 and total_gsc_clicks > 0:
        # 비례 배분: 해당 포스트의 GSC 클릭 비중 × 전체 블로그 조회수
        ratio = post_clicks / total_gsc_clicks
        return max(1, int(total_blog_views_30d * ratio))
    elif total_blog_views_30d > 0 and total_posts > 0:
        # GSC 클릭 없으면 균등 배분
        return max(1, int(total_blog_views_30d / total_posts))
    elif post_clicks > 0:
        # Blogger 조회수 없을 때: 검색 클릭 × 15 (경험적 배율)
        return post_clicks * 15
    else:
        # 최소 추정 (포스트 나이 기반: 30일 지나면 80뷰/일 × 30일)
        return 0


# ──────────────────────────────────────────────────────────────────────────────
# Feature D: S/A/B/C 등급 분류
# ──────────────────────────────────────────────────────────────────────────────

def calculate_grade(
    clicks: int,
    impressions: int,
    ctr: float,
    position: float,
    estimated_views: int,
    post_date_str: str,
) -> tuple[str, float, str]:
    """
    포스트 성과 등급을 계산합니다.

    반환값: (grade, score, action_hint)
    grade: "S" | "A" | "B" | "C"
    score: composite score
    action_hint: 권장 조치 설명
    """
    today = datetime.now()
    try:
        post_date = datetime.strptime(post_date_str, "%Y-%m-%d")
        age_days = max(0, (today - post_date).days)
    except ValueError:
        age_days = 30  # 날짜 파싱 실패 시 30일로 간주

    # ── 복합 점수 계산 ─────────────────────────────────────────────────────
    # 클릭: 수익 직결 (가중치 최고)
    score = clicks * 15.0
    # 노출: 잠재 트래픽
    score += impressions * 0.05
    # CTR: 콘텐츠 매력도
    score += ctr * 3.0
    # 1페이지 진입 보너스 (순위 1~10위)
    if 1.0 <= position <= 10.0:
        score += 20.0
    # 추정 조회수 보조 지표
    score += estimated_views * 0.02

    # ── 나이 보정 ─────────────────────────────────────────────────────────
    # 14일 미만 신규 포스트는 데이터 축적 전: B 이상 보장
    if age_days < 14:
        score = max(score, 20.0)
    # 90일 이상 노출이 거의 없으면 C 확정
    if age_days >= 90 and impressions < 10:
        score = min(score, 10.0)

    score = round(score, 1)

    # ── 등급 판정 ─────────────────────────────────────────────────────────
    if score >= 200:
        grade = "S"
        hint = "최상위 성과 — 유사 주제 시리즈 포스트 확장 권장"
    elif score >= 50:
        grade = "A"
        hint = "양호 — 내부 링크 강화 및 제목 A/B 테스트 고려"
    elif score >= 15:
        grade = "B"
        hint = "기본 성과 — 키워드 최적화 및 콘텐츠 보강 검토"
    else:
        if age_days < 14:
            grade = "B"
            hint = f"신규 포스트 ({age_days}일) — 데이터 축적 대기 중"
        else:
            grade = "C"
            hint = "성과 미흡 — 리라이팅 또는 삭제 검토 대상"

    return grade, score, hint


# ──────────────────────────────────────────────────────────────────────────────
# Feature C: 수익 재계산
# ──────────────────────────────────────────────────────────────────────────────

def calculate_revenue(
    estimated_views_30d: int,
    adsense_category: str,
    cpc: float = 0.0,
) -> dict[str, float]:
    """
    실제 조회수 기반 수익을 재계산합니다.
    반환값: {"estimated30d": 1.23, "estimatedMonthly": 1.23, "cpc": 0.9}
    """
    effective_cpc = cpc if cpc > 0 else _CPC_MAP.get(adsense_category, _DEFAULT_CPC)
    clicks = estimated_views_30d * _ADSENSE_CTR
    revenue_30d = round(clicks * effective_cpc, 4)
    return {
        "estimated30d": revenue_30d,
        "estimatedMonthly": revenue_30d,  # 30일 = 월 수익
        "cpc": round(effective_cpc, 2),
        "estimatedClicks30d": round(clicks, 1),
    }


# ──────────────────────────────────────────────────────────────────────────────
# posts.json 읽기/쓰기
# ──────────────────────────────────────────────────────────────────────────────

def load_posts(limit: int = 0) -> list[dict]:
    """docs/data/posts.json을 로드합니다."""
    if not os.path.exists(_POSTS_JSON):
        logger.warning(f"posts.json 없음: {_POSTS_JSON}")
        return []
    with open(_POSTS_JSON, encoding="utf-8") as f:
        posts = json.load(f)
    if limit > 0:
        posts = posts[:limit]
    logger.info(f"posts.json 로드: {len(posts)}개 포스트")
    return posts


def save_posts(posts: list[dict]) -> None:
    """docs/data/posts.json에 저장합니다."""
    os.makedirs(os.path.dirname(_POSTS_JSON), exist_ok=True)
    with open(_POSTS_JSON, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)
    logger.info(f"posts.json 저장 완료: {len(posts)}개")


# ──────────────────────────────────────────────────────────────────────────────
# 리포트 저장
# ──────────────────────────────────────────────────────────────────────────────

def save_analytics_report(report: dict) -> None:
    """분석 결과를 logs/analytics_report.json 및 docs/data/analytics_summary.json에 저장합니다."""
    os.makedirs(os.path.dirname(_ANALYTICS_LOG), exist_ok=True)
    with open(_ANALYTICS_LOG, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    os.makedirs(os.path.dirname(_ANALYTICS_EXPORT), exist_ok=True)
    with open(_ANALYTICS_EXPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    logger.info(f"분석 리포트 저장: {_ANALYTICS_LOG}")


# ──────────────────────────────────────────────────────────────────────────────
# 메인 실행 함수
# ──────────────────────────────────────────────────────────────────────────────

def run_analytics(
    dry_run: bool = False,
    limit: int = 0,
    report_only: bool = False,
) -> dict:
    """
    블로그 성과 분석 메인 함수.
    반환값: 분석 결과 요약 딕셔너리
    """
    # ── 설정 로드 ────────────────────────────────────────────────────────────
    try:
        from config import (  # noqa: PLC0415
            BLOGGER_CLIENT_ID, BLOGGER_CLIENT_SECRET, BLOGGER_REFRESH_TOKEN,
            BLOGGER_BLOG_ID, GSC_SITE_URL,
        )
        client_id = BLOGGER_CLIENT_ID or ""
        client_secret = BLOGGER_CLIENT_SECRET or ""
        refresh_token = BLOGGER_REFRESH_TOKEN or ""
        blog_id = BLOGGER_BLOG_ID or ""
        gsc_site_url = GSC_SITE_URL or ""
    except ImportError:
        client_id = os.getenv("GOOGLE_CLIENT_ID", "")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
        refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN", "")
        blog_id = os.getenv("BLOGGER_BLOG_ID", "")
        gsc_site_url = os.getenv("GSC_SITE_URL", "")

    # ── OAuth 토큰 ───────────────────────────────────────────────────────────
    token = _get_oauth_token(client_id, client_secret, refresh_token)
    if not token:
        logger.warning("OAuth 토큰 발급 실패 — Blogger/GSC 데이터 없이 기본값으로 등급 분류")

    # ── Feature A: Blogger 실제 조회수 수집 ─────────────────────────────────
    blogger_views = fetch_blogger_pageviews(blog_id, token or "")
    total_blog_views_30d = blogger_views["total_30d"]

    # ── Feature B: GSC 페이지별 클릭 데이터 수집 ────────────────────────────
    gsc_page_data: dict[str, dict] = {}
    if gsc_site_url and token:
        gsc_page_data = fetch_gsc_page_data(gsc_site_url, token)

    total_gsc_clicks = sum(d["clicks"] for d in gsc_page_data.values())

    # ── posts.json 로드 ──────────────────────────────────────────────────────
    posts = load_posts(limit)
    if not posts:
        return {"error": "posts.json 없음 또는 빈 파일"}

    # ── 포스트별 분석 ────────────────────────────────────────────────────────
    grade_counts: dict[str, int] = {"S": 0, "A": 0, "B": 0, "C": 0}
    total_revenue_30d = 0.0
    rewrite_targets: list[dict] = []
    top_performers: list[dict] = []

    updated_posts = []
    for post in posts:
        post_url = post.get("blogUrl", "")
        category = post.get("adsenseCategory", "일반")
        cpc = float(post.get("estimatedCPC", 0))
        post_date = post.get("date", "2020-01-01")

        # GSC 데이터 매핑
        gsc_info = gsc_page_data.get(post_url, {})
        clicks = gsc_info.get("clicks", 0)
        impressions = gsc_info.get("impressions", 0)
        ctr = gsc_info.get("ctr", 0.0)
        position = gsc_info.get("position", 0.0)

        # 추정 조회수
        est_views = estimate_post_pageviews(
            post_url, gsc_page_data, total_blog_views_30d,
            total_gsc_clicks, len(posts)
        )

        # 등급 계산
        grade, score, hint = calculate_grade(
            clicks, impressions, ctr, position, est_views, post_date
        )

        # 수익 재계산
        revenue = calculate_revenue(est_views, category, cpc)
        total_revenue_30d += revenue["estimated30d"]

        # posts 업데이트
        post.update({
            "grade": grade,
            "gradeScore": score,
            "gradeHint": hint,
            "gscClicks30d": clicks,
            "gscImpressions30d": impressions,
            "gscCTR30d": ctr,
            "gscPosition30d": position,
            "estimatedPageviews30d": est_views,
            "estimatedRevenue30d": revenue["estimated30d"],
            "revenueUpdatedAt": datetime.now().strftime("%Y-%m-%d"),
        })
        updated_posts.append(post)
        grade_counts[grade] += 1

        if grade == "C":
            rewrite_targets.append({
                "id": post.get("id", ""),
                "title": post.get("title", ""),
                "keyword": post.get("keyword", ""),
                "blogUrl": post_url,
                "score": score,
                "date": post_date,
                "clicks30d": clicks,
                "impressions30d": impressions,
                "hint": hint,
            })
        elif grade == "S":
            top_performers.append({
                "id": post.get("id", ""),
                "title": post.get("title", ""),
                "keyword": post.get("keyword", ""),
                "blogUrl": post_url,
                "score": score,
                "clicks30d": clicks,
                "impressions30d": impressions,
                "revenue30d": revenue["estimated30d"],
            })

    # 성과 순 정렬
    rewrite_targets.sort(key=lambda x: x["score"])
    top_performers.sort(key=lambda x: -x["score"])

    # ── 요약 리포트 생성 ─────────────────────────────────────────────────────
    report = {
        "generatedAt": datetime.now().isoformat(),
        "period": "30days",
        "totalPosts": len(posts),
        "bloggerPageviews30d": total_blog_views_30d,
        "bloggerPageviews7d": blogger_views["total_7d"],
        "totalGscClicks30d": total_gsc_clicks,
        "totalEstimatedRevenue30d": round(total_revenue_30d, 4),
        "totalEstimatedRevenueMonthly": round(total_revenue_30d, 4),
        "gradeDistribution": grade_counts,
        "gradePercentage": {
            g: round(cnt / len(posts) * 100, 1)
            for g, cnt in grade_counts.items()
        },
        "rewriteTargets": rewrite_targets[:20],       # 상위 20개 C급
        "topPerformers": top_performers[:10],           # 상위 10개 S급
        "dataSource": {
            "bloggerApi": total_blog_views_30d > 0,
            "gscPageData": len(gsc_page_data) > 0,
            "gscUrlsMatched": sum(1 for p in posts if p.get("blogUrl") in gsc_page_data),
        },
    }

    # ── 결과 출력 ────────────────────────────────────────────────────────────
    logger.info("\n" + "="*60)
    logger.info(f"  블로그 성과 분석 결과")
    logger.info("="*60)
    logger.info(f"  분석 포스트: {len(posts)}개")
    logger.info(f"  Blogger 실제 조회수(30일): {total_blog_views_30d:,}회")
    logger.info(f"  GSC 총 클릭(30일): {total_gsc_clicks:,}회")
    logger.info(f"  추정 월 수익: ${total_revenue_30d:.2f} USD")
    logger.info(f"  등급 분포:")
    for g in ["S", "A", "B", "C"]:
        cnt = grade_counts[g]
        pct = cnt / len(posts) * 100 if posts else 0
        bar = "█" * min(cnt, 30)
        label = {"S": "최우수", "A": "양호", "B": "기본", "C": "요주의"}[g]
        logger.info(f"    {g} ({label}): {cnt}개 ({pct:.0f}%) {bar}")
    logger.info(f"  C급 리라이팅 대상: {len(rewrite_targets)}개")
    if rewrite_targets[:3]:
        for t in rewrite_targets[:3]:
            logger.info(f"    ⚠️  [{t['title'][:30]}] score={t['score']}")
    if top_performers[:3]:
        logger.info(f"  S급 최고 성과:")
        for t in top_performers[:3]:
            logger.info(f"    ⭐ [{t['title'][:30]}] score={t['score']} clicks={t['clicks30d']}")
    logger.info("="*60 + "\n")

    # ── 저장 ─────────────────────────────────────────────────────────────────
    if not dry_run and not report_only:
        save_posts(updated_posts)
        save_analytics_report(report)
        logger.info("✅ posts.json 및 analytics_summary.json 업데이트 완료")
    elif report_only:
        save_analytics_report(report)
        logger.info("📊 분석 리포트만 저장 (posts.json 미변경)")
    else:
        logger.info("🔍 --dry 모드: 실제 파일 변경 없음")

    return report


# ──────────────────────────────────────────────────────────────────────────────
# CLI 엔트리포인트
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="블로그 성과 분석 — Blogger 조회수 + GSC + S/A/B/C 등급",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예:
  python blog_analytics.py              # 전체 분석 + posts.json 업데이트
  python blog_analytics.py --dry        # 미리보기만 (파일 변경 없음)
  python blog_analytics.py --limit 30   # 최신 30개만 처리
  python blog_analytics.py --report     # 리포트 저장만 (posts.json 유지)
        """,
    )
    parser.add_argument("--dry", action="store_true", help="미리보기 모드 (파일 변경 없음)")
    parser.add_argument("--limit", type=int, default=0, help="처리할 최대 포스트 수 (0=전체)")
    parser.add_argument("--report", action="store_true", help="리포트 저장만 (posts.json 유지)")
    args = parser.parse_args()

    result = run_analytics(
        dry_run=args.dry,
        limit=args.limit,
        report_only=args.report,
    )

    if "error" in result:
        print(f"❌ 오류: {result['error']}")
        sys.exit(1)

    print(f"\n✅ 분석 완료: {result['totalPosts']}개 포스트")
    print(f"   등급: S={result['gradeDistribution']['S']} | A={result['gradeDistribution']['A']} | B={result['gradeDistribution']['B']} | C={result['gradeDistribution']['C']}")
    print(f"   추정 월 수익: ${result['totalEstimatedRevenueMonthly']:.2f} USD")
    print(f"   C급 리라이팅 대상: {len(result['rewriteTargets'])}개")
    if result['rewriteTargets']:
        print("   C급 포스트 목록:")
        for t in result['rewriteTargets'][:5]:
            print(f"     ⚠️  {t['title'][:50]}")


if __name__ == "__main__":
    main()
