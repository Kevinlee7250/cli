"""색인율 연동 발행 조절 (2026-11-29 · 결재 사무실 기능 12).

주의: 03 업무 매뉴얼 '테스트 중단 규칙'에 따라 작성만 했고 실행하지 않았습니다.
"""

import json
from datetime import datetime, timezone

import index_throttle as I


def _status(tmp_path, n, indexed, checked="2026-11-28T05:00:00+00:00"):
    items = [{"site": "https://www.hoguwhat.com/", "verdict": "indexed" if i < indexed else "not_indexed"} for i in range(n)]
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"checked_at": checked, "items": items}), encoding="utf-8")
    return str(p)


def _reg(tmp_path, published_at):
    p = tmp_path / "r.json"
    p.write_text(json.dumps([{"blogId": "blog1", "status": "published", "publishedAt": published_at}]), encoding="utf-8")
    return str(p)


CFG = {"id": "blog1", "name": "HOGU What?", "gsc_site_url": "https://www.hoguwhat.com/"}
NOW = datetime(2026, 11, 28, 22, 0, tzinfo=timezone.utc)  # 11/29 07:00 KST


def test_low_rate_skips_next_day(tmp_path):
    d = I.decide(CFG, NOW, _status(tmp_path, 16, 0), _reg(tmp_path, "2026-11-28T04:05:55"))
    assert d["skip"] is True


def test_low_rate_publishes_after_gap(tmp_path):
    d = I.decide(CFG, NOW, _status(tmp_path, 16, 0), _reg(tmp_path, "2026-11-27T04:05:55"))
    assert d["skip"] is False


def test_stale_or_small_sample_never_blocks(tmp_path):
    assert I.decide(CFG, NOW, _status(tmp_path, 16, 0, "2026-11-20T00:00:00+00:00"), _reg(tmp_path, "2026-11-28T04:00:00"))["skip"] is False
    assert I.decide(CFG, NOW, _status(tmp_path, 5, 0), _reg(tmp_path, "2026-11-28T04:00:00"))["skip"] is False


def test_flag_is_off_by_default():
    with open(I.os.path.join(I.HERE, "feature_flags.json"), encoding="utf-8") as f:
        assert json.load(f)["index_rate_throttle"] is False
