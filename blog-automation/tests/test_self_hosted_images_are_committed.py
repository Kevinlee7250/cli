"""자체 호스팅한 이미지가 저장소에 남는가.

무슨 일이 있었나
────────────────
발행된 글 5편 이상이 `kevinlee7250.github.io/cli/images/<해시>` 를 가리키는데
그 파일이 저장소에 없었습니다(HTTP 404). 독자 화면에서 그림이 깨집니다.

경로를 따라가면 이렇습니다.

  auto-repair.yml
    → python main.py --retry
      → retry_failed_posts → generate_post
        → _collect_post_images → fetch_images_for_queries → _self_host
           · 이미지를 docs/images/ 에 내려받고
           · 본문 src 를 github.io 주소로 바꾸고
        → upload_post 로 Blogger에 발행 (되돌릴 수 없음)
    → 커밋 단계: 소스 파일과 post_drafts 만 add
       docs/images/ 도 image_mirror.json 도 없음

러너가 사라지면 파일도 사라집니다. 글은 이미 나갔으니 영구 404입니다.
워크플로는 내내 초록이었습니다.

여기서 지키는 것
────────────────
자체 호스팅에 닿을 수 있는 스크립트를 돌리는 워크플로는 반드시
docs/images/ 와 매니페스트를 함께 커밋해야 합니다. "닿을 수 있는지"는
목록을 손으로 적지 않고 호출 관계를 따라 계산합니다 — 손으로 적으면
새 호출부가 생겼을 때 이 검사가 조용히 비켜 갑니다.
"""

import ast
import functools
import glob
import os
import re

import pytest

_SRC = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_WF = os.path.normpath(os.path.join(_SRC, "..", ".github", "workflows"))

#: 이 이름들에 닿으면 docs/images 에 파일을 쓰고 본문 src 를 우리 도메인으로
#: 바꿉니다. 즉 파일이 커밋되지 않으면 발행 글이 깨집니다.
_SELF_HOST_FUNCS = {
    "mirror_url", "mirror_images",          # image_mirror
    "_self_host", "adopt_image",            # image_fetcher
    "fetch_images_for_queries",             # _self_host 를 부름
}
_SELF_HOST_MODULES = {"image_mirror"}

#: 직접 내려받지는 않지만 반드시 그 경로를 타는 함수들.
#: generate_post → _collect_post_images → fetch_images_for_queries → _self_host
#: retry_failed_posts → generate_post (auto-repair가 이 경로로 발행합니다)
_POST_PRODUCERS = {"generate_post", "generate_series_post", "retry_failed_posts"}

#: 커밋 단계가 반드시 담아야 하는 것
_REQUIRED_PATHS = ("docs/images", "image_mirror.json")


def _module_name(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


@functools.lru_cache(maxsize=None)
def _local_modules() -> set[str]:
    return frozenset(_module_name(p) for p in glob.glob(os.path.join(_SRC, "*.py")))


@functools.lru_cache(maxsize=None)
def _parse(path: str) -> ast.Module | None:
    try:
        with open(path, encoding="utf-8") as f:
            return ast.parse(f.read(), filename=path)
    except (SyntaxError, OSError):
        return None


@functools.lru_cache(maxsize=None)
def _imports_of(path: str) -> set[str]:
    """그 파일이 직접 import 하는 로컬 모듈."""
    tree = _parse(path)
    if tree is None:
        return set()
    local = _local_modules()
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            out.add((node.module or "").split(".")[0])
    return frozenset(out & local)


@functools.lru_cache(maxsize=None)
def _calls_in(path: str) -> set[str]:
    tree = _parse(path)
    if tree is None:
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            n = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if n:
                names.add(n)
        elif isinstance(node, ast.ImportFrom):
            names.update(a.name for a in node.names)
    return frozenset(names)


@functools.lru_cache(maxsize=None)
def self_hosting_modules() -> frozenset:
    """docs/images에 파일을 쓸 수 있는 모듈.

    이름으로 판정합니다. 모듈 단위로 한 단계 더 따라가 봤더니
    (content_generator를 import 하기만 해도 걸림) shorts_generator·
    author_profile_check·adsense_audit처럼 이미지를 전혀 내려받지 않는
    것들이 함께 걸려 검사가 무뎌졌습니다. generate_title_thumbnail은
    imgbb나 data URI를 쓰고 파일을 남기지 않아 여기 해당하지 않습니다.
    """
    triggers = _SELF_HOST_FUNCS | _POST_PRODUCERS
    out = set()
    for path in glob.glob(os.path.join(_SRC, "*.py")):
        if _calls_in(path) & triggers or _imports_of(path) & _SELF_HOST_MODULES:
            out.add(_module_name(path))
    return frozenset(out)


def _workflow_files() -> list[str]:
    return sorted(glob.glob(os.path.join(_WF, "*.yml")))


def _scripts_run_by(path: str) -> set[str]:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return set(re.findall(r"python3?\s+([A-Za-z_][A-Za-z0-9_]*)\.py", text))


def _commits_images(path: str) -> bool:
    """실제로 git add 하는지 봅니다.

    처음에는 파일 안에 경로 문자열이 있는지만 확인했습니다. 그런데 "왜
    커밋해야 하는가"를 설명하는 주석에도 docs/images가 들어 있어서, git add
    줄을 지워도 검사가 통과했습니다 — 값은 없는데 통과하는, 이 저장소에서
    반복해 고쳐 온 바로 그 모양입니다.
    """
    with open(path, encoding="utf-8") as f:
        code = [ln for ln in f if not ln.lstrip().startswith("#")]
    text = "".join(code)
    if "git add" not in text:
        return False
    return all(p in text for p in _REQUIRED_PATHS)


# ── 분석 자체가 헛돌지 않는지 ────────────────────────────────────────────────

def test_reachability_finds_the_known_entry_points():
    mods = self_hosting_modules()
    # 이 넷은 확실히 자체 호스팅을 탑니다 — 하나라도 빠지면 분석이 고장 난 것
    for m in ("image_fetcher", "content_generator", "main", "manage_post"):
        assert m in mods, f"{m}이 자체 호스팅 모듈로 안 잡힙니다: {sorted(mods)}"


def test_reachability_does_not_flag_everything():
    """전부 걸리면 검사가 의미를 잃습니다."""
    mods = self_hosting_modules()
    assert len(mods) < len(_local_modules()), "모든 모듈이 자체 호스팅으로 잡혔습니다"


def test_workflow_scan_is_not_vacuous():
    assert len(_workflow_files()) >= 30
    runners = [w for w in _workflow_files() if _scripts_run_by(w) & self_hosting_modules()]
    assert len(runners) >= 5, "자체 호스팅 스크립트를 돌리는 워크플로를 못 찾았습니다"


# ── 본 검사 ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", _workflow_files(), ids=os.path.basename)
def test_workflow_that_self_hosts_commits_the_files(path):
    hits = _scripts_run_by(path) & self_hosting_modules()
    if not hits:
        return
    assert _commits_images(path), (
        f"{os.path.basename(path)}가 {sorted(hits)}를 돌려 이미지를 "
        f"docs/images에 쓰고 본문 src를 우리 도메인으로 바꾸는데, "
        f"커밋 단계에 {list(_REQUIRED_PATHS)}가 없습니다 — "
        f"러너가 사라지면 발행된 글의 이미지가 영구 404가 됩니다"
    )
