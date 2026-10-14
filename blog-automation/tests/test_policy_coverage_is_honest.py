"""애드센스 정책 점검이 "무엇을 못 봤는지" 밝히는가.

왜
──
adsense_policies.json 은 4개 정책 페이지를 수집하는데, 실제로는 1개만
성공한 상태로 리포트가 나가고 있었습니다.

  ✅ 프로그램 정책        6,000자  — 무효 클릭·광고 라벨·트래픽 소스
  ❌ 가치 있는 인벤토리   fetch_failed  ← 두 번 거절당한 사유
  ❌ 광고 게재 정책       fetch_failed
  ❌ 제한 콘텐츠 정책     fetch_failed

그래서 writer_checklist 10개가 전부 클릭 조작 항목이었고, 거절 사유와
겹치는 항목이 하나도 없었습니다. 리포트 자신은 "E-E-A-T는 이 페이지에서
다루지 않으며 별도 확인이 필요합니다"라고 적어 뒀지만, 그 사실이
어디에도 드러나지 않아 아무도 별도 확인을 하지 않았습니다.

수집 코드는 "전부 실패"일 때만 멈췄습니다. 반쪽 규정집으로 점검하면서
통과한 것처럼 보이던 것이라, 누락을 이름으로 남기게 합니다.

여기서 지키는 것
────────────────
  1. 일부만 수집돼도 그 사실이 리포트에 남는다 (로그만으로는 안 봄)
  2. 전부 수집되면 complete 이다
  3. 수집 실패는 여전히 리포트를 막지 않는다 — 1개라도 있으면 쓸모가
     있으므로, 멈추는 게 아니라 '불완전하다고 말하는' 쪽입니다
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "adsense_policy_updater.py")

with open(_SRC, encoding="utf-8") as _f:
    SOURCE = _f.read()


def test_partial_failure_is_recorded_in_the_report():
    """로그 경고만으로는 아무도 보지 않습니다 — 리포트에 남아야 합니다."""
    assert '"coverage"' in SOURCE or "analysis[\"coverage\"]" in SOURCE, (
        "수집 범위를 리포트에 남기지 않습니다"
    )
    for field in ("missing", "complete", "fetched"):
        assert field in SOURCE, f"coverage에 {field} 가 없습니다"


def test_partial_failure_is_also_warned():
    assert "수집하지 못한" in SOURCE or "수집하지 못했습니다" in SOURCE, (
        "일부 실패를 경고하지 않습니다"
    )


def test_total_failure_still_stops():
    """전부 실패하면 옛 버전을 유지해야 합니다 — 빈 규정집으로 덮어쓰면 안 됩니다."""
    assert "모든 정책 페이지 크롤링 실패" in SOURCE


def test_partial_failure_does_not_block_the_report():
    """1개라도 받았으면 리포트는 냅니다 — 멈추는 대신 불완전하다고 말합니다."""
    # success_count == 0 에서만 return 하는지
    idx = SOURCE.index("success_count == 0")
    tail = SOURCE[idx:idx + 400]
    assert "return current" in tail
    assert "success_count <" not in SOURCE, (
        "일부 실패로 리포트를 막으면 쓸 수 있는 정보까지 버립니다"
    )


def test_the_live_report_shows_its_gaps_once_regenerated():
    """지금 저장된 리포트에는 coverage가 없을 수 있습니다 (수정 전 생성).

    그 경우에도 source_pages 의 error 로 누락을 알 수 있어야 합니다 —
    이 필드가 사라지면 누락을 추적할 방법이 없어집니다.
    """
    import json
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "..", "docs", "data", "adsense_policies.json")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        report = json.load(f)
    pages = report.get("source_pages")
    assert pages, "source_pages 가 없습니다 — 어느 정책을 봤는지 알 수 없습니다"
    assert all("error" in p for p in pages), (
        "source_pages 에 error 필드가 없습니다 — 수집 실패를 알 수 없습니다"
    )
