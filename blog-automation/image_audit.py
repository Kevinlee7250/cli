"""게시글 이미지 검증 — 첨부 여부·생존·본문 관련성을 보고 고칩니다.

기존 이미지 도구들이 다루지 않던 빈틈을 채웁니다:

  · fix_unlicensed_images  → 저작권(화이트리스트) 기준
  · fix_duplicate_images   → 같은 이미지 중복 사용
  · **이 모듈**            → 이미지가 아예 없는가 / 링크가 죽었는가 /
                             본문 내용과 관련이 있는가

교체·삭제·캡션 동기화는 fix_unlicensed_images의 검증된 함수를 그대로
재사용합니다. 같은 규칙을 두 번 구현하면 반드시 어긋나기 때문입니다.

판정 5종:
  missing      이미지가 하나도 없음            → 첨부
  insufficient 본문 길이 대비 부족             → 보고만 (--attach-insufficient로 첨부)
  broken       URL이 죽었거나 이미지가 아님     → 교체
  irrelevant   본문 주제와 무관 (AI 확정)      → 교체, 대체 실패 시 삭제
  suspect      관련성 낮아 보임 (미확정)       → 절대 손대지 않음

관련성 판단은 2단계입니다:
  1) 파일명·alt·캡션·출처 페이지 제목을 본문 키워드와 대조 (무료·즉시)
  2) 1)에서 애매한 것만 Claude에게 물어봄 (--ai, 비용 발생)
  판단이 서지 않으면 "관련 있음"으로 둡니다 — 멀쩡한 이미지를 지우는 쪽이
  관련 없는 이미지를 남겨두는 쪽보다 손해가 큽니다.

Usage:
  python image_audit.py                      # 검사만 (변경 없음)
  python image_audit.py --ai                 # 애매한 건 AI로 판정
  python image_audit.py --apply --limit 20   # 실제 첨부·교체·삭제
  python image_audit.py --blog blog1 --apply
"""

import argparse
import html
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import unquote, urlparse

import requests
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"
_BASE_DIR = os.path.dirname(__file__)
REPORT_PATH = os.path.join(_BASE_DIR, "..", "docs", "data", "image_audit.json")

_IMG_TAG_RE = re.compile(r'<img\b[^>]*>', re.I)
_SRC_RE = re.compile(r'src="([^"]+)"', re.I)
_ALT_RE = re.compile(r'alt="([^"]*)"', re.I)
_TAG_RE = re.compile(r'<[^>]+>')

# 본문 대비 이미지가 이보다 적으면 "부족"으로 봅니다 (2500자당 1장 기준)
CHARS_PER_IMAGE = 2500
# 이 점수 미만이면 관련성 의심 — 1단계에서 확정하지 않고 AI 판정 대상이 됩니다
RELEVANCE_SUSPECT = 0.15


def _save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _plain_text(html_str: str) -> str:
    return _TAG_RE.sub(" ", html_str or "")


# ──────────────────────────────────────────────────────────────────────────────
# 1) 첨부 여부
# ──────────────────────────────────────────────────────────────────────────────

def extract_images(content: str) -> list[dict]:
    """본문의 이미지들을 {url, alt} 목록으로 뽑습니다."""
    out = []
    for tag in _IMG_TAG_RE.findall(content or ""):
        src = _SRC_RE.search(tag)
        if not src:
            continue
        alt = _ALT_RE.search(tag)
        out.append({"url": src.group(1), "alt": alt.group(1) if alt else ""})
    return out


