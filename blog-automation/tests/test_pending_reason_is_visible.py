"""보류 사유가 검토 화면까지 도달하는지 확인합니다.

왜
──
main.py의 팩트체크 게이트는 post_data["pending_reason"]을 채우고 글을 보류
목록으로 보냅니다. 그런데 저장 경로(save_pending_posts)의 항목 딕셔너리는
필드 화이트리스트라 사유가 실려 가지 않았습니다. 게이트는 도는데 검토하는
사람 눈에는 "왜 세워졌는지 없는 평범한 검토 대기"로만 보입니다.

레지스트리(post_manager.register_post)도 같은 화이트리스트 구조라 사유를
싣지 않습니다. 그래서 보류 사유가 남는 유일한 곳이 이 경로입니다.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dashboard_exporter  # noqa: E402

_HTML = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..",
                                      "docs", "index.html"))


def _save(monkeypatch, results):
    saved = {}

    class _Store:
        @staticmethod
        def load():
            return []

        @staticmethod
        def save(rows):
            saved["rows"] = rows

    monkeypatch.setitem(sys.modules, "pending_store", _Store)
    dashboard_exporter.save_pending_posts(results, {"id": "blog1", "name": "테스트"})
    return saved.get("rows", [])


def test_pending_reason_survives_the_save(monkeypatch):
    rows = _save(monkeypatch, [{
        "title": "보류된 글",
        "content": "<p>본문</p>",
        "keyword": "키워드",
        "pending_reason": "팩트체크 미수정 2건: 통계 출처 없음",
        "fact_check": {"verdict": "warn", "issues_found": 2, "fixes_applied": 0},
    }])
    assert len(rows) == 1
    assert rows[0]["pendingReason"] == "팩트체크 미수정 2건: 통계 출처 없음"
    assert rows[0]["factCheck"]["issues_found"] == 2


def test_ordinary_review_post_carries_no_reason(monkeypatch):
    """사유 없는 글까지 배너가 뜨면 경고가 의미를 잃습니다."""
    rows = _save(monkeypatch, [{
        "title": "평범한 글", "content": "<p>본문</p>", "keyword": "키워드",
    }])
    assert rows[0]["pendingReason"] == ""
    assert rows[0]["factCheck"] is None


def test_dashboard_actually_renders_the_reason():
    """정의만 있고 부르지 않으면 화면에는 아무것도 안 뜹니다 — 실제 사용처를 셉니다."""
    with open(_HTML, encoding="utf-8") as f:
        html = f.read()
    assert "p.pendingReason" in html, "대시보드가 보류 사유를 읽지 않습니다"
    assert html.count("${reasonHtml}") >= 1, (
        "reasonHtml을 만들기만 하고 카드에 끼워 넣지 않았습니다 — "
        "값은 있는데 화면에는 없는 상태입니다"
    )
