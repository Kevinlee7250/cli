"""포스트 관리 시스템 — 자동/수동 포스트 상태 추적 및 재시도

레지스트리: logs/post_registry.json
초안 저장: logs/post_drafts/{post_id}.json  (실패 포스트 재시도용)

Status:
  pending    — 생성됨, 업로드 대기
  published  — Blogger 게시 완료
  draft      — Blogger 임시저장
  failed     — 업로드 실패 (재시도 가능)
  skipped    — AdSense 검증 실패 등 건너뜀
  retry_queued — 재시도 예약됨
"""

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_BASE_DIR   = os.path.dirname(__file__)
REGISTRY_FILE = os.path.join(_BASE_DIR, "logs", "post_registry.json")
DRAFTS_DIR    = os.path.join(_BASE_DIR, "logs", "post_drafts")

MAX_REGISTRY  = 300   # 최대 보관 포스트 수
MAX_DRAFT_AGE = 14    # 초안 보관 기간 (일)


# ─── Status 상수 ──────────────────────────────────────────────────────────────

class Status:
    PENDING      = "pending"
    PUBLISHED    = "published"
    DRAFT        = "draft"
    FAILED       = "failed"
    SKIPPED      = "skipped"
    RETRY_QUEUED = "retry_queued"

    # 재시도 가능한 상태
    RETRYABLE = {FAILED, RETRY_QUEUED}


# ─── 레지스트리 로드/저장 ────────────────────────────────────────────────────

