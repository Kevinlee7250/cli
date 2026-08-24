#!/usr/bin/env python3
"""
주간 학습 및 시스템 점검 모듈
매주 일요일 23:00 KST (UTC 14:00) 자동 실행

기능:
  - 지난 7일 운영 데이터 수집 및 분석
  - Claude AI 기반 인사이트·추천 키워드 도출
  - 자동 개선사항 적용 (학습 키워드 저장)
  - learning.json 에 이력 누적, docs/data/ 로 내보내기
"""

import json
import logging
import os
import sys
from datetime import datetime, timedelta

from dotenv import load_dotenv
from config import claude_text

load_dotenv()

_log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_log_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(_log_dir, "weekly_learning.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger("weekly_learning")

# ── 경로 상수 ────────────────────────────────────────────────────────────────
_BASE = os.path.dirname(__file__)
LEARNING_FILE = os.path.join(_BASE, "logs", "learning.json")
HISTORY_FILE = os.path.join(_BASE, "logs", "run_history.json")
KEYWORDS_USED_FILE = os.path.join(_BASE, "logs", "used_keywords.json")
LEARNED_KW_FILE = os.path.join(_BASE, "logs", "learned_keywords.json")
# 주간 학습 → 다음 주 글쓰기 프롬프트에 자동 주입되는 지침 (content_generator가 읽음)
WRITING_TIPS_FILE = os.path.join(_BASE, "logs", "learned_writing_tips.json")
DOCS_DATA_DIR = os.path.join(_BASE, "..", "docs", "data")
ANALYTICS_SUMMARY_FILE = os.path.join(DOCS_DATA_DIR, "analytics_summary.json")


# ── 유틸 ─────────────────────────────────────────────────────────────────────
def _load(path, default=None):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"파일 로드 실패 ({path}): {e}")
    return default if default is not None else []


def _save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── 데이터 수집 ───────────────────────────────────────────────────────────────
def _collect_week_data():
    """최근 7일 실행 이력을 반환합니다."""
    history = _load(HISTORY_FILE)
    cutoff = datetime.now() - timedelta(days=7)
    return [
        r for r in history
        if datetime.fromisoformat(r.get("runAt", "2000-01-01T00:00:00")) > cutoff
    ]


def _build_blog_breakdown(week_runs: list[dict]) -> dict:
    """블로그별 집계 — 3개 블로그를 하나로 뭉뚱그리면 특정 블로그의 문제가
    다른 블로그 실적에 가려지므로 블로그 단위로 분리해서 진단합니다."""
    by_blog: dict[str, dict] = {}
    for r in week_runs:
        bid = r.get("blogId", "default")
        b = by_blog.setdefault(bid, {
            "blog_name": r.get("blogName", bid),
            "runs": 0, "posts_generated": 0, "posts_uploaded": 0,
            "pending_review": 0, "errors": 0,
        })
        b["runs"] += 1
        b["posts_generated"] += r.get("postsGenerated", 0)
        b["posts_uploaded"] += r.get("bloggerUploaded", 0)
        b["pending_review"] += r.get("pendingReview", 0)
        b["errors"] += r.get("errors", 0)
    for b in by_blog.values():
        gen = max(b["posts_generated"], 1)
        b["pending_rate_pct"] = round(b["pending_review"] / gen * 100, 1)
        b["upload_rate_pct"] = round(b["posts_uploaded"] / gen * 100, 1)
    return by_blog


