#!/usr/bin/env python3
"""
블로그 댓글 자동화 시스템
━━━━━━━━━━━━━━━━━━━━━━━━
기능:
  1. 씨앗 댓글 — 새 포스트 게시 후 블로그 운영자 명의로 보충 댓글 자동 작성
     (글에서 다루지 못한 팁, 독자 질문 유도 등)
  2. 독자 댓글 자동 답변 — 새 댓글 감지 → Claude가 맥락에 맞는 답변 생성 → 자동 게시
  3. 큐잉 — API 불가 시 docs/data/pending_comments.json에 저장 (대시보드 수동 발행)

Blogger API v3 주요 엔드포인트:
  GET  /blogs/{blogId}/posts/{postId}/comments          — 댓글 목록
  POST /blogs/{blogId}/posts/{postId}/comments          — 댓글 작성 (비공식, 소유자 계정)
  POST /blogs/{blogId}/posts/{postId}/comments/{id}/... — 답글 (inReplyTo 필드)
  GET  /blogs/{blogId}/posts/bypath?path=...            — URL → postId 변환

사용법:
  python comment_manager.py --seed   --hours 25   # 최근 25시간 내 신규 포스트에 씨앗 댓글
  python comment_manager.py --reply  --hours 6    # 최근 6시간 내 신규 댓글 자동 답변
  python comment_manager.py --status              # 댓글 현황 출력
  python comment_manager.py --dry                 # 생성만, 게시 안 함
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

_BASE_DIR        = Path(__file__).parent
_HISTORY_FILE    = _BASE_DIR / "logs" / "comment_history.json"
_PENDING_FILE    = _BASE_DIR.parent / "docs" / "data" / "pending_comments.json"
_REGISTRY_FILE   = _BASE_DIR / "logs" / "post_registry.json"
BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"
TOKEN_URL        = "https://oauth2.googleapis.com/token"

# 씨앗 댓글 딜레이: 포스트 게시 후 최소 몇 분 경과 후 작성
_SEED_DELAY_MINUTES = 3
# 자동 답변 대상: 최소 몇 분 경과한 댓글 (너무 즉시 답변 = 봇처럼 보임)
_REPLY_MIN_AGE_MINUTES = 10
# 1회 실행당 최대 처리 댓글 수
_MAX_REPLIES_PER_RUN = 8
_MAX_SEEDS_PER_RUN   = 5


# ─── OAuth ────────────────────────────────────────────────────────────────────

def _get_access_token(blog_config: dict) -> str | None:
    """blog_config의 OAuth 크리덴셜로 액세스 토큰을 발급합니다."""
    cfg = blog_config or {}
    client_id     = cfg.get("client_id")     or os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = cfg.get("client_secret") or os.getenv("GOOGLE_CLIENT_SECRET", "")
    refresh_token = cfg.get("refresh_token") or os.getenv("GOOGLE_REFRESH_TOKEN", "")

    if not all([client_id, client_secret, refresh_token]):
        logger.error("OAuth 크리덴셜 미설정 (client_id / client_secret / refresh_token)")
        return None

    try:
        resp = requests.post(TOKEN_URL, data={
            "client_id":     client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type":    "refresh_token",
        }, timeout=15)
        if resp.status_code == 200:
            return resp.json().get("access_token")
        body = resp.text
        if "invalid_grant" in body:
            logger.error("refresh_token 만료 — get_refresh_token.py 재실행 필요")
        else:
            logger.error(f"토큰 발급 실패 [{resp.status_code}]: {body[:200]}")
    except Exception as e:
        logger.error(f"토큰 요청 오류: {e}")
    return None


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ─── Blogger API 헬퍼 ─────────────────────────────────────────────────────────

def _get_blogger_post_id(blog_id: str, blog_url: str, token: str) -> str | None:
    """블로그 URL에서 Blogger postId를 조회합니다."""
    try:
        parsed = urlparse(blog_url)
        path   = parsed.path
        url    = f"{BLOGGER_API_BASE}/blogs/{blog_id}/posts/bypath"
        resp   = requests.get(url, params={"path": path},
                              headers=_auth_headers(token), timeout=15)
        if resp.status_code == 200:
            return resp.json().get("id")
        logger.debug(f"bypath 조회 실패 [{resp.status_code}]: {blog_url}")
    except Exception as e:
        logger.debug(f"postId 조회 오류: {e}")
    return None


def _list_comments(blog_id: str, post_id: str, token: str,
                   max_results: int = 50) -> list[dict]:
    """포스트의 댓글 목록을 반환합니다."""
    try:
        url  = f"{BLOGGER_API_BASE}/blogs/{blog_id}/posts/{post_id}/comments"
        resp = requests.get(url, params={"maxResults": max_results, "status": "LIVE"},
                            headers=_auth_headers(token), timeout=15)
        if resp.status_code == 200:
            return resp.json().get("items", [])
        logger.debug(f"댓글 조회 실패 [{resp.status_code}]")
    except Exception as e:
        logger.debug(f"댓글 조회 오류: {e}")
    return []


def _post_comment(blog_id: str, post_id: str, content: str,
                  token: str, in_reply_to_id: str = "") -> dict | None:
    """Blogger API로 댓글 또는 답글을 게시합니다.

    Blogger API v3는 공식적으로 comments.insert를 문서화하지 않지만
    블로그 소유자 토큰으로는 동작합니다. 405 반환 시 큐잉으로 폴백합니다.
    """
    payload: dict = {"content": content}
    if in_reply_to_id:
        payload["inReplyTo"] = {"id": in_reply_to_id}

    url = f"{BLOGGER_API_BASE}/blogs/{blog_id}/posts/{post_id}/comments"
    try:
        resp = requests.post(url, json=payload,
                             headers=_auth_headers(token), timeout=20)
        if resp.status_code in (200, 201):
            result = resp.json()
            logger.info(f"  ✅ 댓글 게시 성공 (id={result.get('id')})")
            return result
        if resp.status_code == 405:
            logger.warning("  ⚠️ Blogger API가 댓글 게시를 지원하지 않음 — 큐잉")
        elif resp.status_code == 403:
            logger.warning(f"  ⚠️ 댓글 권한 없음 [{resp.status_code}] — 큐잉")
        else:
            logger.warning(f"  ⚠️ 댓글 게시 실패 [{resp.status_code}]: {resp.text[:200]} — 큐잉")
    except Exception as e:
        logger.warning(f"  ⚠️ 댓글 게시 오류 ({e}) — 큐잉")
    return None


# ─── 댓글 이력 ────────────────────────────────────────────────────────────────

def _load_history() -> dict:
    """comment_history.json 로드."""
    if _HISTORY_FILE.exists():
        try:
            return json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"seeds": {}, "replies": {}, "owner_comment_ids": []}


def _save_history(h: dict) -> None:
    _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _HISTORY_FILE.write_text(
        json.dumps(h, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _is_already_seeded(post_id: str) -> bool:
    return post_id in _load_history().get("seeds", {})


def _is_already_replied(comment_id: str) -> bool:
    return comment_id in _load_history().get("replies", {})


def _record_seed(post_id: str, entry: dict) -> None:
    h = _load_history()
    h.setdefault("seeds", {})[post_id] = entry
    if entry.get("blogger_comment_id"):
        h.setdefault("owner_comment_ids", []).append(entry["blogger_comment_id"])
    _save_history(h)


def _record_reply(comment_id: str, entry: dict) -> None:
    h = _load_history()
    h.setdefault("replies", {})[comment_id] = entry
    if entry.get("blogger_comment_id"):
        h.setdefault("owner_comment_ids", []).append(entry["blogger_comment_id"])
    _save_history(h)


# ─── 댓글 큐잉 (API 게시 실패 시) ────────────────────────────────────────────

def _queue_comment(entry: dict) -> None:
    """pending_comments.json에 댓글을 추가합니다 (대시보드 수동 발행용)."""
    _PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        pending = json.loads(_PENDING_FILE.read_text(encoding="utf-8")) if _PENDING_FILE.exists() else []
    except Exception:
        pending = []
    pending.insert(0, entry)
    pending = pending[:200]  # 최대 200개 유지
    _PENDING_FILE.write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"  📥 댓글 큐잉: pending_comments.json ({len(pending)}개)")


# ─── Claude 댓글 생성 ─────────────────────────────────────────────────────────

def _call_claude(prompt: str, max_tokens: int = 600) -> str:
    """Claude API 호출."""
    try:
        import anthropic
        from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, claude_generate
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        return claude_generate(
            client,
            model=CLAUDE_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        ).strip()
    except Exception as e:
        logger.error(f"Claude 호출 오류: {e}")
        return ""


def generate_seed_comment(post_data: dict) -> str:
    """새 포스트에 달 씨앗 댓글을 생성합니다.

    글 운영자 입장에서 독자에게 도움이 되는 추가 정보나 질문을 댓글로 남깁니다.
    """
    title    = post_data.get("title", "")
    keyword  = post_data.get("keyword", "")
    content  = re.sub(r'<[^>]+>', ' ', post_data.get("content", ""))[:1500]
    language = post_data.get("language", "ko")

    if language == "en":
        lang_inst = "Write in natural English. Friendly, helpful tone."
    else:
        lang_inst = "자연스러운 한국어로 작성하세요. 친근하고 도움이 되는 어투."

    prompt = f"""당신은 블로그 운영자입니다. 방금 아래 글을 발행했고, 독자에게 도움이 되는 내용을 댓글로 추가하려 합니다.

