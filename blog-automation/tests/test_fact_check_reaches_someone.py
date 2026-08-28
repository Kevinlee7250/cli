"""팩트체크 결과가 실제로 어딘가에 닿는지 검사합니다.

지금까지 팩트체크는 결과를 기록만 하고 아무도 읽지 않았습니다.

  content_generator  → post_data["fact_check"] 기록
  dashboard_exporter → factCheck로 복사
                       ↓
                      끝. 발행도 안 막고 화면에도 안 나옴.

최근 초안 80편 중 68편이 warn이었고, 그중 8편은 이슈를 찾고도 한 건도
고치지 못한 채 발행됐습니다. 검사가 도는 것과 결과가 쓰이는 것은 다릅니다.

warn 전부를 막으면 85%가 걸려 파이프라인이 멈추므로, 실제로 위험한
"찾았는데 못 고친" 글만 pending으로 보냅니다.
"""

import ast
import os
import re

_SRC = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_DASH = os.path.normpath(os.path.join(_SRC, "..", "docs", "index.html"))


def _main_src():
    return open(os.path.join(_SRC, "main.py"), encoding="utf-8").read()


# ── B: 발행 경로가 팩트체크 결과를 실제로 본다 ──────────────────────────────

def test_publish_flow_reads_fact_check():
    src = _main_src()
    assert 'fact_check' in src, (
        "발행 경로가 팩트체크 결과를 전혀 보지 않습니다 — 검사만 돌고 "
        "결과가 아무 데도 닿지 않습니다"
    )


def test_unfixed_issues_go_to_pending_not_live():
    src = _main_src()
    assert "issues_found" in src and "fixes_applied" in src, (
        "찾은 이슈 수와 고친 수를 비교하지 않으면 '못 고친 글'을 가려낼 수 없습니다"
    )
    # 게이트가 pending으로 보내는지
    gate = src[src.index("fact_check"):]
    assert "PostStatus.PENDING" in gate[:2500], "미수정 글이 pending으로 가지 않습니다"


def test_gate_does_not_block_warn_wholesale():
    """warn은 최근 80편 중 68편(85%) — 전부 막으면 파이프라인이 멈춥니다."""
    src = _main_src()
    assert not re.search(r'verdict.*==.*["\']warn["\']', src), (
        "verdict == 'warn'으로 막으면 대부분의 글이 걸립니다. "
        "실제로 위험한 것은 '찾았는데 못 고친' 글입니다"
    )


def test_pending_reason_says_why():
    """왜 보류됐는지 남지 않으면 사람이 판단할 수 없습니다."""
    assert "pending_reason" in _main_src()


def test_gate_is_skipped_in_dry_run():
    """테스트·검토 모드에서는 발행 자체를 안 하므로 게이트도 무의미합니다."""
    src = _main_src()
    i = src.index("_unfixed")
    assert "dry_run or review" in src[i:i + 400]


# ── A: 결과가 화면에 닿는다 ─────────────────────────────────────────────────

def _dash():
    return open(_DASH, encoding="utf-8").read()


def test_dashboard_reads_fact_check():
    assert "factCheck" in _dash(), (
        "dashboard_exporter가 factCheck를 내보내는데 화면이 읽지 않습니다 — "
        "기록은 남지만 아무도 보지 않습니다"
    )


def test_dashboard_distinguishes_unfixed_from_fixed():
    """'수정됨'과 '못 고침'이 같아 보이면 표시하는 의미가 없습니다."""
    dash = _dash()
    i = dash.index("function factCheckBadge")
    body = dash[i:i + 1200]
    assert "issues_found" in body and "fixes_applied" in body


def test_helpers_are_actually_called_not_just_defined():
    """함수가 있는 것과 화면에 그려지는 것은 다릅니다.

    처음 이 파일을 쓸 때 정의만 검사했더니, 호출부를 지워도 테스트가
    통과했습니다 — 검사한 적 없는데 통과로 보이는 쪽이 검사가 없는 것보다
    나쁩니다. 정의를 뺀 나머지에서 호출을 셉니다.
    """
    dash = _dash()
    for name in ("factCheckBadge", "factCheckDetail"):
        start = dash.index(f"function {name}")
        end = dash.index("\n}", start)
        outside = dash[:start] + dash[end:]
        assert f"{name}(p)" in outside, (
            f"{name}이 정의만 되어 있고 어디서도 호출되지 않습니다 — "
            "화면에는 아무것도 나오지 않습니다"
        )


def test_exporter_still_ships_the_field():
    exp = open(os.path.join(_SRC, "dashboard_exporter.py"), encoding="utf-8").read()
    assert '"factCheck"' in exp, "내보내기가 빠지면 화면 쪽 코드가 무의미해집니다"


def test_main_still_parses():
    ast.parse(_main_src())
