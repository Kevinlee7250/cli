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
        # 검토 대기 목록에서 검색 (저장소가 본문을 합쳐 돌려줍니다)
        try:
            import pending_store
            for item in pending_store.load():
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
    if result == "DUPLICATE":
        update_post_status(post_id, Status.SKIPPED, error="중복 제목 — 업로드 건너뜀")
        export_for_dashboard(os.path.abspath(DOCS_DATA))
        logger.warning("⏭ 중복 주제 — 업로드 건너뜀 (유사 제목 이미 발행됨)")
        return 0
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
        try:
            import pending_store
            pending = pending_store.load()
            for item in pending:
                if item.get("id") == post_id or item.get("post_id") == post_id:
                    post_data, source = item, "pending"
                    break
        except Exception:
            pending = []
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
        import pending_store
        pending_store.save(pending)
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
        from image_fetcher import _fetch_best_image, adopt_image
        new_img = adopt_image(_fetch_best_image(
            image_query.strip(),
            naver_client_id=os.getenv("NAVER_CLIENT_ID", ""),
            naver_client_secret=os.getenv("NAVER_CLIENT_SECRET", ""),
            n_candidates=6,
            pixabay_api_key=os.getenv("PIXABAY_API_KEY", ""),
        ))
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
        from image_fetcher import mark_images_used
        mark_images_used([new_img.get("url", "")])
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


def _fetch_published_content(entry: dict):
    """발행 글 본문을 조회합니다. Returns: (ctx, content) 또는 (None, None)."""
    import requests as _rq
    ctx = _get_blogger_ctx(entry)
    if not ctx:
        return None, None
    api_base, blogger_blog_id, bp_id, token = ctx
    r = _rq.get(
        f"{api_base}/blogs/{blogger_blog_id}/posts/{bp_id}",
        headers={"Authorization": f"Bearer {token}"}, timeout=20,
    )
    if r.status_code != 200:
        logger.error(f"게시글 조회 실패 [{r.status_code}]: {r.text[:200]}")
        return None, None
    return ctx, r.json().get("content", "")


def _patch_published_content(ctx, new_content: str) -> bool:
    """발행 글 본문을 갱신합니다."""
    import requests as _rq
    api_base, blogger_blog_id, bp_id, token = ctx
    pr = _rq.patch(
        f"{api_base}/blogs/{blogger_blog_id}/posts/{bp_id}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"content": new_content}, timeout=30,
    )
    if pr.status_code == 200:
        return True
    logger.error(f"게시글 업데이트 실패 [{pr.status_code}]: {pr.text[:300]}")
    return False


def _get_published_entry(post_id: str):
    """레지스트리에서 발행 완료 엔트리를 찾습니다."""
    registry = _load_registry()
    entry = next((p for p in registry if p.get("post_id") == post_id), None)
    if not entry:
        logger.error(f"포스트를 찾을 수 없습니다: {post_id}")
        return None
    if entry.get("status") != "published" or not entry.get("blogUrl"):
        logger.error(f"발행된 포스트만 가능합니다 (현재 상태: {entry.get('status')})")
        return None
    return entry


