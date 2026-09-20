"""수익 추정이 근거 없는 숫자를 만들지 않는지 검사합니다.

2026-09-19 대시보드: Search Console 노출이 **0인데 연 33만원**이 떠
있었습니다. '글 1편당 하루 80 페이지뷰'를 가정해 글 수에 곱한 값이었습니다.

근거 없는 숫자는 판단을 흐립니다. 특히 AdSense 재심사를 앞두고
"이 정도면 되겠지"라는 착각을 만듭니다.
"""
import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import dashboard_exporter as de  # noqa: E402


@pytest.fixture
def gsc(tmp_path, monkeypatch):
    """gsc.json을 임시 경로로 돌립니다."""
    path = tmp_path / "gsc.json"

    def write(data):
        if data is None:
            if path.exists():
                path.unlink()
        else:
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(de, "_measured_impressions",
                            _reader(path), raising=True)
    return write


def _reader(path):
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
        return None
    return read


def test_no_impressions_means_no_revenue_number(gsc):
    gsc({"totalImpressions": 0})
    r = de._estimate_earnings(post_count=98)
    assert r["estimatedYearlyRevenue"] == 0
    assert r["measured"] is False
    assert r["note"], "왜 0인지 이유가 없으면 '안 벌었다'와 구분이 안 됩니다"


def test_missing_gsc_file_means_no_revenue_number(gsc):
    gsc(None)
    r = de._estimate_earnings(post_count=98)
    assert r["estimatedYearlyRevenue"] == 0 and r["measured"] is False


def test_post_count_alone_never_creates_revenue(gsc):
    """글이 1,000편이어도 노출이 없으면 수익은 0입니다."""
    gsc({"totalImpressions": 0})
    assert de._estimate_earnings(post_count=1000)["estimatedYearlyRevenue"] == 0


def test_real_impressions_produce_an_estimate(gsc):
    gsc({"totalImpressions": 30000})
    r = de._estimate_earnings(post_count=98, avg_cpc=1.0)
    # 30,000/30일 = 1,000뷰/일 × 2.5% × $1.0 = $25/일
    assert r["measured"] is True
    assert r["estimatedDailyRevenue"] == pytest.approx(25.0, rel=0.01)
    assert r["estimatedYearlyRevenue"] == pytest.approx(25.0 * 365, rel=0.01)
    assert "30,000" in r["note"]


def test_estimate_scales_with_impressions_not_post_count(gsc):
    """같은 노출이면 글 수가 달라도 추정은 같아야 합니다."""
    gsc({"totalImpressions": 30000})
    a = de._estimate_earnings(post_count=10)
    b = de._estimate_earnings(post_count=1000)
    assert a["estimatedYearlyRevenue"] == b["estimatedYearlyRevenue"]


def test_rows_form_is_also_accepted(gsc):
    gsc({"rows": [{"impressions": 100}, {"impressions": 200}]})
    r = de._estimate_earnings(post_count=98)
    assert r["measured"] is True and r["estimatedDailyRevenue"] > 0
