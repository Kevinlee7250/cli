#!/usr/bin/env python3
"""발행된 글 본문의 '지어낸 경험 주장'을 조사·분석형으로 다시 씁니다.

배경
────
2026-09-12 AdSense 거절("가치가 별로 없는 콘텐츠")의 실제 원인입니다.
제목만 고쳐서는 해결되지 않습니다 — 본문에 이런 문장이 남아 있습니다:

    "저는 2024년 11월 한 달 동안 제주시 이도동의 원룸 오피스텔에서 지냈습니다.
     한 달 총 지출은 178만원이었고, 주거비 98만원 / 식비 52만원 …"

날짜·동네·금액 내역이 전부 지어낸 것입니다. 여행·금융 판단에 쓰일 수 있는
수치라는 점에서 단순 품질 문제가 아닙니다.

어떻게 고치나
────────────
문단 단위로만 손댑니다. 글 전체를 다시 쓰면 멀쩡한 정보까지 흔들리고,
분량이 줄어 thin content 판정을 새로 만들 수 있습니다.

  1. `experience_audit.analyze_text`로 문제 문단을 특정
  2. 그 문단만 Claude에게 넘겨 조사형으로 재작성
     — 지어낸 수치는 **삭제**하고 일반적 범위·공개 자료 기준으로 대체
     — 지어낸 수치를 다른 지어낸 수치로 바꾸는 것이 최악이므로 금지
  3. 재작성 결과를 다시 감사에 통과시켜 확인 — 실패하면 채택하지 않음
  4. 통과한 문단만 원문에서 교체하고 PATCH

critical 글의 처리
─────────────────
`--unpublish-critical`을 주면 리라이팅 대신 **비공개(draft) 전환**합니다.
지어낸 금액 내역이 글의 뼈대인 경우, 그 부분을 걷어내면 남는 게 없어
리라이팅이 오히려 빈 껍데기를 만듭니다. 그럴 때는 내리는 편이 정직합니다.
되돌리려면 Blogger에서 다시 게시하면 됩니다(삭제가 아닙니다).

사용
────
  python fix_experience_claims.py --dry-run                    # 대상·계획만
  python fix_experience_claims.py --dry-run --severity critical
  python fix_experience_claims.py --unpublish-critical --limit 5
  python fix_experience_claims.py --limit 10                   # 리라이팅 10편
"""
import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"
_HERE = os.path.dirname(os.path.abspath(__file__))
_DOCS_DATA = os.path.join(_HERE, "..", "docs", "data")
REPORT_PATH = os.path.join(_DOCS_DATA, "experience_claim_fixes.json")

# 문단 단위 교체 — <p>…</p> 만 대상으로 합니다. 목차·FAQ 카드·이미지 블록은
# 구조가 있어 문장을 갈아끼우면 마크업이 깨집니다.
_P_BLOCK = re.compile(r"<p\b[^>]*>(.*?)</p>", re.I | re.S)

# 본문 길이가 크게 줄면 thin content 판정을 새로 만듭니다.
MIN_LENGTH_RATIO = 0.85


def _text_of(html_fragment: str) -> str:
    s = re.sub(r"<[^>]+>", " ", html_fragment or "")
    return re.sub(r"\s+", " ", s).strip()


def _plain_len(html: str) -> int:
    return len(_text_of(html))


def _iter_posts(blog_id: str, token: str):
    page_token = ""
    while True:
        params = {
            "maxResults": 100, "status": "live", "fetchBodies": "true",
            "fields": "nextPageToken,items(id,title,url,content,published)",
        }
        if page_token:
            params["pageToken"] = page_token
        r = requests.get(
            f"{BLOGGER_API_BASE}/blogs/{blog_id}/posts",
            headers={"Authorization": f"Bearer {token}"}, params=params, timeout=30,
        )
        if r.status_code != 200:
            logger.error(f"글 목록 조회 실패 [{r.status_code}]: {r.text[:200]}")
            return
        data = r.json()
        yield from data.get("items", [])
        page_token = data.get("nextPageToken", "")
        if not page_token:
            return


def find_bad_paragraphs(content_html: str) -> list[tuple[str, str, list[dict]]]:
    """(문단 전체 HTML, 내부 HTML, 감사 히트) 목록을 반환합니다."""
    from experience_audit import analyze_text

    out = []
    for m in _P_BLOCK.finditer(content_html or ""):
        inner = m.group(1)
        hits = analyze_text(_text_of(inner))
        if hits:
            out.append((m.group(0), inner, hits))
    return out


