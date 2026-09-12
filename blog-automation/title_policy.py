"""제목 정책 검사 — AdSense "오해의 소지가 있는 콘텐츠" 정책 사전 차단.

기존에는 발행이 끝난 뒤 adsense_audit.py가 낚시성 제목을 "발견"만 했음
(실제로 blog2 감사에서 '헐' 1건 검출). 이미 게시된 뒤라 정책 위반 상태가
그대로 노출되므로, 생성 단계에서 걸러 재작성을 요청하는 편이 안전하다.

읽기 난이도 검사(readability_checker)와 동일한 패턴으로 content_generator의
재시도 루프에 연결되며, 재시도가 소진되면 sanitize_title()로 위반 표현만
제거해 발행은 계속한다(글 전체를 버리지 않음).

2026-09-12 추가 — 지어낸 경험 주장
────────────────────────────────
AdSense가 hoguwhat.com을 "가치가 별로 없는 콘텐츠"로 거절했고, 원인은
하지 않은 경험을 했다고 쓴 글 39편이었다. 본문은 2026-08-26
`_experience_style_block`으로 막혔지만 **제목은 무방비**였다 — 가드레일
이후인 9월 발행분에도 경험 주장 제목이 남아 있다.

제목은 검색 결과와 SNS 카드에 그대로 노출되므로 본문보다 먼저 읽힌다.
본문을 조사형으로 써도 제목이 "직접 써본 후기"면 독자와 심사관 모두
경험담으로 받아들인다. 그래서 같은 기준을 제목에도 적용한다.

author_profile.json에 실제 경험 자료가 있는 글은 예외다
(`check_title(..., allow_experience=True)`).
"""

import re

# 클릭 유도·과장 표현 — AdSense 정책상 "오해의 소지가 있는" 제목으로 판정될 수 있는 어휘.
# adsense_audit.py의 사후 감사와 동일 기준을 쓰도록 이 모듈을 단일 출처로 삼는다.
CLICKBAIT_TERMS = [
    "충격", "경악", "미쳤다", "대박", "헐", "소름", "절대 하지 마",
    "100% 보장", "무조건 벌", "확실한 수익", "실화냐", "레전드",
    "이것만 알면", "돈 복사", "月수익 보장",
]

# 지어낸 경험 주장 — experience_audit.py와 같은 기준을 쓴다.
# 두 곳이 어긋나면 생성은 통과시키고 감사만 지적하는 상태가 된다.
EXPERIENCE_PATTERNS = [
    (re.compile(r"직접\s*[가-힣]{0,3}?(해|써|사용|가|다녀|먹|살|예약|신청|청구|받|타|읽|보|체험)"
                r"[가-힣]{0,2}?\s*(봤|본|보니|보고|와서|왔)"), "직접 ~해봤"),
    (re.compile(r"(해봤|써봤|가봤|먹어봤|다녀왔|살아봤|겪었|겪어봤)"), "경험 완료형"),
    (re.compile(r"(제가|저는|내가)\s*[^\n]{0,20}?"
                r"(겪은|경험한|해\s*본|써\s*본|가\s*본|살아\s*본)"), "1인칭 경험 수식"),
    (re.compile(r"\d+\s*(개월|주|년|일|주일)\s*(동안\s*)?(직접\s*|실제로\s*)?"
                r"[가-힣]{0,3}?(써|사용|해|살|타|먹|다녀)\s*(봤|본|보니)"), "기간 + 사용 주장"),
    (re.compile(r"겪(은|었|어\s*본)"), "'겪은' 경험 서술"),
    (re.compile(r"솔직(한)?\s*(후기|리뷰|비교|정리|평가|장단점)"), "솔직 후기"),
    (re.compile(r"(실제|실사용)\s*[가-힣A-Za-z0-9·\s]{0,12}?(후기|경험|사용기)"), "실제 후기 표방"),
    (re.compile(r"(해\s*본|써\s*본|다녀온|가\s*본)\s*(후기|리뷰|경험)"), "~해본 후기"),
    (re.compile(r"정산한\s*(실제|직접)?\s*(생활비|비용|지출)"), "실제 정산 공개"),
]

