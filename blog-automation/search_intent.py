"""키워드 검색의도 분류 — 같은 주제라도 독자가 원하는 답의 형태가 다르다.

content_generator의 _detect_article_type()은 "무엇에 대한 글인가"(여행/드라마/
투자)를 봅니다. 이 모듈은 그와 직교하는 축인 "독자가 무엇을 원하는가"를
판별합니다. 두 축이 합쳐져야 글의 형태가 정해집니다.

  "부산 여행 예산"     → travel_guide + transactional (비용을 먼저 보여줘야 함)
  "부산 여행 후기"     → travel_guide + experience    (구체적 경험·수치가 핵심)
  "부산 vs 제주"       → travel_guide + comparison    (비교표 없으면 이탈)

규칙 기반이라 API 호출 비용이 없고, 매 글 생성마다 부담 없이 적용됩니다.
research_collector.analyze_search_intent()와는 목적이 다릅니다 — 그쪽은
자료 조사용 검색어를 뽑는 것이고, 이쪽은 글의 서술 방식을 결정합니다.
"""

import re

# 판별 순서가 중요 — 앞쪽이 더 구체적인 신호.
# 예: "ETF 수수료 비교 후기"는 비교 의도가 우선(표가 없으면 목적 미달성).
_INTENT_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("comparison", (
        "비교", "vs", "차이", "어떤 게", "어느 게", "뭐가 나은", "뭐가 좋", "장단점",
        "대안", "추천 순위", "순위 정리", "best", "top ",
    )),
    ("transactional", (
        "가격", "비용", "얼마", "요금", "수수료", "할인", "최저가", "예약", "신청",
        "구매", "가입", "결제", "환불", "예산", "견적",
    )),
    ("experience", (
        "후기", "리뷰", "해봤", "가봤", "써봤", "먹어봤", "실제로", "직접", "체험",
        "솔직", "1년", "한 달", "경험담",
    )),
    ("howto", (
        "방법", "하는 법", "하는법", "어떻게", "설정", "사용법", "가이드", "따라하기",
        "준비물", "절차", "신청서", "만들기", "고르는", "선택하는", "체크리스트",
    )),
]

_INTENT_LABELS = {
    "informational": "정보형 (개념·현황을 알고 싶어 함)",
    "howto": "방법형 (직접 하려고 함)",
    "comparison": "비교형 (선택하려고 함)",
    "experience": "후기형 (남의 실제 경험이 궁금함)",
    "transactional": "거래형 (비용·조건을 확인하려 함)",
}

# 의도별로 글에 반드시 들어가야 하는 것 — 없으면 독자의 목적이 달성되지 않아 이탈한다.
_INTENT_DIRECTIVES = {
    "informational": (
        "- 첫 H2에서 핵심 개념·현황을 한 문단으로 명확히 정의하고 시작하세요.\n"
        "- 배경 → 현재 상황 → 앞으로의 전망 순으로 전개하세요.\n"
        "- 전문용어는 처음 나올 때 바로 쉬운 말로 풀어주세요."
    ),
    "howto": (
        "- 번호가 붙은 단계별 절차(1단계, 2단계…)를 반드시 포함하세요.\n"
        "- 시작 전 준비물·전제 조건을 절차보다 먼저 정리하세요.\n"
        "- 각 단계마다 '이때 흔히 하는 실수'를 한 줄씩 덧붙이세요.\n"
        "- 소요 시간이나 난이도를 알 수 있으면 명시하세요."
    ),
    "comparison": (
        "- 비교 대상을 나란히 놓은 <table> 표를 반드시 포함하세요 (항목 3개 이상).\n"
        "- 표 뒤에 '어떤 상황이면 무엇을 고르면 되는지'를 상황별로 정리하세요.\n"
        "- 한쪽을 무조건 추천하지 말고, 각각이 유리한 조건을 함께 밝히세요.\n"
        "- 비교 기준(가격·성능·조건 등)을 먼저 설명한 뒤 비교하세요."
    ),
    "experience": (
        "- 기간·금액·횟수 같은 구체적인 수치를 본문에 포함하세요.\n"
        "- 좋았던 점만 쓰지 말고 아쉬웠던 점·예상과 달랐던 점도 함께 쓰세요.\n"
        "- 다시 한다면 무엇을 바꿀지 정리해 마무리하세요.\n"
        "- 단, 자료로 확인되지 않은 경험을 지어내지는 마세요 — "
        "직접 경험 자료가 없으면 조사한 사례·후기를 인용하는 형식으로 쓰세요."
    ),
    "transactional": (
        "- 비용·가격 정보를 글 앞부분(첫 두 H2 안)에 배치하세요. 뒤로 미루면 이탈합니다.\n"
        "- 가격이 조건에 따라 달라지면 조건별로 표에 정리하세요.\n"
        "- 신청·예약 절차가 있으면 순서대로 정리하세요.\n"
        "- 확인되지 않은 가격은 단정하지 말고 '기준 시점'을 함께 밝히세요."
    ),
}


def detect_intent(keyword: str) -> str:
    """키워드에서 검색의도를 판별합니다 (기본값: informational)."""
    if not keyword:
        return "informational"
    kw = keyword.lower()
    for intent, patterns in _INTENT_PATTERNS:
        if any(p in kw for p in patterns):
            return intent
    return "informational"


def intent_label(intent: str) -> str:
    return _INTENT_LABELS.get(intent, _INTENT_LABELS["informational"])


def intent_prompt_block(keyword: str) -> str:
    """검색의도에 맞는 서술 지침 블록을 반환합니다."""
    intent = detect_intent(keyword)
    directives = _INTENT_DIRECTIVES.get(intent)
    if not directives:
        return ""
    return f"""

━━━ 검색의도별 필수 요소 — {intent_label(intent)} ━━━
이 키워드로 검색한 독자는 위 목적을 가지고 들어옵니다. 목적이 충족되지 않으면
바로 뒤로가기를 누르므로, 아래를 반드시 반영하세요.
{directives}"""
