"""포스트 단건 관리 — 발행·보관·삭제·복원

Usage:
  python manage_post.py --action publish  --post-id <post_id>
  python manage_post.py --action archive  --post-id <post_id>  # → skipped
  python manage_post.py --action delete   --post-id <post_id>  # registry에서 제거
  python manage_post.py --action restore  --post-id <post_id>  # skipped → pending
"""

import argparse
import json
import logging
import os
import sys

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_BASE_DIR   = os.path.dirname(__file__)
DOCS_DATA   = os.path.join(_BASE_DIR, "..", "docs", "data")


def _load_registry():
    from post_manager import load_registry
    return load_registry()


def _save_and_export(registry):
    from post_manager import save_registry, export_for_dashboard
    save_registry(registry)
    export_for_dashboard(os.path.abspath(DOCS_DATA))


def action_archive(post_id: str) -> int:
    from post_manager import update_post_status, Status, load_registry
    registry = load_registry()
    entry = next((p for p in registry if p.get("post_id") == post_id), None)
    if not entry:
        logger.error(f"포스트를 찾을 수 없습니다: {post_id}")
        return 1
    current = entry.get("status", "")
    if current == Status.PUBLISHED:
        logger.error(f"게시 완료 포스트는 보관할 수 없습니다 (현재 상태: {current})")
        return 1
    update_post_status(post_id, Status.SKIPPED, error="수동 보관")
    _save_and_export(_load_registry())
    logger.info(f"✅ 보관 완료: {post_id}")
    return 0


def action_delete(post_id: str) -> int:
    from post_manager import load_registry, save_registry, export_for_dashboard, delete_draft
    registry = load_registry()
    before = len(registry)
    registry = [p for p in registry if p.get("post_id") != post_id]
    if len(registry) == before:
        logger.error(f"포스트를 찾을 수 없습니다: {post_id}")
        return 1
    save_registry(registry)
    export_for_dashboard(os.path.abspath(DOCS_DATA))
    delete_draft(post_id)
    logger.info(f"✅ 삭제 완료: {post_id}")
    return 0


def action_restore(post_id: str) -> int:
    from post_manager import update_post_status, Status, load_registry
    registry = load_registry()
    entry = next((p for p in registry if p.get("post_id") == post_id), None)
    if not entry:
        logger.error(f"포스트를 찾을 수 없습니다: {post_id}")
        return 1
    update_post_status(post_id, Status.PENDING, error=None)
    # errorMessage 초기화
    reg2 = _load_registry()
    for p in reg2:
        if p.get("post_id") == post_id:
            p["errorMessage"] = None
            break
    _save_and_export(reg2)
    logger.info(f"✅ 복원 완료 (→ pending): {post_id}")
    return 0


def action_publish(post_id: str) -> int:
    from post_manager import (
        load_draft, update_post_status, Status, load_registry, export_for_dashboard
    )
    from blogger_uploader import upload_post

    registry = _load_registry()
    entry = next((p for p in registry if p.get("post_id") == post_id), None)
    if not entry:
        logger.error(f"포스트를 찾을 수 없습니다: {post_id}")
        return 1

    current = entry.get("status", "")
    if current == Status.PUBLISHED:
        logger.warning(f"이미 게시된 포스트입니다: {entry.get('blogUrl', '')}")
        return 0

    # 초안 파일 로드 시도
    post_data = load_draft(post_id)
    if not post_data:
        # pending_posts.json에서 검색
        pending_path = os.path.join(DOCS_DATA, "pending_posts.json")
        if os.path.exists(pending_path):
            try:
                with open(pending_path, encoding="utf-8") as f:
                    pending = json.load(f)
                for item in pending:
                    if item.get("id") == post_id or item.get("post_id") == post_id:
                        post_data = item
                        break
            except Exception:
                pass

    if not post_data:
        logger.error(f"포스트 콘텐츠를 찾을 수 없습니다 (초안/pending 없음): {post_id}")
        logger.error("초안 파일 위치: blog-automation/logs/post_drafts/{post_id}.json")
        return 1

    # 블로그 config 탐색 (BLOGS_CONFIG 환경변수에서)
    blog_config = None
    blogs_config_raw = os.getenv("BLOGS_CONFIG", "")
    if blogs_config_raw:
        try:
            blogs_list = json.loads(blogs_config_raw)
            blog_id = entry.get("blogId", "")
            if blog_id and blog_id != "default":
                blog_config = next((b for b in blogs_list if b.get("id") == blog_id), None)
            if not blog_config and blogs_list:
                blog_config = blogs_list[0]
        except Exception:
            pass

    logger.info(f"📤 발행 시도: {entry.get('keyword', '')} — {entry.get('title', '')}")
    update_post_status(post_id, Status.RETRY_QUEUED)

    result = upload_post(post_data, blog_config)
    if result:
        url = result.get("url", "")
        update_post_status(post_id, Status.PUBLISHED, blog_url=url)
        from post_manager import delete_draft
        delete_draft(post_id)
        export_for_dashboard(os.path.abspath(DOCS_DATA))
        logger.info(f"✅ 발행 완료: {url}")
        return 0
    else:
        update_post_status(post_id, Status.FAILED, error="수동 발행 실패")
        export_for_dashboard(os.path.abspath(DOCS_DATA))
        logger.error("❌ 발행 실패")
        return 1


