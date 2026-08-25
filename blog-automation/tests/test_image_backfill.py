"""발행 글 이미지 소급 자체 호스팅 — 살아 있는 글을 깨뜨리지 않는지.

발행된 425편을 건드리는 작업이라, 틀렸을 때의 손해가 신규 글과 다릅니다.
여기서 지키는 것:

  1) 무단 이미지는 복제하지 않습니다. 우리 저장소로 옮기면 핫링크보다
     나쁜 상태(직접 배포)가 됩니다.
  2) 배포되지 않은 복제본으로는 본문을 돌리지 않습니다. 이 확인이 1·2단계
     순서를 잘못 돌려도 글이 안 깨지게 하는 안전장치입니다.
  3) 원본은 onerror 폴백으로 남습니다 — 복제본이 나중에 사라져도 복구됩니다.
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import image_mirror  # noqa: E402
import mirror_existing_images as backfill  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(image_mirror, "MIRROR_DIR", str(tmp_path / "images"))
    monkeypatch.setattr(image_mirror, "MANIFEST_FILE", str(tmp_path / "image_mirror.json"))
    monkeypatch.setenv("IMAGE_HOST_BASE", "https://example.test/images")
    return tmp_path


def _img(url):
    return f'<figure><img src="{url}" alt="설명" width="720"/></figure>'


# ── 대상 선별 ────────────────────────────────────────────────────────────────

def test_licensed_hotlink_is_a_target(store):
    targets, unlicensed = backfill.collect_targets(_img("https://pixabay.com/get/a.jpg"))
    assert targets == ["https://pixabay.com/get/a.jpg"] and unlicensed == 0


def test_unlicensed_image_is_never_mirrored(store):
    """무단 이미지를 우리 도메인에서 직접 배포하면 핫링크보다 나쁩니다."""
    targets, unlicensed = backfill.collect_targets(_img("https://imgnews.naver.net/x.jpg"))
    assert targets == [] and unlicensed == 1


def test_data_uri_is_not_a_target(store):
    """본문에 박힌 썸네일은 죽을 수가 없습니다."""
    targets, _ = backfill.collect_targets(_img("data:image/svg+xml;base64,PHN2Zy8+"))
    assert targets == []


def test_already_mirrored_is_not_a_target(store):
    targets, _ = backfill.collect_targets(_img("https://example.test/images/abc.png"))
    assert targets == []


def test_duplicate_urls_are_collected_once(store):
    content = _img("https://pixabay.com/get/a.jpg") + _img("https://pixabay.com/get/a.jpg")
    targets, _ = backfill.collect_targets(content)
    assert targets == ["https://pixabay.com/get/a.jpg"]


# ── 본문 교체 ────────────────────────────────────────────────────────────────

def test_rewrite_points_to_mirror_and_keeps_origin():
    out = backfill.point_to_mirror(_img("https://pixabay.com/get/a.jpg"),
                                   "https://pixabay.com/get/a.jpg",
                                   "https://example.test/images/x.png")
    assert 'src="https://example.test/images/x.png"' in out
    assert "onerror=" in out and "pixabay.com/get/a.jpg" in out
    assert out.count("<img") == 1, "태그가 늘거나 깨졌습니다"


def test_rewrite_keeps_the_tag_well_formed():
    out = backfill.point_to_mirror('<img src="https://pixabay.com/get/a.jpg" alt="x">',
                                   "https://pixabay.com/get/a.jpg",
                                   "https://example.test/images/x.png")
    assert out.endswith(">") and not out.endswith("/>")
    assert 'alt="x"' in out


def test_rewrite_does_not_duplicate_an_existing_onerror():
    tag = ('<img src="https://pixabay.com/get/a.jpg" '
           'onerror="this.onerror=null;this.src=\'https://old/x.jpg\'"/>')
    out = backfill.point_to_mirror(tag, "https://pixabay.com/get/a.jpg",
                                   "https://example.test/images/x.png")
    # 속성만 셉니다 — 값 안의 `this.onerror=`까지 세면 항상 2가 됩니다
    assert out.count(' onerror="') == 1


def test_other_images_are_untouched():
    content = _img("https://pixabay.com/get/a.jpg") + _img("https://pixabay.com/get/b.jpg")
    out = backfill.point_to_mirror(content, "https://pixabay.com/get/a.jpg",
                                   "https://example.test/images/x.png")
    assert 'src="https://pixabay.com/get/b.jpg"' in out


# ── 배포 확인 ────────────────────────────────────────────────────────────────

class _R:
    def __init__(self, code):
        self.status_code = code


def test_liveness_requires_a_real_200(monkeypatch):
    live = backfill.Liveness()
    monkeypatch.setattr(backfill.requests, "head", lambda *a, **k: _R(404))
    assert live.ok("https://example.test/images/x.png") is False


def test_liveness_failure_is_not_optimistic(monkeypatch):
    """확인 못 했으면 교체하지 않습니다 — 낙관적으로 넘기면 글이 깨집니다."""
    def _boom(*a, **k):
        raise backfill.requests.exceptions.ConnectionError("끊김")
    live = backfill.Liveness()
    monkeypatch.setattr(backfill.requests, "head", _boom)
    assert live.ok("https://example.test/images/x.png") is False


def test_liveness_is_cached(monkeypatch):
    calls = []
    live = backfill.Liveness()
    monkeypatch.setattr(backfill.requests, "head",
                        lambda *a, **k: calls.append(a) or _R(200))
    live.ok("https://example.test/images/x.png")
    live.ok("https://example.test/images/x.png")
    assert len(calls) == 1


# ── 매니페스트 조회 ──────────────────────────────────────────────────────────

def test_mirrored_url_for_requires_the_file_to_exist(store, monkeypatch):
    """매니페스트에만 남고 파일이 없으면 그쪽으로 돌리면 안 됩니다."""
    class _Resp:
        headers = {"Content-Type": "image/png"}

        def raise_for_status(self): pass

        def iter_content(self, n): yield b"\x89PNG\r\n\x1a\n" + b"\x00" * 20

    monkeypatch.setattr(image_mirror.requests, "get", lambda *a, **k: _Resp())
    got = image_mirror.mirror_url("https://pixabay.com/get/a.jpg")
    assert image_mirror.mirrored_url_for("https://pixabay.com/get/a.jpg") == got["url"]

    os.remove(os.path.join(image_mirror.MIRROR_DIR, got["file"]))
    assert image_mirror.mirrored_url_for("https://pixabay.com/get/a.jpg") == ""


def test_unknown_origin_has_no_mirror(store):
    assert image_mirror.mirrored_url_for("https://pixabay.com/get/never.jpg") == ""


# ── 배포 연결 ────────────────────────────────────────────────────────────────

_WF = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..",
                                    ".github", "workflows"))


def _wf(name):
    with open(os.path.join(_WF, name), encoding="utf-8") as f:
        return f.read()


def test_backfill_triggers_a_pages_deploy():
    """복제해서 커밋만 하고 배포가 안 되면 복제본은 영원히 404입니다.

    Actions가 기본 GITHUB_TOKEN으로 만든 커밋은 push 트리거를 발동시키지
    않으므로, workflow_run 목록에 이름이 있어야 합니다.
    """
    name = _wf("image-backfill.yml").split("\n")[0].replace("name:", "").strip()
    assert name in _wf("deploy-dashboard.yml"), (
        f"deploy-dashboard.yml의 workflow_run 목록에 '{name}'이 없습니다"
    )


def test_images_are_in_the_deploy_push_paths():
    assert "docs/images/**" in _wf("deploy-dashboard.yml"), (
        "사람이 docs/images를 직접 커밋했을 때 배포되지 않습니다"
    )


def test_backfill_commits_images_with_the_manifest():
    text = _wf("image-backfill.yml")
    assert "docs/data/image_mirror.json" in text and "docs/images/" in text


# ── 커밋 배선 ────────────────────────────────────────────────────────────────

_ADD_RE = re.compile(r"^git add(?:\s+-f)?\s+(.+)$")


def _multi_path_adds(text: str) -> list[str]:
    """literal 경로를 두 개 이상 한 번에 add하는 줄."""
    bad = []
    for raw in text.split("\n"):
        line = raw.strip()
        if '"$f"' in line:
            continue
        m = _ADD_RE.match(line)
        if not m:
            continue
        body = re.sub(r"\s*2>/dev/null\s*", " ", m.group(1))
        body = re.sub(r"\s*\|\|\s*true\s*$", "", body).strip().rstrip("\\").strip()
        paths = [p for p in body.split() if re.match(r"^[A-Za-z0-9_./-]+$", p)]
        if len(paths) > 1:
            bad.append(line)
    return bad


@pytest.mark.parametrize(
    "name", sorted(os.path.basename(p) for p in
                   __import__("glob").glob(os.path.join(_WF, "*.yml"))))
def test_git_add_tolerates_missing_files(name):
    """`git add a b`는 b가 없으면 a까지 통째로 무산됩니다.

    pathspec이 하나라도 안 맞으면 git add는 아무것도 스테이징하지 않고
    128로 끝나는데, 뒤의 `|| true`가 그 실패를 삼킵니다. 워크플로는 초록으로
    끝나고 산출물만 조용히 사라집니다 — 2026-08-25 소급 복제 1회차에서
    image_mirror.json이 아직 없어 image_backfill.json까지 함께 유실됐습니다.

    파일마다 있는지 보고 넣는 `for f in ...; do [ -f "$f" ] && git add -f "$f"; done`
    형태를 쓰세요.
    """
    with open(os.path.join(_WF, name), encoding="utf-8") as f:
        bad = _multi_path_adds(f.read())
    assert not bad, (
        f"{name}: 여러 경로를 한 번에 add합니다 — 하나만 없어도 전부 무산됩니다\n  "
        + "\n  ".join(bad)
    )
