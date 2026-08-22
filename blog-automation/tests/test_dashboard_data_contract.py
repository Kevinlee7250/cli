"""대시보드와 데이터 생산자 사이의 계약 검사.

왜 필요한가
──────────
대시보드는 docs/data/*.json을 fetch로 읽고, 파이썬 모듈과 워크플로가 그 파일을
씁니다. 둘을 이어 주는 것이 파일 이름 문자열뿐이라 한쪽만 바뀌어도 아무도
모릅니다. 실제 전체 점검에서 이런 것들이 나왔습니다.

  · 대시보드가 찾지만 생산자가 없는 파일 → 매 로딩마다 404, 패널은 빈 채로
  · 만들어서 커밋까지 하지만 화면 어디에도 안 나오는 파일 → 워크플로 시간 낭비

사람이 매번 대조하는 대신 여기서 잡습니다. 이 테스트가 실패하면 둘 중
하나입니다 — 이어 주는 코드를 빠뜨렸거나, 아래 목록을 갱신해야 하거나.
"""

import glob
import os
import re

import pytest

# normpath 필수 — 정규화하지 않으면 경로에 ".../tests/../.." 가 남아,
# 아래의 "tests 디렉터리 제외" 검사가 모든 파일을 걸러 버립니다.
_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_DASHBOARD = os.path.join(_ROOT, "docs", "index.html")
_DATA_DIR = os.path.join(_ROOT, "docs", "data")
_PY_DIR = os.path.join(_ROOT, "blog-automation")
_WF_DIR = os.path.join(_ROOT, ".github", "workflows")

_JSON_RE = re.compile(r"([a-z_]+\.json)")

#: 생산자는 있지만 아직 파일이 만들어지지 않은 것들. 404가 나도 정상입니다.
#: 조건이 갖춰지면 생깁니다 — 이유를 함께 적어 두어야 "언젠가 생기겠지"로
#: 방치되지 않습니다.
NOT_YET_GENERATED = {
    "posts_archive.json": "글이 300편을 넘어야 넘침분이 생깁니다 (현재 정확히 300편)",
    "adsense_revenue.json": "AdSense 미승인 — 승인 후 blog-analytics가 만듭니다",
    "shorts_scripts.json": "shorts-generate 워크플로를 아직 돌리지 않았습니다",
}

#: 만들지만 대시보드에는 안 나오는 파일. 지금은 의도된 것만 남깁니다.
#: 새 항목이 여기 없이 생기면 테스트가 잡습니다.
KNOWN_UNDISPLAYED = {
    "enrich_report.json": "보강 작업 결과 — 로그로만 확인",
    "inbound_links.json": "유입 링크 분석 — 아직 패널 없음",
    "unlicensed_images.json": "라이선스 교체 결과 — 로그로만 확인",
    "incident_log.json": "사람이 정리하는 장애 지식 파일 (auto_repair가 대조용으로 읽음)",
    "schedule_config.json": "사람이 정리하는 스케줄 설정 (schedule_manager 입력)",
    "analytics_summary.json": "dashboard_exporter 입력 — 화면에는 analytics.json으로 나감",
    "schedule_history.json": "스케줄 실행 이력 — 아직 패널 없음",
    "link_clusters.json": "related_posts가 관련 글 링크를 넣을 때 쓰는 파이프라인 파일",
}


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def dashboard_reads() -> set[str]:
    """대시보드가 실제로 fetch하는 데이터 파일 이름."""
    html = _read(_DASHBOARD)
    names = set()
    names |= set(re.findall(r"fetchData\(base,\s*'([a-z_]+\.json)'", html))
    names |= set(re.findall(r"ensureData\(base,\s*'([a-z_]+\.json)'", html))
    names |= set(re.findall(r"fetchStamped\(base,\s*'([a-z_]+\.json)'", html))
    names |= set(re.findall(r"base \+ '/([a-z_]+\.json)", html))
    names |= set(re.findall(r"/data/([a-z_]+\.json)", html))
    return names


def producers() -> dict[str, set[str]]:
    """파일 이름 → 그 이름을 다루는 파이썬 모듈·워크플로.

    쓰기와 읽기를 구분하지는 않습니다. 이름이 어디에도 안 나오면 확실히
    고아이고, 그것이 이 검사가 잡으려는 대상입니다.
    """
    found: dict[str, set[str]] = {}
    for path in glob.glob(os.path.join(_PY_DIR, "*.py")) + glob.glob(os.path.join(_WF_DIR, "*.yml")):
        if os.sep + "tests" + os.sep in path:
            continue
        for name in _JSON_RE.findall(_read(path)):
            found.setdefault(name, set()).add(os.path.basename(path))
    return found


