#!/usr/bin/env python3
"""발행 직전 '근거 없는 1인칭 경험·방문·사용 후기 주장'을 차단하는 게이트 (AIOPS-59).

왜 필요한가
──────────
2026-11-26 발행 3편이 모두 "직접 겪었다/방문했다"고 썼습니다. 탐지 규칙은
experience_audit.py에 있었지만 사후 감사에만 쓰였고, 발행 경로에는 본문을
검사하는 결정론적 게이트가 없었습니다. 팩트체크는 본문 앞 3,500자·최대 5건만
보고, 하나라도 고치면 미수정 지적이 남아도 발행했습니다.

규칙
────
차단: 글쓴이가 했다는 주장 — 방문·사용·구매·시청·전화·피해·습관, "제 경험",
      "직접 해본 후기" 류의 제목, "개인적인 경험을 바탕으로" 류의 문구
허용: 공개 정보 기반 서술("공식 안내에 따르면", "이용자 후기를 종합하면"),
      의견("개인적으로는", "저라면"), 독자 권유("직접 확인하세요")
예외: author_profile.json에 해당 주제·블로그의 실제 경험 자료(summary)가 있는 글

검사 중 오류가 나면 통과시키지 않고 보류합니다.
"""
import logging
import re

from experience_audit import _sentences, _strip_html, analyze_text
from title_policy import check_title

logger = logging.getLogger(__name__)

# 앞에 한글이 붙으면 1인칭이 아닙니다 (문제가·실제가·국내가).
_FIRST_PERSON = re.compile(
    r"(?<![가-힣])(?:저는|제가|저도|저\s*역시|저희(?:는|가|도)?|내가|"
    r"필자(?:는|가|도)?|작성자(?:는|가|도)?|글쓴이(?:는|가|도)?)"
)
# 1인칭 뒤에 오면 '했다'는 주장이 되는 표현
_EXPERIENCED = re.compile(
    r"기억이\s*(?:있|나|납)|경험이\s*있|(?:본|간|한|온)\s*적(?:이|은|도)?\s*있|"
    r"해\s*봤|해\s*보았|써\s*봤|가\s*봤|먹어\s*봤|다녀(?:왔|온|와)|"
    r"방문(?:한|했|해\s*(?:확인|본|보니))|돌아(?:본|봤|보니)|돌며|들렀|"
    r"들러(?!\s*(?:보시|보세요|보길|보는|볼))|겪(?:은|었)|걸렸|애를\s*먹|"
    r"수월했|받았|뒤적였|전화(?:했|를\s*걸었)|"
    r"직접\s*(?:확인|조사|비교|계산)(?:한|했|해\s*보니)|(?:년|개월|달|주)\s*째"
)
# "개인적인 경험을 바탕으로 작성" 류 — 1인칭 주어 없이도 경험을 표방합니다.
_EXPERIENCE_BASIS = re.compile(
    r"(?:개인(?:적인)?|실제|직접)\s*경험(?:과|을|,|\s*및)[^.!?]{0,40}?(?:바탕|토대|기반)"
)
_OTHERS = re.compile(r"이용자|사용자|참석자|방문객|여행객|수험생|커뮤니티|후기(?:를|들)")
_INTENT_OR_ADVICE = re.compile(
    r"해\s*보고\s*싶|해\s*보(?:시|세요|는\s*(?:것|편|게))|싶다(?:면|는)"
)
_OPINION = re.compile(
    r"저라면|제\s*생각|제가\s*보기|추천(?:합니다|해요|드립니다)|권합니다|"
    r"(?:낫|좋)다고\s*(?:봅니다|생각)"
)
_FACTCHECK_EXPERIENCE = re.compile(r"1인칭|체험\s*(?:담|주장)|경험\s*(?:담|주장)")


def _hit(where: str, label: str, excerpt: str) -> dict:
    return {"where": where, "label": label, "excerpt": excerpt[:160]}


def _scan_title(title: str) -> list[dict]:
    return [_hit("title", v, title)
            for v in check_title(title) if v.startswith("경험 주장")]


def _scan_text(text: str, where: str) -> list[dict]:
    hits: list[dict] = []
    for sentence in _sentences(text):
        first = _FIRST_PERSON.search(sentence)
        experienced = _EXPERIENCED.search(sentence, first.end()) if first else None
        if experienced:
            hits.append(_hit(where, "1인칭 경험·방문·사용 주장", sentence))
            continue
        if _EXPERIENCE_BASIS.search(sentence) and not _OTHERS.search(sentence):
            hits.append(_hit(where, "경험 기반 작성 표방", sentence))
            continue
        for h in analyze_text(sentence, title_mode=True):
            if h["severity"] not in ("critical", "high"):
                continue
            label = h["label"]
            if "1인칭" in label and (not first or _OPINION.search(sentence)):
                continue
            if label == "'겪은' 경험 서술" and not first:
                continue
            if not first and _INTENT_OR_ADVICE.search(sentence):
                continue
            hits.append(_hit(where, label, sentence))
    return hits


def check_experience_claims(post_data: dict, blog_id: str = "") -> list[dict]:
    """발행하면 안 되는 경험 주장 목록. 빈 리스트면 통과."""
    try:
        from content_generator import _match_experience
        blog_id = blog_id or post_data.get("blog_id") or ""
        if _match_experience(post_data.get("keyword") or "", blog_id):
            return []
        hits = _scan_title(post_data.get("title") or "")
        hits += _scan_text(_strip_html(post_data.get("content") or ""), "body")
        hits += _scan_text(post_data.get("meta_description") or "", "meta")
        # 팩트체크가 경험 주장을 지적하고도 못 고친 경우 (규칙이 놓친 표현 보완)
        for issue in (post_data.get("fact_check") or {}).get("issues") or []:
            problem = str(issue.get("problem", ""))
            if not issue.get("fixed") and _FACTCHECK_EXPERIENCE.search(problem):
                hits.append(_hit("fact_check", "팩트체크 미수정 경험 주장", problem))
        return hits
    except Exception as exc:  # 안전 게이트는 실패 시 닫힙니다
        logger.error(f"경험 주장 게이트 오류 — 발행 보류: {exc}")
        return [_hit("gate", "게이트 오류", str(exc))]


def format_reason(hits: list[dict]) -> str:
    """pending_reason에 넣을 한 줄 요약."""
    head = "; ".join(f"[{h['where']}] {h['excerpt'][:40]}" for h in hits[:3])
    return f"경험 주장 {len(hits)}건: {head}"[:200]
