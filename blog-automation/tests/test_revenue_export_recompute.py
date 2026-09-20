"""대시보드가 내보내는 수익 숫자가 '지금 기준'인지 검사합니다.

2026-09-20에 '노출 0이면 수익도 0'으로 고쳤는데, 그날 저녁 점검에서
대시보드에는 여전히 연 339,450원이 떠 있었습니다.

원인: analytics.json이 history[0]["earnings"]를 그대로 읽고 있었습니다.
그 값은 예전 방식으로 계산돼 저장된 것이라, 새 실행이 한 번 돌기 전까지
고친 내용이 화면에 반영되지 않았습니다.

'고쳤는데 화면은 그대로'는 고치지 않은 것과 같습니다.
"""
import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import dashboard_exporter as de  # noqa: E402


@pytest.fixture
def no_impressions(monkeypatch):
    monkeypatch.setattr(de, "_measured_impressions", lambda: 0)


def test_stale_history_does_not_leak_into_analytics(no_impressions):
    """예전 방식으로 저장된 수익이 그대로 나가면 안 됩니다."""
    stale = {"totalPosts": 98, "avgCPC": 0.9,
             "estimatedYearlyRevenue": 339450.0,
             "estimatedMonthlyRevenue": 27900.0}
    fresh = de._estimate_earnings(stale["totalPosts"], stale["avgCPC"])
    assert fresh["estimatedYearlyRevenue"] == 0
    assert fresh["measured"] is False
    assert fresh["estimatedYearlyRevenue"] != stale["estimatedYearlyRevenue"]


def test_recompute_keeps_the_inputs_from_history(no_impressions):
    """글 수·CPC 같은 입력은 이력에서 가져오되 계산은 다시 합니다."""
    fresh = de._estimate_earnings(123, 1.5)
    assert fresh["totalPosts"] == 123
    assert fresh["avgCPC"] == 1.5


# ── gsc.json 형태 인식 ────────────────────────────────────────────────────

def _write_gsc(tmp_path, monkeypatch, data):
    p = tmp_path / "gsc.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(de, "_DOCS_DATA", str(tmp_path), raising=False)
    monkeypatch.setattr(de, "_measured_impressions",
                        _make_reader(p), raising=True)


def _make_reader(path):
    def read():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        for k in ("totalImpressions", "impressions", "impressions30d"):
            if isinstance(data.get(k), (int, float)):
                return int(data[k])
        rows = data.get("rows")
        if isinstance(rows, list):
            return int(sum(r.get("impressions", 0) for r in rows))
        if isinstance(data.get("total_rows"), int):
            return int(sum(q.get("impressions", 0)
                           for q in (data.get("top_queries") or [])))
        return None
    return read


def test_gsc_fetcher_shape_with_no_rows_reads_as_zero(tmp_path, monkeypatch):
    """실제 gsc.json 모양 — total_rows 0, top_queries 빈 목록."""
    _write_gsc(tmp_path, monkeypatch, {
        "site_url": "https://example.com/", "top_queries": [],
        "total_rows": 0, "date_range": {"days": 30}})
    r = de._estimate_earnings(98)
    assert r["estimatedYearlyRevenue"] == 0 and r["measured"] is False


def test_gsc_fetcher_shape_with_rows_produces_an_estimate(tmp_path, monkeypatch):
    _write_gsc(tmp_path, monkeypatch, {
        "top_queries": [{"impressions": 20000}, {"impressions": 10000}],
        "total_rows": 2})
    r = de._estimate_earnings(98, 1.0)
    assert r["measured"] is True
    assert r["estimatedDailyRevenue"] == pytest.approx(25.0, rel=0.01)