def rewrite_paragraph(paragraph_text: str, hits: list[dict], title: str = "") -> str:
    """문단 하나를 조사·분석형으로 다시 씁니다. 실패하면 빈 문자열."""
    try:
        import anthropic
        from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, claude_generate
    except Exception as e:
        logger.debug(f"Claude 사용 불가: {e}")
        return ""
    if not ANTHROPIC_API_KEY:
        return ""

    labels = ", ".join(sorted({h["label"] for h in hits}))
    prompt = f"""아래 문단을 고쳐 주세요.

글 제목: {title}
문제: 글쓴이가 하지 않은 경험을 한 것처럼 씁니다 ({labels}).

원문:
{paragraph_text}

이 글은 실제 체험이 아니라 자료를 조사해 정리한 글입니다. 다음 규칙을
반드시 지키세요.

1. 1인칭 경험 주장을 전부 없앨 것
   ✗ "저는 ~했습니다" / "직접 써보니" / "제가 겪은"
   ✓ "자료를 종합하면" / "이용자 후기에서는" / "공식 안내 기준으로는"

2. **지어낸 구체 수치는 삭제하거나 범위로 바꿀 것.**
   원문의 금액·날짜·주소가 실제 근거 없이 지어낸 값이라면 그대로 옮기지
   말고 "일반적으로 ○○만원 안팎" 같은 범위나 "공개된 사례에서는"으로
   바꾸세요. **새로운 구체 수치를 지어내지 마세요.** 지어낸 값을 다른
   지어낸 값으로 바꾸는 것이 가장 나쁩니다. 확신이 없으면 수치를 빼세요.

3. 문단의 정보 가치와 길이를 최대한 유지할 것 (원문과 비슷한 분량)

4. HTML 태그를 쓰지 말고 문단 텍스트만 출력할 것. 설명·머리말 없이.

고친 문단:"""
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        raw = claude_generate(
            client, model=CLAUDE_MODEL, max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        ).strip()
    except Exception as e:
        logger.warning(f"문단 재작성 실패: {e}")
        return ""

    raw = re.sub(r"^(고친\s*문단|수정본|결과)\s*[:：]\s*", "", raw).strip()
    raw = re.sub(r"</?p\b[^>]*>", "", raw).strip()
    return raw


def rewrite_content(content_html: str, title: str = "") -> tuple[str, int, int]:
    """본문의 문제 문단을 교체합니다. (새 본문, 교체 수, 반려 수)"""
    from experience_audit import analyze_text

    bad = find_bad_paragraphs(content_html)
    if not bad:
        return content_html, 0, 0

    out = content_html
    replaced = rejected = 0
    for full_block, inner, hits in bad:
        new_text = rewrite_paragraph(_text_of(inner), hits, title)
        if not new_text:
            rejected += 1
            continue
        # 재작성 결과를 같은 감사에 다시 통과시킵니다. 여기를 빼면 경험 주장을
        # 다른 경험 주장으로 바꾸고도 성공으로 집계됩니다.
        if analyze_text(new_text):
            logger.warning(f"    ⏭️  재작성본이 여전히 경험 주장 — 반려: {new_text[:60]}")
            rejected += 1
            continue
        if len(new_text) < len(_text_of(inner)) * 0.5:
            logger.warning(f"    ⏭️  재작성본이 절반 이하로 짧아짐 — 반려")
            rejected += 1
            continue

        # 원래 <p> 속성을 보존한 채 안쪽만 갈아끼웁니다.
        opening = full_block[:full_block.index(">") + 1]
        out = out.replace(full_block, f"{opening}{new_text}</p>", 1)
        replaced += 1
    return out, replaced, rejected


def _severity_of(content_html: str, title: str) -> str:
    from experience_audit import audit_post
    return audit_post(title, content_html)["severity"]


