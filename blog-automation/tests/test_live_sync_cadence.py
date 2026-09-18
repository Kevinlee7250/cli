"""공개 글 목록이 발행 주기에 맞춰 갱신되는지 검사합니다.

live_posts.json은 blog-cluster(주 1회, 일요일)에서만 갱신됐습니다.
그 사이 발행된 글은 목록에 없고, related_posts 필터가 '내려간 글'로 보고
관련 포스트 후보에서 빼버립니다. 새 글일수록 고아가 됩니다.

2026-09-18 확인: live_posts.json은 9/13자였고 그 사이 19편이 발행됐습니다.
"""
import os
import re

import pytest

_WF = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    ".github", "workflows", "blog-run.yml",
)


def _text():
    with open(_WF, encoding="utf-8") as f:
        return f.read()


def test_every_blog_syncs_the_live_list_after_publishing():
    """blog1·2·3 세 잡 모두 발행 뒤 동기화해야 합니다."""
    n = _text().count("python sync_live_posts.py")
    assert n == 3, f"동기화 스텝이 {n}개입니다 — 블로그 3개 모두 필요합니다"


def test_live_list_is_committed():
    """동기화만 하고 커밋하지 않으면 러너와 함께 사라집니다."""
    n = _text().count("docs/data/live_posts.json")
    assert n == 3, f"커밋 목록에 {n}번 들어 있습니다 — 세 잡 모두 필요합니다"


def test_sync_runs_before_the_commit_step():
    """커밋 뒤에 동기화하면 그 실행분은 커밋되지 않습니다."""
    text = _text()
    for blog in ("blog1", "blog2", "blog3"):
        commit = text.find(f"대시보드 데이터 커밋 & 푸시 ({blog})")
        assert commit > 0, f"{blog} 커밋 스텝을 찾지 못했습니다"
        sync = text.rfind("python sync_live_posts.py", 0, commit)
        assert sync > 0, f"{blog} 커밋 앞에 동기화 스텝이 없습니다"


def test_sync_failure_never_blocks_publishing():
    """동기화는 부가 작업입니다 — 실패해도 발행 잡을 죽이면 안 됩니다."""
    text = _text()
    for m in re.finditer(r"python sync_live_posts\.py", text):
        block = text[max(0, m.start() - 400):m.start()]
        assert "continue-on-error: true" in block, (
            "동기화 스텝에 continue-on-error가 없습니다"
        )
