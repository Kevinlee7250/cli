"""검색 스니펫 최적화 — 글 상단 "핵심 요약" 박스.

구글은 질문에 직접 답하는 짧은 블록을 추천 스니펫(0위 노출)으로 뽑습니다.
지금 글은 도입부가 서사형으로 시작해 이 형태가 없어 스니펫 후보에서 밀립니다.

효과는 두 갈래입니다:
  · 검색 — 답을 먼저 제시하는 블록이 추천 스니펫 후보가 됨
  · 체류 — 독자가 "이 글에 내 답이 있다"를 3초 안에 확인해 이탈이 줄어듦
    (두 번째 효과는 검색 노출과 무관하게 모든 글에서 작동)

프롬프트로 요청만 하면 모델이 빠뜨릴 수 있으므로, 생성 결과에 없으면
meta_description·본문 첫 문단에서 만들어 넣는 폴백을 둡니다 — 새 사실을
지어내지 않고 이미 글에 있는 문장만 재사용합니다.
"""

import html as _html_esc
import re

_SUMMARY_MARKER = "📌 핵심 요약"
_MIN_ITEM_LEN = 12
_MAX_ITEM_LEN = 90
_MAX_ITEMS = 3


def has_summary_box(content_html: str) -> bool:
    return _SUMMARY_MARKER in (content_html or "")


def build_summary_box(items: list[str]) -> str:
    """핵심 요약 박스 HTML을 생성합니다 (항목이 없으면 빈 문자열)."""
    clean = [str(i).strip() for i in items if str(i).strip()]
    if not clean:
        return ""
    lis = "".join(
        f'<li style="margin:5px 0;line-height:1.75;">{_html_esc.escape(i)}</li>'
        for i in clean[:_MAX_ITEMS]
    )
    return (
        '<div style="margin:1.5em 0 2em;padding:18px 22px;background:#eff6ff;'
        'border-radius:10px;border-left:4px solid #2563eb;">'
        f'<p style="font-weight:700;font-size:15px;margin:0 0 8px;color:#1e3a8a;">{_SUMMARY_MARKER}</p>'
        f'<ul style="margin:0;padding-left:20px;font-size:14px;color:#1f2937;">{lis}</ul>'
        '</div>'
    )


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?다요])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _fallback_items(post_data: dict) -> list[str]:
    """모델이 summary를 안 줬을 때 — 이미 글에 있는 문장만 재사용합니다."""
    items: list[str] = []

    meta = (post_data.get("meta_description") or "").strip()
    if meta:
        items.extend(_split_sentences(meta))

    if len(items) < _MAX_ITEMS:
        text = re.sub(r"<[^>]+>", " ", post_data.get("content", "") or "")
        text = re.sub(r"\s+", " ", text).strip()
        items.extend(_split_sentences(text[:600]))

    out: list[str] = []
    for s in items:
        s = s.strip()
        if not (_MIN_ITEM_LEN <= len(s) <= _MAX_ITEM_LEN):
            continue
        if s in out:
            continue
        out.append(s)
        if len(out) >= _MAX_ITEMS:
            break
    return out


def _insert_after_intro(content: str, block: str) -> str:
    """도입부 첫 문단 뒤에 삽입합니다 (목차·이미지보다 앞).

    글 맨 앞이 아니라 첫 문단 뒤인 이유: 요약이 제목 바로 밑에 오면 도입부
    후킹이 잘려 몰입이 끊기고, 너무 뒤로 가면 스니펫 후보에서 밀립니다.
    """
    m = re.search(r"</p>", content, re.IGNORECASE)
    if m:
        return content[:m.end()] + "\n" + block + content[m.end():]
    return block + content


def ensure_summary_box(post_data: dict) -> bool:
    """글에 핵심 요약 박스를 보장합니다. 새로 넣었으면 True.

    모델이 준 summary 필드를 우선 쓰고, 없으면 폴백으로 생성합니다.
    만들 문장이 없으면 아무것도 하지 않습니다(빈 박스보다 없는 편이 나음).
    """
    content = post_data.get("content", "") or ""
    if not content or has_summary_box(content):
        return False

    raw_items = post_data.get("summary")
    items = (
        [str(i) for i in raw_items]
        if isinstance(raw_items, list) and raw_items
        else _fallback_items(post_data)
    )
    block = build_summary_box(items)
    if not block:
        return False

    post_data["content"] = _insert_after_intro(content, block)
    return True


def snippet_prompt_block() -> str:
    """생성 단계에서 요약 항목을 함께 받기 위한 프롬프트 지침."""
    return """

━━━ 검색 스니펫 최적화 (핵심 요약) ━━━
JSON 응답에 "summary" 필드를 추가하세요. 독자의 검색 질문에 바로 답하는
핵심 문장 2~3개의 배열입니다.
- 각 문장은 20~80자, 그 자체로 완결된 답이어야 합니다 (앞뒤 문맥 없이도 이해 가능).
- 본문에서 실제로 다루는 내용만 쓰세요 — 요약에만 있고 본문에 없는 내용 금지.
- "이 글에서는 ~을 알아봅니다" 같은 예고형 문장은 쓰지 마세요. 답을 직접 쓰세요.
  나쁜 예: "부산 여행 비용에 대해 알아봅니다"
  좋은 예: "부산 1박2일 2인 기준 총 비용은 약 25만원이었습니다"
"""
