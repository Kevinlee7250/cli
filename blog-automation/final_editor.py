"""
최종 편집기 (Publishing Editor) — 업로드 직전 품질 마무리

AdSense 검증을 통과한 글에 대해 Claude로 최종 편집을 수행합니다:
  1. 제목 ↔ H2 소제목 주제 정합성 교정
  2. 문체 일관성·어색한 문장 정리
  3. SEO 체크리스트 최종 점검 (키워드 밀도, meta_description 길이)

원본 내용의 80% 이상을 유지하며, 구조·사실은 변경하지 않습니다.
오류 발생 시 원본 post_data를 그대로 반환 (게시 차단 없음).
"""

import json
import logging
import re

from config import claude_generate, CLAUDE_MODEL

logger = logging.getLogger(__name__)


def _strip_html(html: str, max_chars: int = 3000) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def _extract_h2s(html: str) -> list[str]:
    return re.findall(r"<h2[^>]*>(.*?)</h2>", html, re.IGNORECASE | re.DOTALL)


def _clean_tag(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def polish_post(post_data: dict) -> dict:
    """
    업로드 직전 최종 편집을 수행합니다.
    수정된 post_data를 반환합니다. 실패 시 원본을 반환합니다.
    """
    title = post_data.get("title", "").strip()
    content = post_data.get("content", "")
    meta_desc = post_data.get("meta_description", "")
    keyword = post_data.get("keyword", "")
    word_count = post_data.get("word_count", 0)

    if not title or not content:
        logger.debug("final_editor: title 또는 content 없음 — 건너뜀")
        return post_data

    h2_list = [_clean_tag(h) for h in _extract_h2s(content)]
    plain_text = _strip_html(content)
    orig_len = len(re.sub(r"\s+", "", plain_text))

    h2_block = "\n".join(f"  - {h}" for h in h2_list) if h2_list else "  (H2 없음)"
    meta_len_note = f"{len(meta_desc)}자" if meta_desc else "없음"

    prompt = f"""당신은 한국어 블로그 최종 편집자입니다.
아래 글을 업로드 직전 마지막으로 다듬어 주세요.

=== 현재 글 정보 ===
제목: {title}
키워드: {keyword}
글자 수(공백제외): {word_count}자
meta_description({meta_len_note}): {meta_desc}

=== H2 소제목 목록 ===
{h2_block}

=== 본문 (HTML, 앞 3000자) ===
{plain_text}

=== 편집 지침 (중요도 순) ===

① 제목 ↔ 소제목 정합성
   - 제목에서 독자에게 약속한 내용이 H2에 반드시 포함되어야 합니다
   - 제목과 무관한 H2가 있으면 제목 취지에 맞게 소제목 텍스트를 수정하세요
   - H2 순서는 유지하되 텍스트만 교정합니다

② 문체 일관성
   - "~입니다" 체 통일 (반말·격식체 혼용 금지)
   - 같은 문장 구조 반복(예: "~하세요. ~하세요. ~하세요.") 변환
   - AI 투 표현 제거: "살펴보겠습니다", "정리해드리겠습니다", "다음과 같습니다"

③ SEO 최종 점검
   - 키워드 "{keyword}"가 본문에 10~14회 자연스럽게 포함되어 있는지 확인
   - meta_description이 100~160자 사이인지 확인하고 벗어나면 수정
   - 제목 40자 이내인지 확인

④ 절대 변경 금지
   - 수치·날짜·출처·사실 관계
   - HTML 구조 (div, img, a 태그 등)
   - 원본 분량의 80% 이상 유지

수정 후 반드시 아래 JSON만 출력하세요 (마크다운 없이):
{{
  "title": "수정된 제목 (변경 없으면 원본 그대로)",
  "h2_fixes": [
    {{"original": "원래 소제목", "revised": "수정된 소제목"}}
  ],
  "meta_description": "수정된 meta_description (변경 없으면 원본 그대로)",
  "changes_summary": "변경 요약 1~2줄"
}}

h2_fixes는 실제로 변경된 항목만 포함하세요. 변경 없으면 빈 배열 [].
"""

    try:
        import anthropic
        client = anthropic.Anthropic()
        raw = claude_generate(
            client,
            model=CLAUDE_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )

        # JSON 파싱
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        result = json.loads(raw)

        changed = False

        # 제목 업데이트
        new_title = (result.get("title") or "").strip()
        if new_title and new_title != title:
            post_data["title"] = new_title
            logger.info(f"  ✏️ 제목 교정: '{title}' → '{new_title}'")
            changed = True

        # H2 소제목 교정 (HTML 내 직접 치환)
        h2_fixes: list[dict] = result.get("h2_fixes") or []
        for fix in h2_fixes:
            orig_h2 = (fix.get("original") or "").strip()
            rev_h2 = (fix.get("revised") or "").strip()
            if orig_h2 and rev_h2 and orig_h2 != rev_h2:
                # 태그 내 텍스트만 교체 (태그 속성 보존)
                content = re.sub(
                    rf"(<h2[^>]*>)\s*{re.escape(orig_h2)}\s*(</h2>)",
                    rf"\g<1>{rev_h2}\g<2>",
                    content,
                    flags=re.IGNORECASE,
                )
                logger.info(f"  ✏️ H2 교정: '{orig_h2}' → '{rev_h2}'")
                changed = True

        if changed:
            post_data["content"] = content

        # meta_description 업데이트
        new_meta = (result.get("meta_description") or "").strip()
        if new_meta and new_meta != meta_desc:
            post_data["meta_description"] = new_meta
            logger.info(f"  ✏️ meta_description 교정 ({len(new_meta)}자)")
            changed = True

        summary = result.get("changes_summary", "변경 없음")
        if changed:
            logger.info(f"  ✅ 최종 편집 완료 — {summary}")
        else:
            logger.info("  ✅ 최종 편집 검토 완료 — 수정 없음")

        post_data["final_edit_applied"] = changed
        return post_data

    except Exception as e:
        logger.warning(f"  ⚠️ 최종 편집 건너뜀 (무시): {e}")
        return post_data
