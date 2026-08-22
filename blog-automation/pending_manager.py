"""검토 대기 글 정리·재검증 — "글 무덤"이 된 pending 큐를 비웁니다.

품질 게이트(분량·AdSense 점수)에 걸린 글은 pending_posts.json으로 가는데,
거기서 나오는 경로가 사실상 없어 계속 쌓이기만 했습니다.
2026-08-10 기준 152건 / 2.2MB — 대시보드가 매번 이 파일을 통째로 받습니다.

세 가지 일을 합니다:
  1) prune     — 이미 끝난 건(published/expired)의 본문을 제거해 파일을 줄임
                 (기록은 남기되 2.2MB를 차지하는 content만 덜어냄)
  2) revalidate— 대기 중인 글을 AdSense 기준으로 다시 검증. 기준이 바뀌었거나
                 그 사이 보완된 글이 통과하면 발행 대상으로 표시
  3) expire    — 오래 방치된 글을 만료 처리 (auto_repair와 같은 기준)

기본은 리포트만 만들고 파일을 바꾸지 않습니다(--apply 필요).
발행은 이 모듈이 직접 하지 않고, 통과한 글을 표시만 해서 기존
publish_pending.py 흐름을 그대로 태웁니다 — 발행 경로를 둘로 나누지 않기 위함.

Usage:
  python pending_manager.py                      # 현황 리포트만
  python pending_manager.py --apply              # 정리·재검증 실제 반영
  python pending_manager.py --apply --expire-days 45
"""

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_BASE_DIR = os.path.dirname(__file__)
PENDING_FILE = os.path.join(_BASE_DIR, "..", "docs", "data", "pending_posts.json")
REPORT_PATH = os.path.join(_BASE_DIR, "..", "docs", "data", "pending_report.json")

TERMINAL_STATUSES = ("published", "expired", "skipped")
DEFAULT_EXPIRE_DAYS = 30
# 끝난 건은 이 기간이 지나면 본문을 버림 (되돌릴 일이 사실상 없는 시점)
CONTENT_KEEP_DAYS = 3


