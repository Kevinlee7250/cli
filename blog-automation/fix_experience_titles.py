#!/usr/bin/env python3
"""발행된 글의 '지어낸 경험 주장' 제목을 조사형으로 바꿔 재게시합니다.

배경
────
2026-09-12 AdSense 거절("가치가 별로 없는 콘텐츠") 이후, 발행글 제목
39편이 하지 않은 경험을 했다고 말하고 있음을 `experience_audit.py`로
확인했습니다. 본문 가드레일은 2026-08-26에 들어갔지만 제목은 무방비였고,
검색 결과와 SNS 카드에는 제목이 먼저 노출되므로 심사관이 본 것도
이 제목들입니다.

무엇을 하나
──────────
  1. 발행 글을 순회하며 `title_policy.check_title`로 경험 주장을 찾음
  2. Claude로 조사형 제목을 다시 씀 (사실 관계·키워드는 유지)
  3. 다시 쓴 제목이 정책을 통과하는지 재검사 — 통과 못 하면 채택하지 않음
  4. Claude가 실패하면 `sanitize_title`의 규칙 기반 치환으로 폴백
  5. 제목만 PATCH (본문은 건드리지 않음 — 그건 fix_experience_claims.py)

제목만 바꾸는 것으로 충분하지 않습니다. 본문에 "저는 2024년 11월…"이
남아 있으면 제목만 고쳐도 여전히 조작입니다. 이 도구는 두 단계 중
첫 단계이고, 본문은 반드시 이어서 처리해야 합니다.

⚠️ URL은 바뀌지 않습니다. Blogger의 글 주소는 최초 발행 시점의 제목으로
정해지고 이후 제목을 바꿔도 그대로입니다. 색인·내부 링크가 깨지지 않으므로
이 도구 입장에서는 다행이지만, 주소에 옛 표현이 남는 것은 감수해야 합니다
(주소를 바꾸면 지금까지 쌓인 색인이 전부 무효가 됩니다).

사용
────
  python fix_experience_titles.py --dry-run           # 무엇이 어떻게 바뀌는지만
  python fix_experience_titles.py --dry-run --blog blog1
  python fix_experience_titles.py --limit 10          # 10편만 실제 적용
  python fix_experience_titles.py                     # 전체 적용
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
REPORT_PATH = os.path.join(_DOCS_DATA, "experience_title_fixes.json")

MAX_TITLE_LEN = 60


def _iter_posts(blog_id: str, token: str):
    """블로그의 발행(live) 글 전체를 순회합니다 (본문은 받지 않습니다)."""
    page_token = ""
    while True:
        params = {
            "maxResults": 100, "status": "live", "fetchBodies": "false",
            "fields": "nextPageToken,items(id,title,url,published)",
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


def _rewrite_with_claude(title: str, violations: list[str]) -> str:
    """Claude로 조사형 제목을 다시 씁니다. 실패하면 빈 문자열."""
    try:
        import anthropic
        from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, claude_generate
    except Exception as e:
        logger.debug(f"Claude 사용 불가: {e}")
        return ""
    if not ANTHROPIC_API_KEY:
        return ""

    labels = ", ".join(v.replace("경험 주장: ", "") for v in violations)
    prompt = f"""블로그 글 제목을 고쳐 주세요.

현재 제목: {title}
문제: 글쓴이가 하지 않은 경험을 한 것처럼 말합니다 ({labels}).

이 글은 실제 체험이 아니라 자료를 조사해 정리한 글입니다. 제목이 체험담처럼
읽히면 독자를 오도하고, 구글 애드센스 '가치가 별로 없는 콘텐츠' 정책에
걸립니다.

규칙:
- 경험 주장 표현을 빼고 조사·종합한 글이라는 것이 드러나게
  ("직접 써본 후기" → "사용 후기 종합", "제가 겪은 절차" → "공식 안내 기준 절차")
- 주제·고유명사·숫자는 그대로 유지 (검색 유입이 끊기지 않게)
- {MAX_TITLE_LEN}자 이내, 과장·낚시 표현 금지
- 구체성은 "내가 해봤다"가 아니라 숫자·비교·범위로 표현
- 제목만 한 줄로 출력. 따옴표·설명·접두어 없이.