def _load_real_performance() -> dict | None:
    """blog_analytics.py 가 생성한 실제 Blogger/GSC 성과 데이터(analytics_summary.json)를
    있으면 로드합니다. 정적 CPC 가정 대신 실제 클릭·수익 데이터로 카테고리 가치를 판단합니다."""
    if not os.path.exists(ANALYTICS_SUMMARY_FILE):
        return None
    try:
        with open(ANALYTICS_SUMMARY_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return {
            "blogger_pageviews_30d": data.get("bloggerPageviews30d", 0),
            "gsc_clicks_30d": data.get("totalGscClicks30d", 0),
            "estimated_monthly_revenue": data.get("totalEstimatedRevenueMonthly", 0),
            "grade_distribution": data.get("gradeDistribution", {}),
            "top_performers": [
                {"title": p.get("title", ""), "keyword": p.get("keyword", ""), "clicks30d": p.get("clicks30d", 0)}
                for p in data.get("topPerformers", [])[:5]
            ],
            "rewrite_targets": [
                {"title": p.get("title", ""), "keyword": p.get("keyword", ""), "hint": p.get("hint", "")}
                for p in data.get("rewriteTargets", [])[:5]
            ],
        }
    except Exception as e:
        logger.warning(f"실제 성과 데이터 로드 실패 (무시): {e}")
        return None


def _build_summary(week_runs: list[dict]) -> dict:
    """주간 데이터에서 집계 요약을 만듭니다."""
    all_posts = [p for r in week_runs for p in r.get("posts", [])]
    all_keywords = [kw for r in week_runs for kw in r.get("keywords", [])]
    total_errors = sum(r.get("errors", 0) for r in week_runs)
    total_posts = sum(r.get("postsGenerated", 0) for r in week_runs)
    total_uploaded = sum(r.get("bloggerUploaded", 0) for r in week_runs)
    total_pending = sum(r.get("pendingReview", 0) for r in week_runs)

    # adsenseCategory 가 없는 구형 이력은 keyword 로 카테고리를 도출 (하위 호환)
    _CAT_KW = {
        "금융": ["주식", "코인", "ETF", "펀드", "재테크", "투자", "금리", "배당", "채권", "보험", "대출", "신용"],
        "부동산": ["아파트", "분양", "청약", "전세", "월세", "부동산", "재건축", "임대"],
        "건강": ["다이어트", "운동", "영양", "건강", "병원", "치료", "의료", "약", "혈당", "면역"],
        "기술": ["AI", "챗GPT", "코딩", "스마트폰", "앱", "IT", "자동화", "소프트웨어", "유튜브", "블로그"],
        "여행": ["여행", "호텔", "항공", "캠핑", "해외", "국내여행", "맛집"],
        "교육": ["영어", "자격증", "취업", "공부", "학습", "시험", "재취업"],
        "쇼핑": ["할인", "세일", "쿠폰", "구매", "패션", "가전"],
        "법률": ["법률", "소송", "변호사", "계약", "이혼", "상속", "교통사고"],
    }
    def _cat_from_keyword(kw: str) -> str:
        kw_l = kw.lower()
        for c, words in _CAT_KW.items():
            if any(w in kw_l for w in words):
                return c
        return "일반"

    cat_count: dict[str, int] = {}
    type_count: dict[str, int] = {}
    risk_count: dict[str, int] = {}
    for p in all_posts:
        cat = p.get("adsenseCategory") or _cat_from_keyword(p.get("keyword", ""))
        cat_count[cat] = cat_count.get(cat, 0) + 1
        at = p.get("articleType") or "unknown"
        type_count[at] = type_count.get(at, 0) + 1
        rl = p.get("riskLevel") or "unknown"
        risk_count[rl] = risk_count.get(rl, 0) + 1

    cpc_map = {
        "법률": 3.2, "부동산": 2.8, "금융": 2.5, "건강": 1.8,
        "기술": 1.5, "교육": 1.3, "여행": 1.2, "쇼핑": 0.9,
    }
    top_cats = sorted(cat_count.items(), key=lambda x: cpc_map.get(x[0], 0.9) * x[1], reverse=True)

    return {
        "runs": len(week_runs),
        "posts_generated": total_posts,
        "posts_uploaded": total_uploaded,
        "pending_review": total_pending,
        "pending_rate_pct": round(total_pending / max(total_posts, 1) * 100, 1),
        "errors": total_errors,
        "error_rate_pct": round(total_errors / max(total_posts, 1) * 100, 1),
        "unique_keywords": list(set(all_keywords))[:30],
        "category_distribution": dict(cat_count),
        "article_type_distribution": dict(type_count),
        "risk_level_distribution": dict(risk_count),
        "top_categories_by_revenue": [c[0] for c in top_cats[:3]],
        "avg_word_count": round(sum(p.get("wordCount", 0) for p in all_posts) / max(len(all_posts), 1)),
        "avg_images": round(sum(p.get("imagesInserted", 0) for p in all_posts) / max(len(all_posts), 1), 1),
        "avg_faq": round(sum(p.get("faqCount", 0) for p in all_posts) / max(len(all_posts), 1), 1),
        "blog_ids": list({r.get("blogId", "default") for r in week_runs}),
        "blog_breakdown": _build_blog_breakdown(week_runs),
        "real_performance": _load_real_performance(),
    }


# ── Claude 분석 ───────────────────────────────────────────────────────────────
def _analyze_with_claude(summary: dict, api_key: str, prev_summary: dict | None = None) -> dict:
    """Claude Haiku 로 주간 데이터를 분석하고 JSON 인사이트를 반환합니다."""
    from anthropic import Anthropic

    client = Anthropic(api_key=api_key)

    real_perf = summary.get("real_performance")
    perf_block = (
        f"\n## 실제 성과 데이터 (Blogger/GSC, 정적 CPC 가정보다 우선 신뢰)\n"
        f"{json.dumps(real_perf, ensure_ascii=False, indent=2)}\n"
        if real_perf else
        "\n## 실제 성과 데이터: 아직 없음 (blog-analytics.yml 미실행) — 아래 CPC 가정으로만 판단\n"
    )
    trend_block = ""
    if prev_summary:
        trend_block = f"""
## 지난 주 대비 추세
- 지난 주 건강점수: {prev_summary.get('health_score', 'N/A')} (이번 주와 비교해 개선/악화 판단에 활용)
- 지난 주 오류율: {prev_summary.get('error_rate_pct', 'N/A')}% → 이번 주: {summary['error_rate_pct']}%
- 지난 주 검토대기율: {prev_summary.get('pending_rate_pct', 'N/A')}% → 이번 주: {summary['pending_rate_pct']}%
"""

    prompt = f"""당신은 블로그 자동화 시스템의 AI 분석가입니다. 아래 지난 7일 운영 데이터를 분석하고 개선 방안을 도출해주세요.

## 주간 운영 데이터 (블로그별 breakdown 포함)
{json.dumps(summary, ensure_ascii=False, indent=2)}
{perf_block}{trend_block}
## AdSense CPC 기준 카테고리 가치(참고용, real_performance 있으면 그쪽을 우선): 법률($3.2) > 부동산($2.8) > 금융($2.5) > 건강($1.8) > 기술($1.5) > 교육($1.3) > 여행($1.2) > 쇼핑($0.9)

## 분석 요청 (JSON 형식으로만 응답)
{{
  "health_score": 0-100 점수 (포스트 수·오류율·업로드율·검토대기율·실제 성과 종합),
  "performance_summary": "이번 주 성과 요약 (2문장 이내, 지난 주 대비 추세 언급)",
  "key_insights": ["핵심 인사이트 1", "인사이트 2", "인사이트 3"],
  "error_diagnosis": "오류율 {summary['error_rate_pct']}%의 주요 원인 및 해결책",
  "blog_specific_insights": {{"blog1": "blog1 관련 인사이트", "blog2": "...", "blog3": "..."}},
  "recommended_categories": ["다음 주 집중 카테고리 1", "카테고리 2"],
  "recommended_keywords": ["추천 키워드 1", "키워드 2", "키워드 3", "키워드 4", "키워드 5"],
  "keyword_reason": "위 키워드를 추천하는 이유 (real_performance가 있으면 실제 클릭/수익 근거로 설명)",
  "writing_guidelines": [
    "다음 주 글쓰기에 바로 반영할 지침 (성과가 좋았던 글의 실제 공통점 기반, 한 문장 명령형)",
    "지침 2 (예: '도입부 첫 문장에 구체적 수치를 넣을 것 — 클릭률 높은 글의 공통점')",
    "지침 3"
  ],
  "guidelines_reason": "위 글쓰기 지침을 도출한 근거 (어떤 글이 왜 잘됐는지)",
  "auto_apply": {{
    "posts_per_run_recommendation": 3,
    "focus_category": "가장 집중할 카테고리",
    "notes": "자동 적용 이유"
  }},
  "improvement_roadmap": [
    {{"week": 1, "action": "1주 내 실행 가능한 개선"}},
    {{"week": 2, "action": "2주 내 실행 가능한 개선"}},
    {{"week": 4, "action": "4주 내 실행 가능한 개선"}}
  ],
  "system_upgrade_suggestions": ["코드/설정 레벨 업그레이드 제안 1", "제안 2"]
}}"""

    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1800,
        messages=[{"role": "user", "content": prompt}],
    )

    text = claude_text(resp).strip()
    # JSON 블록 추출
    for marker in ("```json", "```"):
        if marker in text:
            text = text.split(marker, 1)[1].split("```", 1)[0].strip()
            break

    return json.loads(text)


