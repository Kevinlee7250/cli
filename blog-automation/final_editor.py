"""
3차 최종 발행 편집기 (Publishing Editor)

AdSense 검증·자동수정을 통과한 글을 Blogger에 바로 업로드 가능한
최종 발행본으로 다듬습니다.

수행 작업:
  1. 최종 SEO 제목 / 메타 설명 / URL 슬러그 정리
  2. 본문 구조 재편 (요약 박스·목차·표·개인메모·주의사항·FAQ·결론·작성자메모·참고자료·내부링크)
  3. 이미지 alt text 목록 생성 (2~4개 제안)
  4. 발행 전 체크리스트 생성
  5. 카테고리·태그 추천

원본 내용의 80% 이상을 유지하며 사실·수치를 변경하지 않습니다.
오류 발생 시 원본 post_data를 그대로 반환 (게시 차단 없음).
"""

import json
import logging
import re

from config import claude_generate, CLAUDE_MODEL

logger = logging.getLogger(__name__)

_NEEDS_WARNING = {
    "finance": {"재테크", "투자", "주식", "etf", "펀드", "부동산", "연금", "보험",
                "절세", "대출", "금리", "채권", "코인", "암호화폐"},
    "health":  {"건강", "다이어트", "운동", "영양", "질병", "증상", "의약", "치료",
                "수면", "혈압", "혈당", "비만", "면역"},
    "legal":   {"법률", "계약", "소송", "판결", "임대차", "세금", "세무", "약관", "분쟁"},
}


def _needs_warning(keyword: str) -> str:
    kw = keyword.lower()
    for cat, kws in _NEEDS_WARNING.items():
        if any(w in kw for w in kws):
            return cat
    return ""


def _strip_html(html: str, max_chars: int = 3500) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def _extract_h2s(html: str) -> list[str]:
    return [re.sub(r"<[^>]+>", "", h).strip()
            for h in re.findall(r"<h2[^>]*>(.*?)</h2>", html, re.IGNORECASE | re.DOTALL)]


def _extract_sources(post_data: dict) -> str:
    sources = post_data.get("sources") or []
    if not sources:
        return "(없음)"
    return "\n".join(f"- {s.get('title','')}: {s.get('url','')}" for s in sources)


