"""대시보드의 발행 스케줄이 실제 설정과 같은가.

무슨 일이 있었나
────────────────
2026-10-08에 세 블로그의 발행을 전부 멈췄습니다(enabled=false). 그런데
대시보드는 엿새 동안 세 블로그 모두 "매일 1편 발행 중"으로 표시했습니다.

원인이 둘이었습니다.

  1. 내보내기가 발행 때만 돌았다
     _export_publish_schedule은 export_dashboard() 안에 있고, 그건
     main.py의 발행 파이프라인에서만 호출됩니다. 발행을 끄면 대시보드
     갱신도 같이 멈춥니다. 정지 커밋이 10-08 13:58 UTC, 마지막 내보내기가
     같은 날 10:47 UTC — 세 시간 차로 정지 직전 상태가 얼어붙었습니다.

  2. 화면이 데이터가 없으면 "발행 중"으로 꾸몄다
     const e = cfg[id] || { enabled: true, postsPerDay: 1 }
     파일을 못 읽어도 매일 1편으로 보입니다.

조용히 틀리는 종류라 — 아무것도 실패하지 않고 숫자만 거짓입니다 —
"언제 기준인지"까지 함께 검사합니다.

여기서 지키는 것
────────────────
  1. 내보낸 값이 저장소의 실제 설정과 같다
  2. 발행과 무관하게 내보낼 수 있다 (export_settings)
  3. 기준 시각이 함께 나간다
  4. 화면이 없는 데이터를 "발행 중"으로 꾸미지 않는다
  5. 동기화 결과가 실제 사이트까지 간다 (Pages 배포 트리거)
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dashboard_exporter as de  # noqa: E402
import publish_schedule as ps  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_HTML = os.path.join(_ROOT, "docs", "index.html")
_WF = os.path.join(_ROOT, ".github", "workflows")


def _export(monkeypatch, tmp_path):
    monkeypatch.setattr(de, "DOCS_DATA_DIR", str(tmp_path))
    de.export_settings()
    with open(tmp_path / "publish_schedule.json", encoding="utf-8") as f:
        return json.load(f)


# ── 내보낸 값이 진실인가 ────────────────────────────────────────────────────

def test_export_matches_the_real_setting(monkeypatch, tmp_path):
    out = _export(monkeypatch, tmp_path)
    sched = ps.load_schedule()
    for blog_id in ps.BLOG_IDS:
        assert out["blogs"][blog_id] == ps.entry_for(blog_id, sched), (
            f"{blog_id}의 내보낸 설정이 publish_schedule.json과 다릅니다"
        )


def test_export_carries_todays_plan(monkeypatch, tmp_path):
    out = _export(monkeypatch, tmp_path)
    assert out["today"] == ps.plan_for_today(ps.load_schedule())


def test_export_stamps_when_it_ran(monkeypatch, tmp_path):
    """기준 시각이 없으면 몇 달 전 설정이 현재처럼 읽힙니다."""
    out = _export(monkeypatch, tmp_path)
    assert out.get("exportedAt"), "exportedAt이 없습니다"


def test_stopped_blogs_are_exported_as_stopped(monkeypatch, tmp_path):
    """정지가 화면까지 전달되는지 — 이번 사고의 핵심입니다."""
    monkeypatch.setattr(ps, "load_schedule", lambda: {
        "blogs": {b: {"enabled": False, "postsPerDay": 1, "days": "daily"}
                  for b in ps.BLOG_IDS}})
    out = _export(monkeypatch, tmp_path)
    assert all(not e["enabled"] for e in out["blogs"].values()), (
        f"멈춘 블로그가 켜진 것으로 나갔습니다: {out['blogs']}"
    )
    assert set(out["today"].values()) == {0}


# ── 발행과 분리돼 있는가 ────────────────────────────────────────────────────

def test_settings_export_does_not_need_the_publish_pipeline():
    """export_settings가 발행 이력·수익 집계에 묶여 있으면 같은 일이 반복됩니다."""
    assert hasattr(de, "export_settings")
    import ast
    import inspect
    import textwrap
    # 설명문에 함수 이름이 나오므로 docstring·주석을 뺀 코드만 봅니다.
    # (전에 같은 방식의 가드가 자기 주석 때문에 통과한 적이 있습니다.
    #  문자열 치환은 들여쓰기 때문에 빗나가므로 AST로 지웁니다)
    tree = ast.parse(textwrap.dedent(inspect.getsource(de.export_settings)))
    fn = tree.body[0]
    if (fn.body and isinstance(fn.body[0], ast.Expr)
            and isinstance(fn.body[0].value, ast.Constant)
            and isinstance(fn.body[0].value.value, str)):
        fn.body = fn.body[1:]
    src = ast.unparse(fn)
    for forbidden in ("_load_history", "export_dashboard(", "_estimate_earnings"):
        assert forbidden not in src, (
            f"export_settings가 {forbidden}에 의존합니다 — 발행이 멈추면 또 멈춥니다"
        )


def test_a_workflow_exports_settings_on_its_own_schedule():
    path = os.path.join(_WF, "export-settings.yml")
    assert os.path.exists(path), "설정 내보내기 워크플로가 없습니다"
    with open(path, encoding="utf-8") as f:
        wf = f.read()
    assert "--settings-only" in wf
    assert "schedule:" in wf and "cron:" in wf, (
        "자체 스케줄이 없으면 발행이 멈춘 동안 갱신되지 않습니다"
    )


def test_the_sync_reaches_the_live_site():
    """Actions가 만든 커밋은 다른 워크플로를 트리거하지 않습니다 —
    Pages 배포의 workflow_run 목록에 들어 있어야 실제 사이트가 바뀝니다."""
    with open(os.path.join(_WF, "deploy-dashboard.yml"), encoding="utf-8") as f:
        deploy = f.read()
    with open(os.path.join(_WF, "export-settings.yml"), encoding="utf-8") as f:
        name = f.readline().split("name:", 1)[1].strip()
    assert name in deploy, (
        f"'{name}'이 Pages 배포 트리거 목록에 없습니다 — 동기화해도 "
        f"실제 사이트는 그대로입니다"
    )


# ── 화면이 꾸미지 않는가 ────────────────────────────────────────────────────

def test_dashboard_does_not_default_to_publishing():
    with open(_HTML, encoding="utf-8") as f:
        html = f.read()
    assert "cfg[id] || { enabled: true" not in html, (
        "설정을 못 읽으면 '매일 1편 발행 중'으로 보입니다"
    )
    assert "const e = cfg[id]" in html


def test_dashboard_shows_how_old_the_setting_is():
    with open(_HTML, encoding="utf-8") as f:
        html = f.read()
    body = html[html.index("function renderPublishSchedule"):]
    body = body[:body.index("\nasync function savePublishSchedule")]
    assert "exportedAt" in body, "기준 시각을 읽지 않습니다"
    assert "publish-schedule-asof" in body
    assert 'id="publish-schedule-asof"' in html, "표시할 자리가 없습니다"