def _insert_thumbnail_html(content: str, img_html: str) -> str:
    """썸네일 figure를 본문 첫 </p> 바로 뒤에 삽입합니다 (없으면 맨 앞)."""
    import re
    m = re.search(r'</p>', content, re.IGNORECASE)
    if m:
        return content[:m.end()] + img_html + content[m.end():]
    return img_html + content


def action_insert_thumbnail(post_id: str, thumb_title: str = "", thumb_theme: str = "") -> int:
    """포스트에 제목 기반 썸네일을 삽입합니다.
    - published: Blogger API로 게시글 본문을 가져와 삽입 후 업데이트 (자동 삽입)
    - pending/draft: 초안 content에 삽입 저장 → 발행 시 반영
    """
    from image_fetcher import generate_title_thumbnail, _make_img_html

    registry = _load_registry()
    entry = next((p for p in registry if p.get("post_id") == post_id), None)
    if not entry:
        logger.error(f"포스트를 찾을 수 없습니다: {post_id}")
        return 1

    title = thumb_title or entry.get("title") or entry.get("keyword", "")
    thumb = generate_title_thumbnail(title, entry.get("keyword", ""), theme=thumb_theme)
    if not thumb:
        logger.error("썸네일 생성 실패 (제목 없음)")
        return 1
    alt = thumb.get("alt_text", title)
    img_html = _make_img_html(thumb, alt, "")
    _DUP_MARKERS = ("data:image/svg+xml", "generated_thumbnail")

    status = entry.get("status", "")
    blog_url = entry.get("blogUrl", "")

    # ── 게시된 포스트: Blogger에서 본문 가져와 삽입 후 업데이트 ──
    if status == "published" and blog_url:
        import requests as _rq
        from blogger_uploader import (
            _get_access_token, get_post_id_by_url, BLOGGER_API_BASE, BLOGGER_BLOG_ID,
        )

        # 블로그 config 탐색
        blog_config = None
        raw = os.getenv("BLOGS_CONFIG", "")
        if raw:
            try:
                blogs = json.loads(raw)
                blog_config = next((b for b in blogs if b.get("id") == entry.get("blogId")), None)
            except Exception:
                pass

        bp_id = get_post_id_by_url(blog_url, blog_config)
        if not bp_id:
            logger.error(f"Blogger 포스트 ID 조회 실패: {blog_url}")
            return 1

        cfg = blog_config or {}
        blogger_blog_id = cfg.get("blog_id") or BLOGGER_BLOG_ID
        token = _get_access_token(blog_config)
        if not token:
            logger.error("Blogger 액세스 토큰 없음")
            return 1

        r = _rq.get(
            f"{BLOGGER_API_BASE}/blogs/{blogger_blog_id}/posts/{bp_id}",
            headers={"Authorization": f"Bearer {token}"}, timeout=20,
        )
        if r.status_code != 200:
            logger.error(f"게시글 조회 실패 [{r.status_code}]: {r.text[:200]}")
            return 1
        content = r.json().get("content", "")

        if any(mk in content for mk in _DUP_MARKERS):
            logger.warning("이미 생성 썸네일이 삽입된 포스트입니다 — 중복 삽입 건너뜀")
            return 0

        new_content = _insert_thumbnail_html(content, img_html)
        pr = _rq.patch(
            f"{BLOGGER_API_BASE}/blogs/{blogger_blog_id}/posts/{bp_id}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"content": new_content}, timeout=30,
        )
        if pr.status_code == 200:
            logger.info(f"✅ 게시글에 썸네일 삽입 완료: {blog_url}")
            return 0
        logger.error(f"게시글 업데이트 실패 [{pr.status_code}]: {pr.text[:300]}")
        return 1

    # ── 미발행 포스트: 초안/pending content에 삽입 ──
    from post_manager import load_draft, save_draft
    post_data = load_draft(post_id)
    source = "draft"
    if not post_data:
        pending_path = os.path.join(DOCS_DATA, "pending_posts.json")
        if os.path.exists(pending_path):
            try:
                with open(pending_path, encoding="utf-8") as f:
                    pending = json.load(f)
                for item in pending:
                    if item.get("id") == post_id or item.get("post_id") == post_id:
                        post_data, source = item, "pending"
                        break
            except Exception:
                pass
    if not post_data:
        logger.error(f"포스트 콘텐츠를 찾을 수 없습니다 (초안/pending 없음): {post_id}")
        return 1

    content = post_data.get("content", "")
    if any(mk in content for mk in _DUP_MARKERS):
        logger.warning("이미 생성 썸네일이 삽입된 초안입니다 — 중복 삽입 건너뜀")
        return 0
    post_data["content"] = _insert_thumbnail_html(content, img_html)
    post_data["images_inserted"] = post_data.get("images_inserted", 0) + 1

    if source == "draft":
        save_draft(post_id, post_data)
    else:
        with open(pending_path, "w", encoding="utf-8") as f:
            json.dump(pending, f, ensure_ascii=False, indent=2)
    logger.info(f"✅ 초안({source})에 썸네일 삽입 완료 — 발행 시 반영됩니다: {post_id}")
    return 0


