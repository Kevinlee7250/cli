"""품질 게이트가 글을 붙잡은 것을 '고장'으로 세지 않는가.

무슨 일이 있었나
────────────────
자동수리 리포트가 "critical_errors: 7" 을 보고했습니다. 열어 보니 7줄이
이런 것이었습니다.

  2026-10-07 [ERROR] main — ❌ 게시 0건 — 1건 모두 검토 대기로 빠졌습니다
  2026-10-07 [ERROR] main —    품질 기준(ADSENSE_MIN_SCORE) 미달 …
  2026-10-07 [ERROR] main — ============================================
  2026-10-08 [ERROR] (같은 3줄 반복)
  2026-10-08 [ERROR] main — ============================================

별개의 7개 문제가 아니라 **같은 상황 2번에서 나온 7줄**이고, 그중 3줄은
구분선이었습니다. 그리고 그 '상황'은 고장이 아닙니다 — 품질 기준에 못
미치는 글을 발행하지 않고 검토 대기로 돌린 것이므로 설계된 동작입니다.

고칠 코드가 없는 것을 고장으로 세면, 숫자가 부풀고 정작 진짜 고장이 그
숫자에 묻힙니다.

여기서 지키는 것
────────────────
  1. 품질 게이트가 막은 경우는 error 가 아니다 (warning)
  2. 업로드가 실제로 실패한 경우는 여전히 error 다
  3. 구분선은 오류로 세지 않는다
  4. 내용 있는 오류는 그대로 센다 (필터가 과하게 먹지 않는다)
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import code_repair as cr  # noqa: E402

_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "main.py")

with open(_MAIN, encoding="utf-8") as _f:
    MAIN_SRC = _f.read()


def _zero_published_block() -> str:
    """'한 편도 올라가지 않은 경우' 블록의 소스."""
    start = MAIN_SRC.index("여기부터는 블로그에 한 편도 올라가지 않은 경우")
    return MAIN_SRC[start:start + 2000].split("sys.exit(1)")[0]


# ── 1·2. 심각도가 상황에 맞는가 ─────────────────────────────────────────────

def test_quality_gate_hold_is_logged_as_warning():
    block = _zero_published_block()
    # 게이트가 막은 경우의 문장이 error 로 나가면 안 됩니다
    for line in block.splitlines():
        if "검토 대기로 빠졌습니다" in line or "ADSENSE_MIN_SCORE" in line:
            assert "logger.error" not in line, (
                f"품질 게이트가 막은 경우를 error 로 기록합니다 — 고장이 아닙니다:\n{line.strip()}"
            )
            assert "logger.warning" in line, f"warning 으로 기록해야 합니다:\n{line.strip()}"


def test_real_upload_failure_is_still_an_error():
    """게이트와 달리 업로드 실패는 진짜 고장입니다 — 낮추면 안 됩니다."""
    block = _zero_published_block()
    fail_lines = [l for l in block.splitlines()
                  if "오류 {failed}건" in l or "시도, 오류" in l]
    assert fail_lines, "업로드 실패 경로의 로그를 찾지 못했습니다"
    for line in fail_lines:
        assert "logger.error" in line, (
            f"업로드 실패를 error 보다 낮게 기록합니다:\n{line.strip()}"
        )


def test_separator_is_not_logged_as_error_in_the_gate_path():
    block = _zero_published_block()
    gate = block.split("else:", 1)[-1]
    assert "logger.error" not in gate, (
        "게이트 경로에 error 로그가 남아 있습니다 — 구분선 포함"
    )


# ── 3. 구분선을 세지 않는가 ─────────────────────────────────────────────────

def test_separator_lines_are_not_counted(tmp_path):
    log = tmp_path / "automation.log"
    log.write_text(
        "2026-10-07 01:40:53 [ERROR] main — ============================================================\n"
        "2026-10-07 01:40:54 [ERROR] main — ------------------------------------------------------------\n"
        "2026-10-07 01:40:55 [ERROR] main — ************************************************************\n",
        encoding="utf-8",
    )
    assert cr._extract_critical_lines(log) == [], (
        "구분선을 오류로 세고 있습니다 — 건수가 부풀어 진짜 오류가 묻힙니다"
    )


def test_real_errors_are_still_counted(tmp_path):
    """필터가 과하게 먹어 진짜 오류를 놓치면 더 나쁩니다."""
    log = tmp_path / "automation.log"
    log.write_text(
        "2026-10-07 01:40:53 [ERROR] main — ====================\n"
        "2026-10-07 01:40:54 [ERROR] main — ❌ 업로드 실패: 토큰 만료\n"
        "2026-10-07 01:40:55 [CRITICAL] uploader — 이미지 호스팅 실패\n"
        "2026-10-07 01:40:56 [INFO] main — 정상 동작\n",
        encoding="utf-8",
    )
    got = cr._extract_critical_lines(log)
    assert len(got) == 2, f"내용 있는 오류 2건을 세야 합니다: {got}"
    assert any("토큰 만료" in g for g in got)
    assert any("이미지 호스팅" in g for g in got)


def test_noise_check_does_not_eat_short_real_messages(tmp_path):
    """짧아도 내용이 있으면 오류입니다."""
    log = tmp_path / "automation.log"
    log.write_text("2026-10-07 01:40:54 [ERROR] main — 실패\n", encoding="utf-8")
    assert len(cr._extract_critical_lines(log)) == 1


# ── 실제 로그로 확인 ────────────────────────────────────────────────────────

def test_the_live_log_no_longer_counts_separators():
    """저장소에 있는 실제 로그 — 구분선이 섞여 있던 그 로그입니다."""
    if not cr.LOG_FILE.exists():
        return
    for line in cr._extract_critical_lines(cr.LOG_FILE):
        body = line.split("—", 1)[-1].strip().strip("·-=_*# ")
        assert body, f"내용 없는 줄이 오류로 집계됩니다: {line[:80]}"