def load_registry() -> list[dict]:
    os.makedirs(os.path.dirname(REGISTRY_FILE), exist_ok=True)
    if os.path.exists(REGISTRY_FILE):
        try:
            with open(REGISTRY_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return []


def save_registry(registry: list[dict]) -> None:
    os.makedirs(os.path.dirname(REGISTRY_FILE), exist_ok=True)
    # 최신순 정렬 후 MAX_REGISTRY 개 유지
    registry.sort(key=lambda p: p.get("createdAt", ""), reverse=True)
    registry = registry[:MAX_REGISTRY]
    tmp_path = REGISTRY_FILE + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(registry, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, REGISTRY_FILE)  # 원자적 교체 — 중간 크래시 시 기존 파일 보존
    except OSError as e:
        logger.error(f"레지스트리 저장 실패: {e}")
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


# ─── 포스트 ID 생성 ──────────────────────────────────────────────────────────

def generate_post_id(keyword: str, title: str = "", created_at: str = "") -> str:
    date_str = (created_at or datetime.now().isoformat())[:10]
    raw      = f"{date_str}|{keyword}|{title}"
    h        = hashlib.md5(raw.encode()).hexdigest()[:8]
    slug     = re.sub(r"[^가-힣a-zA-Z0-9]", "", keyword)[:20]
    return f"{date_str}_{slug}_{h}"


# ─── 포스트 등록/업데이트 ────────────────────────────────────────────────────

def register_post(
    post_data:   dict,
    status:      str,
    blog_config: dict | None = None,
    source:      str  = "auto",   # auto | manual | series | retry
    run_number:  int  = 0,
) -> str:
    """포스트를 레지스트리에 등록하고 post_id를 반환합니다."""
    cfg      = blog_config or {}
    now      = datetime.now().isoformat()
    keyword  = post_data.get("keyword", "")
    title    = post_data.get("title", "")
    post_id  = post_data.get("_post_id") or generate_post_id(keyword, title, now)

    entry = {
        "post_id":       post_id,
        "keyword":       keyword,
        "title":         title,
        "status":        status,
        "source":        source,
        "blogId":        cfg.get("id", "default"),
        "blogName":      cfg.get("name", ""),
        "blogUrl":       post_data.get("blogUrl", ""),
        "errorMessage":  None,
        "createdAt":     now,
        "publishedAt":   now if status == Status.PUBLISHED else None,
        "lastAttemptAt": now,
        "attempts":      1,
        "runNumber":     run_number,
        # 대시보드 표시용 요약 정보
        "wordCount":     post_data.get("word_count", 0),
        "faqCount":      len(post_data.get("faq", [])),
        "category":      post_data.get("adsense_category", "일반"),
        "labels":        post_data.get("labels", [])[:7],
        "metaDescription": post_data.get("meta_description", ""),
        "contentPreview": (post_data.get("content_preview") or post_data.get("meta_description", ""))[:300],
        "articleType":   post_data.get("article_type", ""),
    }

    registry = load_registry()
    # 중복 제거 (같은 post_id)
    registry = [p for p in registry if p.get("post_id") != post_id]
    registry.insert(0, entry)
    save_registry(registry)

    # post_id를 post_data에 주입 (update_post_status 에서 참조)
    post_data["_post_id"] = post_id
    return post_id


def update_post_status(
    post_id:   str,
    status:    str,
    blog_url:  str | None = None,
    error:     str | None = None,
) -> None:
    """기존 레지스트리 항목의 상태를 업데이트합니다."""
    registry = load_registry()
    now = datetime.now().isoformat()

    for entry in registry:
        if entry.get("post_id") == post_id:
            entry["status"]        = status
            entry["lastAttemptAt"] = now
            entry["attempts"]      = entry.get("attempts", 0) + 1
            if blog_url:
                entry["blogUrl"] = blog_url
            if status == Status.PUBLISHED:
                entry["publishedAt"] = now
                entry["errorMessage"] = None
            if error:
                entry["errorMessage"] = str(error)[:500]
            break

    save_registry(registry)


# ─── 초안 저장/로드 ──────────────────────────────────────────────────────────

def save_draft(post_id: str, post_data: dict) -> None:
    """실패 시 재시도를 위해 포스트 전체 내용을 저장합니다."""
    os.makedirs(DRAFTS_DIR, exist_ok=True)
    path = os.path.join(DRAFTS_DIR, f"{post_id}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(post_data, f, ensure_ascii=False, indent=2)
        logger.debug(f"포스트 초안 저장: {path}")
    except OSError as e:
        logger.warning(f"초안 저장 실패: {e}")


def load_draft(post_id: str) -> dict | None:
    """저장된 초안을 로드합니다. 없으면 None."""
    path = os.path.join(DRAFTS_DIR, f"{post_id}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def delete_draft(post_id: str) -> None:
    path = os.path.join(DRAFTS_DIR, f"{post_id}.json")
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


# ─── 제목 중복 검사 ──────────────────────────────────────────────────────────

def _tokenize_title(text: str) -> set:
    """제목을 단어 토큰 집합으로 변환합니다 (2자+ 한글, 2자+ 영문)."""
    return {w for w in re.findall(r'[가-힣]{2,}|[a-zA-Z]{2,}', text.lower()) if w}


def _title_similarity(a: str, b: str) -> float:
    """두 제목의 Jaccard 단어 겹침 비율을 반환합니다."""
    ta, tb = _tokenize_title(a), _tokenize_title(b)
    if not ta or not tb:
        return 1.0 if a.strip() == b.strip() else 0.0
    return len(ta & tb) / len(ta | tb)


# 제목 유사도 임계값 (0.6 이상이면 중복으로 판단)
_TITLE_DEDUP_THRESHOLD = 0.6


def find_duplicate_post(
    title: str,
    blog_id: str = "",
    status_filter: tuple = (Status.PUBLISHED,),
) -> dict | None:
    """레지스트리에서 동일하거나 유사한 제목의 기존 포스트를 반환합니다.

    title: 검사할 새 제목
    blog_id: 같은 블로그 내에서만 비교 (빈 문자열이면 전체 비교)
    status_filter: 비교 대상 상태 (기본: published 포스트만)

    Returns:
        중복 포스트 dict 또는 None
    """
    registry = load_registry()
    cand = title.strip().lower()
    status_set = set(status_filter)

    for entry in registry:
        if entry.get("status") not in status_set:
            continue
        if blog_id and entry.get("blogId") not in ("", "default", blog_id):
            continue
        existing = (entry.get("title") or "").strip().lower()
        if not existing:
            continue
        # 완전 일치 또는 한쪽이 다른 쪽을 포함
        if cand == existing or cand in existing or existing in cand:
            return entry
        # 단어 겹침 유사도
        if _title_similarity(cand, existing) >= _TITLE_DEDUP_THRESHOLD:
            return entry
    return None


# ─── 조회 ────────────────────────────────────────────────────────────────────

def get_posts_by_status(
    status:   str | list | None = None,
    blog_id:  str | None = None,
    max_days: int | None = None,
) -> list[dict]:
    """레지스트리에서 조건에 맞는 포스트 목록을 반환합니다."""
    registry = load_registry()
    result   = registry

    if status:
        if isinstance(status, str):
            result = [p for p in result if p.get("status") == status]
        else:
            status_set = set(status)
            result = [p for p in result if p.get("status") in status_set]

    if blog_id:
        result = [p for p in result if p.get("blogId") == blog_id]

    if max_days is not None:
        cutoff = (datetime.now() - timedelta(days=max_days)).isoformat()
        result = [p for p in result if p.get("createdAt", "") >= cutoff]

    return result


def get_failed_posts(max_age_days: int = 7, blog_id: str | None = None) -> list[dict]:
    """재시도 가능한 실패 포스트를 반환합니다."""
    return get_posts_by_status(
        status=list(Status.RETRYABLE),
        blog_id=blog_id,
        max_days=max_age_days,
    )


def get_status_summary() -> dict:
    """상태별 포스트 수를 반환합니다."""
    registry = load_registry()
    summary  = {
        Status.PUBLISHED:    0,
        Status.FAILED:       0,
        Status.PENDING:      0,
        Status.DRAFT:        0,
        Status.SKIPPED:      0,
        Status.RETRY_QUEUED: 0,
        "total":             len(registry),
    }
    for p in registry:
        s = p.get("status", "")
        if s in summary:
            summary[s] += 1
    return summary


# ─── 대시보드 내보내기 ────────────────────────────────────────────────────────

def export_for_dashboard(docs_data_dir: str) -> None:
    """post_registry.json을 docs/data/ 로 복사합니다."""
    dst = os.path.join(docs_data_dir, "post_registry.json")
    registry = load_registry()
    try:
        with open(dst, "w", encoding="utf-8") as f:
            json.dump(registry, f, ensure_ascii=False, indent=2)
        summary = get_status_summary()
        logger.info(
            f"  포스트 레지스트리: 전체 {summary['total']}개 "
            f"(게시 {summary[Status.PUBLISHED]} / 실패 {summary[Status.FAILED]} "
            f"/ 대기 {summary[Status.PENDING]})"
        )
    except OSError as e:
        logger.error(f"레지스트리 내보내기 실패: {e}")


# ─── 실패 포스트 재시도 ───────────────────────────────────────────────────────

def retry_failed_posts(
    blog_config:  dict | None = None,
    max_posts:    int  = 10,
    max_age_days: int  = 7,
) -> dict:
    """실패한 포스트를 재시도합니다. main.py의 upload_post()를 직접 import해서 사용.

    Returns:
        {"success": int, "failed": int, "skipped": int}
    """
    from blogger_uploader import upload_post
    from content_generator import generate_post

    cfg     = blog_config or {}
    blog_id = cfg.get("id")

    failed  = get_failed_posts(max_age_days=max_age_days, blog_id=blog_id)
    if not failed:
        logger.info("재시도할 실패 포스트가 없습니다.")
        return {"success": 0, "failed": 0, "skipped": 0}

    logger.info(f"재시도 대상: {len(failed)}개 포스트 (최대 {max_posts}개 처리)")

    counts = {"success": 0, "failed": 0, "skipped": 0}

    for meta in failed[:max_posts]:
        post_id = meta["post_id"]
        keyword = meta.get("keyword", "")
        title   = meta.get("title", "")
        attempts = meta.get("attempts", 0)

        logger.info(f"\n  재시도 [{attempts + 1}회차]: '{keyword}' — {title}")

        # 저장된 초안 로드 (없으면 재생성)
        post_data = load_draft(post_id)
        if post_data:
            logger.info(f"  초안 로드 성공: {post_id}")
        else:
            logger.info(f"  초안 없음 — 재생성: '{keyword}'")
            post_data = generate_post(keyword)
            if not post_data:
                logger.error(f"  재생성 실패: '{keyword}'")
                counts["failed"] += 1
                update_post_status(post_id, Status.FAILED, error="재생성 실패")
                continue

        # 업로드 전 제목 중복 검사 — 다른 경로로 이미 게시됐을 수 있음
        dup = find_duplicate_post(title, blog_id=cfg.get("id", ""))
        if dup:
            logger.warning(
                f"  ⚠️ 재시도 건너뜀 — 유사 제목이 이미 게시됨: "
                f"'{dup.get('title', '')[:60]}' ({dup.get('blogUrl', '')})"
            )
            update_post_status(post_id, Status.SKIPPED, error="중복 제목 — 재시도 건너뜀")
            delete_draft(post_id)
            counts["skipped"] += 1
            continue

        # 업로드 시도
        update_post_status(post_id, Status.RETRY_QUEUED)
        result = upload_post(post_data, blog_config)

        if result:
            url = result.get("url", "")
            post_data["blogUrl"] = url
            update_post_status(post_id, Status.PUBLISHED, blog_url=url)
            delete_draft(post_id)   # 성공 시 초안 삭제
            counts["success"] += 1
            logger.info(f"  ✅ 재시도 성공: {url}")
        else:
            update_post_status(post_id, Status.FAILED, error=f"재시도 #{attempts + 1} 실패")
            counts["failed"] += 1
            logger.error(f"  ❌ 재시도 실패: '{keyword}'")

    logger.info(
        f"\n재시도 완료 — "
        f"성공: {counts['success']} / 실패: {counts['failed']} / 건너뜀: {counts['skipped']}"
    )
    return counts


# ─── 이전 run_history 마이그레이션 ───────────────────────────────────────────

def migrate_from_run_history(history: list[dict]) -> int:
    """기존 run_history.json에서 레지스트리로 마이그레이션합니다.
    이미 레지스트리에 있는 항목은 스킵합니다.

    Returns: 새로 추가된 포스트 수
    """
    registry   = load_registry()
    existing   = {p["post_id"] for p in registry}
    new_entries = []

    for run in history:
        run_date = (run.get("runAt", "") or "")[:10]
        blogger_uploaded = run.get("bloggerUploaded", 0)

        for i, post in enumerate(run.get("posts", [])):
            keyword = post.get("keyword", "")
            title   = post.get("title", "")
            if not title:
                continue

            post_id = generate_post_id(keyword, title, run_date + "T00:00:00")
            if post_id in existing:
                continue

            blog_url = post.get("blogUrl", "")
            # bloggerUploaded 수로 추정 (순서상 처음 N개가 업로드됨)
            status = Status.PUBLISHED if blog_url else Status.FAILED

            entry = {
                "post_id":       post_id,
                "keyword":       keyword,
                "title":         title,
                "status":        status,
                "source":        "auto",
                "blogId":        post.get("blogId", "default"),
                "blogName":      post.get("blogName", ""),
                "blogUrl":       blog_url,
                "errorMessage":  None if status == Status.PUBLISHED else "이전 실행 기록 (상세 오류 없음)",
                "createdAt":     run_date + "T00:00:00",
                "publishedAt":   run_date + "T00:00:00" if status == Status.PUBLISHED else None,
                "lastAttemptAt": run_date + "T00:00:00",
                "attempts":      1,
                "runNumber":     0,
                "wordCount":     post.get("wordCount", 0),
                "faqCount":      post.get("faqCount", 0),
                "category":      post.get("adsenseCategory", "일반"),
                "labels":        post.get("labels", [])[:7],
                "metaDescription": post.get("metaDescription", ""),
                "contentPreview":  post.get("contentPreview", "")[:300],
                "articleType":   post.get("articleType", ""),
            }
            new_entries.append(entry)
            existing.add(post_id)

    if new_entries:
        registry = new_entries + registry
        save_registry(registry)
        logger.info(f"run_history 마이그레이션: {len(new_entries)}개 포스트 추가")

    return len(new_entries)