def run(blog_filter: str = "", dry_run: bool = True, limit: int = 0,
        severity_filter: str = "", unpublish_critical: bool = False) -> dict:
    from blogger_uploader import _get_access_token
    from config import get_blog_configs

    blogs = [b for b in get_blog_configs()
             if not blog_filter or b.get("id") == blog_filter]

    scanned = flagged = fixed = unpublished = failed = 0
    total_replaced = total_rejected = 0
    items = []

    for cfg in blogs:
        name, blog_id = cfg.get("name", ""), cfg.get("blog_id", "")
        if not blog_id:
            continue
        token = _get_access_token(cfg)
        if not token:
            logger.error(f"[{name}] 액세스 토큰 발급 실패 — 건너뜀")
            failed += 1
            continue

        logger.info(f"── [{name}] 시작 ──")
        for post in _iter_posts(blog_id, token):
            if limit and (fixed + unpublished) >= limit:
                logger.info(f"--limit {limit} 도달 — 중단합니다")
                break
            scanned += 1
            title = post.get("title", "") or ""
            content = post.get("content", "") or ""
            sev = _severity_of(content, title)
            if sev == "ok":
                continue
            if severity_filter and sev != severity_filter:
                continue
            flagged += 1

            # critical + 비공개 옵션 → 리라이팅 대신 내립니다.
            if sev == "critical" and unpublish_critical:
                logger.info(f"  🔴 비공개 전환: {title[:50]}")
                if not dry_run:
                    r = requests.post(
                        f"{BLOGGER_API_BASE}/blogs/{blog_id}/posts/{post['id']}/revert",
                        headers={"Authorization": f"Bearer {token}"}, timeout=30,
                    )
                    if r.status_code != 200:
                        failed += 1
                        logger.error(f"    ❌ 비공개 실패 [{r.status_code}]: {r.text[:160]}")
                        continue
                    time.sleep(1)
                unpublished += 1
                items.append({"url": post.get("url", ""), "blog": name, "title": title[:80],
                              "severity": sev, "action": "unpublished"})
                continue

            new_content, replaced, rejected = rewrite_content(content, title)
            total_replaced += replaced
            total_rejected += rejected
            if not replaced:
                logger.warning(f"  ⏭️  교체된 문단 없음 — 수동 처리: {title[:46]}")
                items.append({"url": post.get("url", ""), "blog": name, "title": title[:80],
                              "severity": sev, "action": "skipped",
                              "replaced": 0, "rejected": rejected})
                continue

            # 분량이 크게 줄면 thin content 판정을 새로 만듭니다.
            ratio = _plain_len(new_content) / max(1, _plain_len(content))
            if ratio < MIN_LENGTH_RATIO:
                logger.warning(f"  ⏭️  본문이 {ratio:.0%}로 줄어 반려 — 수동 처리: {title[:40]}")
                items.append({"url": post.get("url", ""), "blog": name, "title": title[:80],
                              "severity": sev, "action": "rejected-shrunk",
                              "lengthRatio": round(ratio, 3)})
                continue

            logger.info(f"  ✏️  {title[:46]} — 문단 {replaced}개 교체"
                        f"{f' (반려 {rejected})' if rejected else ''}")
            if dry_run:
                fixed += 1
                items.append({"url": post.get("url", ""), "blog": name, "title": title[:80],
                              "severity": sev, "action": "dry-run",
                              "replaced": replaced, "rejected": rejected})
                continue

            r = requests.patch(
                f"{BLOGGER_API_BASE}/blogs/{blog_id}/posts/{post['id']}",
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json"},
                json={"content": new_content}, timeout=30,
            )
            if r.status_code == 200:
                fixed += 1
                items.append({"url": post.get("url", ""), "blog": name, "title": title[:80],
                              "severity": sev, "action": "updated",
                              "replaced": replaced, "rejected": rejected})
            else:
                failed += 1
                logger.error(f"    ❌ 본문 갱신 실패 [{r.status_code}]: {r.text[:160]}")
            time.sleep(1)

        if limit and (fixed + unpublished) >= limit:
            break

    report = {
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "dryRun": dry_run,
        "severityFilter": severity_filter,
        "unpublishCritical": unpublish_critical,
        "scanned": scanned, "flagged": flagged,
        "rewritten": fixed, "unpublished": unpublished, "failed": failed,
        "paragraphsReplaced": total_replaced, "paragraphsRejected": total_rejected,
        "items": items,
    }
    try:
        os.makedirs(_DOCS_DATA, exist_ok=True)
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info(f"리포트 저장: {REPORT_PATH}")
    except OSError as e:
        logger.warning(f"리포트 저장 실패: {e}")
    return report


def main() -> int:
    p = argparse.ArgumentParser(description="발행 글 본문의 경험 주장을 조사형으로 재작성")
    p.add_argument("--dry-run", action="store_true", help="계획만 보고 적용하지 않음")
    p.add_argument("--blog", default="", help="특정 블로그 ID만")
    p.add_argument("--limit", type=int, default=0, help="처리할 최대 글 수 (0=제한 없음)")
    p.add_argument("--severity", default="", choices=["", "critical", "high", "medium"],
                   help="이 심각도만 처리")
    p.add_argument("--unpublish-critical", action="store_true",
                   help="critical 글은 리라이팅 대신 비공개(draft) 전환")
    args = p.parse_args()

    rep = run(args.blog, args.dry_run, args.limit, args.severity, args.unpublish_critical)
    mode = "(dry-run) " if rep["dryRun"] else ""
    logger.info("=" * 62)
    logger.info(
        f"{mode}완료 — 검사 {rep['scanned']}편 / 대상 {rep['flagged']}편 / "
        f"재작성 {rep['rewritten']}편 / 비공개 {rep['unpublished']}편 / 실패 {rep['failed']}편"
    )
    logger.info(f"  문단 교체 {rep['paragraphsReplaced']}개 / 반려 {rep['paragraphsRejected']}개")
    if rep["paragraphsRejected"]:
        logger.info("  반려는 재작성본이 여전히 경험 주장이거나 너무 짧아진 경우입니다 — "
                    "리포트에서 확인 후 수동 처리하세요.")
    return 0 if rep["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
