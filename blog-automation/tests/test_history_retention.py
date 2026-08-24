"""실행 이력 보존 — 건수가 아니라 기간 기준.

100건 고정이던 시절에는 하루 9건씩 쌓이면 12일치밖에 남지 않았습니다.
발행량이 늘수록 보존 기간이 저절로 짧아지는 구조라, 월 단위 추세를 볼 수
없었습니다.
"""

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dashboard_exporter import (  # noqa: E402
    HISTORY_DETAIL_KEEP_DAYS,
    HISTORY_KEEP_DAYS,
    _trim_history,
)

NOW = datetime(2026, 8, 22, 12, 0, 0)


def _entry(days_ago, with_posts=True):
    e = {
        "runAt": (NOW - timedelta(days=days_ago)).isoformat(),
        "date": (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%d"),
        "postsGenerated": 1,
        "bloggerUploaded": 1,
    }
    if with_posts:
        e["posts"] = [{"title": "글", "faq": [{"q": "q", "a": "a"}]}]
    return e


def test_keeps_recent_entries_whole():
    out = _trim_history([_entry(1), _entry(10)], now=NOW)
    assert len(out) == 2
    assert all("posts" in e for e in out)


def test_drops_entries_older_than_keep_days():
    out = _trim_history([_entry(HISTORY_KEEP_DAYS - 1), _entry(HISTORY_KEEP_DAYS + 1)], now=NOW)
    assert len(out) == 1


def test_old_entries_keep_totals_but_lose_post_details():
    """오래된 기록도 집계는 남습니다 — 추세를 보려고 늘린 것이니까요."""
    out = _trim_history([_entry(HISTORY_DETAIL_KEEP_DAYS + 5)], now=NOW)
    assert len(out) == 1
    assert "posts" not in out[0]
    assert out[0]["postsTrimmed"] is True
    assert out[0]["postsGenerated"] == 1      # 집계는 그대로
    assert out[0]["bloggerUploaded"] == 1


def test_retention_is_longer_than_the_old_fixed_count():
    """하루 9건씩 쌓여도 90일이 남는지 — 예전 100건 고정의 실패를 고정합니다."""
    history = []
    for day in range(120):
        history.extend(_entry(day) for _ in range(9))
    out = _trim_history(history, now=NOW)
    days = {e["date"] for e in out}
    assert len(days) == HISTORY_KEEP_DAYS + 1, f"보존 일수 {len(days)}일"
    assert len(out) > 100, "건수 기준이던 시절보다 많이 남아야 합니다"


def test_unparseable_timestamp_is_kept():
    """시각을 못 읽으면 남깁니다 — 지운 기록은 되돌릴 수 없습니다."""
    out = _trim_history([{"runAt": "", "postsGenerated": 1},
                         {"postsGenerated": 1},
                         {"runAt": "언젠가", "postsGenerated": 1}], now=NOW)
    assert len(out) == 3


def test_empty_history():
    assert _trim_history([], now=NOW) == []