def existing_files() -> set[str]:
    return {os.path.basename(p) for p in glob.glob(os.path.join(_DATA_DIR, "*.json"))}


# ──────────────────────────────────────────────────────────────────────────────

def test_every_file_the_dashboard_reads_has_a_producer():
    """읽는데 아무도 안 만드는 파일 = 영원히 404."""
    orphaned = sorted(dashboard_reads() - set(producers()))
    assert not orphaned, (
        "대시보드가 읽지만 만드는 곳이 없습니다: " + ", ".join(orphaned) +
        "\n생산자를 추가하거나 대시보드에서 그 fetch를 지우세요."
    )


def test_missing_files_are_explained():
    """파일이 없다면 왜 없는지가 적혀 있어야 합니다."""
    missing = dashboard_reads() - existing_files()
    unexplained = sorted(missing - set(NOT_YET_GENERATED))
    assert not unexplained, (
        "대시보드가 읽는데 파일이 없고 이유도 적혀 있지 않습니다: " +
        ", ".join(unexplained) +
        "\n생산자를 돌려 파일을 만들거나, NOT_YET_GENERATED에 이유를 적으세요."
    )


def test_not_yet_generated_list_stays_current():
    """파일이 생겼는데 '아직 없음' 목록에 남아 있으면 목록이 낡은 것입니다."""
    stale = sorted(set(NOT_YET_GENERATED) & existing_files())
    assert not stale, (
        "이미 생성된 파일이 NOT_YET_GENERATED에 남아 있습니다: " + ", ".join(stale) +
        "\n목록에서 지우세요."
    )


def test_no_new_undisplayed_outputs():
    """만들어서 저장까지 하는데 화면에 안 나오는 파일이 늘지 않았는지."""
    undisplayed = existing_files() - dashboard_reads()
    unexpected = sorted(undisplayed - set(KNOWN_UNDISPLAYED))
    assert not unexpected, (
        "저장되지만 대시보드 어디에도 나오지 않습니다: " + ", ".join(unexpected) +
        "\n패널을 붙이거나, 의도된 것이면 KNOWN_UNDISPLAYED에 이유를 적으세요."
    )


def test_undisplayed_list_stays_current():
    """대시보드에 붙었는데 '안 나옴' 목록에 남아 있으면 목록이 낡은 것입니다."""
    now_shown = sorted(set(KNOWN_UNDISPLAYED) & dashboard_reads())
    assert not now_shown, (
        "대시보드에 표시되는데 KNOWN_UNDISPLAYED에 남아 있습니다: " +
        ", ".join(now_shown) + "\n목록에서 지우세요."
    )


def test_freshness_meta_covers_what_the_dashboard_loads():
    """신선도 패널이 주요 파일을 빠뜨리지 않았는지.

    SOURCE_META에 없는 파일은 나이가 표시되지 않아, 낡아도 알 수 없습니다.
    본문 없이 지연 로딩만 하는 보조 파일은 제외합니다.
    """
    html = _read(_DASHBOARD)
    block = html[html.index("const SOURCE_META = {"):]
    block = block[:block.index("\n}")]
    covered = set(re.findall(r"'([a-z_]+\.json)'", block))

    # 화면에 수치를 그리지 않는 보조 파일은 나이를 표시할 자리가 없습니다
    auxiliary = {"pending_bodies.json", "pending_archive.json", "posts_archive.json",
                 "affiliate_links.json", "bot_reply.json", "adsense_revenue.json",
                 "shorts_scripts.json", "post_details.json"}
    uncovered = sorted(dashboard_reads() - covered - auxiliary)
    assert not uncovered, (
        "신선도 표시에서 빠진 파일: " + ", ".join(uncovered) +
        "\ndocs/index.html의 SOURCE_META에 라벨과 기대 주기를 추가하세요."
    )


@pytest.mark.parametrize("name", sorted(NOT_YET_GENERATED))
def test_not_yet_generated_files_have_a_reason(name):
    assert NOT_YET_GENERATED[name].strip(), f"{name}에 이유가 비어 있습니다"
