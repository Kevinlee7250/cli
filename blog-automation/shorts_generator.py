"""유튜브 쇼츠/릴스 스크립트 자동 생성 — 발행 글 → 60초 영상 스크립트 + 세로 썸네일

발행된 블로그 글을 60초 쇼츠용으로 변환합니다:
  - 훅(0~3초) / 장면별 대본(내레이션 + 화면 지시) / CTA
  - 업로드용 캡션 + 해시태그
  - 9:16 세로(1080x1920) SVG 썸네일 (data URI)

결과는 docs/data/shorts_scripts.json에 저장되어 대시보드 소셜 미디어
페이지에서 확인·복사할 수 있습니다.

사용법:
  python shorts_generator.py --post-id <post_id>   # 특정 발행 글
  python shorts_generator.py --latest 3            # 스크립트 없는 최근 발행 글 N건
"""

import argparse
import base64
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_BASE = os.path.dirname(__file__)
_DOCS_DATA = os.path.join(_BASE, "..", "docs", "data")
_SCRIPTS_FILE = os.path.join(_DOCS_DATA, "shorts_scripts.json")
_MAX_SCRIPTS = 50


# ──────────────────────────────────────────────────────────────────────────────
# 9:16 세로 썸네일 (쇼츠 표지)
# ──────────────────────────────────────────────────────────────────────────────

def generate_shorts_thumbnail(title: str, keyword: str = "") -> str:
    """9:16 세로 SVG 썸네일을 data URI로 생성합니다."""
    from image_fetcher import _thumb_theme, _wrap_title
    import html as _html

    c1, c2, accent, emoji = _thumb_theme(f"{title} {keyword}")
    lines = _wrap_title(title, max_chars=9, max_lines=5)
    text_els = "".join(
        f'<text x="540" y="{880 + i * 130}" font-size="96" font-weight="800" '
        f'fill="#ffffff" text-anchor="middle" font-family="sans-serif">'
        f'{_html.escape(line)}</text>'
        for i, line in enumerate(lines)
    )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1920" viewBox="0 0 1080 1920">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0%" stop-color="{c1}"/><stop offset="100%" stop-color="{c2}"/></linearGradient></defs>
