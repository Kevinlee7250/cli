"""시즌 이벤트 실제 날짜 (2026-11-29 · 결재 사무실 기능 11).

주의: 03 업무 매뉴얼 '테스트 중단 규칙'에 따라 작성만 했고 실행하지 않았습니다.
"""

from datetime import datetime, timezone

import season_calendar as C


def test_chuseok_uses_real_date():
    """2026: 추석이 9/1로 잡혀 PR #116 만료 규칙(행사 3일 뒤)과 만나면 9/4에 키워드가 만료됐다."""
    d, basis = C.resolve({"name": "추석준비", "month": 9, "day": 1}, 2026)
    assert (d.date().isoformat(), basis) == ("2026-09-25", "exact")


def test_seollal_2027_from_kasi_table():
    d, _ = C.resolve({"name": "설날연휴", "month": 1, "day": 20}, 2027)
    assert d.date().isoformat() == "2027-02-07"


def test_black_friday_rule():
    assert [C._black_friday(y).date().isoformat() for y in (2026, 2027)] == ["2026-11-27", "2027-11-26"]


def test_missing_year_is_marked():
    _, basis = C.resolve({"name": "수능", "month": 11, "day": 14}, 2030)
    assert basis == "missing"
