#!/usr/bin/env python3
"""발행 직전 '없는 1인칭 경험·방문 주장' 게이트 (AIOPS-59, 2026-11-26).

왜 따로 있는가
──────────────
2026-11-26 발행 3편이 모두 하지 않은 경험을 주장했습니다("11월 9일 …
가격표를 직접 확인", "고3 때 … 알바부터 시작해봤는데", "제가 겪었던 순서").
세 편 모두 생성 뒤의 AdSense 자동 수정을 거쳤고, 그 단계 이후에는 본문을
다시 보는 검사가 없었습니다. 이 모듈은 마지막 단계에서 규칙(정규식)으로만
판정합니다 — LLM 응답에 기대지 않으므로 API 오류로 통과되지 않습니다.

규칙 요약은 EXPERIENCE_RULES.md를 보세요.
`experience_audit`는 발행 글 소급 감사용(심각도 분류)이고, 여기는 발행
차단용이라 '완료된 경험 주장'만 좁게 잡고 권유·희망 표현은 통과시킵니다.
"""
import html as _html
import re

from experience_audit import strip_chrome
from title_policy import check_title

# 앞에 한글이 붙으면 "문제가", "안내가"처럼 다른 낱말입니다.
_FIRST_PERSON = re.compile(
    r"(?<![가-힣])(?:저는|저도|저\s*역시|저\s*또한|저희(?:는|도|가)|제가|저의|"
    r"필자(?:는|가|도)?|작성자(?:는|가|도))(?![가-힣])"
)
# "내가 살 품목"처럼 '내가'는 독자를 가리킬 때가 많아, 체험 동사가 붙을 때만 봅니다.
_NAEGA_DONE = re.compile(r"(?<![가-힣])내가\s[^.!?\n]{0,20}?(?:방문했|다녀|겪었|겪은|써\s*[봤본]|먹어\s*[봤본]|가\s*[봤본])")
# 남의 말 인용은 글쓴이 주장이 아닙니다.
_QUOTED = re.compile(r"“[^”]*”|‘[^’]*’|\"[^\"]*\"|'[^']*'")
# 조사·정리는 글을 쓴 행위입니다 — 과거형이어도 경험 주장으로 보지 않습니다.
_RESEARCH_VERB = re.compile(
    r"(?:조사|정리|요약|분석|검색|계산|비교|종합|소개|설명|언급|작성|참고|"
    r"찾아|살펴|알아)\s*(?:해\s*)?(?:봤\w*|보았\w*|본|했\w*|한|드렸\w*|였\w*|았\w*|었\w*)"
)
_COMPLETED_ATTR = re.compile(
    r"(?:겪은|해\s*본|써\s*본|가\s*본|다녀온|방문한|돌아본|둘러본|먹어\s*본|"
    r"살아\s*본|받아\s*본|경험한|이용한|구매한|확인한)(?![가-힣])|"
    r"\d+\s*(?:년|개월|달|주)\s*째"
)
# '직접 대조해본 결과'처럼 자료를 본 것은 경험 주장이 아닙니다.
_DESK_WORK = re.compile(r"직접\s*(?:자료를\s*)?(?:조사|정리|검색|대조|찾아)\s*(?:해\s*)?(?:봤\w*|보았\w*|본|보고|했\w*|한)")
# 1인칭 주어가 없어도 '직접 + 완료형'이면 글쓴이가 했다는 말입니다.
_DIRECT_DONE = re.compile(
    r"직접\s[^.!?\n]{0,40}?(?:겪은|겪었|겪어|해\s*본(?!\s*(?:뒤|후|다음))|해\s*봤|써\s*본|써\s*봤|"
    r"다녀온|다녀왔|다녀와|돌며|돌아본|돌아봤|둘러본|둘러봤|들러|먹어\s*본|먹어\s*봤|"
    r"방문(?:한|했|해\s*(?:본|봤|확인한|확인했))|확인한(?!\s*(?:뒤|후|다음))|확인했|"
    r"경험한(?!\s*(?:뒤|후|다음))|경험했|사용해\s*(?:본|봤)|구매해\s*(?:본|봤))|"
    r"직접\s*(?:겪은|겪었|다녀온|다녀왔|방문한|방문했|써\s*본|해\s*본|해\s*봤)"
)
# "이용자가 직접 확인한" 같은 3인칭 서술
_THIRD_PARTY = re.compile(
    r"(?:이용자|여행자|방문객|방문자|구매자|신청자|투숙객|관람객|시청자|독자|"
    r"누리꾼|기자|참석자|사용자|소비자)(?:들)?(?:이|가|은|는|도)?[^.!?\n]{0,15}직접"
)
# 출처 표시 대신 붙는 상투 문구
_BOILERPLATE = re.compile(
    r"(?:개인적인|개인|실제|직접)\s*(?:경험(?:담)?|체험)(?:과|와|을|를|에|,)"
    r"[^.!?\n]{0,60}?(?:바탕|토대|기반|작성|정리)|개인\s*경험\s*메모|"
    r"(?:제|저의)\s*(?:개인\s*)?(?:경험|체험)(?:상|담|으로|에)|"
    r"(?:경험|기억)이\s*(?:있습니다|있어요|납니다|나요)"
)
_BLOCK_END = re.compile(r"</(?:p|div|li|h[1-6]|td|th|tr|blockquote|figcaption)>|<br\s*/?>", re.I)
_NUMBER = re.compile(r"\d+")