<rect width="1080" height="1920" fill="url(#g)"/>
<circle cx="920" cy="240" r="220" fill="{accent}" opacity="0.18"/>
<circle cx="140" cy="1680" r="280" fill="{accent}" opacity="0.14"/>
<text x="540" y="560" font-size="180" text-anchor="middle">{emoji}</text>
{text_els}
<rect x="340" y="{900 + len(lines) * 130}" width="400" height="10" rx="5" fill="{accent}"/>
<text x="540" y="1800" font-size="44" fill="#ffffff" opacity="0.75" text-anchor="middle" font-family="sans-serif">#Shorts</text>
</svg>"""
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


# ──────────────────────────────────────────────────────────────────────────────
# 스크립트 생성
# ──────────────────────────────────────────────────────────────────────────────

def _repair_json(client, bad_json: str) -> dict | None:
    """손상된 JSON을 Claude에게 수정 요청합니다."""
    from config import claude_generate, CLAUDE_MODEL
    try:
        fixed = claude_generate(
            client, model=CLAUDE_MODEL, max_tokens=4000,
            system="JSON 전문가입니다. 손상된 JSON을 완전히 유효한 JSON으로 수정해 JSON만 출력하세요. 설명·마크다운 없이 JSON만.",
            messages=[{"role": "user", "content": f"손상된 JSON:\n{bad_json[:3000]}"}],
        ).strip()
        m = re.search(r"\{.*\}", fixed, re.DOTALL)
        if m:
            return json.loads(m.group(0))
    except Exception as e:
        logger.warning(f"JSON 수정 재시도 실패: {e}")
    return None


def generate_shorts_script(title: str, content_html: str, keyword: str = "",
                           blog_url: str = "") -> dict | None:
    """글 내용을 60초 쇼츠 스크립트로 변환합니다 (Claude, 한도 시 OpenAI 폴백)."""
    import anthropic
    from config import claude_generate, ANTHROPIC_API_KEY, CLAUDE_MODEL

    plain = re.sub(r"<[^>]+>", " ", content_html or "")
    plain = re.sub(r"\s+", " ", plain).strip()[:2500]
    if len(plain) < 200:
        logger.error("본문이 너무 짧아 스크립트 생성 불가")
        return None

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        raw = claude_generate(
            client, model=CLAUDE_MODEL, max_tokens=6000,
            system=(
                "당신은 조회수 잘 나오는 유튜브 쇼츠 대본 작가입니다. "
                "블로그 글을 60초 세로 영상 대본으로 변환하세요. 규칙:\n"
                "1. 첫 3초 훅이 승부 — 궁금증·공감·반전으로 시작 (인사말 금지)\n"
                "2. 말하듯 자연스러운 구어체, 한 문장은 짧게\n"
                "3. 글에 있는 사실만 사용 — 과장·창작 금지\n"
                "4. 전체 내레이션은 소리 내어 읽어 55~60초 분량 (한국어 기준 약 280~330자)\n"
                "5. JSON만 응답"
            ),
            messages=[{"role": "user", "content": (
                f"블로그 제목: {title}\n본문 요약:\n{plain}\n\n"
                'JSON 형식:\n{"hook": "0~3초 훅 멘트", '
                '"scenes": [{"time": "0-3초", "voice": "내레이션", "visual": "화면 지시 (자막·이미지·연출)"}], '
                '"cta": "마지막 구독·블로그 유도 멘트", '
                '"video_title": "쇼츠 제목 (40자 이내, 클릭 유도)", '
                '"caption": "업로드 설명글 (블로그 링크 자리는 {URL})", '
                '"hashtags": ["#태그1", ...최대 8개]}'
            )}],
        ).strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            logger.error(f"스크립트 JSON 파싱 실패: {raw[:200]}")
            return None
        try:
            script = json.loads(m.group(0))
        except json.JSONDecodeError as je:
            logger.warning(f"JSON 파싱 오류 ({je}) — 수정 재시도")
            script = _repair_json(client, m.group(0))
            if not script:
                logger.error("JSON 수정 재시도도 실패 — 스크립트 생성 불가")
                return None
        if blog_url:
            script["caption"] = (script.get("caption") or "").replace("{URL}", blog_url)
        return script
    except Exception as e:
        logger.error(f"쇼츠 스크립트 생성 실패: {e}")
        return None


def _load_scripts() -> list:
    try:
        with open(_SCRIPTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_scripts(scripts: list) -> None:
    os.makedirs(_DOCS_DATA, exist_ok=True)
    with open(_SCRIPTS_FILE, "w", encoding="utf-8") as f:
        json.dump(scripts[:_MAX_SCRIPTS], f, ensure_ascii=False, indent=2)


def _fetch_post_content(entry: dict) -> str:
    """발행 글 본문을 Blogger에서 가져옵니다 (초안 폴백 포함)."""
    try:
        from manage_post import _fetch_published_content
        ctx, content = _fetch_published_content(entry)
        if content:
            return content
    except Exception as e:
        logger.debug(f"Blogger 본문 조회 실패: {e}")
    # 폴백: 초안 파일
    try:
        from post_manager import load_draft
        draft = load_draft(entry.get("post_id", ""))
        if draft:
            return draft.get("content", "")
    except Exception:
        pass
    return ""


def create_for_post(entry: dict) -> dict | None:
    """레지스트리 엔트리 1건에 대해 쇼츠 스크립트+썸네일을 생성·저장합니다."""
    title = entry.get("title") or entry.get("keyword", "")
    post_id = entry.get("post_id", "")
    logger.info(f"🎬 쇼츠 스크립트 생성: '{title[:40]}'")

    content = _fetch_post_content(entry)
    if not content:
        logger.error("본문을 가져올 수 없습니다")
        return None

    script = generate_shorts_script(
        title, content, entry.get("keyword", ""), entry.get("blogUrl", ""))
    if not script:
        return None

    item = {
        "post_id": post_id,
        "title": title,
        "blog_url": entry.get("blogUrl", ""),
        "blog_id": entry.get("blogId", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "thumbnail": generate_shorts_thumbnail(script.get("video_title") or title,
                                               entry.get("keyword", "")),
        **script,
    }

    scripts = _load_scripts()
    scripts = [s for s in scripts if s.get("post_id") != post_id]  # 재생성 시 교체
    scripts.insert(0, item)
    _save_scripts(scripts)
    logger.info(f"✅ 저장 완료: '{item.get('video_title', title)[:40]}' "
                f"(장면 {len(item.get('scenes', []))}개)")
    return item


def main() -> int:
    parser = argparse.ArgumentParser(description="유튜브 쇼츠 스크립트 생성")
    parser.add_argument("--post-id", default="", dest="post_id", help="특정 발행 글 post_id")
    parser.add_argument("--latest", type=int, default=0,
                        help="스크립트 없는 최근 발행 글 N건 자동 생성")
    args = parser.parse_args()

    from post_manager import load_registry
    registry = load_registry()
    published = [p for p in registry if p.get("status") == "published" and p.get("blogUrl")]

    targets = []
    if args.post_id:
        entry = next((p for p in published if p.get("post_id") == args.post_id), None)
        if not entry:
            logger.error(f"발행 글을 찾을 수 없습니다: {args.post_id}")
            return 1
        targets = [entry]
    elif args.latest > 0:
        done_ids = {s.get("post_id") for s in _load_scripts()}
        published.sort(key=lambda p: p.get("publishedAt") or p.get("createdAt") or "", reverse=True)
        targets = [p for p in published if p.get("post_id") not in done_ids][:args.latest]
        if not targets:
            logger.info("스크립트가 없는 최근 발행 글이 없습니다")
            return 0
    else:
        parser.print_help()
        return 1

    ok = 0
    for entry in targets:
        if create_for_post(entry):
            ok += 1
    logger.info(f"완료: {ok}/{len(targets)}건 생성")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