def action_improve(post_id: str, improve_request: str = "") -> int:
    """발행 글을 AI로 수정·보완합니다 (Blogger 즉시 반영).

    improve_request 미지정 시 기본 보완: 얇은 섹션 분량 보강, 최신성 문구 정비,
    가독성 개선. 이미지·figure·광고·면책 등 기존 HTML 블록은 그대로 유지합니다.
    Claude 한도 도달 시 config.claude_generate의 OpenAI 폴백이 동작합니다.
    """
    entry = _get_published_entry(post_id)
    if not entry:
        return 1
    ctx, content = _fetch_published_content(entry)
    if not ctx or not content:
        return 1

    import re as _re
    img_count_before = len(_re.findall(r'<img\b', content, _re.IGNORECASE))

    request_text = improve_request.strip() or (
        "내용이 얇은 섹션의 분량을 보강하고, 오래된 표현·시점을 현재 기준으로 정비하고, "
        "문단 가독성을 개선하세요. 전체 구조와 어조는 유지하세요."
    )
    system = (
        "당신은 발행된 블로그 글을 보완하는 편집자입니다. 규칙:\n"
        "1. 입력으로 받은 HTML 본문을 보완해 완성된 HTML 전체를 반환 (설명·마크다운 없이 HTML만)\n"
        "2. <img>·<figure>·<script>·광고·면책·출처·FAQ 블록은 위치·내용 그대로 유지\n"
        "3. 인라인 스타일과 HTML 구조 형식 유지, H2 소제목 골격 유지\n"
        "4. 사실이 불확실한 수치·날짜는 새로 만들지 말 것 (기존 내용 재구성 위주)\n"
        "5. 분량은 기존 대비 같거나 늘어나야 함 (줄이지 말 것)"
    )
    import anthropic
    from config import claude_generate, ANTHROPIC_API_KEY, CLAUDE_MODEL
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    new_content = claude_generate(
        client, model=CLAUDE_MODEL, max_tokens=24000, temperature=0.7,
        system=system,
        messages=[{"role": "user", "content":
                   f"보완 요청: {request_text}\n\n제목: {entry.get('title','')}\n\n본문 HTML:\n{content}"}],
    )
    new_content = new_content.strip()
    # 코드펜스로 감싸 반환된 경우 벗겨냄
    m = _re.match(r"^```(?:html)?\s*(.*?)\s*```$", new_content, _re.DOTALL)
    if m:
        new_content = m.group(1)

    if not new_content or len(new_content) < len(content) * 0.7:
        logger.error(f"AI 보완 결과가 비었거나 너무 짧음 ({len(new_content)}자 vs 기존 {len(content)}자) — 반영 취소")
        return 1
    img_count_after = len(_re.findall(r'<img\b', new_content, _re.IGNORECASE))
    if img_count_after < img_count_before:
        logger.error(f"AI 보완 결과에서 이미지 손실 감지 ({img_count_before}→{img_count_after}) — 반영 취소")
        return 1

    if not _patch_published_content(ctx, new_content):
        return 1
    logger.info(f"✅ AI 보완 완료 ({len(content)}자 → {len(new_content)}자): {entry.get('blogUrl','')}")
    return 0


def action_add_image(post_id: str, image_query: str = "", image_index: int = 0,
                     thumb_title: str = "", thumb_theme: str = "") -> int:
    """발행 글에 이미지를 추가합니다 (Blogger 즉시 반영).

    - image_query 지정 → 검색 이미지 (Pixabay→네이버→DDG→Wikimedia)
    - image_query 없음 → 제목 기반 생성 썸네일
    - image_index: N번째 H2 앞에 삽입 (0=도입부 첫 문단 뒤)
    """
    import re as _re
    entry = _get_published_entry(post_id)
    if not entry:
        return 1

    if image_query.strip():
        from image_fetcher import _fetch_best_image, adopt_image
        new_img = adopt_image(_fetch_best_image(
            image_query.strip(),
            naver_client_id=os.getenv("NAVER_CLIENT_ID", ""),
            naver_client_secret=os.getenv("NAVER_CLIENT_SECRET", ""),
            n_candidates=6,
            pixabay_api_key=os.getenv("PIXABAY_API_KEY", ""),
        ))
        if not new_img:
            logger.error(f"이미지 검색 실패: '{image_query}'")
            return 1
        alt = image_query.strip()[:50]
    else:
        from image_fetcher import generate_title_thumbnail
        title = thumb_title or entry.get("title") or entry.get("keyword", "")
        new_img = generate_title_thumbnail(title, entry.get("keyword", ""), theme=thumb_theme)
        if not new_img:
            logger.error("썸네일 생성 실패 (제목 없음)")
            return 1
        alt = new_img.get("alt_text", title)

    ctx, content = _fetch_published_content(entry)
    if not ctx or not content:
        return 1

    from image_fetcher import _make_img_html, _safe_caption
    img_html = _make_img_html(new_img, alt, _safe_caption(new_img, alt))

    if image_index >= 1:
        h2s = [mm.start() for mm in _re.finditer(r'<h2', content, _re.IGNORECASE)]
        if image_index > len(h2s):
            logger.error(f"H2 번호 범위 초과: {image_index} (본문 H2 {len(h2s)}개)")
            return 1
        pos = h2s[image_index - 1]
        new_content = content[:pos] + img_html + content[pos:]
    else:
        first_p = _re.search(r'</p>', content, _re.IGNORECASE)
        pos = first_p.end() if first_p else 0
        new_content = content[:pos] + img_html + content[pos:]

    if not _patch_published_content(ctx, new_content):
        return 1
    from image_fetcher import mark_images_used
    mark_images_used([new_img.get("url", "")])
    where = f"{image_index}번째 H2 앞" if image_index >= 1 else "도입부 뒤"
    logger.info(f"✅ 이미지 추가 완료 ({where}): {entry.get('blogUrl','')}")
    return 0