글 제목: {title}
핵심 키워드: {keyword}
글 내용 (요약):
{content}

━━━ 댓글 작성 지침 ━━━
{lang_inst}
• 글에서 미처 다루지 못한 실용적인 팁 1~2가지를 추가하거나,
  독자가 이 글을 읽고 궁금해할 법한 질문을 던지세요.
• 글 요약이나 홍보가 되어서는 안 됩니다 — 댓글 고유의 부가 가치를 담으세요.
• 너무 길지 않게 2~4문장으로 작성하세요.
• "블로그 운영자입니다" 같은 자기소개는 생략하세요.
• 독자 참여를 유도하는 질문으로 마무리하면 좋습니다.

댓글 내용만 출력하세요 (따옴표·설명 없이):"""

    text = _call_claude(prompt, max_tokens=300)
    return text


def generate_reply(post_data: dict, comment: dict) -> str:
    """독자 댓글에 대한 AI 답변을 생성합니다."""
    title         = post_data.get("title", "")
    keyword       = post_data.get("keyword", "")
    post_content  = re.sub(r'<[^>]+>', ' ', post_data.get("content", ""))[:1200]
    comment_text  = comment.get("content", "")
    commenter     = comment.get("author", {}).get("displayName", "독자")
    language      = post_data.get("language", "ko")

    if language == "en":
        lang_inst = "Write in natural English. Friendly, helpful, conversational."
    else:
        lang_inst = "자연스러운 한국어로 작성하세요. 친근하고 따뜻한 어투."

    prompt = f"""당신은 블로그 운영자입니다. 독자 댓글에 진심 어린 답변을 달아주세요.