# ── 자동 적용 ─────────────────────────────────────────────────────────────────
def _auto_apply(analysis: dict) -> list[str]:
    """분석 결과에서 즉시 적용 가능한 개선사항을 적용합니다."""
    applied = []

    # 1. 추천 키워드 → learned_keywords.json 에 저장 (주간 학습 키워드풀)
    rec_kws = analysis.get("recommended_keywords", [])
    if rec_kws:
        existing = _load(LEARNED_KW_FILE, default=[])
        if isinstance(existing, list):
            merged = list(dict.fromkeys(rec_kws + existing))[:60]
        else:
            merged = rec_kws
        _save(LEARNED_KW_FILE, merged)
        applied.append(f"추천 키워드 {len(rec_kws)}개 학습 저장: {', '.join(rec_kws[:3])}…")
        logger.info(f"  ✅ 학습 키워드 저장: {rec_kws}")

    # 1.5 글쓰기 지침 → learned_writing_tips.json (다음 주 글 생성 프롬프트에 자동 주입)
    guidelines = [
        str(g).strip() for g in (analysis.get("writing_guidelines") or [])
        if str(g).strip()
    ][:5]
    if guidelines:
        _save(WRITING_TIPS_FILE, {
            "generated_at": datetime.now().isoformat(),
            "guidelines": guidelines,
            "reason": str(analysis.get("guidelines_reason", "")).strip(),
        })
        applied.append(f"글쓰기 지침 {len(guidelines)}개 저장 → 다음 주 글부터 자동 반영")
        for g in guidelines:
            logger.info(f"  ✍️ 지침: {g}")

    # 2. 포스트 수 추천 → auto_apply 섹션에 저장 (실제 변경은 사람이 확인 후)
    aa = analysis.get("auto_apply", {})
    rec_count = aa.get("posts_per_run_recommendation")
    if rec_count and isinstance(rec_count, int) and 1 <= rec_count <= 10:
        note = aa.get("notes", "AI 추천")
        applied.append(f"권장 posts_per_run: {rec_count} ({note})")
        logger.info(f"  ℹ️  권장 포스트 수: {rec_count} ({note})")

    focus_cat = aa.get("focus_category", "")
    if focus_cat:
        applied.append(f"집중 카테고리: {focus_cat}")

    return applied