def action_remove_image(post_id: str, image_index: int = 1) -> int:
    """발행 글의 N번째 이미지를 제거합니다 (감싼 figure 블록째, Blogger 즉시 반영)."""
    import re as _re
    entry = _get_published_entry(post_id)
    if not entry:
        return 1
    ctx, content = _fetch_published_content(entry)
    if not ctx or not content:
        return 1

    img_tags = list(_re.finditer(r'<img\b[^>]*>', content, _re.IGNORECASE))
    if not img_tags:
        logger.error("본문에 이미지가 없습니다")
        return 1
    if not (1 <= image_index <= len(img_tags)):
        logger.error(f"이미지 번호 범위 초과: {image_index} (본문 이미지 {len(img_tags)}개)")
        return 1

    target = img_tags[image_index - 1]
    # 이미지를 감싼 <figure>...</figure> 블록을 찾으면 통째로 제거
    remove_start, remove_end = target.start(), target.end()
    for fm in _re.finditer(r'<figure\b[^>]*>.*?</figure>', content, _re.IGNORECASE | _re.DOTALL):
        if fm.start() <= target.start() and target.end() <= fm.end():
            remove_start, remove_end = fm.start(), fm.end()
            break

    new_content = content[:remove_start] + content[remove_end:]
    if not _patch_published_content(ctx, new_content):
        return 1
    logger.info(f"✅ 이미지 제거 완료 ({image_index}/{len(img_tags)}번째): {entry.get('blogUrl','')}")
    return 0


def _plan_images_with_ai(title: str, plain_text: str, h2_titles: list[str],
                         sections_without_img: list[int], max_images: int) -> list[dict]:
    """글을 읽고 어떤 섹션에 어떤 이미지를 넣을지 AI가 계획합니다.

    Returns: [{"h2_index": int, "query": str}] — h2_index는 1-based (0=도입부 뒤).
    실패 시 빈 리스트 (호출부에서 휴리스틱 폴백).
    """
    import anthropic
    from config import claude_generate, ANTHROPIC_API_KEY, CLAUDE_MODEL

    h2_list = "\n".join(
        f"  {i+1}. {t}" + ("" if (i + 1) in sections_without_img else " (이미 이미지 있음)")
        for i, t in enumerate(h2_titles)
    )
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        raw = claude_generate(
            client, model=CLAUDE_MODEL, max_tokens=2000,
            system=(
                "당신은 블로그 이미지 편집자입니다. 글을 읽고 시각 자료가 가장 도움이 될 "
                "섹션을 고르고, 이미지 검색에 적합한 짧은 검색어(핵심 명사 2~3개)를 제안하세요. "
                "'이미 이미지 있음' 섹션은 제외하세요. JSON만 응답하세요."
            ),
            messages=[{"role": "user", "content": (
                f"제목: {title}\n\nH2 섹션 목록:\n{h2_list}\n\n"
                f"본문 요약:\n{plain_text[:2500]}\n\n"
                f"최대 {max_images}개 계획. JSON 형식:\n"
                '{"images": [{"h2_index": 섹션번호(0=도입부), "query": "검색어"}]}'
            )}],
        ).strip()
        m = __import__("re").search(r"\{.*\}", raw, __import__("re").DOTALL)
        if not m:
            return []
        plan = json.loads(m.group(0)).get("images", [])
        return [p for p in plan
                if isinstance(p, dict) and p.get("query", "").strip()][:max_images]
    except Exception as e:
        logger.warning(f"AI 이미지 계획 실패 — 휴리스틱 폴백 사용: {e}")
        return []


