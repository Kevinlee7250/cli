"""글 템플릿 추천 — 수동 발행 시 어떤 구조로 쓸지 고르게 돕습니다.

왜 필요한가
──────────
_detect_article_type이 키워드로 유형을 자동 결정하고, 그 유형의 구조 가이드가
프롬프트에 들어갑니다. 자동 판정은 대개 맞지만 두 가지 문제가 있습니다.

1. 같은 키워드 성격이 이어지면 같은 템플릿만 반복됩니다. AdSense 검증기가
   "정형화된 AI 템플릿 패턴이 반복됨"으로 감점하는 이유 중 하나입니다.
2. 사람이 보기엔 다른 구조가 나은 경우에도 개입할 방법이 없었습니다.

그래서 추천은 하되 결정은 사람이 하도록, 후보와 근거를 함께 제시합니다.

판정 규칙은 content_generator.TYPE_SIGNALS 하나만 씁니다. 대시보드도 이
모듈이 내보낸 templates.json을 받아 쓰므로 규칙이 두 곳에 살지 않습니다.
"""

import json
import logging
import os
from collections import Counter

logger = logging.getLogger(__name__)

_BASE_DIR = os.path.dirname(__file__)
REGISTRY_PATH = os.path.join(_BASE_DIR, "logs", "post_registry.json")
EXPORT_PATH = os.path.join(_BASE_DIR, "..", "docs", "data", "templates.json")

#: 최근 몇 편을 보고 "많이 쓴 템플릿"을 판단할지
RECENT_WINDOW = 12
#: 최근 사용 비중이 이보다 높으면 다양화를 위해 순위를 낮춥니다
OVERUSE_RATIO = 0.4


#: 사람이 고를 때 필요한 설명. 구조 본문은 content_generator._STRUCTURE_GUIDE에
#: 있고, 여기에는 "언제 고르면 좋은가"만 둡니다.
TEMPLATE_META: dict[str, dict] = {
    "how_to":        {"name": "사용법·절차형",
                      "summary": "준비 → 단계 → 오류 해결 → 체크리스트",
                      "best_for": "따라 하면 끝나는 일. 신청·설치·가입처럼 순서가 분명한 주제",
                      "avoid_when": "순서가 없는 개념 설명"},
    "comparison":    {"name": "비교·선택형",
                      "summary": "비교 기준 → 항목별 분석(표) → 상황별 추천",
                      "best_for": "선택지가 2개 이상이고 독자가 고민 중일 때",
                      "avoid_when": "대상이 하나뿐일 때"},
    "explainer":     {"name": "개념 설명형",
                      "summary": "문제 → 핵심 정보 → 사례 → 주의사항",
                      "best_for": "용어·제도가 헷갈려 검색한 독자",
                      "avoid_when": "이미 아는 것을 실행하려는 독자"},
    "review":        {"name": "후기 종합형",
                      "summary": "관심 배경 → 공식 스펙 vs 실사용 반응 → 공통 불만 → 추천 기준",
                      "best_for": "쓸까 말까 망설이는 독자. 실사용 반응이 많은 주제",
                      "avoid_when": "후기 자료가 거의 없는 신상품"},
    "analysis":      {"name": "분석·정리형",
                      "summary": "현황 → 원인 → 영향 → 대응",
                      "best_for": "다른 유형에 딱 맞지 않는 주제의 기본값",
                      "avoid_when": "절차나 비교가 핵심인 주제"},
    "investment":    {"name": "투자 분석형",
                      "summary": "시장 상황 → 지표 → 시나리오 → 유의사항",
                      "best_for": "종목·상품 전망. 반드시 투자 판단 책임 고지 포함",
                      "avoid_when": "단정적 수익 예측이 필요한 자리 (정책 위반)"},
    "news_analysis": {"name": "뉴스 해설형",
                      "summary": "무슨 일 → 배경 → 나에게 미치는 영향 → 앞으로",
                      "best_for": "발표·개정처럼 시점이 분명한 사건",
                      "avoid_when": "시의성 없는 상시 정보"},
    "drama_review":  {"name": "드라마·영화형",
                      "summary": "관전 포인트 → 인물·전개 → 반응 → 볼만한지",
                      "best_for": "작품 단위 콘텐츠. 스포일러 경계 필요",
                      "avoid_when": "작품 외 산업 이슈"},
    "kpop_review":   {"name": "K-POP·연예형",
                      "summary": "일정·정보 → 확인 방법 → 팬 반응 → 정리",
                      "best_for": "컴백·시상식처럼 일정과 사실 확인이 핵심",
                      "avoid_when": "인물에 대한 추측성 서술"},
    "travel_guide":  {"name": "여행 가이드형",
                      "summary": "언제 가면 좋은지 → 동선 → 비용 → 놓치기 쉬운 것",
                      "best_for": "지역·코스·숙소처럼 계획을 돕는 주제",
                      "avoid_when": "가보지 않은 곳의 체험담 서술"},
    "sports_review": {"name": "스포츠 분석형",
                      "summary": "경기·시즌 상황 → 기록 → 관전 포인트 → 전망",
                      "best_for": "경기·선수·순위처럼 기록이 근거가 되는 주제",
                      "avoid_when": "결과 예측을 단정하는 서술"},
}