글 제목: {title}
핵심 키워드: {keyword}
글 내용 (요약):
{post_content}

━━━ 독자 댓글 ━━━
작성자: {commenter}
내용: {comment_text}

━━━ 답변 지침 ━━━
{lang_inst}
• 댓글 내용을 정확히 이해하고 맥락에 맞게 답변하세요.
• 질문이면 → 구체적이고 도움이 되는 답변
• 감사/칭찬이면 → 진심 어린 감사 + 추가 인사이트 1개
• 비판/부정적 의견이면 → 방어적이지 않게, 건설적으로 수용
• 2~4문장, 자연스러운 대화체로 작성하세요.
• 댓글 작성자 이름을 자연스럽게 포함하면 좋습니다.

답변 내용만 출력하세요 (따옴표·설명 없이):"""

    text = _call_claude(prompt, max_tokens=400)
    return text


# ─── 포스트 레지스트리 로드 ───────────────────────────────────────────────────

def _load_published_posts(hours: int = 25) -> list[dict]:
    """post_registry.json에서 published 포스트를 최근 N시간 기준으로 로드합니다."""
    if not _REGISTRY_FILE.exists():
        return []
    try:
        registry = json.loads(_REGISTRY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    result = []
    for p in registry:
        if p.get("status") != "published":
            continue
        published_at = p.get("publishedAt") or p.get("createdAt") or ""
        if published_at >= cutoff and p.get("blogUrl"):
            result.append(p)
    return result


# ─── 씨앗 댓글 ────────────────────────────────────────────────────────────────

def seed_new_post(
    post_data:        dict,
    blog_config:      dict,
    blogger_post_id:  str  = "",
    dry_run:          bool = False,
) -> bool:
    """새 포스트에 씨앗 댓글을 작성합니다."""
    internal_post_id = post_data.get("_post_id", "")
    blog_url         = post_data.get("blogUrl", "")
    title            = post_data.get("title", "")

    if not blog_url:
        logger.debug("blogUrl 없음 — 씨앗 댓글 건너뜀")
        return False

    if _is_already_seeded(internal_post_id or blog_url):
        logger.debug(f"이미 씨앗 댓글 작성됨: {title[:40]}")
        return False

    logger.info(f"\n🌱 씨앗 댓글 작성: '{title[:45]}'")

    # Claude로 댓글 생성
    comment_text = generate_seed_comment(post_data)
    if not comment_text:
        logger.warning("씨앗 댓글 생성 실패")
        return False

    logger.info(f"  생성된 댓글: {comment_text[:80]}...")

    now_iso = datetime.now(timezone.utc).isoformat()
    entry = {
        "type":         "seed",
        "post_id":      internal_post_id,
        "blog_url":     blog_url,
        "title":        title,
        "content":      comment_text,
        "created_at":   now_iso,
        "status":       "pending",
        "blogger_comment_id": None,
    }

    if dry_run:
        logger.info("  [DRY RUN] 게시 건너뜀")
        return True

    # 게시 딜레이 (봇 감지 방지)
    time.sleep(_SEED_DELAY_MINUTES * 60 if _SEED_DELAY_MINUTES > 0 else 0)

    token = _get_access_token(blog_config)
    if not token:
        logger.warning("  OAuth 토큰 없음 — 큐잉")
        entry["status"] = "queued"
        _queue_comment(entry)
        _record_seed(internal_post_id or blog_url, entry)
        return False

    # Blogger postId 확보
    cfg     = blog_config or {}
    blog_id = str(cfg.get("blog_id") or os.getenv("BLOGGER_BLOG_ID", ""))
    if not blogger_post_id and blog_url:
        blogger_post_id = _get_blogger_post_id(blog_id, blog_url, token) or ""

    if not blogger_post_id:
        logger.warning("  Blogger postId 조회 실패 — 큐잉")
        entry["status"] = "queued"
        _queue_comment(entry)
        _record_seed(internal_post_id or blog_url, entry)
        return False

    # 게시
    result = _post_comment(blog_id, blogger_post_id, comment_text, token)
    if result:
        entry["status"]              = "posted"
        entry["blogger_comment_id"]  = result.get("id")
        entry["blogger_post_id"]     = blogger_post_id
        _record_seed(internal_post_id or blog_url, entry)
        return True
    else:
        entry["status"] = "queued"
        _queue_comment(entry)
        _record_seed(internal_post_id or blog_url, entry)
        return False


# ─── 자동 답변 ────────────────────────────────────────────────────────────────

def process_incoming_comments(
    blog_configs: list[dict],
    hours:        int  = 6,
    dry_run:      bool = False,
) -> dict:
    """최근 N시간 내 신규 댓글에 자동으로 답변합니다."""
    stats = {"checked": 0, "replied": 0, "queued": 0, "skipped": 0, "errors": 0}
    replied_this_run = 0

    published = _load_published_posts(hours=max(hours * 4, 72))
    if not published:
        logger.info("최근 게시된 포스트 없음")
        return stats

    owner_ids: set[str] = set(_load_history().get("owner_comment_ids", []))

    for cfg in blog_configs:
        blog_id = str(cfg.get("blog_id") or os.getenv("BLOGGER_BLOG_ID", ""))
        if not blog_id:
            continue

        blog_posts = [p for p in published
                      if p.get("blogId") in (cfg.get("id", ""), "default", "")]

        token = _get_access_token(cfg)
        if not token:
            logger.warning(f"[{cfg.get('name','?')}] OAuth 토큰 발급 실패 — 건너뜀")
            continue

        for post_meta in blog_posts:
            if replied_this_run >= _MAX_REPLIES_PER_RUN:
                logger.info(f"답변 최대 건수 도달 ({_MAX_REPLIES_PER_RUN}건) — 종료")
                break

            blog_url = post_meta.get("blogUrl", "")
            title    = post_meta.get("title", "")

            blogger_post_id = _get_blogger_post_id(blog_id, blog_url, token)
            if not blogger_post_id:
                continue

            comments = _list_comments(blog_id, blogger_post_id, token)
            stats["checked"] += len(comments)

            # 새 댓글 필터링
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            new_comments = []
            for c in comments:
                pub = c.get("published", "")
                try:
                    dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                except Exception:
                    continue
                # 너무 새 댓글은 잠시 기다림 (봇 감지 방지)
                age_min = (datetime.now(timezone.utc) - dt).total_seconds() / 60
                if age_min < _REPLY_MIN_AGE_MINUTES:
                    continue
                if dt < cutoff:
                    continue
                # 이미 답변한 댓글 제외
                if _is_already_replied(c.get("id", "")):
                    continue
                # 운영자 자신의 댓글 제외
                author_id = c.get("author", {}).get("id", "")
                if author_id and author_id in owner_ids:
                    continue
                new_comments.append(c)

            if not new_comments:
                continue

            logger.info(f"\n💬 '{title[:40]}' — 미답변 댓글 {len(new_comments)}개")

            # 포스트 데이터 복원 (레지스트리에서 최소 정보만 사용)
            post_data = {
                "title":    title,
                "keyword":  post_meta.get("keyword", ""),
                "content":  post_meta.get("contentPreview", ""),
                "language": cfg.get("language", "ko"),
            }

            for comment in new_comments:
                if replied_this_run >= _MAX_REPLIES_PER_RUN:
                    break

                comment_id   = comment.get("id", "")
                comment_text = comment.get("content", "")
                commenter    = comment.get("author", {}).get("displayName", "독자")
                logger.info(f"  답변 대상: [{commenter}] {comment_text[:60]}")

                reply_text = generate_reply(post_data, comment)
                if not reply_text:
                    stats["errors"] += 1
                    continue

                logger.info(f"  생성된 답변: {reply_text[:80]}...")

                now_iso = datetime.now(timezone.utc).isoformat()
                entry = {
                    "type":               "reply",
                    "blog_url":           blog_url,
                    "title":              title,
                    "comment_id":         comment_id,
                    "comment_author":     commenter,
                    "comment_content":    comment_text,
                    "reply_content":      reply_text,
                    "created_at":         now_iso,
                    "status":             "pending",
                    "blogger_comment_id": None,
                }

                if dry_run:
                    logger.info("  [DRY RUN] 게시 건너뜀")
                    _record_reply(comment_id, {**entry, "status": "dry_run"})
                    stats["replied"] += 1
                    replied_this_run += 1
                    continue

                result = _post_comment(blog_id, blogger_post_id, reply_text, token,
                                       in_reply_to_id=comment_id)
                if result:
                    entry["status"]              = "posted"
                    entry["blogger_comment_id"]  = result.get("id")
                    _record_reply(comment_id, entry)
                    stats["replied"] += 1
                else:
                    entry["status"] = "queued"
                    _queue_comment(entry)
                    _record_reply(comment_id, entry)
                    stats["queued"] += 1

                replied_this_run += 1
                time.sleep(3)  # 연속 댓글 사이 딜레이

    logger.info(
        f"\n📊 댓글 처리 결과 — "
        f"확인: {stats['checked']}개 | 답변: {stats['replied']}개 | "
        f"큐잉: {stats['queued']}개 | 오류: {stats['errors']}개"
    )
    return stats


# ─── 씨앗 댓글 일괄 처리 ──────────────────────────────────────────────────────

def seed_recent_posts(
    blog_configs: list[dict],
    hours:        int  = 25,
    dry_run:      bool = False,
) -> dict:
    """최근 N시간 내 게시된 포스트 중 씨앗 댓글이 없는 것에 댓글을 작성합니다."""
    stats   = {"seeded": 0, "skipped": 0, "errors": 0}
    seeded  = 0
    published = _load_published_posts(hours=hours)

    if not published:
        logger.info(f"최근 {hours}시간 내 게시 포스트 없음 — 씨앗 댓글 건너뜀")
        return stats

    logger.info(f"씨앗 댓글 대상 포스트: {len(published)}개")

    for cfg in blog_configs:
        blog_posts = [p for p in published
                      if p.get("blogId") in (cfg.get("id", ""), "default", "")]

        for post_meta in blog_posts:
            if seeded >= _MAX_SEEDS_PER_RUN:
                break

            internal_id = post_meta.get("post_id", "")
            blog_url    = post_meta.get("blogUrl", "")

            if _is_already_seeded(internal_id or blog_url):
                stats["skipped"] += 1
                continue

            # 최소 딜레이 경과 확인
            published_at = post_meta.get("publishedAt") or post_meta.get("createdAt") or ""
            if published_at:
                try:
                    pub_dt  = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                    age_min = (datetime.now(timezone.utc) - pub_dt).total_seconds() / 60
                    if age_min < _SEED_DELAY_MINUTES:
                        logger.debug(f"게시 후 {age_min:.0f}분 경과 — 씨앗 댓글 대기")
                        stats["skipped"] += 1
                        continue
                except Exception:
                    pass

            # 최소한의 post_data 재구성
            post_data_min = {
                "_post_id":  internal_id,
                "blogUrl":   blog_url,
                "title":     post_meta.get("title", ""),
                "keyword":   post_meta.get("keyword", ""),
                "content":   post_meta.get("contentPreview", ""),
                "language":  cfg.get("language", "ko"),
            }

            ok = seed_new_post(post_data_min, cfg, dry_run=dry_run)
            if ok or dry_run:
                stats["seeded"] += 1
                seeded += 1
            else:
                stats["errors"] += 1
            time.sleep(2)

    logger.info(
        f"씨앗 댓글 완료 — 작성: {stats['seeded']}개 | "
        f"건너뜀: {stats['skipped']}개 | 오류: {stats['errors']}개"
    )
    return stats


# ─── 상태 출력 ────────────────────────────────────────────────────────────────

def print_status() -> None:
    h = _load_history()
    seeds   = h.get("seeds", {})
    replies = h.get("replies", {})

    # 큐잉 현황
    pending = []
    if _PENDING_FILE.exists():
        try:
            pending = json.loads(_PENDING_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    print("\n" + "=" * 60)
    print("💬 댓글 자동화 현황")
    print("=" * 60)
    print(f"  씨앗 댓글 게시됨:  {sum(1 for s in seeds.values() if s.get('status')=='posted')}건")
    print(f"  씨앗 댓글 큐잉:    {sum(1 for s in seeds.values() if s.get('status')=='queued')}건")
    print(f"  자동 답변 게시됨:  {sum(1 for r in replies.values() if r.get('status')=='posted')}건")
    print(f"  자동 답변 큐잉:    {sum(1 for r in replies.values() if r.get('status')=='queued')}건")
    print(f"  대시보드 큐 대기:  {len(pending)}건")

    if pending:
        print("\n  [미발행 댓글 큐 (최신 5개)]")
        for item in pending[:5]:
            print(f"    • [{item.get('type','?')}] {item.get('title','')[:40]}")
            print(f"      내용: {item.get('content') or item.get('reply_content','')[:60]}")
    print("=" * 60 + "\n")


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="블로그 댓글 자동화")
    parser.add_argument("--seed",    action="store_true", help="씨앗 댓글 작성")
    parser.add_argument("--reply",   action="store_true", help="독자 댓글 자동 답변")
    parser.add_argument("--status",  action="store_true", help="현황 출력")
    parser.add_argument("--hours",   type=int, default=6,  help="대상 시간 범위 (기본 6시간)")
    parser.add_argument("--dry",     action="store_true",  help="생성만, 게시 안 함")
    args = parser.parse_args()

    from config import get_blog_configs
    configs = get_blog_configs()

    if args.status:
        print_status()
        sys.exit(0)

    if not args.seed and not args.reply:
        parser.print_help()
        sys.exit(1)

    if args.seed:
        seed_recent_posts(configs, hours=args.hours, dry_run=args.dry)

    if args.reply:
        process_incoming_comments(configs, hours=args.hours, dry_run=args.dry)
