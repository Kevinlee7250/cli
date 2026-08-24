"""이미 분석한 예외를 반복 분석하지 않기 (2026-08-22).

automation.log는 저장소에 커밋돼 계속 누적됩니다. 마지막 300줄을 그냥
읽으면 이미 고친 예외가 며칠씩 "최근 오류"로 다시 잡히고, 그때마다 Claude
분석을 다시 부릅니다. 실제로 04:06에 고친 temperature 오류가 04:57·05:01·
05:07·05:11·05:52 다섯 번 재분석됐고 대시보드는 계속 빨간 상태였습니다.

실행: cd blog-automation && python -m pytest tests/test_code_repair_mark.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import code_repair as cr  # noqa: E402

_LOG = '''2026-08-21 22:33:23,702 [ERROR] content_generator — 포스트 생성 오류: boom
Traceback (most recent call last):
  File "/app/blog-automation/content_generator.py", line 2766, in generate_post
    raw = _ai_generate(...)
TypeError: Messages.stream() got an unexpected keyword argument 'temperature'
2026-08-22 06:30:00,001 [ERROR] main — 다른 오류
Traceback (most recent call last):
  File "/app/blog-automation/main.py", line 10, in main
    x = 1 / 0
ZeroDivisionError: division by zero
'''


def _log(tmp_path):
    p = tmp_path / "automation.log"
    p.write_text(_LOG, encoding="utf-8")
    return p


def test_timestamp_is_attached_to_each_traceback(tmp_path):
    """시각이 없으면 '이미 분석함'을 판단할 수 없습니다."""
    tbs = cr._extract_tracebacks(_log(tmp_path))
    assert [tb["at"] for tb in tbs] == ["2026-08-21 22:33:23", "2026-08-22 06:30:00"]


def test_no_mark_returns_everything(tmp_path):
    assert len(cr.new_tracebacks(_log(tmp_path), mark="")) == 2


def test_mark_filters_already_analyzed(tmp_path):
    got = cr.new_tracebacks(_log(tmp_path), mark="2026-08-21 22:33:23")
    assert len(got) == 1
    assert "ZeroDivisionError" in got[0]["error"]


def test_mark_after_everything_returns_none(tmp_path):
    assert cr.new_tracebacks(_log(tmp_path), mark="2026-08-22 23:59:59") == []


def test_recurrence_after_the_mark_is_reported_again(tmp_path):
    """같은 오류라도 나중에 또 나면 다시 봐야 합니다."""
    p = tmp_path / "automation.log"
    p.write_text(_LOG + '''2026-08-22 07:00:00,000 [ERROR] content_generator — 또 발생
Traceback (most recent call last):
  File "/app/blog-automation/content_generator.py", line 2766, in generate_post
    raw = _ai_generate(...)
TypeError: Messages.stream() got an unexpected keyword argument 'temperature'
''', encoding="utf-8")
    got = cr.new_tracebacks(p, mark="2026-08-22 06:30:00")
    assert len(got) == 1 and got[0]["at"] == "2026-08-22 07:00:00"


def test_traceback_without_timestamp_is_treated_as_new(tmp_path):
    """판단이 안 서면 한 번 더 보는 쪽이 안전합니다."""
    p = tmp_path / "automation.log"
    p.write_text('''Traceback (most recent call last):
  File "/app/blog-automation/main.py", line 3, in <module>
    boom()
NameError: name 'boom' is not defined
''', encoding="utf-8")
    assert len(cr.new_tracebacks(p, mark="2026-08-22 23:59:59")) == 1


def test_mark_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(cr, "CODE_REPAIR_MARK", tmp_path / "mark.json")
    assert cr._load_mark() == ""          # 없으면 빈 문자열
    cr._save_mark("2026-08-22 06:30:00")
    assert cr._load_mark() == "2026-08-22 06:30:00"


def test_corrupt_mark_does_not_crash(tmp_path, monkeypatch):
    bad = tmp_path / "mark.json"
    bad.write_text("깨진 내용", encoding="utf-8")
    monkeypatch.setattr(cr, "CODE_REPAIR_MARK", bad)
    assert cr._load_mark() == ""
