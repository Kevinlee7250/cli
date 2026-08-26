#!/usr/bin/env python3
"""발행된 글에서 저작권 화이트리스트 밖 이미지를 찾아 안전한 이미지로 교체합니다.

배경
────
2026-08-19 감사에서 발행 이미지 835장 중 71%가 무단 저작물로 확인됐습니다.
imgnews.naver.net(언론사 뉴스 사진) 299장을 비롯해 다음·네이버블로그·
핀터레스트·유튜브 썸네일·나무위키, 한국경제·동아일보, 뽐뿌·보배드림·
인스티즈 커뮤니티 게시물이 그대로 본문에 박혀 있었습니다.

image_fetcher.py는 같은 날 화이트리스트를 도입해 신규 글은 막았지만,
이미 발행된 글은 그대로 남아 있습니다. AdSense 심사는 지금 게시된
상태를 보므로 이 스크립트로 소급 정리해야 합니다.

동작
────
  1. Blogger API로 발행 글을 전부 순회
  2. 본문 <img>의 src 중 is_license_safe()를 통과하지 못하는 것만 선별
  3. 글 제목 기반으로 안전한 대체 이미지 확보
     (Pixabay → Wikimedia → AI 생성 → SVG 제목 썸네일)
  4. 대체 실패 시 해당 <figure>/<img>를 통째로 제거
     — 무단 이미지를 남겨두는 것보다 이미지가 없는 편이 낫습니다
  5. 변경된 글만 PATCH

사용
────
  python fix_unlicensed_images.py --dry-run              # 대상만 확인 (권장 첫 실행)
  python fix_unlicensed_images.py --dry-run --blog blog3 # 특정 블로그만
  python fix_unlicensed_images.py --limit 20             # 20건만 실제 교체
  python fix_unlicensed_images.py                        # 전체 교체

--limit으로 나눠서 돌리는 것을 권합니다. 한 번에 수백 건을 고치면
Blogger API 제한에 걸리고, 중간에 끊겼을 때 어디까지 됐는지 알기 어렵습니다.
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
_DOCS_DATA = os.path.join(os.path.dirname(__file__), "..", "docs", "data")

_IMG_TAG_RE = re.compile(r'<img\b[^>]*>', re.I)
_SRC_RE = re.compile(r'src="([^"]+)"', re.I)
# 이미지를 감싼 figure 블록 — 대체 실패 시 캡션까지 함께 제거해야
# "이미지 출처: ..." 문구만 덩그러니 남지 않습니다.
_FIGURE_RE = re.compile(r'<figure\b[^>]*>.*?</figure>', re.I | re.S)


def _extract_unsafe_urls(content: str) -> list[str]:
    """본문에서 화이트리스트를 통과하지 못하는 이미지 URL을 추출합니다."""
    from image_fetcher import is_license_safe

    out: list[str] = []
    for tag in _IMG_TAG_RE.findall(content or ""):
        m = _SRC_RE.search(tag)
        if not m:
            continue
        url = m.group(1)
        if not is_license_safe(url) and url not in out:
            out.append(url)
    return out


class ListingTruncated(RuntimeError):
    """글 목록을 끝까지 읽지 못했습니다 — 부분 결과를 전체로 보고하면 안 됩니다."""


def _iter_posts(blog_id: str, token: str):
    """블로그의 발행(live) 글 전체를 최신순으로 순회합니다."""
    page_token = ""
    fetched = 0
    attempt = 0
    while True:
        params = {
            "maxResults": 100,
            "status": "live",
            "fetchBodies": "true",
            "fields": "nextPageToken,items(id,title,url,content,published)",
        }
        if page_token:
            params["pageToken"] = page_token
        r = requests.get(
            f"{BLOGGER_API_BASE}/blogs/{blog_id}/posts",
            headers={"Authorization": f"Bearer {token}"},
            params=params, timeout=30,
        )
        if r.status_code != 200:
            # 여기서 그냥 return하면 "그 블로그에는 글이 이만큼뿐"인 것처럼
            # 보입니다. 검사·수정 도구가 절반만 훑고 성공으로 끝나므로,
            # "다 처리했는가"를 아무도 알 수 없게 됩니다.
            #
            # 2026-08-25 소급 교체에서 실제로 그랬습니다. 같은 limit 0 실행이
            # 437 → 382 → 291편으로 줄었는데, 글이 준 게 아니라 PATCH를
            # 연달아 보내 API가 목록 요청을 거절한 것이었습니다.
            if attempt < 2:
                wait = 3 * (attempt + 1)
                logger.warning(
                    f"글 목록 조회 실패 [{r.status_code}] — {wait}초 후 재시도")
                time.sleep(wait)
                attempt += 1
                continue
            raise ListingTruncated(
                f"글 목록을 끝까지 읽지 못했습니다 (HTTP {r.status_code}, "
                f"{fetched}편까지 조회): {r.text[:120]}")
        attempt = 0
        data = r.json()
        items = data.get("items", [])
        fetched += len(items)
        yield from items
        page_token = data.get("nextPageToken", "")
        if not page_token:
            return


def _find_safe_replacement(title: str, keyword: str = "") -> dict | None:
    """제목 기반으로 저작권 안전한 대체 이미지를 확보합니다.

    같은 사진이 여러 글에 반복되지 않도록, 후보를 관련성 순으로 훑으면서
    "이미 많이 쓴 사진"은 건너뜁니다.

    URL이나 제목으로는 이 판정을 할 수 없습니다 — Pixabay는 같은 사진에
    매번 다른 서명 URL을 주고, 태그 문자열도 조금씩 달라집니다. 내려받아
    내용 해시를 계산한 뒤에야 같은 사진인 줄 압니다. 그래서 복제기가
    돌려주는 uses를 보고 판단합니다 (2026-08-25 실측: 사진 한 장이 61편).

    후보가 전부 과다 사용이면 그중 가장 덜 쓴 것을 씁니다 — 이미지 없는
    글보다는 반복이라도 낫고, 여기서 None을 돌려주면 교체 대상 이미지가
    삭제됩니다.
    """
    import image_mirror
    from image_fetcher import (
        _score_title_relevance, _search_all_sources, _simplify_query, adopt_image,
        filter_license_safe, generate_fallback_image, is_license_safe,
    )

    query = _simplify_query(title, 3) or title
    candidates = filter_license_safe(_search_all_sources(
        query, "", "", 8, pixabay_api_key=os.getenv("PIXABAY_API_KEY", ""),
    ))
    candidates.sort(key=lambda c: -_score_title_relevance(c, query))

    least_used = None
    for cand in candidates[:5]:
        if not is_license_safe(cand.get("url", "")):
            continue
        cand["alt_text"] = query[:50]
        got = adopt_image(cand)
        if not got:
            continue
        uses = image_mirror.times_used(got.get("url", ""))
        if uses < image_mirror.MAX_REUSE:
            image_mirror.note_use(got.get("url", ""))
            return got
        logger.info(f"    이미 {uses}편에 쓴 사진 — 다른 후보 확인: {query[:20]}")
        if least_used is None or uses < least_used[0]:
            least_used = (uses, got)

    thumb = generate_fallback_image(title, keyword)
    if thumb and is_license_safe(thumb.get("url", "")):
        kind = "AI 생성 이미지" if thumb.get("source") == "ai_generated" else "생성 썸네일"
        logger.info(f"    쓸 만한 새 사진 없음 → {kind} 사용")
        return thumb
    if least_used:
        logger.warning(f"    후보가 전부 과다 사용 — {least_used[0]}편짜리 사진을 재사용")
        image_mirror.note_use(least_used[1].get("url", ""))
        return least_used[1]
    return None


def _replace_image(content: str, old_url: str, new_img: dict) -> str:
    """본문에서 old_url 이미지 태그의 src/alt/title을 새 이미지로 교체합니다."""
    import html as _h
    new_alt = _h.escape(new_img.get("alt_text", ""), quote=True)

    def _sub(m: re.Match) -> str:
        tag = m.group(0)
        if f'src="{old_url}"' not in tag:
            return tag
        tag = tag.replace(f'src="{old_url}"', f'src="{new_img["url"]}"')
        for attr in ("alt", "title"):
            if new_alt and re.search(rf'{attr}="[^"]*"', tag):
                tag = re.sub(rf'{attr}="[^"]*"', f'{attr}="{new_alt}"', tag)
        return _with_fallback(tag, new_img)

    return _IMG_TAG_RE.sub(_sub, content)


def _with_fallback(tag: str, img: dict) -> str:
    """자체 호스팅 주소에 원본을 onerror 예비로 붙입니다.

    복제본은 커밋된 뒤 GitHub Pages가 배포해야 열립니다. 교체 직후 배포
    전까지는 없는 파일을 가리키는데, 이 예비가 없으면 그동안 발행 글이
    그냥 깨져 보입니다 — 2026-08-25 교체에서 25장이 그 상태였습니다.
    복제본이 나중에 사라졌을 때도 같은 예비가 받아 줍니다.

    복제하지 않은 이미지(원본 그대로)는 되돌아갈 곳이 없으므로 붙이지
    않습니다. 이미 onerror가 있으면 건드리지 않습니다.
    """
    import html as _h
    origin = (img.get("origin_url") or "").strip()
    if not origin.startswith("http") or "onerror=" in tag.lower():
        return tag
    closer = "/>" if tag.rstrip().endswith("/>") else ">"
    body = tag.rstrip()[:-len(closer)].rstrip()
    esc = _h.escape(origin, quote=True)
    return body + ' onerror="this.onerror=null;this.src=\'' + esc + '\'"' + closer


# 캡션 안의 출처 표기 — "이미지 출처: 네이버 블로그 nowand4eva" 같은 조각을 찾습니다.
# <br> 또는 태그 경계 앞까지를 한 덩어리로 봅니다.
_ATTR_IN_CAPTION_RE = re.compile(r'이미지\s*출처\s*:\s*[^<]*', re.I)
_FIGURE_BLOCK_RE = re.compile(r'(<figure\b[^>]*>)(.*?)(</figure>)', re.I | re.S)
_FIGCAPTION_RE = re.compile(r'(<figcaption\b[^>]*>)(.*?)(</figcaption>)', re.I | re.S)


def sync_captions(content: str) -> tuple[str, int]:
    """figcaption의 출처 표기를 실제 이미지 src에 맞게 다시 씁니다.

    왜 필요한가
    ──────────
    _replace_image()는 <img>의 src/alt/title만 바꿉니다. figure 안의
    figcaption은 그대로 남아서, Pixabay 사진 밑에 "이미지 출처: 네이버 블로그
    nowand4eva"가 그대로 붙어 있는 상태가 됩니다. 실제와 다른 출처를 적어둔
    것이라 AdSense 심사에서는 여전히 무단 사용으로 읽히고, 원 저작자에게도
    부적절합니다.

    이미 교체가 끝난 글에도 소급 적용할 수 있도록 src URL만 보고 판정합니다
    (발행된 HTML에는 source 필드가 남지 않기 때문입니다).

    Returns: (수정된 content, 고친 캡션 수)
    """
    from image_fetcher import source_label_for_url

    fixed = 0

    def _fix_figure(m: re.Match) -> str:
        nonlocal fixed
        open_tag, inner, close_tag = m.group(1), m.group(2), m.group(3)

        img_m = _IMG_TAG_RE.search(inner)
        if not img_m:
            return m.group(0)
        src_m = _SRC_RE.search(img_m.group(0))
        if not src_m:
            return m.group(0)
        label = source_label_for_url(src_m.group(1))

        def _fix_caption(cm: re.Match) -> str:
            nonlocal fixed
            c_open, c_inner, c_close = cm.group(1), cm.group(2), cm.group(3)
            if not _ATTR_IN_CAPTION_RE.search(c_inner):
                return cm.group(0)
            if label:
                new_inner = _ATTR_IN_CAPTION_RE.sub(f'이미지 출처: {label}', c_inner)
            else:
                # 라이선스를 모르는 이미지 → 출처 줄을 통째로 지웁니다.
                # 앞의 <br>까지 같이 지워야 빈 줄이 남지 않습니다.
                new_inner = re.sub(r'(?:<br\s*/?>)?\s*이미지\s*출처\s*:\s*[^<]*', '',
                                   c_inner, flags=re.I)
            if new_inner != c_inner:
                fixed += 1
            return c_open + new_inner + c_close

        return open_tag + _FIGCAPTION_RE.sub(_fix_caption, inner) + close_tag

    return _FIGURE_BLOCK_RE.sub(_fix_figure, content or ""), fixed


def _remove_image(content: str, url: str) -> str:
    """대체 이미지를 못 구했을 때 해당 이미지를 본문에서 제거합니다.

    figure로 감싸여 있으면 캡션까지 통째로, 아니면 img 태그만 지웁니다.
    """
    def _drop_figure(m: re.Match) -> str:
        return "" if f'src="{url}"' in m.group(0) else m.group(0)

    out = _FIGURE_RE.sub(_drop_figure, content)
    if out != content:
        return out

    def _drop_img(m: re.Match) -> str:
        return "" if f'src="{url}"' in m.group(0) else m.group(0)

    return _IMG_TAG_RE.sub(_drop_img, content)


def scan_and_fix(blogs: list[dict], dry_run: bool, limit: int = 0) -> dict:
    from blogger_uploader import _get_access_token
    from image_fetcher import mark_images_used

    scanned = 0
    fixed = 0
    failed = 0
    removed_total = 0
    captions_total = 0
    replaced_total = 0
    host_counts: dict[str, int] = {}
    report_items: list[dict] = []

    for cfg in blogs:
        name = cfg.get("name") or cfg.get("id", "")
        blog_id = cfg.get("blog_id", "")
        if not blog_id:
            logger.warning(f"[{name}] blog_id 없음 — 건너뜀")
            continue

        token = _get_access_token(cfg)
        if not token:
            logger.error(f"[{name}] 액세스 토큰 발급 실패 — 건너뜀")
            failed += 1
            continue

        logger.info(f"── [{name}] 스캔 시작 ──")
        for post in _iter_posts(blog_id, token):
            if limit and fixed >= limit:
                logger.info(f"--limit {limit} 도달 — 중단합니다")
                break

            scanned += 1
            content = post.get("content", "") or ""
            title = post.get("title", "") or ""
            unsafe = _extract_unsafe_urls(content)

            # 이미지가 이미 안전해도 캡션에 옛 출처가 남아 있을 수 있습니다.
            # 1회차에서 202장을 교체하면서 figcaption을 손대지 않아
            # Pixabay 사진 밑에 "이미지 출처: 네이버 블로그"가 남았습니다.
            # 그래서 위반 이미지가 없는 글도 캡션은 확인합니다.
            _, stale_captions = sync_captions(content)

            if not unsafe and not stale_captions:
                continue

            for u in unsafe:
                h = re.sub(r'^https?://([^/:]+).*', r'\1', u)
                host_counts[h] = host_counts.get(h, 0) + 1

            if dry_run:
                if unsafe:
                    logger.info(f"  [dry-run] '{title[:45]}' — 위반 이미지 {len(unsafe)}장")
                    for u in unsafe:
                        logger.info(f"      · {u[:90]}")
                if stale_captions:
                    logger.info(f"  [dry-run] '{title[:45]}' — 출처 표기 불일치 {stale_captions}건")
                fixed += 1
                report_items.append({
                    "title": title[:60], "url": post.get("url", ""),
                    "unsafe": [u[:100] for u in unsafe],
                    "stale_captions": stale_captions,
                })
                continue

            actions: list[dict] = []
            for old_url in unsafe:
                new_img = _find_safe_replacement(title)
                if new_img:
                    content = _replace_image(content, old_url, new_img)
                    mark_images_used([new_img.get("url", "")])
                    actions.append({"old": old_url[:80], "new": new_img.get("url", "")[:80],
                                    "action": "replaced"})
                    replaced_total += 1
                else:
                    # 무단 이미지를 남기느니 지웁니다.
                    content = _remove_image(content, old_url)
                    actions.append({"old": old_url[:80], "new": "", "action": "removed"})
                    removed_total += 1
                    logger.warning(f"    ⚠️ 대체 실패 → 이미지 제거: {old_url[:70]}")

            # 이미지 교체가 끝난 뒤 캡션을 실제 src에 맞춰 다시 씁니다.
            content, n_cap = sync_captions(content)
            if n_cap:
                captions_total += n_cap
                actions.append({"old": "", "new": "", "action": "caption_synced",
                                "count": n_cap})
                logger.info(f"    ✏️ 출처 표기 {n_cap}건 정정")

            pr = requests.patch(
                f"{BLOGGER_API_BASE}/blogs/{blog_id}/posts/{post['id']}",
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json"},
                json={"content": content}, timeout=30,
            )
            if pr.status_code == 200:
                logger.info(f"  ✅ '{title[:45]}' — {len(actions)}장 처리 완료")
                fixed += 1
            else:
                logger.error(f"  ❌ 업데이트 실패 [{pr.status_code}]: {pr.text[:200]}")
                failed += 1
            time.sleep(1)  # Blogger API rate limit 배려

            report_items.append({
                "title": title[:60], "url": post.get("url", ""), "actions": actions,
            })

        if limit and fixed >= limit:
            break

    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "scanned_posts": scanned,
        "posts_with_violations": fixed,
        "images_replaced": replaced_total,
        "images_removed": removed_total,
        "captions_synced": captions_total,
        "posts_failed": failed,
        "violating_hosts": dict(sorted(host_counts.items(), key=lambda x: -x[1])),
        "items": report_items[:100],
    }
    try:
        os.makedirs(_DOCS_DATA, exist_ok=True)
        with open(os.path.join(_DOCS_DATA, "unlicensed_images.json"), "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.warning(f"리포트 저장 실패: {e}")

    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="발행 글의 저작권 위반 이미지를 안전한 이미지로 교체")
    parser.add_argument("--dry-run", action="store_true",
                        help="대상만 확인하고 수정하지 않음 (첫 실행 권장)")
    parser.add_argument("--blog", default="", help="특정 블로그 ID만 (기본: 전체)")
    parser.add_argument("--limit", type=int, default=0,
                        help="처리할 글 수 상한 (0=제한 없음). 나눠서 돌리는 것을 권장")
    args = parser.parse_args()

    from config import get_blog_configs
    blogs = get_blog_configs()
    if args.blog:
        blogs = [b for b in blogs if b.get("id") == args.blog] or blogs

    report = scan_and_fix(blogs, args.dry_run, args.limit)

    mode = "(dry-run) " if report["dry_run"] else ""
    logger.info("=" * 60)
    logger.info(
        f"{mode}완료 — 글 {report['scanned_posts']}건 스캔 / "
        f"위반 글 {report['posts_with_violations']}건 / "
        f"교체 {report['images_replaced']}장 / 제거 {report['images_removed']}장 / "
        f"출처표기 정정 {report['captions_synced']}건 / 실패 {report['posts_failed']}건"
    )
    if report["violating_hosts"]:
        logger.info("위반 출처 분포:")
        for host, n in list(report["violating_hosts"].items())[:15]:
            logger.info(f"  {n:>4}  {host}")
    return 0 if report["posts_failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
