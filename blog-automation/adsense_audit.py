"""AdSense 승인 대비 발행 글 일괄 감사·보완

블로그의 발행 글 전체를 Blogger API로 검사하고, 안전하게 자동 보완
가능한 항목은 즉시 수정합니다. 본문 텍스트는 재작성하지 않습니다.

검사 항목 (AdSense '가치 없는 콘텐츠' 정책 기준):
  ① 글자 수 ≥ 2,500자                       → 미달 시 리포트
  ② 이미지 ≥ 1개                            → 없으면 제목 썸네일 자동 삽입 [자동보완]
  ③ 모든 이미지 alt 텍스트                   → 없으면 제목 기반 alt 채움 [자동보완]
  ④ 목차 정확히 1개                          → 중복 시 제거 [자동보완]
  ⑤ YMYL(금융·건강·법률) 글 면책 문구        → 없으면 하단 주의 박스 삽입 [자동보완]
  ⑥ FAQ 섹션                                → 없으면 리포트 (본문 재작성 없음)
  ⑦ 출처·참고자료                            → 없으면 리포트
  ⑧ 과장·클릭 유도 문구 (제목)               → 감지 시 리포트

결과는 docs/data/adsense_audit.json에 저장되어 대시보드에서 확인 가능.

Usage:
  python adsense_audit.py --blog blog1            # 검사 + 자동 보완
  python adsense_audit.py --blog blog1 --dry-run  # 검사만
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime

import requests
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BLOGGER_API_BASE = "https://www.googleapis.com/blogger/v3"
_BASE_DIR = os.path.dirname(__file__)
REPORT_PATH = os.path.join(_BASE_DIR, "..", "docs", "data", "adsense_audit.json")

MIN_CHARS = 2500

_YMYL_KW = {"투자", "주식", "etf", "펀드", "재테크", "부동산", "금리", "대출", "보험",
            "연금", "세금", "절세", "코인", "건강", "다이어트", "질병", "의료", "치료",
            "영양", "혈압", "당뇨", "법률", "계약", "소송", "상속"}

_CLICKBAIT = ["충격", "경악", "미쳤다", "대박", "헐", "소름", "절대 하지 마",
              "100% 보장", "무조건 벌", "확실한 수익"]

_DISCLAIMER_MARKERS = ["전문가와 상담", "투자 판단", "의학적 조언", "법률 자문",
                       "개인의 상황", "참고용", "면책", "책임지지 않"]

_DISCLAIMER_HTML = (
    '\n<div style="margin-top:2.5em;padding:16px 20px;background:#fffbeb;'
    'border-radius:0 10px 10px 0;border-left:4px solid #d97706;">'
    '<p style="font-size:13px;color:#78350f;margin:0;line-height:1.8;">'
    '⚠️ 이 글은 일반적인 정보 제공을 목적으로 하며, 전문적인 조언을 대신하지 않습니다. '
    '투자·건강·법률 등 중요한 결정은 반드시 해당 분야 전문가와 상담 후 진행하세요. '
    '개인의 상황에 따라 결과가 다를 수 있습니다.</p></div>'
)


def _plain_len(html: str) -> int:
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return len(re.sub(r"\s+", "", text))


def _is_ymyl(title: str, labels: list[str]) -> bool:
    hay = (title + " " + " ".join(labels or [])).lower()
    return any(w in hay for w in _YMYL_KW)


def _fix_empty_alts(content: str, title: str) -> tuple[str, int]:
    """alt가 없거나 빈 <img>에 제목 기반 alt를 채웁니다."""
    fixed = 0

    def repl(m: re.Match) -> str:
        nonlocal fixed
        tag = m.group(0)
        alt_m = re.search(r'alt="([^"]*)"', tag)
        if alt_m and alt_m.group(1).strip():
            return tag
        import html as _h
        alt = _h.escape(f"{title} 관련 이미지", quote=True)
        fixed += 1
        if alt_m:  # alt="" → 채움
            return tag.replace(alt_m.group(0), f'alt="{alt}"')
        return tag[:-2] + f' alt="{alt}"/>' if tag.endswith('/>') else tag[:-1] + f' alt="{alt}">'

    new = re.sub(r'<img\b[^>]*>', repl, content, flags=re.I)
    return new, fixed


def audit_post(post: dict) -> tuple[list[str], list[str], str]:
    """단일 글 검사. Returns (자동보완 로그, 리포트 이슈, 수정된 content)."""
    from fix_duplicate_toc import count_tocs, dedupe_toc

    title   = post.get("title", "")
    content = post.get("content", "")
    labels  = post.get("labels", []) or []
    fixes: list[str] = []
    issues: list[str] = []

    # ① 글자 수
    n_chars = _plain_len(content)
    if n_chars < MIN_CHARS:
        issues.append(f"글자수 부족 ({n_chars}자 < {MIN_CHARS}자) — 내용 보강 필요")

    # ④ 목차 중복
    n_toc = count_tocs(content)
    if n_toc > 1:
        new = dedupe_toc(content)
        if count_tocs(new) == 1:
            content = new
            fixes.append(f"중복 목차 제거 ({n_toc}→1)")
        else:
            issues.append(f"목차 {n_toc}개 — 자동 정리 실패, 수동 확인 필요")

    # ② 이미지 존재
    imgs = re.findall(r'<img\b[^>]*>', content, re.I)
    if not imgs:
        from image_fetcher import generate_title_thumbnail, _make_img_html
        thumb = generate_title_thumbnail(title)
        if thumb:
            img_html = _make_img_html(thumb, thumb.get("alt_text", title), "")
            m = re.search(r'</p>', content, re.I)
            content = (content[:m.end()] + img_html + content[m.end():]) if m else img_html + content
            fixes.append("이미지 없음 → 제목 썸네일 삽입")
        else:
            issues.append("이미지 없음 — 썸네일 생성 실패")
    else:
        # ③ alt 텍스트
        content, n_alt = _fix_empty_alts(content, title)
        if n_alt:
            fixes.append(f"빈 alt 텍스트 {n_alt}개 채움")

    # ⑤ YMYL 면책 문구
    if _is_ymyl(title, labels):
        if not any(mk in content for mk in _DISCLAIMER_MARKERS):
            content += _DISCLAIMER_HTML
            fixes.append("YMYL 글 면책 문구 추가")

    # ⑥ FAQ
    if not re.search(r'자주\s*묻는\s*질문|FAQ', content, re.I):
        issues.append("FAQ 섹션 없음 — 재작성 필요 시 검토")

    # ⑦ 출처
    if not re.search(r'참고\s*자료|출처|références|reference', content, re.I):
        issues.append("출처·참고자료 섹션 없음")

    # ⑧ 낚시성 제목
    hits = [w for w in _CLICKBAIT if w in title]
    if hits:
        issues.append(f"제목 과장 표현 감지: {hits}")

    return fixes, issues, content


def run_audit(blog_cfg: dict, dry_run: bool) -> dict:
    from blogger_uploader import _get_access_token

    name = blog_cfg.get("name") or blog_cfg.get("id", "")
    blogger_blog_id = blog_cfg.get("blog_id", "")
    token = _get_access_token(blog_cfg)
    if not (blogger_blog_id and token):
        logger.error(f"[{name}] blog_id 또는 토큰 없음 — 건너뜀")
        return {"blog": name, "scanned": 0, "fixed": 0, "posts": []}

    logger.info(f"══ [{name}] AdSense 감사 시작 ══")
    scanned = fixed_posts = 0
    report_posts = []
    page_token = ""
    while True:
        params = {"maxResults": 100, "status": "live", "fetchBodies": "true",
                  "fields": "nextPageToken,items(id,title,url,content,labels)"}
        if page_token:
            params["pageToken"] = page_token
        r = requests.get(f"{BLOGGER_API_BASE}/blogs/{blogger_blog_id}/posts",
                         headers={"Authorization": f"Bearer {token}"}, params=params, timeout=30)
        if r.status_code != 200:
            logger.error(f"글 목록 조회 실패 [{r.status_code}]: {r.text[:200]}")
            break
        data = r.json()

        for post in data.get("items", []):
            scanned += 1
            fixes, issues, new_content = audit_post(post)
            title_s = post.get("title", "")[:45]

            if not fixes and not issues:
                continue

            logger.info(f"  📄 '{title_s}'")
            for f in fixes:
                logger.info(f"     🔧 {f}" + (" [dry-run]" if dry_run else ""))
            for i in issues:
                logger.warning(f"     ⚠️ {i}")

            if fixes and not dry_run and new_content != post.get("content", ""):
                pr = requests.patch(
                    f"{BLOGGER_API_BASE}/blogs/{blogger_blog_id}/posts/{post['id']}",
                    headers={"Authorization": f"Bearer {token}",
                             "Content-Type": "application/json"},
                    json={"content": new_content}, timeout=30)
                if pr.status_code == 200:
                    fixed_posts += 1
                    logger.info("     ✅ 자동 보완 반영 완료")
                else:
                    logger.error(f"     ❌ 업데이트 실패 [{pr.status_code}]: {pr.text[:150]}")
                    issues.append("업데이트 실패")
                time.sleep(1)
            elif fixes and dry_run:
                fixed_posts += 1

            report_posts.append({
                "title": post.get("title", ""), "url": post.get("url", ""),
                "fixes": fixes, "issues": issues,
            })

        page_token = data.get("nextPageToken", "")
        if not page_token:
            break

    logger.info(f"══ [{name}] 스캔 {scanned}건 / 자동보완 {fixed_posts}건 / "
                f"수동확인 필요 {sum(1 for p in report_posts if p['issues'])}건 ══")
    return {"blog": name, "scanned": scanned, "fixed": fixed_posts, "posts": report_posts}


def main() -> int:
    parser = argparse.ArgumentParser(description="AdSense 승인 대비 감사·보완")
    parser.add_argument("--blog", default="blog1", help="블로그 ID (기본: blog1, 'all'=전체)")
    parser.add_argument("--dry-run", action="store_true", help="검사만 하고 수정하지 않음")
    args = parser.parse_args()

    from config import get_blog_configs
    blogs = get_blog_configs()
    if args.blog != "all":
        blogs = [b for b in blogs if b.get("id") == args.blog]
        if not blogs:
            logger.error(f"블로그 '{args.blog}' 없음")
            return 1

    results = [run_audit(cfg, args.dry_run) for cfg in blogs]

    report = {
        "auditedAt": datetime.now().isoformat(),
        "dryRun": args.dry_run,
        "results": results,
    }
    try:
        os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info(f"감사 리포트 저장: {REPORT_PATH}")
    except Exception as e:
        logger.warning(f"리포트 저장 실패 (무시): {e}")

    total_issues = sum(1 for r in results for p in r["posts"] if p["issues"])
    logger.info("=" * 55)
    logger.info(f"전체 완료 — 스캔 {sum(r['scanned'] for r in results)}건 / "
                f"자동보완 {sum(r['fixed'] for r in results)}건 / "
                f"수동확인 필요 {total_issues}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