# 재시도가 소진됐을 때 제목을 버리지 않고 조사형으로 바꾸는 치환표.
# 순서가 중요하다 — 긴 표현을 먼저 지워야 짧은 표현이 조각을 남기지 않는다.
_EXPERIENCE_REWRITES = [
    # 기간이 붙은 형태를 먼저 통째로 바꿉니다. 뒤의 '직접~' 규칙이 먼저 돌면
    # "3개월 직접 써본 후기"가 "3개월 총정리 후기"라는 이상한 말이 됩니다.
    (re.compile(r"(\d+\s*(?:개월|주|년|일))\s*(?:동안\s*)?(?:직접\s*|실제로\s*)?"
                r"[가-힣]{0,3}?(?:써|사용|해|살|타|먹|다녀)\s*(?:봤|본|보니)\s*"
                r"(?:솔직(?:한)?\s*)?(?:후기|리뷰|장단점|평가|비교)?"), r"\1 사용 후기 종합"),
    (re.compile(r"직접\s*[가-힣]{0,3}?(써|사용|해|가|다녀|먹|살|예약|신청|청구|읽)"
                r"[가-힣]{0,2}?\s*(봤더니|봤습니다|본|봤|보니|보고|와서|왔)"), "총정리"),
    (re.compile(r"솔직(한)?\s*후기"), "후기 종합"),
    (re.compile(r"솔직(한)?\s*(리뷰|평가)"), "평가 정리"),
    (re.compile(r"솔직(한)?\s*(비교|정리|장단점)"), "비교 정리"),
    (re.compile(r"(실제|실사용)\s*후기"), "이용 후기 종합"),
    (re.compile(r"(해\s*본|써\s*본|다녀온|가\s*본)\s*(후기|리뷰)"), "후기 종합"),
    (re.compile(r"(제가|저는|내가)\s*겪은\s*(실제\s*)?"), ""),
    (re.compile(r"겪은\s*"), ""),
    (re.compile(r"정산한\s*(실제|직접)?\s*"), ""),
    (re.compile(r"직접\s*(비교|정리|확인|점검|계산)"), r"\1"),
]

# 표현을 제거한 뒤 남는 군더더기 기호·접속어 정리용
_LEADING_JUNK = re.compile(r"^[\s,.!?~·—\-–…]+")
_TRAILING_JUNK = re.compile(r"[\s,.!?~·—\-–…]+$")
_MULTI_SPACE = re.compile(r"\s{2,}")


def check_title(title: str, *, allow_experience: bool = False) -> list[str]:
    """제목의 정책 위반 목록을 반환합니다 (없으면 빈 리스트).

    allow_experience=True 이면 경험 주장 검사를 건너뜁니다 —
    author_profile.json에 실제 경험 자료가 있는 글은 1인칭이 정당합니다.
    """
    if not title:
        return []
    lowered = title.lower()
    out = [t for t in CLICKBAIT_TERMS if t.lower() in lowered]
    if not allow_experience:
        out += [f"경험 주장: {label}" for pat, label in EXPERIENCE_PATTERNS
                if pat.search(title)]
    return out


