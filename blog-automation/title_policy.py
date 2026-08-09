"""제목 정책 검사 — AdSense "오해의 소지가 있는 콘텐츠" 정책 사전 차단.

기존에는 발행이 끝난 뒤 adsense_audit.py가 낚시성 제목을 "발견"만 했음
(실제로 blog2 감사에서 '헐' 1건 검출). 이미 게시된 뒤라 정책 위반 상태가
그대로 노출되므로, 생성 단계에서 걸러 재작성을 요청하는 편이 안전하다.

읽기 난이도 검사(readability_checker)와 동일한 패턴으로 content_generator의
재시도 루프에 연결되며, 재시도가 소진되면 sanitize_title()로 위반 표현만
제거해 발행은 계속한다(글 전체를 버리지 않음).
"""

import re

# 클릭 유도·과장 표현 — AdSense 정책상 "오해의 소지가 있는" 제목으로 판정될 수 있는 어휘.
# adsense_audit.py의 사후 감사와 동일 기준을 쓰도록 이 모듈을 단일 출처로 삼는다.
CLICKBAIT_TERMS = [
    "충격", "경악", "미쳤다", "대박", "헐", "소름", "절대 하지 마",
    "100% 보장", "무조건 벌", "확실한 수익", "실화냐", "레전드",
    "이것만 알면", "돈 복사", "月수익 보장",
]

# 표현을 제거한 뒤 남는 군더더기 기호·접속어 정리용
_LEADING_JUNK = re.compile(r"^[\s,.!?~·—\-–…]+")
_TRAILING_JUNK = re.compile(r"[\s,.!?~·—\-–…]+$")
_MULTI_SPACE = re.compile(r"\s{2,}")


def check_title(title: str) -> list[str]:
    """제목에 포함된 클릭 유도·과장 표현 목록을 반환합니다 (없으면 빈 리스트)."""
    if not title:
        return []
    lowered = title.lower()
    return [t for t in CLICKBAIT_TERMS if t.lower() in lowered]


def sanitize_title(title: str) -> str:
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
    cleaned = _MULTI_SPACE.sub(" ", cleaned)
    cleaned = _LEADING_JUNK.sub("", cleaned)
    cleaned = _TRAILING_JUNK.sub("", cleaned).strip()
    return cleaned if len(cleaned) >= 10 else title


def title_escalation_note(violations: list[str]) -> str:
    """제목 재작성 요청용 프롬프트 보강 문구."""
    if not violations:
        return ""
    terms = ", ".join(f'"{v}"' for v in violations)
    return (
        f"\n\n⚠️⚠️⚠️ [제목 재작성 요청] 이전 제목에 클릭 유도·과장 표현({terms})이 있었습니다.\n"
        "구글 애드센스 '오해의 소지가 있는 콘텐츠' 정책 위반 소지가 있습니다.\n"
        "이번에는 반드시:\n"
        "  - 위 표현을 쓰지 말고, 글이 실제로 다루는 내용만 제목에 담을 것\n"
        "  - 궁금증은 과장이 아니라 '구체적인 정보'로 유발할 것\n"
        "    나쁜 예: \"충격! 이것만 알면 대박\" / 좋은 예: \"실제로 비교해보니 가격 차이가 3배였다\"\n"
        "⚠️⚠️⚠️\n"
    )