# ── 시스템 진단 ───────────────────────────────────────────────────────────────
def _diagnose_system(week_runs: list[dict], summary: dict) -> list[dict]:
    """시스템 상태를 진단하고 이슈 목록을 반환합니다."""
    issues = []

    if summary["error_rate_pct"] > 30:
        issues.append({
            "level": "error",
            "message": f"오류율 {summary['error_rate_pct']}% — 업로드 실패 다수 발생",
            "suggestion": "Google OAuth 토큰 만료 여부 및 API 할당량 확인 필요",
        })
    elif summary["error_rate_pct"] > 10:
        issues.append({
            "level": "warning",
            "message": f"오류율 {summary['error_rate_pct']}% — 간헐적 오류 발생",
            "suggestion": "최근 로그 파일에서 구체적인 오류 원인 확인",
        })

    if summary["runs"] == 0:
        issues.append({
            "level": "error",
            "message": "지난 7일간 실행 기록 없음",
            "suggestion": "GitHub Actions 스케줄 워크플로가 실행되고 있는지 확인",
        })
    elif summary["runs"] < 5:
        issues.append({
            "level": "warning",
            "message": f"지난 7일 실행 횟수: {summary['runs']}회 (기대: 14회)",
            "suggestion": "스케줄 워크플로 설정(KST 07:00/19:00) 확인",
        })

    if summary["avg_word_count"] < 800:
        issues.append({
            "level": "warning",
            "message": f"평균 포스트 길이 {summary['avg_word_count']}자 — SEO 최적 기준(1,500자) 미달",
            "suggestion": "content_generator.py 의 MIN_WORD_COUNT 설정 확인",
        })

    if summary.get("pending_rate_pct", 0) > 40:
        issues.append({
            "level": "warning",
            "message": f"검토 대기 전환율 {summary['pending_rate_pct']}% — 분량/AdSense 점수 미달 글이 다수",
            "suggestion": "프롬프트 분량 목표·AdSense 자동 수정 로직 점검 필요",
        })

    for bid, b in (summary.get("blog_breakdown") or {}).items():
        if b["runs"] > 0 and b["posts_uploaded"] == 0 and b["posts_generated"] > 0:
            issues.append({
                "level": "warning",
                "message": f"[{b['blog_name']}] 이번 주 생성 {b['posts_generated']}건 중 업로드 0건 "
                            f"(검토대기율 {b['pending_rate_pct']}%)",
                "suggestion": f"{bid} 전용 프롬프트/AdSense 기준 재검토",
            })

    return issues


