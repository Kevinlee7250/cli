"""고아 페이지 해소가 발행 속도를 따라잡는지 확인합니다.

도구(inbound_linker)는 2026-08-21부터 정상 동작했는데도 고아가 165건에서
172건으로 오히려 늘었습니다. 링크가 안 걸린 게 아니라 처리량이 모자랐습니다.

  해소:  주 1회 × 10건 = 10건/주
  생성:  발행 1건당 고아 1건 → 하루 1~3편이면 7~21건/주

주간 배치만으로는 수렴하지 않습니다. 두 갈래로 고칩니다.
  1) 발행 직후 그 글에 역방향 링크를 걸어 새 고아가 쌓이지 않게 (blog-run)
  2) 밀린 물량은 매일 배치로 걷어냄 (inbound-links)

이 테스트는 그 설정이 되돌아가지 않는지 지킵니다. 특히 스케줄 실행에는
inputs가 없어 `${{ inputs.limit || 'N' }}`의 N이 실제 값이 되는데, 입력란의
default만 고치고 이쪽을 놓치면 조용히 옛 처리량으로 돌아갑니다.
"""

import os
import re

import pytest

_WF = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..",
                                    ".github", "workflows"))

#: 하루 최대 발행량(블로그 3개 × 여유). 이보다 많이 해소해야 밀린 것이 줄어듭니다.
MAX_POSTS_PER_DAY = 3


def _read(name):
    with open(os.path.join(_WF, name), encoding="utf-8") as f:
        return f.read()


def test_backlog_job_runs_daily():
    """주간이면 밀린 물량을 따라잡지 못합니다."""
    text = _read("inbound-links.yml")
    crons = re.findall(r"cron:\s*'([^']+)'", text)
    assert crons, "스케줄이 없습니다"
    for cron in crons:
        dom, dow = cron.split()[2], cron.split()[4]
        assert dom == "*" and dow == "*", (
            f"매일 실행이어야 합니다 (현재 '{cron}') — 주간 배치로는 "
            f"발행 속도를 따라잡지 못합니다"
        )


def test_scheduled_limit_beats_publish_rate():
    """스케줄 실행이 실제로 쓰는 기본값을 봅니다.

    입력란의 default가 아니라 `inputs.limit || 'N'`의 N이 스케줄 실행 값입니다.
    """
    text = _read("inbound-links.yml")
    m = re.search(r"--limit \$\{\{ inputs\.limit \|\| '(\d+)' \}\}", text)
    assert m, "스케줄 실행의 limit 기본값을 찾지 못했습니다"
    limit = int(m.group(1))
    assert limit > MAX_POSTS_PER_DAY, (
        f"하루 해소 {limit}건이 최대 발행 {MAX_POSTS_PER_DAY}건보다 커야 "
        f"밀린 고아가 줄어듭니다"
    )


def test_input_default_matches_scheduled_default():
    """수동 실행과 스케줄 실행의 기본값이 어긋나면 사람이 오해합니다."""
    text = _read("inbound-links.yml")
    scheduled = re.search(r"--limit \$\{\{ inputs\.limit \|\| '(\d+)' \}\}", text)
    block = text[text.index("      limit:"):]
    declared = re.search(r"default:\s*'(\d+)'", block)
    assert scheduled and declared
    assert scheduled.group(1) == declared.group(1), (
        f"입력란 기본값 {declared.group(1)} ≠ 스케줄 기본값 {scheduled.group(1)}"
    )


@pytest.mark.parametrize("blog", ["blog1", "blog2", "blog3"])
def test_publish_flow_links_new_posts(blog):
    """발행 직후 역방향 링크 단계가 블로그마다 있어야 합니다.

    이것이 없으면 배치가 아무리 빨라도 새 고아가 계속 생깁니다.
    """
    text = _read("blog-run.yml")
    assert f"역방향 내부 링크 ({blog})" in text, f"{blog}에 발행 직후 링크 단계가 없습니다"
    assert f"inbound_linker.py --blog {blog}" in text


def test_publish_flow_refreshes_audit_first():
    """방금 올린 글이 고아 목록에 들어가려면 진단을 먼저 돌려야 합니다.

    inbound_linker는 internal_links.json의 고아 목록을 읽습니다. 진단을
    건너뛰면 새 글이 목록에 없어 그 글만 계속 고아로 남습니다.
    """
    text = _read("blog-run.yml")
    for blog in ("blog1", "blog2", "blog3"):
        seg = text[text.index(f"역방향 내부 링크 ({blog})"):]
        seg = seg[:seg.index("- name:", 10)] if "- name:" in seg[10:] else seg
        audit_at = seg.find("internal_link_audit.py")
        link_at = seg.find("inbound_linker.py")
        assert audit_at != -1, f"{blog}: 진단 단계가 없습니다"
        assert audit_at < link_at, f"{blog}: 진단이 링크 생성보다 먼저여야 합니다"


def test_link_results_are_committed():
    """산출물을 커밋하지 않으면 다음 실행이 낡은 고아 목록을 읽습니다."""
    text = _read("blog-run.yml")
    for path in ("docs/data/internal_links.json", "docs/data/inbound_links.json"):
        assert path in text, f"{path}가 커밋 목록에 없습니다"