def _plain_sentences(body_html: str) -> list[str]:
    s = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", body_html or "", flags=re.I | re.S)
    s = strip_chrome(s)
    s = _BLOCK_END.sub("\n", s)
    s = _html.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ")
    parts = re.split(r"(?<=[.!?])\s+|\n+", s)
    return [re.sub(r"\s+", " ", p).strip() for p in parts if p.strip()]


def _has_past_tense(text: str) -> bool:
    """받침 ㅆ(했·았·었·였·왔·렸…)이 있으면 과거형. '있/겠'은 제외합니다."""
    return any(
        "가" <= c <= "힣" and (ord(c) - 0xAC00) % 28 == 20 and c not in "있겠"
        for c in text
    )


def _claim_label(sentence: str) -> str:
    """문장이 경험 주장이면 이유를, 아니면 빈 문자열을 돌려줍니다."""
    own = _QUOTED.sub(" ", sentence)
    if _BOILERPLATE.search(own):
        return "경험 근거 문구"
    if _DIRECT_DONE.search(_DESK_WORK.sub(" ", own)) and not _THIRD_PARTY.search(own):
        return "직접 방문·수행 주장"
    if _NAEGA_DONE.search(own):
        return "1인칭 경험 주장"
    if _FIRST_PERSON.search(own):
        rest = _RESEARCH_VERB.sub(" ", own)
        if _has_past_tense(rest) or _COMPLETED_ATTR.search(rest):
            return "1인칭 경험 주장"
    return ""


def _experience_material(keyword: str, blog_id: str) -> str:
    """author_profile.json의 실제 경험 자료. 없으면 빈 문자열."""
    from content_generator import _match_experience
    exp = _match_experience(keyword or "", blog_id or "")
    if not exp:
        return ""
    return f"{exp.get('summary', '')} {exp.get('detail', '')}".strip()


def find_claims(post_data: dict, blog_id: str = "") -> list[dict]:
    """발행을 막아야 하는 경험 주장 목록 [{where, label, excerpt}] (없으면 빈 목록)."""
    material = _experience_material(post_data.get("keyword", ""), blog_id)
    known = set(_NUMBER.findall(material))
    hits: list[dict] = []

    def _add(where: str, label: str, text: str) -> None:
        # 실제 자료가 있는 주제는 허용하되, 자료에 없는 숫자(날짜·금액·횟수)가
        # 붙은 주장은 막습니다.
        if material and set(_NUMBER.findall(text)) <= known:
            return
        hits.append({"where": where, "label": label, "excerpt": text[:160]})

    title = post_data.get("title", "") or ""
    title_hits = [v for v in check_title(title) if v.startswith("경험 주장")]
    if title_hits:
        _add("title", title_hits[0], title)
    elif _claim_label(title):
        _add("title", _claim_label(title), title)

    meta = post_data.get("meta_description") or post_data.get("metaDescription") or ""
    for where, sentences in (("meta", _plain_sentences(meta)),
                             ("body", _plain_sentences(post_data.get("content", "")))):
        for sentence in sentences:
            label = _claim_label(sentence)
            if label:
                _add(where, label, sentence)
    return hits


def hold_reason(post_data: dict, blog_id: str = "") -> str:
    """보류 사유 문자열. 통과면 빈 문자열. 검사 자체가 실패해도 보류합니다."""
    try:
        hits = find_claims(post_data, blog_id)
    except Exception as exc:  # 검사하지 못한 글은 내보내지 않습니다
        return f"경험 주장 검사 실패로 보류: {exc}"[:200]
    if not hits:
        return ""
    first = hits[0]
    return (f"근거 없는 경험 주장 {len(hits)}건 — "
            f"[{first['where']}/{first['label']}] {first['excerpt']}")[:200]