def _diagnose_trend(summary: dict, prev_summary: dict | None) -> list[dict]:
    """직전 주 대비 추세 악화를 감지합니다 (연속 저하는 단발 이슈보다 늦게 발견되기 쉬움)."""
    issues = []
    if not prev_summary:
        return issues
    prev_err = prev_summary.get("error_rate_pct", 0)
    if summary["error_rate_pct"] > prev_err + 10:
        issues.append({
            "level": "warning",
            "message": f"오류율 상승 추세: {prev_err}% → {summary['error_rate_pct']}%",
            "suggestion": "최근 코드 변경·API 키 만료 여부 확인",
        })
    prev_pending = prev_summary.get("pending_rate_pct", 0)
    if summary.get("pending_rate_pct", 0) > prev_pending + 15:
        issues.append({
            "level": "warning",
            "message": f"검토 대기율 상승 추세: {prev_pending}% → {summary.get('pending_rate_pct', 0)}%",
            "suggestion": "콘텐츠 품질 게이트 기준 대비 생성 프롬프트 정합성 확인",
        })
    return issues


# ── 메인 엔트리 ───────────────────────────────────────────────────────────────
def run_weekly_check() -> dict:
    """주간 시스템 점검 및 학습 실행."""
    from config import claude_text, ANTHROPIC_API_KEY

    logger.info("=" * 60)
    logger.info("주간 시스템 점검 시작")
    logger.info("=" * 60)
    now = datetime.now()

    # 0. 지난 주 학습 이력 로드 (추세 비교용)
    learning_history = _load(LEARNING_FILE, default=[])
    prev_report = learning_history[0] if learning_history else None
    prev_summary = prev_report.get("stats") if prev_report else None
    if prev_summary:
        prev_summary = dict(prev_summary)
        prev_summary["health_score"] = (prev_report.get("analysis") or {}).get("health_score")

    # 1. 데이터 수집
    week_runs = _collect_week_data()
    logger.info(f"분석 대상: 지난 7일 {len(week_runs)}회 실행")

    summary = _build_summary(week_runs)
    logger.info(
        f"집계: 포스트 {summary['posts_generated']}개 생성 / "
        f"{summary['posts_uploaded']}개 게시 / 오류율 {summary['error_rate_pct']}% / "
        f"검토대기율 {summary['pending_rate_pct']}%"
    )

    # 2. 시스템 진단 (기본 + 추세)
    issues = _diagnose_system(week_runs, summary) + _diagnose_trend(summary, prev_summary)
    for issue in issues:
        level = issue["level"]
        if level == "error":
            logger.error(f"  ❌ {issue['message']}")
        else:
            logger.warning(f"  ⚠️  {issue['message']}")

    # 3. Claude AI 분석
    analysis: dict = {}
    ai_ok = False
    if ANTHROPIC_API_KEY and not ANTHROPIC_API_KEY.startswith("sk-ant-xxx"):
        try:
            logger.info("Claude AI 분석 중…")
            analysis = _analyze_with_claude(summary, ANTHROPIC_API_KEY, prev_summary)
            ai_ok = True
            logger.info(
                f"AI 분석 완료 — 건강점수: {analysis.get('health_score', 'N/A')} / "
                f"추천 키워드: {analysis.get('recommended_keywords', [])[:3]}"
            )
        except Exception as e:
            logger.error(f"AI 분석 실패: {e}")
            analysis = {"error": str(e), "health_score": None}
    else:
        logger.warning("ANTHROPIC_API_KEY 미설정 — AI 분석 생략")
        analysis = {"health_score": None, "error": "API 키 없음"}

    # 4. 자동 적용
    auto_applied: list[str] = []
    if ai_ok:
        try:
            auto_applied = _auto_apply(analysis)
            logger.info(f"자동 적용 완료: {len(auto_applied)}건")
        except Exception as e:
            logger.error(f"자동 적용 실패: {e}")

    # 5. 보고서 구성
    report = {
        "checked_at": now.isoformat(),
        "week_start": (now - timedelta(days=7)).strftime("%Y-%m-%d"),
        "week_end": now.strftime("%Y-%m-%d"),
        "stats": summary,
        "issues": issues,
        "analysis": analysis,
        "auto_applied": auto_applied,
        "ai_analyzed": ai_ok,
    }

    # 6. 이력 저장
    history = learning_history
    history.insert(0, report)
    history = history[:52]  # 최대 1년치(52주)
    _save(LEARNING_FILE, history)
    logger.info(f"학습 이력 저장 완료 (총 {len(history)}주)")

    # 7. docs/data/ 내보내기
    docs_path = os.path.join(DOCS_DATA_DIR, "learning.json")
    os.makedirs(DOCS_DATA_DIR, exist_ok=True)
    _save(docs_path, history)
    logger.info(f"대시보드 내보내기 완료 → {docs_path}")

    health = analysis.get("health_score")
    logger.info("=" * 60)
    logger.info(
        f"주간 점검 완료 | 건강점수: {health if health is not None else 'N/A'} | "
        f"이슈: {len(issues)}건 | 자동적용: {len(auto_applied)}건"
    )
    logger.info("=" * 60)
    return report


if __name__ == "__main__":
    report = run_weekly_check()
    health = report["analysis"].get("health_score")
    issues = report.get("issues", [])
    print(f"\n✅ 완료 | 건강점수: {health} | 이슈: {len(issues)}건")
    for issue in issues:
        icon = "❌" if issue["level"] == "error" else "⚠️"
        print(f"  {icon} {issue['message']}")
    for applied in report.get("auto_applied", []):
        print(f"  ✨ 자동적용: {applied}")
