"""색인 요청 우선순위 큐 — 하루 10건을 무엇에 쓸지 정합니다.

색인을 자동으로 요청하는 방법은 없습니다. Google Indexing API는 문서상
채용공고(JobPosting)·방송이벤트(BroadcastEvent) 전용이고, Search Console API에는
색인 요청 엔드포인트가 없습니다 — 웹 UI의 "색인 생성 요청" 버튼뿐입니다.
그 버튼은 속성당 하루 10건 안팎으로 제한됩니다.

그래서 자동화 대신 "무엇을 먼저 넣을지"를 정합니다. 아무 글이나 넣으면
할당량만 태우고 끝나기 때문입니다.

우선순위 기준 (높을수록 먼저):
  · 사이트맵에 있는데도 "URL is unknown to Google" — 발견 자체가 안 된 심각한 상태
  · 검색 수요가 있는 키워드 (GSC 노출이 잡힌 글)
  · 분량·FAQ를 갖춰 심사에서 가치 있는 콘텐츠로 보일 글
  · 최근 글보다 어느 정도 시간이 지난 글 (갓 발행한 글은 원래 시간이 걸림)
이미 색인된 글은 제외합니다.

Usage:
  python index_priority.py            # 상위 10건 (하루 할당량)
  python index_priority.py --limit 30
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_BASE = os.path.dirname(__file__)
_DOCS_DATA = os.path.join(_BASE, "..", "docs", "data")
REPORT_PATH = os.path.join(_DOCS_DATA, "index_priority.json")

# GSC UI의 "색인 생성 요청"은 속성당 하루 10건 안팎입니다
DAILY_QUOTA = 10
# 발행 직후에는 원래 시간이 걸리므로, 이 기간이 지나야 요청 대상으로 봅니다
MIN_AGE_DAYS = 3


def _load(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _age_days(raw: str) -> int | None:
    raw = str(raw or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw.replace("Z", "").split("+")[0][:19 if "T" in raw else 10], fmt)
            return (datetime.now() - dt).days
        except ValueError:
            continue
    return None


def score_candidate(item: dict, post: dict) -> tuple[int, list[str]]:
    """(점수, 이유) — 왜 이 글을 먼저 넣는지 사람이 읽을 수 있게 남깁니다."""
    score = 0
    reasons: list[str] = []

    coverage = str(item.get("coverage", ""))
    if "unknown to Google" in coverage:
        score += 50
        reasons.append("구글이 URL 존재 자체를 모름")
    elif "Discovered" in coverage:
        score += 30
        reasons.append("발견됐지만 색인 보류 중")
    elif "Crawled" in coverage:
        score += 20
        reasons.append("크롤은 됐지만 색인 안 됨")

    impressions = int(post.get("gscImpressions30d", 0) or 0)
    if impressions > 0:
        score += 25
        reasons.append(f"검색 노출 {impressions}회 — 수요 있음")

    words = int(post.get("wordCount", 0) or 0)
    if words >= 3000:
        score += 15
        reasons.append(f"분량 {words:,}자")
    elif words and words < 2000:
        score -= 15
        reasons.append(f"분량 부족 {words:,}자 — 보강 먼저 권장")

    if int(post.get("faqCount", 0) or 0) > 0:
        score += 10
        reasons.append("FAQ 있음")
    else:
        score -= 5
        reasons.append("FAQ 없음")

    age = _age_days(post.get("date") or item.get("published_at"))
    if age is not None and age >= 14:
        score += 10
        reasons.append(f"발행 {age}일 경과 — 자연 색인 기대 어려움")

    return score, reasons


def build_queue(limit: int = DAILY_QUOTA) -> dict:
    status = _load(os.path.join(_DOCS_DATA, "index_status.json"), {})
    posts = _load(os.path.join(_DOCS_DATA, "posts.json"), [])
    by_url = {p.get("blogUrl", ""): p for p in posts if p.get("blogUrl")}

    items = status.get("items") or []
    if not items:
        logger.warning("색인 리포트가 없습니다 — 먼저 gsc_indexing.py --inspect 를 실행하세요")
        return {"generatedAt": datetime.now(timezone.utc).isoformat(),
                "queue": [], "skipped": 0, "note": "색인 리포트 없음"}

    candidates = []
    skipped_indexed = skipped_fresh = 0
    for it in items:
        if it.get("verdict") == "indexed":
            skipped_indexed += 1
            continue
        post = by_url.get(it.get("url", ""), {})
        age = _age_days(post.get("date") or it.get("published_at"))
        if age is not None and age < MIN_AGE_DAYS:
            # 갓 발행한 글은 원래 시간이 걸림 — 할당량을 여기 쓰면 낭비
            skipped_fresh += 1
            continue
        score, reasons = score_candidate(it, post)
        # 대시보드 색인 패널이 어느 Search Console 속성을 열지 판단할 때 씁니다.
        # gsc_indexing이 실제로 200을 받은 속성(URL-프리픽스 또는 sc-domain)이
        # 유일하게 확실한 값이고, 없으면 사이트 URL로 대체합니다.
        site = it.get("site", "")
        candidates.append({
            "url": it.get("url", ""),
            "title": (post.get("title") or it.get("title") or "")[:80],
            "blog": it.get("blog", ""),
            "coverage": it.get("coverage", ""),
            "site": site,
            "gscProperty": it.get("gsc_property") or site,
            "score": score,
            "reasons": reasons,
        })

    candidates.sort(key=lambda c: -c["score"])
    report = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "checkedAt": status.get("checked_at", ""),
        "dailyQuota": DAILY_QUOTA,
        "totalNotIndexed": len(candidates) + skipped_fresh,
        "skippedIndexed": skipped_indexed,
        "skippedTooFresh": skipped_fresh,
        "queue": candidates[:limit],
        "backlog": max(0, len(candidates) - limit),
    }

    logger.info(f"미색인 {len(candidates)}건 중 상위 {len(report['queue'])}건 선정 "
                f"(이미 색인 {skipped_indexed} / 발행 직후 제외 {skipped_fresh})")
    for i, c in enumerate(report["queue"], 1):
        logger.info(f"  {i:2}. [{c['score']:3}점] {c['title'][:44]}")
        logger.info(f"      {c['url']}")
        logger.info(f"      사유: {' · '.join(c['reasons'][:3])}")
    if report["backlog"]:
        logger.info(f"  … 대기 {report['backlog']}건 (내일 이후 순차 처리)")

    return report


def run(limit: int = DAILY_QUOTA) -> dict:
    report = build_queue(limit)
    try:
        os.makedirs(_DOCS_DATA, exist_ok=True)
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info(f"리포트 저장: {REPORT_PATH}")
    except OSError as e:
        logger.warning(f"리포트 저장 실패 (무시): {e}")

    if report.get("queue"):
        logger.info("\n👉 Search Console → URL 검사에 위 주소를 하나씩 넣고 "
                    "'색인 생성 요청'을 누르세요 (속성당 하루 10건 내외)")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="색인 요청 우선순위 큐")
    parser.add_argument("--limit", type=int, default=DAILY_QUOTA,
                        help=f"뽑을 건수 (기본 {DAILY_QUOTA} = 하루 할당량)")
    args = parser.parse_args()
    run(args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