def _load(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _entry_date(entry: dict) -> datetime | None:
    """savedAt 우선, 없으면 date. 파싱 불가면 None."""
    for key in ("savedAt", "publishedAt", "expired_at", "date"):
        raw = str(entry.get(key) or "").strip()
        if not raw:
            continue
        try:
            return datetime.fromisoformat(raw.replace("Z", "").split("+")[0])
        except ValueError:
            try:
                return datetime.strptime(raw[:10], "%Y-%m-%d")
            except ValueError:
                continue
    return None


def _age_days(entry: dict) -> int | None:
    dt = _entry_date(entry)
    return (datetime.now() - dt).days if dt else None


# ──────────────────────────────────────────────────────────────────────────────
# 1) 끝난 건 본문 제거
# ──────────────────────────────────────────────────────────────────────────────

def prune_terminal(pending: list[dict], keep_days: int = CONTENT_KEEP_DAYS) -> int:
    """종료 상태 글의 본문을 제거합니다. 제거한 건수를 반환.

    엔트리 자체는 지우지 않습니다 — 무엇이 언제 어떻게 처리됐는지는 남기고,
    파일 용량의 대부분을 차지하는 content만 덜어냅니다.
    """
    pruned = 0
    for e in pending:
        if e.get("status") not in TERMINAL_STATUSES:
            continue
        if not e.get("content"):
            continue
        age = _age_days(e)
        if age is not None and age < keep_days:
            continue
        e["contentBytes"] = len(e.get("content") or "")
        e["content"] = ""
        e["contentPrunedAt"] = datetime.now().isoformat()
        pruned += 1
    return pruned


# ──────────────────────────────────────────────────────────────────────────────
# 2) 대기 글 재검증
# ──────────────────────────────────────────────────────────────────────────────

def _word_count(entry: dict) -> int:
    """엔트리의 글자 수. 저장된 값이 없으면 본문에서 태그를 걷어내고 셉니다."""
    saved = entry.get("wordCount") or entry.get("word_count")
    if isinstance(saved, (int, float)) and saved > 0:
        return int(saved)
    text = re.sub(r"<[^>]+>", "", entry.get("content") or "")
    return len(text.strip())


def _is_unvalidated(result: dict) -> bool:
    """검증기가 실제로 평가하지 못한 결과인지 판별합니다.

    adsense_validator는 API 오류 시 _default_pass()로 score=65 / recommendation=review를
    돌려주며 모든 항목 note에 "검증 생략"을 남깁니다. 이걸 미달과 구분하지 않으면
    리포트가 "콘텐츠 미달"이라고 거짓말을 하게 됩니다.
    """
    checks = result.get("checks") or {}
    if checks and all("검증 생략" in str(c.get("note", "")) for c in checks.values()):
        return True
    return any("검증이 API 오류" in str(w) for w in (result.get("warnings") or []))


def revalidate_pending(pending: list[dict], limit: int = 0) -> dict:
    """대기 글을 AdSense 기준으로 다시 검증하고 결과를 엔트리에 기록합니다.

    통과한 글은 revalidated=True로 표시만 하고 발행은 하지 않습니다 —
    실제 게시는 기존 publish_pending.py가 담당합니다.
    """
    from adsense_validator import validate_adsense
    from config import ADSENSE_MIN_SCORE

    passed = failed = checked = unvalidated = 0
    for e in pending:
        if e.get("status") != "pending":
            continue
        if not e.get("content"):
            continue
        if limit and checked >= limit:
            break
        checked += 1
        try:
            result = validate_adsense({
                "title": e.get("title", ""),
                "content": e.get("content", ""),
                "keyword": e.get("keyword", ""),
                "faq": e.get("faq", []),
                "meta_description": e.get("metaDescription", ""),
                "sources": e.get("sources", []),
                # 검증기는 분량을 word_count 키로 읽습니다. 이걸 빼먹으면 0자로
                # 판정돼 모든 글이 "글자 수 0자 — 분량 미달"로 떨어집니다
                # (2026-08-20 확인: 재검증 30건 전부 이 이유로 미달 처리됨).
                # 엔트리에 값이 없으면 본문 태그를 걷어내고 직접 셉니다.
                "word_count": _word_count(e),
            })
        except Exception as exc:
            logger.warning(f"재검증 실패 '{e.get('title','')[:40]}': {exc}")
            continue

        score = result.get("score", 0)
        e["revalidatedAt"] = datetime.now().isoformat()
        e["revalidatedScore"] = score

        # 검증기는 API 오류 시 "검증 생략" 기본값(score 65)을 돌려줌 —
        # 이걸 '미달'로 집계하면 평가조차 안 된 글을 콘텐츠 문제로 오해하게 됨
        if _is_unvalidated(result):
            e["revalidated"] = False
            e["revalidateReason"] = "검증 불가 (AdSense 검증 API 오류) — 콘텐츠 문제 아님"
            unvalidated += 1
        elif result.get("recommendation") == "upload" and score >= ADSENSE_MIN_SCORE:
            e["revalidated"] = True
            passed += 1
        else:
            e["revalidated"] = False
            e["revalidateReason"] = (result.get("issues") or [f"점수 {score} < 기준 {ADSENSE_MIN_SCORE}"])[0][:120]
            failed += 1

    return {"checked": checked, "passed": passed, "failed": failed,
            "unvalidated": unvalidated}


# ──────────────────────────────────────────────────────────────────────────────
# 3) 만료 처리
# ──────────────────────────────────────────────────────────────────────────────

def expire_old(pending: list[dict], days: int = DEFAULT_EXPIRE_DAYS) -> int:
    """오래 방치된 대기 글을 만료 처리합니다 (재검증 통과분은 제외)."""
    expired = 0
    for e in pending:
        if e.get("status") != "pending" or e.get("revalidated"):
            continue
        age = _age_days(e)
        if age is not None and age >= days:
            e["status"] = "expired"
            e["expired_at"] = datetime.now().isoformat()
            expired += 1
    return expired


# ──────────────────────────────────────────────────────────────────────────────
# 실행
# ──────────────────────────────────────────────────────────────────────────────

def _summarize(pending: list[dict]) -> dict:
    from collections import Counter
    status = Counter(e.get("status", "unknown") for e in pending)
    with_content = sum(1 for e in pending if e.get("content"))
    return {
        "total": len(pending),
        "byStatus": dict(status),
        "withContent": with_content,
    }


def run(apply_changes: bool, expire_days: int, revalidate_limit: int) -> dict:
    # 목록·본문·보관이 나뉘어 있으므로 저장소를 거쳐 읽습니다 (본문이 합쳐져 옴).
    # 끝난 기록의 본문 정리도 이 모듈 담당이라 보관본까지 함께 받습니다.
    import pending_store
    pending = pending_store.load()
    if not isinstance(pending, list):
        logger.error("pending_posts.json 형식 오류")
        return {"error": "형식 오류"}

    before = _summarize(pending)
    logger.info(f"현황: 총 {before['total']}건 / 상태 {before['byStatus']} / 본문 보유 {before['withContent']}건")

    reval = revalidate_pending(pending, limit=revalidate_limit)
    logger.info(
        f"재검증: {reval['checked']}건 검사 → 통과 {reval['passed']} / "
        f"미달 {reval['failed']} / 검증불가 {reval['unvalidated']}"
    )
    if reval["unvalidated"]:
        logger.warning(
            f"⚠️ {reval['unvalidated']}건은 AdSense 검증 API 오류로 평가하지 못했습니다 "
            f"— 콘텐츠 문제가 아니며, ANTHROPIC_API_KEY 확인 후 재실행하세요"
        )

    expired = expire_old(pending, days=expire_days)
    logger.info(f"만료 처리: {expired}건 ({expire_days}일 이상 방치)")

    pruned = prune_terminal(pending)
    logger.info(f"본문 정리: {pruned}건 (종료 상태 글의 본문 제거)")

    after = _summarize(pending)
    report = {
        "ranAt": datetime.now().isoformat(),
        "applied": apply_changes,
        "before": before,
        "after": after,
        "revalidate": reval,
        "expired": expired,
        "pruned": pruned,
        "readyToPublish": [
            {"id": e.get("id"), "title": e.get("title", "")[:80],
             "score": e.get("revalidatedScore"), "blogId": e.get("blogId")}
            for e in pending if e.get("revalidated")
        ],
    }

    if apply_changes:
        pending_store.save(pending)
        logger.info(f"✅ pending_posts.json 반영 완료 (본문 보유 {before['withContent']} → {after['withContent']}건)")
    else:
        logger.info("🔍 리포트 전용 모드 — 파일 변경 없음 (--apply 로 반영)")

    try:
        _save(REPORT_PATH, report)
        logger.info(f"리포트 저장: {REPORT_PATH}")
    except Exception as exc:
        logger.warning(f"리포트 저장 실패 (무시): {exc}")

    if report["readyToPublish"]:
        logger.info(f"📤 재검증 통과 {len(report['readyToPublish'])}건 — "
                    f"manual-publish 워크플로로 게시할 수 있습니다")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="검토 대기 글 정리·재검증")
    parser.add_argument("--apply", action="store_true", help="실제로 파일에 반영 (기본: 리포트만)")
    parser.add_argument("--expire-days", type=int, default=DEFAULT_EXPIRE_DAYS,
                        help=f"이 일수 이상 방치된 대기 글을 만료 처리 (기본 {DEFAULT_EXPIRE_DAYS})")
    parser.add_argument("--revalidate-limit", type=int, default=0,
                        help="재검증할 최대 건수 (0=전체)")
    args = parser.parse_args()

    report = run(args.apply, args.expire_days, args.revalidate_limit)
    return 1 if report.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