def needed_image_count(content: str) -> int:
    """본문 길이에 견줘 있어야 할 최소 이미지 수."""
    chars = len(_plain_text(content).strip())
    if chars <= 0:
        return 0
    return max(1, chars // CHARS_PER_IMAGE)


# ──────────────────────────────────────────────────────────────────────────────
# 2) 링크 생존 확인
# ──────────────────────────────────────────────────────────────────────────────

def check_alive(url: str, timeout: int = 10) -> tuple[bool, str]:
    """(살아있음, 사유). 판단이 안 서면 살아있는 것으로 둡니다.

    네트워크 일시 오류로 멀쩡한 이미지를 지우면 안 되므로,
    확실히 죽은 경우(404/410)에만 False를 돌려줍니다.
    """
    if not url:
        return False, "URL 없음"
    # 이 시스템이 만드는 썸네일은 data:image/svg+xml;base64,... 로 본문에 박혀
    # 있습니다. 파일이 아니라 본문 그 자체이므로 죽을 수가 없습니다.
    # 이 갈래가 없어서 첫 실행 때 멀쩡한 썸네일 227장이 broken으로 잡혔습니다.
    if url.startswith("data:"):
        if url.startswith("data:image/"):
            return True, ""
        return False, "이미지가 아닌 data URI"
    if not url.startswith("http"):
        return False, "URL 형식 아님"
    try:
        r = requests.head(url, timeout=timeout, allow_redirects=True)
        if r.status_code == 405:                 # HEAD 미지원 서버
            r = requests.get(url, timeout=timeout, stream=True)
    except requests.exceptions.RequestException as e:
        return True, f"확인 불가 ({type(e).__name__}) — 살아있는 것으로 간주"

    if r.status_code in (404, 410):
        return False, f"HTTP {r.status_code}"
    if r.status_code >= 400:
        return True, f"HTTP {r.status_code} — 일시적일 수 있어 유지"
    ctype = (r.headers.get("Content-Type") or "").lower()
    if ctype and not ctype.startswith("image/"):
        return False, f"이미지가 아님 ({ctype[:30]})"
    return True, ""


# ──────────────────────────────────────────────────────────────────────────────
# 3) 본문 관련성
# ──────────────────────────────────────────────────────────────────────────────

def _image_terms(img: dict) -> str:
    """이미지가 스스로 말하는 정보 — 파일명·alt를 한 덩어리로."""
    url = img.get("url", "")
    if url.startswith("data:"):
        return img.get("alt", "").strip()   # base64 덩어리는 파일명이 아닙니다
    name = unquote(os.path.basename(urlparse(url).path))
    name = re.sub(r"\.(jpg|jpeg|png|gif|webp|svg)$", "", name, flags=re.I)
    name = re.sub(r"[_\-/]+", " ", name)
    return f"{img.get('alt', '')} {name}".strip()


def relevance_score(img: dict, title: str, keyword: str = "") -> float:
    """0.0~1.0. 이미지 정보와 글 주제가 겹치는 정도.

    AI 생성 썸네일은 그 글을 위해 만든 것이므로 항상 관련 있음으로 봅니다.
    """
    from image_fetcher import _core_terms

    url = img.get("url", "")
    # data URI 썸네일도 그 글을 위해 생성된 것이므로 무관할 수 없습니다
    if (url.startswith("data:image/") or "/ai_generated/" in url
            or img.get("source") in ("ai_generated", "generated_thumbnail")):
        return 1.0

    terms = _core_terms(f"{title} {keyword}", 6)
    if not terms:
        return 1.0                       # 비교 기준이 없으면 판단하지 않음

    haystack = _image_terms(img).lower()
    if not haystack:
        return 0.0
    hits = sum(1 for t in terms if t and t.lower() in haystack)
    return round(hits / len(terms), 3)


def judge_with_ai(img: dict, title: str, excerpt: str) -> tuple[bool, str]:
    """애매한 이미지를 Claude에게 물어봅니다. (관련 있음, 사유)

    호출이 실패하면 "관련 있음"으로 둡니다 — 판단하지 못한 것을 근거로
    멀쩡한 이미지를 지우면 안 됩니다.
    """
    try:
        import anthropic
        from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, claude_generate
    except ImportError as e:
        return True, f"AI 판정 불가 ({e})"
    if not ANTHROPIC_API_KEY:
        return True, "AI 판정 불가 (ANTHROPIC_API_KEY 없음)"

    prompt = (
        "블로그 글에 삽입된 이미지가 글 내용과 관련이 있는지 판단하세요.\n\n"
        f"글 제목: {title}\n"
        f"본문 발췌: {excerpt[:600]}\n"
        f"이미지 정보: {_image_terms(img) or '(파일명·설명 없음)'}\n"
        f"이미지 주소: {img.get('url', '')[:200]}\n\n"
        "이미지 정보만으로 판단이 어려우면 '관련'으로 답하세요. "
        "확실히 무관할 때만 '무관'으로 답하세요.\n"
        "형식: 관련|무관 · 한 줄 이유"
    )
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        answer = (claude_generate(
            client, model=CLAUDE_MODEL, max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        ) or "").strip()
    except Exception as e:
        logger.debug(f"AI 판정 실패: {e}")
        return True, "AI 판정 실패 — 유지"

    if answer.startswith("무관"):
        return False, answer[:120]
    return True, answer[:120]


# ──────────────────────────────────────────────────────────────────────────────
# 검사
# ──────────────────────────────────────────────────────────────────────────────

def audit_post(post: dict, use_ai: bool = False) -> dict:
    """글 하나를 검사해 문제 목록을 돌려줍니다 (변경하지 않음)."""
    content = post.get("content", "")
    title = post.get("title", "")
    images = extract_images(content)
    need = needed_image_count(content)

    issues: list[dict] = []
    if not images:
        issues.append({"type": "missing", "detail": f"이미지 0장 (권장 {need}장)"})
    elif len(images) < need:
        issues.append({"type": "insufficient",
                       "detail": f"이미지 {len(images)}장 (권장 {need}장)"})

    excerpt = _plain_text(content)[:600]
    for img in images:
        alive, why = check_alive(img["url"])
        if not alive:
            issues.append({"type": "broken", "url": img["url"], "detail": why})
            continue

        score = relevance_score(img, title, post.get("keyword", ""))
        if score >= RELEVANCE_SUSPECT:
            continue
        if use_ai:
            related, reason = judge_with_ai(img, title, excerpt)
            if related:
                continue
            issues.append({"type": "irrelevant", "url": img["url"],
                           "detail": f"AI 판정: {reason}", "score": score})
        else:
            issues.append({"type": "suspect", "url": img["url"],
                           "detail": f"관련성 낮음 (점수 {score}) — --ai로 확정 판정",
                           "score": score})

    return {"title": title[:70], "url": post.get("url", ""),
            "images": len(images), "needed": need, "issues": issues}


# ──────────────────────────────────────────────────────────────────────────────
# 수정
# ──────────────────────────────────────────────────────────────────────────────

def attach_image(content: str, title: str, keyword: str = "") -> tuple[str, bool, str]:
    """이미지가 없는 글에 관련 이미지를 첨부합니다. (본문, 성공, 사유)"""
    from fix_unlicensed_images import _find_safe_replacement
    from image_fetcher import inject_images_into_content

    img = _find_safe_replacement(title, keyword)
    if not img:
        return content, False, "대체 이미지를 찾지 못함"
    updated = inject_images_into_content(content, [img], keyword or title)
    if updated == content:
        return content, False, "삽입 위치를 찾지 못함"
    return updated, True, f"{img.get('source', '?')} 이미지 1장 첨부"


#: 손댈 문제 유형의 기본값. insufficient(권장 장수 미달)는 빠져 있습니다 —
#: 첫 검사에서 431건 중 282건이 여기 걸려, 기본으로 두면 사실상 전 게시글에
#: 이미지를 한 장씩 밀어 넣게 됩니다. 필요하면 --attach-insufficient로 켜세요.
DEFAULT_FIX_KINDS = ("missing", "broken", "irrelevant")


def fix_post(post: dict, audit: dict, kinds: tuple[str, ...] = DEFAULT_FIX_KINDS) -> tuple[str, list[str]]:
    """검사 결과에 따라 본문을 고칩니다. (수정된 본문, 수행 내역)

    kinds에 없는 유형은 건드리지 않습니다. suspect는 확정 판정 전이라
    어떤 경우에도 제외됩니다.
    """
    from fix_unlicensed_images import _find_safe_replacement, _remove_image, _replace_image, sync_captions

    content = post.get("content", "")
    title = post.get("title", "")
    keyword = post.get("keyword", "")
    actions: list[str] = []

    for issue in audit["issues"]:
        kind = issue["type"]
        if kind == "suspect" or kind not in kinds:
            continue

        if kind in ("missing", "insufficient"):
            content, ok, why = attach_image(content, title, keyword)
            actions.append(f"첨부: {why}" if ok else f"첨부 실패: {why}")
            continue

        new_img = _find_safe_replacement(title, keyword)
        if new_img:
            content = _replace_image(content, issue["url"], new_img)
            actions.append(f"{kind} 교체 → {new_img.get('source', '?')}")
        else:
            content = _remove_image(content, issue["url"])
            actions.append(f"{kind} 삭제 (대체 이미지 없음)")

    if actions:
        # 이미지를 바꿨으면 출처 표기도 실제 src에 맞춰야 합니다
        content, fixed = sync_captions(content)
        if fixed:
            actions.append(f"캡션 동기화 {fixed}건")
    return content, actions


# ──────────────────────────────────────────────────────────────────────────────
# 실행
# ──────────────────────────────────────────────────────────────────────────────

def run(blog_filter: str = "", limit: int = 0, apply_changes: bool = False,
        use_ai: bool = False, attach_insufficient: bool = False) -> dict:
    from config import get_blog_configs
    from blogger_uploader import _get_access_token
    from fix_unlicensed_images import _iter_posts

    fix_kinds = DEFAULT_FIX_KINDS + (("insufficient",) if attach_insufficient else ())

    blogs = get_blog_configs()
    if blog_filter:
        blogs = [b for b in blogs if b.get("id") == blog_filter] or blogs

    results, totals = [], {"scanned": 0, "withIssues": 0, "fixed": 0}
    counts: dict[str, int] = {}

    for cfg in blogs:
        name = cfg.get("name") or cfg.get("id", "")
        blogger_id = cfg.get("blog_id", "")
        token = _get_access_token(cfg)
        if not (blogger_id and token):
            logger.error(f"[{name}] blog_id 또는 토큰 없음 — 건너뜀")
            continue

        logger.info(f"══ [{name}] 이미지 검사 시작 (apply={apply_changes}, ai={use_ai}) ══")
        for post in _iter_posts(blogger_id, token):
            if limit and totals["scanned"] >= limit:
                break
            totals["scanned"] += 1
            audit = audit_post(post, use_ai)
            if not audit["issues"]:
                continue

            totals["withIssues"] += 1
            for i in audit["issues"]:
                counts[i["type"]] = counts.get(i["type"], 0) + 1
            audit["blog"] = name
            logger.info(f"  ⚠️ {audit['title'][:44]} — "
                        f"{', '.join(i['type'] for i in audit['issues'])}")

            if apply_changes:
                updated, actions = fix_post(post, audit, fix_kinds)
                if actions and updated != post.get("content", ""):
                    r = requests.patch(
                        f"{BLOGGER_API_BASE}/blogs/{blogger_id}/posts/{post['id']}",
                        headers={"Authorization": f"Bearer {token}",
                                 "Content-Type": "application/json"},
                        json={"content": updated}, timeout=30)
                    if r.status_code == 200:
                        totals["fixed"] += 1
                        audit["actions"] = actions
                        logger.info(f"     ✅ {' / '.join(actions)}")
                        time.sleep(1)      # Blogger 쓰기 레이트 리밋 배려
                    else:
                        audit["actions"] = [f"수정 실패 HTTP {r.status_code}"]
                        logger.warning(f"     ❌ 수정 실패 [{r.status_code}]")
                else:
                    audit["actions"] = actions or ["변경 없음"]
            results.append(audit)

    report = {
        "auditedAt": datetime.now(timezone.utc).isoformat(),
        "applied": apply_changes,
        "aiJudged": use_ai,
        "fixKinds": list(fix_kinds),
        **totals,
        "issueCounts": counts,
        "posts": results[:100],
    }
    logger.info("=" * 60)
    logger.info(f"검사 {totals['scanned']}건 / 문제 {totals['withIssues']}건 "
                f"/ 수정 {totals['fixed']}건")
    if counts:
        logger.info(f"유형별: {counts}")
    if not apply_changes and totals["withIssues"]:
        logger.info("🔍 검사 전용 — 실제 수정은 --apply")
    if counts.get("suspect"):
        logger.info(f"관련성 의심 {counts['suspect']}건은 --ai 로 확정 판정할 수 있습니다")

    try:
        _save(REPORT_PATH, report)
        logger.info(f"리포트 저장: {REPORT_PATH}")
    except OSError as e:
        logger.warning(f"리포트 저장 실패 (무시): {e}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="게시글 이미지 검증·수정")
    parser.add_argument("--apply", action="store_true", help="실제로 글을 수정")
    parser.add_argument("--ai", action="store_true",
                        help="관련성이 애매한 이미지를 Claude로 확정 판정 (비용 발생)")
    parser.add_argument("--limit", type=int, default=0, help="검사할 최대 글 수 (0=전체)")
    parser.add_argument("--blog", default="", help="특정 블로그 ID만")
    parser.add_argument("--attach-insufficient", action="store_true",
                        help="권장 장수에 못 미치는 글에도 이미지를 추가 (기본은 건너뜀)")
    args = parser.parse_args()
    run(args.blog, args.limit, args.apply, args.ai, args.attach_insufficient)
    return 0


if __name__ == "__main__":
    sys.exit(main())
