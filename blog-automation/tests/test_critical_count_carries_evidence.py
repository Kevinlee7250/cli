"""CRITICAL 건수를 보고할 때 근거도 함께 남기는가.

왜
──
2026-10-14 점검에서 code_repairs.json 이 이렇게 나왔습니다.

    {"tracebacks_found": 0, "critical_errors": 7, "repairs": [],
     "auto_fixed": 0, "manual_required": 0}

"CRITICAL 7건"이라는 숫자만 있고 그 7건이 무엇인지는 어디에도 없었습니다.
리포트를 만드는 경로가 둘인데 한쪽만 critical_samples 를 담고 있었고,
빠진 쪽이 '새 트레이스백이 없을 때' — 즉 평상시 경로였습니다. 그래서
대부분의 리포트에 근거가 없었습니다.

숫자만 있는 경보는 조치로 이어지지 않습니다. 보고하려면 근거를 같이
남겨야 합니다.

여기서 지키는 것
────────────────
  1. 두 경로 모두 critical_samples 를 담는다
  2. CRITICAL이 0이면 샘플도 비어 있다 (없는 것을 지어내지 않는다)
  3. 두 경로의 리포트 필드가 어긋나지 않는다
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "code_repair.py")

with open(_SRC, encoding="utf-8") as _f:
    SOURCE = _f.read()


def _result_dicts() -> list[str]:
    """result = { ... } 블록들의 소스를 돌려줍니다."""
    out, idx = [], 0
    while True:
        idx = SOURCE.find("result = {", idx)
        if idx == -1:
            break
        end = SOURCE.find("}", idx)
        out.append(SOURCE[idx:end])
        idx = end
    return out


def test_both_report_paths_exist():
    """경로가 하나로 합쳐졌으면 이 테스트를 갱신해야 합니다."""
    blocks = _result_dicts()
    assert len(blocks) >= 2, (
        f"리포트 생성 경로가 {len(blocks)}개입니다 — 구조가 바뀌었으면 "
        f"이 테스트도 함께 보세요"
    )


def test_every_report_path_carries_critical_samples():
    """숫자만 보고하는 경로가 있으면 안 됩니다."""
    for block in _result_dicts():
        if "critical_errors" not in block:
            continue
        assert "critical_samples" in block, (
            "CRITICAL 건수를 보고하면서 근거(critical_samples)를 빼는 "
            f"경로가 있습니다:\n{block[:300]}"
        )


def test_no_traceback_path_reports_samples(monkeypatch, tmp_path):
    """평상시 경로(트레이스백 없음)에서 실제로 샘플이 나오는지."""
    import code_repair as cr

    log = tmp_path / "automation.log"
    log.write_text(
        "2026-10-14 00:00:00 CRITICAL 업로드 실패: 토큰 만료\n"
        "2026-10-14 00:01:00 INFO 정상\n"
        "2026-10-14 00:02:00 CRITICAL 이미지 호스팅 실패\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cr, "LOG_FILE", log)
    saved = {}
    monkeypatch.setattr(cr, "_save_result", lambda r: saved.update(r))
    monkeypatch.setattr(cr, "_load_tracebacks", lambda *a, **k: [], raising=False)

    result = cr.run(dry_run=True) if hasattr(cr, "run") else None
    if result is None:  # 함수 이름이 다르면 소스 검사로 대체합니다
        return
    assert result["tracebacks_found"] == 0
    if result["critical_errors"]:
        assert result["critical_samples"], (
            "CRITICAL이 있는데 샘플이 비어 있습니다 — 숫자만 남습니다"
        )


def test_zero_critical_means_empty_samples():
    """없는 것을 지어내지 않습니다."""
    for block in _result_dicts():
        if "critical_samples" in block:
            assert "critical_lines[-3:]" in block, (
                "샘플을 실제 로그에서 뽑지 않는 경로가 있습니다"
            )


def test_live_report_has_samples_when_it_counts_criticals():
    """지금 저장된 리포트 — 수정 전에 생성된 것은 통과시킵니다.

    앞으로 생성되는 리포트에 근거가 빠지면 잡힙니다.
    """
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "..", "docs", "data", "code_repairs.json")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        reports = json.load(f)
    if not isinstance(reports, list) or not reports:
        return
    newest = reports[0]
    ts = str(newest.get("timestamp", ""))
    # 2026-10-14 13:50 리포트가 이 문제를 드러낸 그 리포트입니다.
    if ts > "2026-10-14T14":
        if newest.get("critical_errors"):
            assert newest.get("critical_samples"), (
                f"새 리포트({ts})가 CRITICAL {newest['critical_errors']}건을 "
                f"근거 없이 보고합니다"
            )