def action_auto_images(post_id: str, max_images: int = 2) -> int:
    """발행 글을 분석해 이미지를 자동 검색·생성·첨부합니다 (Blogger 즉시 반영).

    1) 본문의 H2 섹션 중 이미지가 없는 섹션 파악
    2) AI가 글을 읽고 섹션별 이미지 검색어 계획 (실패 시 섹션 제목 휴리스틱)
    3) 검색(Pixabay→네이버→DDG→Wikimedia) → 실패 시 제목 기반 생성 썸네일
    4) 해당 섹션 앞에 삽입 (이미 이미지가 있는 섹션은 건너뜀)
    """
    import re as _re
    from image_fetcher import (
        _fetch_best_image, _make_img_html, _safe_caption, adopt_image,
        _simplify_query, generate_fallback_image,
    )

    entry = _get_published_entry(post_id)
    if not entry:
        return 1
    ctx, content = _fetch_published_content(entry)
    if not ctx or not content:
        return 1

    title = entry.get("title") or entry.get("keyword", "")

    # ── 섹션 구조 분석 ──
    h2_matches = list(_re.finditer(r'<h2[^>]*>(.*?)</h2>', content, _re.IGNORECASE | _re.DOTALL))
    h2_titles = [_re.sub(r'<[^>]+>', '', m.group(1)).strip()[:60] for m in h2_matches]

    def _section_span(i: int) -> tuple[int, int]:
        start = h2_matches[i].start()
        end = h2_matches[i + 1].start() if i + 1 < len(h2_matches) else len(content)
        return start, end

    intro_end = h2_matches[0].start() if h2_matches else len(content)
    intro_has_img = '<img' in content[:intro_end].lower()
    sections_without_img = [
        i + 1 for i in range(len(h2_matches))
        if '<img' not in content[slice(*_section_span(i))].lower()
    ]
    total_imgs = len(_re.findall(r'<img\b', content, _re.IGNORECASE))
    logger.info(
        f"본문 분석: H2 {len(h2_matches)}개, 이미지 {total_imgs}개, "
        f"이미지 없는 섹션 {len(sections_without_img)}개, 도입부 이미지 {'있음' if intro_has_img else '없음'}"
    )
    if not sections_without_img and intro_has_img:
        logger.info("모든 섹션에 이미지가 이미 있습니다 — 추가 없이 종료")
        return 0

    # ── AI 계획 (실패 시 휴리스틱: 이미지 없는 섹션 제목에서 검색어 추출) ──
    plain = _re.sub(r'\s+', ' ', _re.sub(r'<[^>]+>', ' ', content)).strip()
    plan = _plan_images_with_ai(title, plain, h2_titles, sections_without_img, max_images)
    if not plan:
        plan = []
        if not intro_has_img:
            plan.append({"h2_index": 0, "query": _simplify_query(title, 2) or title})
        for idx in sections_without_img:
            q = _simplify_query(f"{title} {h2_titles[idx - 1]}", 3) or h2_titles[idx - 1]
            plan.append({"h2_index": idx, "query": q})
        plan = plan[:max_images]
        logger.info(f"휴리스틱 계획 사용: {[(p['h2_index'], p['query']) for p in plan]}")
    else:
        logger.info(f"AI 계획: {[(p.get('h2_index'), p.get('query')) for p in plan]}")

    # ── 계획 실행: 검색 → 폴백 썸네일 → 삽입 ──
    inserted = 0
    inserted_urls: list[str] = []
    for item in plan:
        if inserted >= max_images:
            break
        try:
            h2_index = int(item.get("h2_index", 0))
        except (TypeError, ValueError):
            h2_index = 0
        query = str(item.get("query", "")).strip()
        if not query:
            continue
        if h2_index < 0 or h2_index > len(h2_matches):
            h2_index = 0

        img = adopt_image(_fetch_best_image(
            query,
            naver_client_id=os.getenv("NAVER_CLIENT_ID", ""),
            naver_client_secret=os.getenv("NAVER_CLIENT_SECRET", ""),
            n_candidates=6,
            pixabay_api_key=os.getenv("PIXABAY_API_KEY", ""),
        ))
        if not img:
            img = generate_fallback_image(query if len(query) >= 6 else title,
                                          entry.get("keyword", ""))
            if not img:
                logger.warning(f"이미지 확보 실패 (검색·생성 모두): '{query}' — 건너뜀")
                continue
            logger.info(f"검색 실패 → 생성 썸네일 사용: '{query}'")

        alt = query[:50]
        img_html = _make_img_html(img, alt, _safe_caption(img, alt))

        # 삽입 직전에 현재 content 기준으로 대상 위치 재계산 (누적 삽입 반영)
        cur_h2 = list(_re.finditer(r'<h2', content, _re.IGNORECASE))
        if h2_index >= 1 and h2_index <= len(cur_h2):
            span_start = cur_h2[h2_index - 1].start()
            span_end = cur_h2[h2_index].start() if h2_index < len(cur_h2) else len(content)
            if '<img' in content[span_start:span_end].lower():
                logger.info(f"{h2_index}번째 섹션에 이미 이미지 있음 — 건너뜀")
                continue
            pos = span_start
        else:
            head = content[:cur_h2[0].start()] if cur_h2 else content
            if '<img' in head.lower():
                logger.info("도입부에 이미 이미지 있음 — 건너뜀")
                continue
            fp = _re.search(r'</p>', content, _re.IGNORECASE)
            pos = fp.end() if fp else 0

        content = content[:pos] + img_html + content[pos:]
        inserted += 1
        inserted_urls.append(img.get("url", ""))
        where = f"{h2_index}번째 H2 앞" if h2_index >= 1 else "도입부 뒤"
        logger.info(f"🖼 이미지 삽입 ({where}): '{query}' → {img.get('title','')[:40]}")

    if not inserted:
        logger.warning("삽입된 이미지가 없습니다 — 변경 없이 종료")
        return 0
    if not _patch_published_content(ctx, content):
        return 1
    from image_fetcher import mark_images_used
    mark_images_used(inserted_urls)
    logger.info(f"✅ 자동 이미지 첨부 완료: {inserted}개 — {entry.get('blogUrl','')}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="포스트 단건 관리")
    parser.add_argument("--action", required=True,
                        choices=["publish", "archive", "delete", "restore",
                                 "insert_thumbnail", "replace_image",
                                 "improve", "add_image", "remove_image", "auto_images"])
    parser.add_argument("--post-id", required=True, dest="post_id")
    parser.add_argument("--thumb-title", default="", dest="thumb_title",
                        help="썸네일 제목 (기본: 포스트 제목)")
    parser.add_argument("--thumb-theme", default="", dest="thumb_theme",
                        help="테마 (travel/drama/kpop/finance/sports/health/default, 기본: 자동 감지)")
    parser.add_argument("--image-index", type=int, default=1, dest="image_index",
                        help="교체할 이미지 번호 (1=첫 번째, replace_image 전용)")
    parser.add_argument("--image-query", default="", dest="image_query",
                        help="교체용 이미지 검색어 (비워두면 생성 썸네일로 교체, replace_image 전용)")
    parser.add_argument("--improve-request", default="", dest="improve_request",
                        help="AI 보완 요청 내용 (improve 전용, 비워두면 기본 보완)")
    parser.add_argument("--max-images", type=int, default=2, dest="max_images",
                        help="자동 첨부할 최대 이미지 수 (auto_images 전용, 1~4)")
    args = parser.parse_args()

    if args.action == "insert_thumbnail":
        return action_insert_thumbnail(args.post_id, args.thumb_title, args.thumb_theme)
    if args.action == "replace_image":
        return action_replace_image(args.post_id, args.image_index, args.image_query,
                                    args.thumb_title, args.thumb_theme)
    if args.action == "improve":
        return action_improve(args.post_id, args.improve_request)
    if args.action == "add_image":
        return action_add_image(args.post_id, args.image_query, args.image_index,
                                args.thumb_title, args.thumb_theme)
    if args.action == "remove_image":
        return action_remove_image(args.post_id, args.image_index)
    if args.action == "auto_images":
        return action_auto_images(args.post_id, max(1, min(args.max_images, 4)))

    dispatch = {
        "publish": action_publish,
        "archive": action_archive,
        "delete":  action_delete,
        "restore": action_restore,
    }
    return dispatch[args.action](args.post_id)


if __name__ == "__main__":
    sys.exit(main())