def _recent_type_counts(registry_path: str = REGISTRY_PATH,
                        blog_id: str = "") -> Counter:
    """최근 발행 글의 유형 분포. 파일이 없으면 빈 Counter."""
    try:
        with open(registry_path, encoding="utf-8") as f:
            rows = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return Counter()
    if not isinstance(rows, list):
        return Counter()
    picked = [r for r in rows
              if isinstance(r, dict)
              and r.get("status") == "published"
              and (not blog_id or r.get("blogId") == blog_id)]
    return Counter(r.get("articleType") for r in picked[-RECENT_WINDOW:]
                   if r.get("articleType"))


def recommend(keyword: str, blog_id: str = "",
              registry_path: str = REGISTRY_PATH) -> dict:
    """키워드에 맞는 템플릿을 추천합니다.

    Returns:
        {"keyword", "recommended", "why", "candidates": [{id, name, score, why}],
         "recentUsage": {type: count}}

    자동 판정을 1순위로 두되, 최근에 과하게 쓴 템플릿이면 그 사실을 근거에
    적어 사람이 다른 선택을 고려하게 합니다. 자동으로 바꿔치기하지는
    않습니다 — 키워드에 맞는 구조가 우선이고, 다양화는 그다음입니다.
    """
    from content_generator import DEFAULT_ARTICLE_TYPE, TYPE_SIGNALS, _detect_article_type

    kw = (keyword or "").lower()
    auto = _detect_article_type(keyword or "")
    recent = _recent_type_counts(registry_path, blog_id)
    total_recent = sum(recent.values())

    # 키워드 신호가 몇 개나 걸리는지로 적합도를 매깁니다
    hits: dict[str, int] = {}
    for article_type, words in TYPE_SIGNALS:
        n = sum(1 for w in words if w in kw)
        if n:
            hits[article_type] = n

    candidates = []
    for tid, meta in TEMPLATE_META.items():
        score = hits.get(tid, 0) * 10
        if tid == auto:
            score += 50                      # 자동 판정이 1순위
        elif tid == DEFAULT_ARTICLE_TYPE:
            score += 5                       # 기본값은 항상 후보로 남김
        why = []
        if tid == auto:
            why.append("키워드 신호와 가장 잘 맞음")
        elif hits.get(tid):
            why.append(f"키워드에 관련 표현 {hits[tid]}개")
        if total_recent:
            ratio = recent.get(tid, 0) / total_recent
            if ratio >= OVERUSE_RATIO:
                score -= 20
                why.append(f"최근 {RECENT_WINDOW}편 중 {recent[tid]}편이 이 구조 — 반복 주의")
            elif recent.get(tid, 0) == 0:
                score += 8
                why.append("최근에 쓰지 않은 구조")
        if score <= 0:
            continue
        candidates.append({"id": tid, "name": meta["name"], "score": score,
                           "summary": meta["summary"], "bestFor": meta["best_for"],
                           "why": " · ".join(why) or meta["best_for"]})

    candidates.sort(key=lambda c: (-c["score"], c["id"]))
    top = candidates[0]["id"] if candidates else auto
    why = candidates[0]["why"] if candidates else "기본 구조"
    return {"keyword": keyword, "recommended": top, "why": why,
            "autoDetected": auto, "candidates": candidates[:5],
            "recentUsage": dict(recent)}


def export_templates(path: str = EXPORT_PATH) -> str:
    """대시보드가 쓸 템플릿 목록·판정 규칙을 내보냅니다.

    규칙을 JS에 다시 적지 않기 위해서입니다. 대시보드는 이 파일의
    signals로 단순 문자열 포함 검사만 합니다.
    """
    from content_generator import DEFAULT_ARTICLE_TYPE, TYPE_SIGNALS

    signals = {t: words for t, words in TYPE_SIGNALS}
    data = {
        "defaultType": DEFAULT_ARTICLE_TYPE,
        "order": [t for t, _ in TYPE_SIGNALS] + [DEFAULT_ARTICLE_TYPE],
        "templates": {
            tid: {**meta, "signals": signals.get(tid, [])}
            for tid, meta in TEMPLATE_META.items()
        },
    }
    path = os.path.normpath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"템플릿 목록 저장: {path} ({len(TEMPLATE_META)}종)")
    return path


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="글 템플릿 추천")
    parser.add_argument("keyword", nargs="?", default="", help="추천받을 키워드")
    parser.add_argument("--blog", default="", help="블로그 ID (최근 사용 이력 반영)")
    parser.add_argument("--export", action="store_true", help="templates.json 내보내기")
    args = parser.parse_args()

    if args.export:
        export_templates()
    if not args.keyword:
        return 0

    r = recommend(args.keyword, args.blog)
    print(f"\n키워드: {r['keyword']}")
    print(f"추천: {TEMPLATE_META[r['recommended']]['name']} ({r['recommended']})")
    print(f"근거: {r['why']}\n")
    print("후보:")
    for c in r["candidates"]:
        mark = "★" if c["id"] == r["recommended"] else " "
        print(f"  {mark} {c['name']:14} {c['summary']}")
        print(f"      {c['why']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
