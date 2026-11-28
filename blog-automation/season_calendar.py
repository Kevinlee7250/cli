"""시즌 이벤트의 '그해 실제 날짜'를 정합니다 (trend_scheduler 보조).

왜 필요한가
────────────
trend_scheduler.SEASONAL_EVENTS 는 음력·요일로 정해지는 날(설날·추석·수능 등)을
'평균 양력 날짜'로 적어 두었습니다(설날 1/20, 추석 9/1). 실제와 많게는 3주 넘게
어긋납니다 — 2026년 추석은 9/25인데 9/1로 잡혀 있었습니다.

2026-11-28 PR #116(AIOPS-65 ④)부터 시즌 키워드는 행사일(event_date) 3일 뒤에
만료됩니다. 행사일이 틀리면 추석 키워드가 추석 3주 전에 만료되는 식으로,
정작 검색이 몰리는 기간에 시즌 글이 빠집니다.

규칙
────
  1. EXACT 표에 그해 날짜가 있으면 그 날짜(basis="exact").
  2. 요일 규칙으로 계산되는 날(블랙프라이데이)은 계산(basis="rule").
  3. 둘 다 없으면 SEASONAL_EVENTS의 month/day 그대로(basis="approx").
     EXACT 표에 있는 이벤트인데 그해만 빠졌으면 basis="missing" — 탐지 범위에
     들어왔을 때 경고를 남겨, 표를 채워야 할 해가 왔다는 신호로 씁니다.

EXACT 표 출처 (확인 2026-11-29)
──────────────────────────────
  · 설날·추석·부처님오신날: 우주항공청 월력요항(2026·2027년),
    한국천문연구원 음양력 자료(astro.kasi.re.kr) — 2027 음력 1.1 = 양력 2.7,
    음력 8.1 = 양력 9.1(→ 8.15 = 9.15), 음력 4.1 = 양력 5.6(→ 4.8 = 5.13)
  · 수능: 교육부·한국교육과정평가원 — 2027학년도 2026-11-19,
    2028학년도 2027-11-18
  다음 해 월력요항(매년 6월 말 발표)이 나오면 표에 한 해를 더합니다.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

#: 이벤트 이름(SEASONAL_EVENTS의 name) → {연도: "YYYY-MM-DD"}
#: '추석준비'·'추석특선영화'는 추석 당일을 행사일로 둡니다(lead_days로 미리 시작).
_SEOLLAL = {2026: "2026-02-17", 2027: "2027-02-07"}
_CHUSEOK = {2026: "2026-09-25", 2027: "2027-09-15"}
EXACT: dict[str, dict[int, str]] = {
    "설날연휴": _SEOLLAL,
    "추석준비": _CHUSEOK,
    "추석특선영화": _CHUSEOK,
    "부처님오신날": {2026: "2026-05-24", 2027: "2027-05-13"},
    "수능": {2026: "2026-11-19", 2027: "2027-11-18"},
}


def _black_friday(year: int) -> datetime:
    """미국 추수감사절(11월 넷째 목요일) 다음 날."""
    d = datetime(year, 11, 1)
    first_thu = d + timedelta(days=(3 - d.weekday()) % 7)
    return first_thu + timedelta(days=21 + 1)


RULES = {"블랙프라이데이": _black_friday}


def resolve(ev: dict, year: int) -> tuple[datetime, str]:
    """(그해 행사일, 근거) — 근거는 exact / rule / approx / missing(표에 그해가 없음)."""
    name = ev.get("name", "")
    s = EXACT.get(name, {}).get(year)
    if s:
        return datetime.strptime(s, "%Y-%m-%d"), "exact"
    if name in RULES:
        return RULES[name](year), "rule"
    # 표에 있는 이벤트인데 그해가 비었으면 'missing' — 호출부가 탐지 범위 안일 때만 경고합니다
    # (매 실행마다 내년 날짜도 보므로, 여기서 경고하면 늘 시끄럽습니다).
    return datetime(year, ev["month"], ev["day"]), ("missing" if name in EXACT else "approx")
