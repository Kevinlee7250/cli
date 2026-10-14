"""대시보드에서 모든 기능을 실행할 수 있는가.

왜
──
실행 버튼이 화면에 손으로 박혀 있었습니다. dispatch 가능한 워크플로 70개
중 30개만 올라와 있었고, 블로그 관련으로만 세도 19개가 빠져 있었습니다 —
백업·사이트맵·클러스터·게시글 검증·면책 링크·무단 이미지 교체·체험담
정정·글 비공개 등. 손으로 유지하면 새 워크플로가 생길 때마다 또 빠집니다.

그래서 목록을 워크플로 파일에서 생성합니다(workflow_catalog). 이 테스트는
"생성이 실제로 전부를 담는지"와 "위험한 기능이 표시되는지"를 봅니다.

여기서 지키는 것
────────────────
  1. 수동 실행이 가능한 블로그 워크플로가 하나도 빠지지 않는다
  2. 빠뜨린 것은 이유와 함께 집계된다 (npm 상속 CI / 수동 실행 없음)
  3. 발행 글을 바꾸거나 지우는 기능은 danger 로 표시된다
  4. 입력값이 화면이 그릴 수 있는 형태로 넘어간다
  5. 설정 내보내기가 이 목록과 저자 경험 자료를 함께 만든다
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import workflow_catalog as wc  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WF_DIR = os.path.join(_ROOT, ".github", "workflows")
_HTML = os.path.join(_ROOT, "docs", "index.html")


#: npm/cli에서 상속받은 워크플로 — 여기에 '독립적으로' 적어 둡니다.
#:
#: 처음에는 workflow_catalog._is_upstream() 을 그대로 썼는데, 그러면
#: 제외 목록에 파일을 추가하는 것만으로 테스트도 같이 눈을 감습니다.
#: 실제로 backup-live-posts.yml·blog-sitemap.yml 을 제외 목록에 넣어 봤더니
#: "하나도 빠지지 않는다"는 테스트가 그대로 통과했습니다. 검사 대상과
#: 검사 기준이 같은 코드를 보면 안 됩니다.
_NPM_UPSTREAM = {
    "audit.yml", "ci.yml", "create-node-pr.yml",
    "node-integration.yml", "release-integration.yml",
}


def _is_npm_upstream(name: str) -> bool:
    return name in _NPM_UPSTREAM or name.startswith("ci-")


def _dispatchable_blog_workflows() -> set[str]:
    """수동 실행이 가능한 '블로그' 워크플로 — npm 상속분 제외."""
    import yaml
    out = set()
    for name in os.listdir(_WF_DIR):
        if not name.endswith((".yml", ".yaml")):
            continue
        if _is_npm_upstream(name):
            continue
        with open(os.path.join(_WF_DIR, name), encoding="utf-8") as f:
            parsed = yaml.safe_load(f)
        on = parsed.get("on", parsed.get(True)) if isinstance(parsed, dict) else None
        has_dispatch = (
            (isinstance(on, dict) and "workflow_dispatch" in on)
            or (isinstance(on, list) and "workflow_dispatch" in on)
            or on == "workflow_dispatch"
        )
        if has_dispatch:
            out.add(name)
    return out


def test_the_exclusion_list_only_holds_npm_upstream_files():
    """제외 목록에 블로그 워크플로를 넣어 목록에서 감추는 것을 막습니다.

    이 테스트가 없으면 '빠진 기능' 검사를 제외 목록으로 우회할 수 있습니다.
    """
    declared = set(wc.UPSTREAM_FILES)
    not_npm = sorted(f for f in declared if not _is_npm_upstream(f))
    assert not not_npm, (
        f"npm 상속분이 아닌데 제외 목록에 있습니다: {not_npm} — "
        f"블로그 기능을 대시보드에서 감추게 됩니다"
    )
    assert wc.UPSTREAM_PREFIXES == ("ci-",), (
        f"제외 접두사가 늘었습니다: {wc.UPSTREAM_PREFIXES} — "
        f"블로그 워크플로가 접두사로 걸러질 수 있습니다"
    )


# ── 1. 하나도 빠지지 않는가 ─────────────────────────────────────────────────

def test_catalog_lists_every_dispatchable_blog_workflow():
    listed = {w["file"] for w in wc.build()["workflows"]}
    expected = _dispatchable_blog_workflows()
    missing = sorted(expected - listed)
    assert not missing, (
        f"대시보드에서 실행할 수 없는 기능이 있습니다: {missing}"
    )


def test_catalog_does_not_invent_workflows():
    """없는 워크플로를 목록에 넣으면 누르는 순간 404입니다."""
    for w in wc.build()["workflows"]:
        assert os.path.exists(os.path.join(_WF_DIR, w["file"])), (
            f"목록에 있는데 파일이 없습니다: {w['file']}"
        )


def test_upstream_npm_ci_is_excluded():
    """이 저장소는 npm/cli 포크입니다 — 상속받은 CI는 블로그와 무관합니다."""
    listed = {w["file"] for w in wc.build()["workflows"]}
    assert not any(f.startswith("ci-") for f in listed)
    for f in ("ci.yml", "audit.yml", "node-integration.yml"):
        assert f not in listed


# ── 2. 빠뜨린 것이 집계되는가 ───────────────────────────────────────────────

def test_exclusions_are_counted_with_reasons():
    """'왜 74개 중 48개만 보이지'를 다시 파지 않게 합니다."""
    cat = wc.build()
    counts, skipped = cat["counts"], cat["skipped"]
    assert counts["listed"] == len(cat["workflows"])
    assert counts["upstreamSkipped"] == len(skipped["upstream"])
    assert counts["noDispatch"] == len(skipped["noDispatch"])
    # 모든 워크플로 파일이 어느 한 쪽에는 들어가야 합니다
    total_files = len([n for n in os.listdir(_WF_DIR)
                       if n.endswith((".yml", ".yaml"))])
    accounted = (counts["listed"] + counts["upstreamSkipped"]
                 + counts["noDispatch"] + counts["unreadable"])
    assert accounted == total_files, (
        f"집계가 맞지 않습니다: {accounted} != {total_files} — "
        f"어디로 사라졌는지 알 수 없는 워크플로가 있습니다"
    )


def test_unreadable_workflow_is_not_silently_dropped():
    """읽지 못한 파일을 조용히 빼면 목록이 줄어든 것도 모릅니다."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "broken.yml"), "w", encoding="utf-8") as f:
            f.write("name: [ 깨진\n  yaml: : :\n")
        cat = wc.build(workflow_dir=d)
        assert cat["counts"]["unreadable"] == 1
        assert "broken.yml" in cat["skipped"]["unreadable"]


