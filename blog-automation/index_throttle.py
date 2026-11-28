"""색인율 연동 발행량 조절 — 구글이 글을 거의 색인하지 않을 때 발행 간격을 늘립니다.

기능 스위치 ``index_rate_throttle`` (기본 꺼짐). 켜기 전에는 아무 영향이 없습니다.

왜
──
2026-11-28 기준 색인 점검 45건 중 색인 0건입니다(docs/data/index_status.json).
색인이 붙지 않는 상태에서 매일 새 글을 더하면 '크롤 예산'이 새 글로 흩어지고,
이미 쓴 글이 색인될 기회가 줄어든다는 판단으로, 색인율이 낮은 블로그는 하루
걸러 발행하도록 합니다(결재 사무실 기능 12 · 2026-11-29 오너 지시 "전체를
순차적으로 만들어"). 효과는 검증되지 않았습니다 — 그래서 기본값을 끔으로 두고,
켤지는 오너가 정합니다.

규칙
────
  · 이 블로그의 색인 점검 표본이 MIN_SAMPLE(기본 10) 미만이면 조절하지 않습니다.
  · 색인율 < LOW_RATE(기본 10%)면, 이 블로그의 마지막 발행일(KST 날짜)로부터
    GAP_DAYS(기본 2)일이 지나지 않은 회차를 건너뜁니다. 매일 실행이면 하루 걸러
    발행이 됩니다.
  · 색인 자료가 없거나 STALE_HOURS(기본 72시간)보다 오래됐으면 조절하지 않습니다.
    자료가 없다는 이유로 발행을 막지 않습니다(막는 쪽으로 실패하지 않기).
  · 수동 키워드 실행·미리보기·검토 모드는 조절하지 않습니다(호출부에서 거릅니다).

건너뛴 회차는 run_once 집계에서 '시도 0건'(idle)이 되어 실패로 세지 않습니다.

환경변수로 덮어쓰기: INDEX_THROTTLE_LOW_RATE · INDEX_THROTTLE_MIN_SAMPLE ·
INDEX_THROTTLE_GAP_DAYS · INDEX_THROTTLE_STALE_HOURS
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

HERE = os.path.dirname(os.path.abspath(__file__))
STATUS_PATH = os.path.normpath(os.path.join(HERE, "..", "docs", "data", "index_status.json"))
REGISTRY_PATH = os.path.join(HERE, "logs", "post_registry.json")
KST = timezone(timedelta(hours=9))


def _env_num(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def _ts(s: str) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _host(u: str) -> str:
    h = urlparse(u or "").netloc.lower()
    return h[4:] if h.startswith("www.") else h


def _blog_items(status: dict, cfg: dict) -> list[dict]:
    """이 블로그의 색인 점검 항목. gsc 사이트 주소 또는 블로그 이름으로 맞춥니다."""
    site = _host(cfg.get("gsc_site_url", ""))
    name = cfg.get("name", "")
    out = []
    for it in status.get("items", []) or []:
        if (site and _host(it.get("site", "") or it.get("url", "")) == site) or (name and it.get("blog") == name):
            out.append(it)
    return out


def _last_published_kst_date(blog_id: str, registry_path: str = REGISTRY_PATH):
    try:
        with open(registry_path, encoding="utf-8") as f:
            reg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    best = None
    for p in reg if isinstance(reg, list) else []:
        if p.get("status") != "published" or p.get("blogId") != blog_id:
            continue
        t = _ts(p.get("publishedAt", ""))
        if t and (best is None or t > best):
            best = t
    return best.astimezone(KST).date() if best else None


def decide(cfg: dict, now: datetime | None = None, status_path: str = STATUS_PATH,
           registry_path: str = REGISTRY_PATH) -> dict:
    """{"skip", "reason", "rate", "sample"} — skip=True면 이번 회차 발행을 건너뜁니다."""
    now = now or datetime.now(timezone.utc)
    low = _env_num("INDEX_THROTTLE_LOW_RATE", 0.10)
    min_sample = int(_env_num("INDEX_THROTTLE_MIN_SAMPLE", 10))
    gap = int(_env_num("INDEX_THROTTLE_GAP_DAYS", 2))
    stale_h = _env_num("INDEX_THROTTLE_STALE_HOURS", 72)
    keep = {"skip": False, "rate": None, "sample": 0}

    try:
        with open(status_path, encoding="utf-8") as f:
            status = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {**keep, "reason": "색인 자료 없음 — 조절하지 않음"}
    checked = _ts(status.get("checked_at", ""))
    if not checked or now - checked > timedelta(hours=stale_h):
        return {**keep, "reason": f"색인 자료가 {int(stale_h)}시간보다 오래됨 — 조절하지 않음"}

    items = _blog_items(status, cfg)
    n = len(items)
    if n < min_sample:
        return {**keep, "sample": n, "reason": f"색인 표본 {n}건(<{min_sample}) — 조절하지 않음"}
    rate = sum(1 for i in items if i.get("verdict") == "indexed") / n
    if rate >= low:
        return {**keep, "rate": rate, "sample": n, "reason": f"색인율 {rate:.0%} ≥ {low:.0%} — 평소대로"}

    last = _last_published_kst_date(cfg.get("id", ""), registry_path)
    today = now.astimezone(KST).date()
    if last and (today - last).days < gap:
        return {"skip": True, "rate": rate, "sample": n,
                "reason": f"색인율 {rate:.0%}(<{low:.0%}, 표본 {n}) · 마지막 발행 {last} — {gap}일 간격 유지"}
    return {"skip": False, "rate": rate, "sample": n,
            "reason": f"색인율 {rate:.0%}(<{low:.0%}) · 마지막 발행 {last or '없음'} — 이번 회차는 발행"}