def polish_post(post_data: dict) -> dict:
    """
    3차 최종 발행 편집을 수행합니다.
    수정된 post_data를 반환합니다. 실패 시 원본을 반환합니다.
    """
    title    = post_data.get("title", "").strip()
    content  = post_data.get("content", "")
    meta_desc = post_data.get("meta_description", "")
    keyword  = post_data.get("keyword", "")
    labels   = post_data.get("labels") or []
    sources_str = _extract_sources(post_data)
    blog_name   = post_data.get("_blog_name", "")
    h2_list  = _extract_h2s(content)
    plain    = _strip_html(content)
    warning_cat = _needs_warning(keyword)

    h2_block = "\n".join(f"  - {h}" for h in h2_list) if h2_list else "  (H2 없음)"
    tags_hint = ", ".join(labels[:5]) if labels else "(없음)"

    warning_note = ""
    if warning_cat == "finance":
        warning_note = "투자·금융 주제 → ⚠️ 주의사항 섹션 필수 포함"
    elif warning_cat == "health":
        warning_note = "건강·의료 주제 → ⚠️ 주의사항 섹션 필수 포함"
    elif warning_cat == "legal":
        warning_note = "법률·세무 주제 → ⚠️ 주의사항 섹션 필수 포함"

    prompt = f"""당신은 블로그 글을 실제 발행 가능한 형태로 정리하는 "3차 최종 발행 편집 Agent"입니다.

2차 품질 검수를 통과한 글을 Blogger에 바로 업로드할 수 있는 최종 발행본으로 다듬어 주세요.
새 글을 처음부터 쓰는 것이 아니라, 완료된 글을 발행 품질로 편집하는 것입니다.

━━━━━━━━━━━━━━━━━━━━
[입력 정보]

- 블로그명: {blog_name or "개인 블로그"}
- 주요 키워드: {keyword}
- 현재 제목: {title}
- 현재 태그: {tags_hint}
- 블로그 플랫폼: Blogger
- 문체: 친근하고 신뢰감 있는 한국어 블로그 문체
- H2 소제목 목록:
{h2_block}
- 참고 자료:
{sources_str}
{f"- 특이 사항: {warning_note}" if warning_note else ""}

[2차 개선 완료 본문 (앞 3,500자)]
{plain}

━━━━━━━━━━━━━━━━━━━━
[최종 편집 목표]

1. 제목·메타 설명·URL 슬러그가 정리되어 있다 (제목 30~45자, 메타 120~160자)
2. 본문 구조가 자연스럽고 읽기 쉽다
3. 모바일에서 문단이 길지 않다 (한 문단 2~4문장 이내)
4. 요약 박스·목차·표·개인경험메모·주의사항·FAQ·결론·작성자메모·내부링크 포함
5. 이미지 alt text가 구체적이다
6. AdSense 승인에 불리한 문구, 광고 클릭 유도 문구, 저작권 침해 문장이 없다
7. 실제 발행자가 복사해 바로 업로드할 수 있다

━━━━━━━━━━━━━━━━━━━━
[본문 편집 규칙]

소제목:
- H2는 명확하게, H3는 구체적으로 — 소제목만 봐도 흐름이 이해되어야 함

요약 박스 (도입부 직후):
<div style="background:#f0fdf4;border-left:5px solid #16a34a;padding:16px 22px;margin:1.5em 0;border-radius:0 12px 12px 0;color:#14532d;font-size:0.96em;line-height:1.9;">
✅ <strong>핵심 요약</strong><br>
• 대상: [누구에게 유용한가]<br>
• 핵심 내용: [한 줄 요약]<br>
• 비용/조건: [있다면]<br>
• 장점: [주요 장점]<br>
• 주의할 점: [한 줄]<br>
• 결론: [한 줄 결론]
</div>

표 (본문 중간 최소 1개):
<table style="width:100%;border-collapse:collapse;margin:1.5em 0;">
<tr style="background:#f1f5f9;"><th style="border:1px solid #cbd5e1;padding:10px;">항목</th><th>내용</th><th>체크 포인트</th></tr>
<tr><td style="border:1px solid #cbd5e1;padding:10px;">...</td><td>...</td><td>...</td></tr>
</table>

개인 경험 메모 (본문 중간 또는 결론 전):
<div style="background:#fefce8;border-left:4px solid #ca8a04;padding:14px 20px;margin:1.5em 0;border-radius:0 8px 8px 0;color:#713f12;font-size:0.95em;line-height:1.8;">
📌 <strong>개인 경험 메모</strong><br>
[4~6문장. 직접 경험이 없으면 "공개 자료와 공식 정보를 바탕으로 정리했습니다"로 표시]
</div>

주의사항 ({"건강·금융·법률 주제이므로 반드시 포함" if warning_note else "필요 시 포함"}):
<div style="background:#fff7ed;border-left:4px solid #ea580c;padding:14px 20px;margin:1.5em 0;border-radius:0 8px 8px 0;color:#7c2d12;font-size:0.9em;line-height:1.7;">
⚠️ <strong>주의사항</strong><br>
이 글은 일반적인 정보와 개인적인 경험을 바탕으로 작성한 글입니다. 개인의 상황, 건강 상태, 재정 상태, 거주 지역, 이용 조건에 따라 결과가 달라질 수 있습니다. 중요한 결정을 하기 전에는 공식 기관, 전문가, 해당 서비스 제공처의 최신 안내를 확인하는 것이 좋습니다.
</div>

FAQ (4~6개, h3 형식):
<h2>자주 묻는 질문</h2>
<h3>Q1. 질문</h3><p>답변 (2~4문장)</p>
...

결론 (추천/비추천 대상 구분, 과장 없이):
<h2>마무리</h2>
<p>...</p>

작성자 메모 (글 하단):
<p style="background:#f8fafc;border-left:4px solid #94a3b8;padding:12px 18px;margin:2em 0 0;border-radius:0 8px 8px 0;color:#64748b;font-size:0.9em;line-height:1.7;">
✍️ <strong>작성자 메모</strong><br>
이 글은 실제 경험, 공개 자료, 공식 정보를 바탕으로 작성했습니다. 블로그 운영자는 생활정보, AI 활용, 여행, 건강관리, 재테크 관련 정보를 직접 조사하고 초보자도 이해하기 쉽게 정리하는 것을 목표로 합니다.
</p>

내부 링크 (글 하단):
<div style="background:#f1f5f9;padding:14px 20px;margin:2em 0;border-radius:8px;">
<strong>📎 함께 읽으면 좋은 글</strong><br>
<a href="#">관련 글 제목 1</a> /
<a href="#">관련 글 제목 2</a> /
<a href="#">관련 글 제목 3</a>
</div>

━━━━━━━━━━━━━━━━━━━━
[이미지 규칙]

본문에 이미지 2~4개를 제안합니다 (실제 삽입 X, 위치와 alt만 명시).
alt text는 구체적으로 — "이미지"처럼 쓰지 말 것.
좋은 예: "{keyword} 관련 체크리스트를 정리한 블로그 대표 이미지"

━━━━━━━━━━━━━━━━━━━━
[출력 형식 — 반드시 JSON만 출력 (마크다운 코드 블록 없이)]

{{
  "seo_title": "최종 SEO 제목 (30~45자, 키워드 포함, 과장 없음)",
  "meta_description": "최종 메타 설명 (120~160자)",
  "url_slug": "recommended-url-slug-in-english",
  "category": "카테고리 1개 (건강관리/생활정보/AI활용/여행/재테크/맛집/블로그운영 중 선택)",
  "tags": ["태그1","태그2","태그3","태그4","태그5"],
  "representative_image": {{
    "position": "글 최상단",
    "description": "대표 이미지 설명",
    "style": "추천 스타일",
    "alt": "구체적인 alt text",
    "filename": "recommended-filename.jpg"
  }},
  "content": "<Blogger에 바로 붙여넣기 가능한 완전한 HTML 본문>",
  "image_list": [
    {{"position": "삽입 위치", "description": "이미지 설명", "alt": "alt text", "filename": "파일명.jpg"}},
    {{"position": "삽입 위치", "description": "이미지 설명", "alt": "alt text", "filename": "파일명.jpg"}}
  ],
  "internal_links": ["관련 글 제목 1", "관련 글 제목 2", "관련 글 제목 3"],
  "references": [{{"name": "기관명", "note": "참고 내용"}}],
  "checklist": {{
    "title_matches_intent": true,
    "meta_120_160": true,
    "slug_clean": true,
    "intro_starts_with_reader_concern": true,
    "summary_box_present": true,
    "table_present": true,
    "faq_4_plus": true,
    "warning_if_needed": true,
    "author_memo_present": true,
    "references_present": true,
    "internal_links_present": true,
    "alt_text_specific": true,
    "no_ad_cta": true,
    "no_exaggeration": true,
    "no_ai_phrases": true,
    "mobile_friendly_paragraphs": true
  }},
  "changes_summary": "변경 요약 1~2줄"
}}"""

    try:
        import anthropic
        client = anthropic.Anthropic()
        raw = claude_generate(
            client,
            model=CLAUDE_MODEL,
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        result = json.loads(raw)

        changed = False

        # 제목
        new_title = (result.get("seo_title") or "").strip()
        if new_title and new_title != title:
            post_data["title"] = new_title
            logger.info(f"  ✏️ 제목 최종 교정: '{title}' → '{new_title}'")
            changed = True

        # 본문
        new_content = (result.get("content") or "").strip()
        if new_content and len(new_content) >= len(content) * 0.7:
            post_data["content"] = new_content
            changed = True

        # 메타 설명
        new_meta = (result.get("meta_description") or "").strip()
        if new_meta and new_meta != meta_desc:
            post_data["meta_description"] = new_meta
            logger.info(f"  ✏️ 메타 설명 교정 ({len(new_meta)}자)")
            changed = True

        # 태그
        new_tags = [t for t in (result.get("tags") or []) if isinstance(t, str)]
        if new_tags:
            post_data["labels"] = new_tags
            changed = True

        # 추가 필드 저장 (Blogger 업로드에는 영향 없음)
        post_data["url_slug"]             = result.get("url_slug", "")
        post_data["category"]             = result.get("category", "")
        post_data["representative_image"] = result.get("representative_image", {})
        post_data["image_list"]           = result.get("image_list", [])
        post_data["internal_links"]       = result.get("internal_links", [])
        post_data["references"]           = result.get("references", [])
        post_data["publish_checklist"]    = result.get("checklist", {})
        post_data["final_edit_applied"]   = changed

        summary = result.get("changes_summary", "")
        logger.info(f"  ✅ 3차 최종 편집 완료 — {summary}")

        # 체크리스트 요약 로그
        checklist = result.get("checklist") or {}
        fails = [k for k, v in checklist.items() if v is False]
        if fails:
            logger.warning(f"  ⚠️ 발행 전 체크리스트 미충족 항목: {', '.join(fails)}")

        return post_data

    except Exception as e:
        logger.warning(f"  ⚠️ 3차 최종 편집 건너뜀 (무시): {e}")
        return post_data
