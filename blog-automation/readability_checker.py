"""읽기 난이도 자동 검사 — 문장 길이·전문용어 비율을 스캔해 과도하게 어려우면
재작성을 요청합니다.

글작성 고도화 로드맵의 일부: 아무리 도입부 후킹이 좋아도 본문 문장이 길고
전문용어를 설명 없이 쏟아내면 중간에 이탈합니다. content_generator.py의
생성 재시도 루프(분량 미달 재시도와 동일한 패턴)에 연결되어, 기준 미달 시
같은 요청 내에서 최대 2회 더 시도합니다 — 새 API 호출이나 별도 워크플로가
아니라 기존 재시도 루프에 검사 하나를 추가하는 것입니다.
"""

import re

# 카테고리별 전문용어 — 설명 없이 쓰면 이탈을 유발하는 용어들.
# 완전한 사전이 아니라 "설명이 필요한 용어가 나왔는지" 신호로만 사용.
_JARGON_BY_CATEGORY: dict[str, set[str]] = {
    "finance": {
        "레버리지", "파생상품", "스프레드", "변동성지수", "배당수익률", "듀레이션",
        "베이시스포인트", "환헤지", "액티브리밸런싱", "이표", "표면금리", "만기수익률",
        "공매도", "숏커버링", "옵션프리미엄", "괴리율", "익스포저", "헤지펀드",
    },
    "sports": {
        "포제션", "익스펙티드골", "오프사이드트랩", "카운터프레싱", "빌드업",
        "제로톱", "스위퍼키퍼", "언더핸드토스", "픽앤롤", "존디펜스",
    },
    "drama": {
        "메타포", "미장센", "옴니버스", "클리셰", "떡밥", "복선", "카타르시스",
    },
    "travel": {
        "레이오버", "오버부킹", "얼리버드", "노쇼", "코드셰어", "스탑오버",
    },
}
_GENERIC_EXPLAIN_MARKERS = ("쉽게 말해", "쉽게 말하면", "쉽게 설명하면", "즉,", "다시 말해", "말하자면")

_MAX_AVG_SENTENCE_LEN = 75      # 평균 문장 길이(공백 제외 글자수) 임계값
_MAX_LONG_SENTENCE_RATIO = 0.35  # 임계값 초과 문장 비율
_LONG_SENTENCE_LEN = 90


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?다요])\s+", text)
    return [p.strip() for p in parts if len(p.strip()) >= 5]


def assess_readability(html: str, category: str = "") -> dict:
    """본문 HTML의 읽기 난이도를 평가합니다.

    Returns:
        ok, avgSentenceLen, longSentenceRatio, jargonHits, jargonTerms, issues
    """
    text = _strip_html(html)
    sentences = _split_sentences(text)
    if not sentences:
        return {"ok": True, "avgSentenceLen": 0, "longSentenceRatio": 0.0,
                "jargonHits": 0, "jargonTerms": [], "issues": []}

    lengths = [len(re.sub(r"\s+", "", s)) for s in sentences]
    avg_len = sum(lengths) / len(lengths)
    long_ratio = sum(1 for l in lengths if l > _LONG_SENTENCE_LEN) / len(lengths)

    jargon_pool = _JARGON_BY_CATEGORY.get(category, set())
    hit_terms = sorted({term for term in jargon_pool if term in text})
    jargon_hits = sum(text.count(term) for term in hit_terms)
    explain_markers = sum(text.count(m) for m in _GENERIC_EXPLAIN_MARKERS)

    issues = []
    if avg_len > _MAX_AVG_SENTENCE_LEN:
        issues.append(f"평균 문장 길이가 {round(avg_len)}자로 김 (기준 {_MAX_AVG_SENTENCE_LEN}자 이하)")
    if long_ratio > _MAX_LONG_SENTENCE_RATIO:
        issues.append(f"긴 문장({_LONG_SENTENCE_LEN}자 초과) 비율이 {round(long_ratio*100)}%로 높음")
    if hit_terms and explain_markers == 0:
        issues.append(f"전문용어 {len(hit_terms)}개({', '.join(hit_terms[:5])})가 쉬운 설명 없이 사용됨")

    return {
        "ok": not issues,
        "avgSentenceLen": round(avg_len, 1),
        "longSentenceRatio": round(long_ratio, 3),
        "jargonHits": jargon_hits,
        "jargonTerms": hit_terms,
        "issues": issues,
    }


def readability_escalation_note(assessment: dict | None) -> str:
    """읽기 난이도 재시도용 프롬프트 보강 문구."""
    if not assessment or assessment.get("ok", True):
        return ""
    issues = "\n".join(f"  - {i}" for i in assessment.get("issues", []))
    return (
        "\n\n⚠️⚠️⚠️ [읽기 난이도 재작성 요청] 이전 응답이 다음 이유로 읽기 어려웠습니다:\n"
        f"{issues}\n"
        "이번에는 반드시:\n"
        "  - 한 문장에 한 가지 사실만 담고, 문장을 짧게 끊어 쓸 것\n"
        "  - 전문용어가 나오면 바로 뒤에 '쉽게 말하면 ~라는 뜻입니다' 형태로 풀어서 설명할 것\n"
        "  - 어려운 개념은 비유나 일상적인 예시로 바꿔 설명할 것\n"
        "⚠️⚠️⚠️\n"
    )
