"""워크플로에서 도달할 수 없는 모듈이 조용히 늘어나지 않게 합니다.

전체 점검에서 두 건이 나왔습니다.

  sitemap_generator   워크플로가 로직을 heredoc으로 인라인해 두어 모듈은
                      죽어 있었습니다. 구현이 두 벌이 되고, 도는 쪽에는
                      테스트가 없어 블로그 하나가 통째로 누락된 채 돌았습니다.
  author_profile_check "조용한 실패를 잡는" 점검기인데 아무도 부르지 않아
                      점검기 자신이 같은 침묵에 빠져 있었습니다.

죽은 모듈은 그냥 무해한 잉여가 아닙니다. 고쳐도 아무 일이 일어나지 않아
다음 사람이 헛수고하게 만듭니다.

새 모듈이 의도적으로 워크플로 밖에 있다면(로컬 도구 등) _EXPECTED_LOCAL에
이유와 함께 넣으세요. 목록에 넣는 행위 자체가 판단을 남깁니다.
"""

import ast
import glob
import os

_SRC = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_WF = os.path.normpath(os.path.join(_SRC, "..", ".github", "workflows"))

# 워크플로에서 안 도는 것이 맞는 모듈 — 이유를 함께 적습니다.
_EXPECTED_LOCAL = {
    # OAuth 토큰 교환은 로컬에서만 합니다. 공개 저장소·포크라 refresh_token과
    # client_secret이 Actions 로그·아티팩트에 남으면 안 됩니다.
    "get_refresh_token": "로컬 전용 OAuth",
    "setup_google_auth": "로컬 전용 OAuth",
    "setup_blogger_auth": "로컬 전용 OAuth",
    "setup_github_secrets": "로컬 전용 시크릿 등록",
    # 사람이 필요할 때 직접 부르는 복구·점검 도구
    "recover_post_details": "수동 복구 도구",
    "series_relink": "수동 복구 도구",
    "manual_image_check": "로컬 수동 점검",
    "dashboard": "대시보드가 읽는 데이터 모듈",
    "trend_fetcher": "미사용 — 정리 대상",
}


def _modules():
    return {os.path.basename(p)[:-3] for p in glob.glob(os.path.join(_SRC, "*.py"))}


def _imports(mods):
    edges = {}
    for p in glob.glob(os.path.join(_SRC, "*.py")):
        name = os.path.basename(p)[:-3]
        deps = set()
        try:
            tree = ast.parse(open(p, encoding="utf-8").read())
        except SyntaxError:
            edges[name] = deps
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                deps |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module:
                deps.add(n.module.split(".")[0])
        edges[name] = deps & mods
    return edges


def _entrypoints():
    import re
    out = set()
    for wf in glob.glob(os.path.join(_WF, "*.yml")):
        text = open(wf, encoding="utf-8").read()
        out |= set(re.findall(r"python3?\s+(?:-m\s+)?([A-Za-z0-9_]+)\.py", text))
    return out


def _reachable():
    mods = _modules()
    edges = _imports(mods)
    seen, stack = set(), list(_entrypoints() & mods)
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack += list(edges.get(cur, ()))
    return mods, seen


def test_every_module_is_reachable_or_declared_local():
    mods, seen = _reachable()
    orphans = sorted(mods - seen - set(_EXPECTED_LOCAL))
    assert not orphans, (
        "어느 워크플로에서도 도달할 수 없는 모듈입니다. 배선하거나, 로컬 "
        "전용이라면 _EXPECTED_LOCAL에 이유와 함께 넣으세요: " + ", ".join(orphans)
    )


def test_declared_local_modules_still_exist():
    """지운 모듈이 목록에 남으면 그 항목은 아무것도 지켜주지 않습니다."""
    stale = sorted(set(_EXPECTED_LOCAL) - _modules())
    assert not stale, f"_EXPECTED_LOCAL에 없는 모듈이 적혀 있습니다: {stale}"


def test_workflows_only_call_modules_that_exist():
    missing = sorted(_entrypoints() - _modules())
    assert not missing, f"워크플로가 없는 스크립트를 부릅니다: {missing}"


def test_check_is_not_vacuous():
    mods, seen = _reachable()
    assert len(mods) >= 60 and len(seen) >= 40