# ── 3. 위험한 기능이 표시되는가 ─────────────────────────────────────────────

def test_destructive_workflows_are_flagged():
    """버튼 하나로 발행된 글이 사라지는 일을 막습니다."""
    by_file = {w["file"]: w for w in wc.build()["workflows"]}
    for f in ("delete-low-grade-posts.yml", "unpublish-url.yml",
              "fix-affiliate-disclosure.yml", "fix-posts.yml",
              "image-backfill.yml"):
        assert by_file[f]["danger"] is True, f"{f} 가 위험 표시가 없습니다"


def test_read_only_workflows_are_not_flagged():
    """전부 위험으로 표시하면 표시가 의미를 잃습니다."""
    by_file = {w["file"]: w for w in wc.build()["workflows"]}
    for f in ("gsc-indexing.yml", "blog-tests.yml", "export-settings.yml",
              "weekly-brief.yml"):
        assert by_file[f]["danger"] is False, f"{f} 는 위험하지 않습니다"


def test_dry_run_input_is_identified():
    """화면이 '미리보기인지 실제 변경인지'를 말해주려면 필요합니다."""
    by_file = {w["file"]: w for w in wc.build()["workflows"]}
    assert by_file["fix-affiliate-disclosure.yml"]["dryRunInput"] == "dry_run"
    assert by_file["unpublish-url.yml"]["dryRunInput"] == "apply"