def sanitize_title(title: str, *, allow_experience: bool = False) -> str:
    """위반 표현만 제거한 제목을 반환합니다 (재시도 소진 시 최후 수단).

    글 전체를 폐기하는 대신 제목의 문제 어휘만 덜어내고 발행을 이어간다.
    제거 후 제목이 너무 짧아지면(10자 미만) 원본을 유지해 무의미한 제목이
    나가는 것을 막는다 — 그 경우는 감사 리포트로 수동 처리 대상이 된다.
    """
    if not title:
        return title
    cleaned = title
    for term in CLICKBAIT_TERMS:
        cleaned = re.sub(re.escape(term), "", cleaned, flags=re.IGNORECASE)
    if not allow_experience:
        # 경험 주장은 지우기만 하면 "여수 숙소 가성비 비교," 처럼 문장이
        # 끊기므로, 삭제 대신 조사형 표현으로 갈아끼웁니다.
        for pat, repl in _EXPERIENCE_REWRITES:
            cleaned = pat.sub(repl, cleaned)
    cleaned = _MULTI_SPACE.sub(" ", cleaned)
    # 치환이 겹치면 "비교 정리 정리"처럼 같은 말이 붙습니다 — 하나로 줄입니다.
    cleaned = re.sub(r"\b([가-힣]{2,4})(\s+\1)+\b", r"\1", cleaned)
    cleaned = re.sub(r"(후기)\s*(종합)\s*\1", r"\1 \2", cleaned)
    # 치환이 겹치면 마무리 상투어가 줄줄이 붙습니다
    # ("… 총정리 평가 정리 총정리"). 맨 뒤 하나만 남깁니다.
    _FILLER = r"(?:총정리|정리|가이드|모음|안내)"
    cleaned = re.sub(rf"(?:\s*{_FILLER}){{2,}}\s*$", " 총정리", cleaned)
    cleaned = _LEADING_JUNK.sub("", cleaned)
    cleaned = _TRAILING_JUNK.sub("", cleaned).strip()
    return cleaned if len(cleaned) >= 10 else title


def title_escalation_note(violations: list[str]) -> str:
    """제목 재작성 요청용 프롬프트 보강 문구."""
    if not violations:
        return ""
    terms = ", ".join(f'"{v}"' for v in violations)
    # 경험 주장과 클릭 유도는 고치는 방향이 다릅니다. 전자는 "표현을 빼라"가
    # 아니라 "근거를 바꿔라"이므로 별도 지시를 얹습니다.
    exp_note = ""
    if any(v.startswith("경험 주장") for v in violations):
        exp_note = (
            "\n🚫 [경험 주장 제목 금지]\n"
            "제목이 하지 않은 경험을 한 것처럼 말하고 있습니다. 본문이 조사·분석형인데\n"
            "제목만 체험담이면 독자를 오도하는 것이고, AdSense '가치가 별로 없는 콘텐츠'\n"
            "판정의 직접적인 사유가 됩니다 (2026-09-12 hoguwhat.com 실제 거절 사유).\n"
            "  ✗ \"3개월 직접 써본 후기\"  → ✓ \"3개월 사용 후기 종합\"\n"
            "  ✗ \"제가 겪은 실제 절차\"    → ✓ \"공식 안내 기준 절차 정리\"\n"
            "  ✗ \"직접 다녀온 솔직 후기\"  → ✓ \"방문 후기 종합과 체크리스트\"\n"
            "  ✗ \"정산한 실제 생활비\"      → ✓ \"생활비 얼마나 드나, 사례 종합\"\n"
            "실제로 조사한 내용만 제목에 담으세요. 조사형도 충분히 구체적일 수 있습니다.\n"
        )
    clickbait_note = ""
    if any(not v.startswith("경험 주장") for v in violations):
        clickbait_note = (
            f"\n\n⚠️⚠️⚠️ [제목 재작성 요청] 이전 제목에 클릭 유도·과장 표현({terms})이 있었습니다.\n"
            "구글 애드센스 '오해의 소지가 있는 콘텐츠' 정책 위반 소지가 있습니다.\n"
            "이번에는 반드시:\n"
            "  - 위 표현을 쓰지 말고, 글이 실제로 다루는 내용만 제목에 담을 것\n"
            "  - 궁금증은 과장이 아니라 '구체적인 정보'로 유발할 것\n"
            "    나쁜 예: \"충격! 이것만 알면 대박\" / 좋은 예: \"요금제 3종 비교, 가격 차이 3배\"\n"
            "⚠️⚠️⚠️\n"
        )
    return exp_note + clickbait_note