바꾼 제목:"""
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        raw = claude_generate(
            client, model=CLAUDE_MODEL, max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        ).strip()
    except Exception as e:
        logger.warning(f"Claude 제목 재작성 실패: {e}")
        return ""

    # 모델이 설명을 덧붙이는 경우가 있어 첫 줄만 취하고 따옴표를 벗깁니다.
    line = (raw.splitlines() or [""])[0].strip()
    line = re.sub(r'^["\'“”‘’]+|["\'“”‘’]+$', "", line).strip()
    line = re.sub(r"^(바꾼\s*제목|제목)\s*[:：]\s*", "", line).strip()
    return line[:MAX_TITLE_LEN]


def propose_title(title: str, violations: list[str]) -> tuple[str, str]:
    """새 제목과 그 출처("claude" | "rule" | "")를 반환합니다.

    Claude 결과라도 정책을 통과하지 못하면 채택하지 않습니다 — 통과 검사를
    빼면 경험 주장을 다른 경험 주장으로 바꾸는 일이 생깁니다.
    """
    from title_policy import check_title, sanitize_title

    cand = _rewrite_with_claude(title, violations)
    if cand and len(cand) >= 10 and not check_title(cand):
        return cand, "claude"
    if cand:
        logger.debug(f"Claude 제안 반려(정책 재위반 또는 너무 짧음): {cand!r}")

    fallback = sanitize_title(title)
    if fallback != title and not check_title(fallback):
        return fallback, "rule"
    return "", ""


def run(blog_filter: str = "", dry_run: bool = True, limit: int = 0) -> dict:
    from blogger_uploader import _get_access_token
    from config import get_blog_configs
    from title_policy import check_title

    blogs = [b for b in get_blog_configs()
             if not blog_filter or b.get("id") == blog_filter]

    scanned = flagged = changed = failed = skipped = 0
    items = []

    for cfg in blogs:
        name, blog_id = cfg.get("name", ""), cfg.get("blog_id", "")
        if not blog_id:
            logger.warning(f"[{name}] blog_id 없음 — 건너뜀")
            continue
        token = _get_access_token(cfg)
        if not token:
            logger.error(f"[{name}] 액세스 토큰 발급 실패 — 건너뜀")
            failed += 1
            continue

        logger.info(f"── [{name}] 시작 ──")
        for post in _iter_posts(blog_id, token):
            if limit and changed >= limit:
                logger.info(f"--limit {limit} 도달 — 중단합니다")
                break
            scanned += 1
            title = post.get("title", "") or ""
            violations = check_title(title)
            if not violations:
                continue
            flagged += 1

            new_title, source = propose_title(title, violations)
            if not new_title:
                skipped += 1
                logger.warning(f"  ⏭️  대체 제목 확보 실패 — 수동 처리 필요: {title[:50]}")
                items.append({"url": post.get("url", ""), "blog": name,
                              "old": title, "new": "", "source": "",
                              "violations": violations, "action": "skipped"})
                continue

            logger.info(f"  ✏️  [{source}] {title[:46]}")
            logger.info(f"      → {new_title}")

            if dry_run:
                changed += 1
                items.append({"url": post.get("url", ""), "blog": name,
                              "old": title, "new": new_title, "source": source,
                              "violations": violations, "action": "dry-run"})
                continue

            r = requests.patch(
                f"{BLOGGER_API_BASE}/blogs/{blog_id}/posts/{post['id']}",
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json"},
                json={"title": new_title}, timeout=30,
            )
            if r.status_code == 200:
                changed += 1
                items.append({"url": post.get("url", ""), "blog": name,
                              "old": title, "new": new_title, "source": source,
                              "violations": violations, "action": "updated"})
            else:
                failed += 1
                logger.error(f"  ❌ 제목 변경 실패 [{r.status_code}]: {r.text[:160]}")
                items.append({"url": post.get("url", ""), "blog": name,
                              "old": title, "new": new_title, "source": source,
                              "violations": violations, "action": "failed"})
            time.sleep(1)  # Blogger API rate limit 배려

        if limit and changed >= limit:
            break

    report = {
        "ranAt": datetime.now(timezone.utc).isoformat(),
        "dryRun": dry_run,
        "scanned": scanned,
        "flagged": flagged,
        "changed": changed,
        "skipped": skipped,
        "failed": failed,
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
    p = argparse.ArgumentParser(description="발행 글의 경험 주장 제목을 조사형으로 정정")
    p.add_argument("--dry-run", action="store_true",
                   help="바뀔 제목만 보여주고 적용하지 않음 (첫 실행 권장)")
    p.add_argument("--blog", default="", help="특정 블로그 ID만")
    p.add_argument("--limit", type=int, default=0,
                   help="적용할 최대 글 수 (0=제한 없음)")
    args = p.parse_args()

    rep = run(args.blog, args.dry_run, args.limit)
    mode = "(dry-run) " if rep["dryRun"] else ""
    logger.info("=" * 62)
    logger.info(
        f"{mode}완료 — 검사 {rep['scanned']}편 / 위반 {rep['flagged']}편 / "
        f"정정 {rep['changed']}편 / 보류 {rep['skipped']}편 / 실패 {rep['failed']}편"
    )
    if rep["skipped"]:
        logger.info("보류된 글은 대체 제목을 만들지 못한 경우입니다 — 리포트에서 확인 후 수동 정정하세요.")
    logger.info("⚠️ 제목만 바뀌었습니다. 본문의 경험 주장은 "
                "fix_experience_claims.py 로 이어서 처리하세요.")
    return 0 if rep["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