# ── 4. 입력값이 그릴 수 있는 형태인가 ───────────────────────────────────────

def test_inputs_carry_what_the_screen_needs():
    by_file = {w["file"]: w for w in wc.build()["workflows"]}
    fields = {i["name"]: i for i in by_file["unpublish-url.yml"]["inputs"]}
    assert fields["url"]["required"] is True
    assert fields["apply"]["type"] == "boolean"
    # 불리언 기본값은 문자열이어야 합니다 — dispatch API가 문자열을 받습니다
    assert fields["apply"]["default"] in ("true", "false")


def test_choice_inputs_keep_their_options():
    """옵션이 있는 입력은 자유 입력칸이 아니라 선택 목록이어야 합니다."""
    cat = wc.build()
    with_options = [i for w in cat["workflows"] for i in w["inputs"]
                    if i.get("options")]
    assert with_options, "옵션 있는 입력이 하나도 없습니다 — 파싱이 빠졌을 수 있습니다"
    for i in with_options:
        assert all(isinstance(o, str) for o in i["options"])


# ── 5. 화면과 내보내기가 연결돼 있는가 ──────────────────────────────────────

def test_dashboard_reads_the_catalog_and_profile():
    with open(_HTML, encoding="utf-8") as f:
        html = f.read()
    for needle in ("workflow_catalog.json", "author_profile.json",
                   "renderWorkflowCatalog", "renderAuthorProfile",
                   "wfcRun", "saveAuthorExperience"):
        assert needle in html, f"대시보드가 {needle} 를 쓰지 않습니다"


def test_dashboard_confirms_before_destructive_runs():
    with open(_HTML, encoding="utf-8") as f:
        html = f.read()
    body = html[html.index("async function wfcRun("):]
    body = body[:body.index("\n// ════════ 저자 경험 자료")]
    assert "confirm(" in body, "위험한 기능을 확인 없이 실행합니다"
    assert "w.danger" in body
    assert "되돌리기 어렵습니다" in body


def test_settings_export_builds_both_files(monkeypatch, tmp_path):
    import dashboard_exporter as de
    monkeypatch.setattr(de, "DOCS_DATA_DIR", str(tmp_path))
    de.export_settings()
    for name in ("workflow_catalog.json", "author_profile.json"):
        path = tmp_path / name
        assert path.exists(), f"{name} 이 만들어지지 않았습니다"
        with open(path, encoding="utf-8") as f:
            json.load(f)  # 유효한 JSON인지


def test_author_profile_export_marks_unusable_entries(monkeypatch, tmp_path):
    """요약이 비면 매칭되지 않습니다 — 화면이 그걸 보여줘야 합니다."""
    import dashboard_exporter as de
    monkeypatch.setattr(de, "DOCS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "config.get_author_profile",
        lambda: {"name": "테스트", "experiences": [
            {"topics": ["a"], "blogs": [], "summary": "있음", "detail": "d"},
            {"topics": ["b"], "blogs": [], "summary": "", "detail": ""},
        ]})
    de.export_settings()
    with open(tmp_path / "author_profile.json", encoding="utf-8") as f:
        prof = json.load(f)
    assert prof["activeCount"] == 1
    assert prof["totalCount"] == 2
    assert [e["active"] for e in prof["experiences"]] == [True, False]


def test_profile_editor_blocks_personal_data():
    """공개 저장소입니다 — 전화번호·이메일이 올라가면 지워도 커밋에 남습니다."""
    with open(_HTML, encoding="utf-8") as f:
        html = f.read()
    body = html[html.index("async function saveAuthorExperience("):]
    body = body[:body.index("\nfunction renderPublishSchedule")]
    assert "공개 저장소" in body
    for pattern in ("전화번호", "이메일", "주민번호", "계좌번호"):
        assert pattern in body, f"{pattern} 검사가 없습니다"