def _get_blogger_ctx(entry: dict):
    """레지스트리 엔트리로 Blogger API 컨텍스트를 구성합니다.
    Returns: (api_base, blogger_blog_id, blogger_post_id, token) 또는 None
    """
    from blogger_uploader import (
        _get_access_token, get_post_id_by_url, BLOGGER_API_BASE, BLOGGER_BLOG_ID,
    )
    blog_url = entry.get("blogUrl", "")
    blog_config = None
    raw = os.getenv("BLOGS_CONFIG", "")
    if raw:
        try:
            blogs = json.loads(raw)
            blog_config = next((b for b in blogs if b.get("id") == entry.get("blogId")), None)
        except Exception:
            pass
    bp_id = get_post_id_by_url(blog_url, blog_config)
    if not bp_id:
        logger.error(f"Blogger 포스트 ID 조회 실패: {blog_url}")
        return None
    cfg = blog_config or {}
    blogger_blog_id = cfg.get("blog_id") or BLOGGER_BLOG_ID
    token = _get_access_token(blog_config)
    if not token:
        logger.error("Blogger 액세스 토큰 없음")
        return None
    return BLOGGER_API_BASE, blogger_blog_id, bp_id, token


def action_replace_image(
    post_id: str,
    image_index: int = 1,
    image_query: str = "",
    thumb_title: str = "",
    thumb_theme: str = "",
) -> int:
    """발행된 글의 N번째 이미지를 교체합니다.
    - image_query 지정 → 해당 검색어로 새 이미지 검색 (Pixabay→네이버→DDG→Wikimedia)
    - image_query 없음 → 제목 기반 생성 썸네일로 교체
    이미지의 src/alt/title 속성만 바꾸므로 기존 레이아웃(figure·캡션 스타일)은 유지됩니다.
    """
    import re
    import requests as _rq

    registry = _load_registry()
    entry = next((p for p in registry if p.get("post_id") == post_id), None)
    if not entry:
        logger.error(f"포스트를 찾을 수 없습니다: {post_id}")
        return 1
    if entry.get("status") != "published" or not entry.get("blogUrl"):
        logger.error(f"발행된 포스트만 이미지 교체가 가능합니다 (현재 상태: {entry.get('status')})")
        return 1

    # ── 새 이미지 결정 ──
    if image_query.strip():
        from image_fetcher import _fetch_best_image
        new_img = _fetch_best_image(
            image_query.strip(),
            naver_client_id=os.getenv("NAVER_CLIENT_ID", ""),
            naver_client_secret=os.getenv("NAVER_CLIENT_SECRET", ""),
            n_candidates=6,
            pixabay_api_key=os.getenv("PIXABAY_API_KEY", ""),
        )
        if not new_img:
            logger.error(f"교체용 이미지 검색 실패: '{image_query}'")
            return 1
        new_alt = image_query.strip()[:50]
        logger.info(f"교체 이미지 검색 성공: '{new_img.get('title','')[:40]}'")
    else:
        from image_fetcher import generate_title_thumbnail
        title = thumb_title or entry.get("title") or entry.get("keyword", "")
        new_img = generate_title_thumbnail(title, entry.get("keyword", ""), theme=thumb_theme)
        if not new_img:
            logger.error("썸네일 생성 실패 (제목 없음)")
            return 1
        new_alt = new_img.get("alt_text", title)

    # ── 게시글 본문 조회 ──
    ctx = _get_blogger_ctx(entry)
    if not ctx:
        return 1
    api_base, blogger_blog_id, bp_id, token = ctx
    r = _rq.get(
        f"{api_base}/blogs/{blogger_blog_id}/posts/{bp_id}",
        headers={"Authorization": f"Bearer {token}"}, timeout=20,
    )
    if r.status_code != 200:
        logger.error(f"게시글 조회 실패 [{r.status_code}]: {r.text[:200]}")
        return 1
    content = r.json().get("content", "")

    # ── N번째 <img> 찾아 src/alt/title 교체 ──
    img_tags = list(re.finditer(r'<img\b[^>]*>', content, re.IGNORECASE))
    if not img_tags:
        logger.error("본문에 이미지가 없습니다")
        return 1
    if not (1 <= image_index <= len(img_tags)):
        logger.error(f"이미지 번호 범위 초과: {image_index} (본문 이미지 {len(img_tags)}개)")
        return 1

    target = img_tags[image_index - 1]
    tag = target.group(0)
    old_src_m = re.search(r'src="([^"]*)"', tag)
    old_src = old_src_m.group(1) if old_src_m else ""
    if old_src == new_img["url"]:
        logger.warning("기존 이미지와 동일한 URL — 교체 건너뜀")
        return 0

    import html as _h
    alt_safe = _h.escape(new_alt, quote=True)
    new_tag = tag
    new_tag = re.sub(r'src="[^"]*"', f'src="{new_img["url"]}"', new_tag)
    for attr in ("alt", "title"):
        if re.search(rf'{attr}="[^"]*"', new_tag):
            new_tag = re.sub(rf'{attr}="[^"]*"', f'{attr}="{alt_safe}"', new_tag)
    new_content = content[:target.start()] + new_tag + content[target.end():]

    # figure 캡션도 새 alt로 갱신 (해당 이미지의 figure 안에 figcaption이 있을 때)
    fig_m = re.search(
        re.escape(new_tag) + r'\s*<figcaption([^>]*)>(.*?)</figcaption>',
        new_content, re.IGNORECASE | re.DOTALL,
    )
    if fig_m:
        new_content = (
            new_content[:fig_m.start()] + new_tag
            + f'\n  <figcaption{fig_m.group(1)}>{alt_safe}</figcaption>'
            + new_content[fig_m.end():]
        )

    pr = _rq.patch(
        f"{api_base}/blogs/{blogger_blog_id}/posts/{bp_id}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"content": new_content}, timeout=30,
    )
    if pr.status_code == 200:
        src_type = "검색 이미지" if image_query.strip() else "생성 썸네일"
        logger.info(
            f"✅ 이미지 교체 완료 ({image_index}/{len(img_tags)}번째 → {src_type}): "
            f"{entry.get('blogUrl','')}"
        )
        logger.info(f"   이전: {old_src[:80]}")
        logger.info(f"   이후: {new_img['url'][:80]}")
        return 0
    logger.error(f"게시글 업데이트 실패 [{pr.status_code}]: {pr.text[:300]}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="포스트 단건 관리")
    parser.add_argument("--action", required=True,
                        choices=["publish", "archive", "delete", "restore",
                                 "insert_thumbnail", "replace_image"])
    parser.add_argument("--post-id", required=True, dest="post_id")
    parser.add_argument("--thumb-title", default="", dest="thumb_title",
                        help="썸네일 제목 (기본: 포스트 제목)")
    parser.add_argument("--thumb-theme", default="", dest="thumb_theme",
                        help="테마 (travel/drama/kpop/finance/sports/health/default, 기본: 자동 감지)")
    parser.add_argument("--image-index", type=int, default=1, dest="image_index",
                        help="교체할 이미지 번호 (1=첫 번째, replace_image 전용)")
    parser.add_argument("--image-query", default="", dest="image_query",
                        help="교체용 이미지 검색어 (비워두면 생성 썸네일로 교체, replace_image 전용)")
    args = parser.parse_args()

    if args.action == "insert_thumbnail":
        return action_insert_thumbnail(args.post_id, args.thumb_title, args.thumb_theme)
    if args.action == "replace_image":
        return action_replace_image(args.post_id, args.image_index, args.image_query,
                                    args.thumb_title, args.thumb_theme)

    dispatch = {
        "publish": action_publish,
        "archive": action_archive,
        "delete":  action_delete,
        "restore": action_restore,
    }
    return dispatch[args.action](args.post_id)


if __name__ == "__main__":
    sys.exit(main())
