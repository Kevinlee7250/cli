"""정책 위반과 '있으면 좋은 것'을 같은 숫자로 세지 않는지 검사합니다.

2026-09-27 주간 점검: 새 글 22편이 올라온 뒤 AdSense 구조 지적이
1건 → 9건으로 늘었습니다. 그런데 **8건이 전부 "FAQ 섹션 없음"**이었습니다.

생성 프롬프트는 일부러 이렇게 적고 있습니다 —
  "검색 의도상 독자가 실제로 궁금해할 때만 2~5개.
   필요 없으면 FAQ 섹션을 생략하세요."

즉 생성은 "생략해도 된다", 감사는 "없으면 지적"이라 서로 어긋났습니다.
FAQ는 AdSense 요건이 아니고, 모든 글에 억지로 붙이면 심사가 싫어하는
형식적 채우기가 됩니다. 그래서 감사 쪽을 고쳤습니다.

지적 9건이라고 하면 9개를 고쳐야 하는 것처럼 읽힙니다. 이 프로젝트는
이미 그 착시로 시간을 썼습니다(9/19 과탐지 42건 중 진짜 3건).
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from adsense_audit import audit_post  # noqa: E402

LONG = "충분히 긴 본문입니다. " * 400          # 2,500자 초과
SOURCES = "<h2>참고자료</h2><ul><li>출처</li></ul>"
FAQ = "<h2>자주 묻는 질문</h2><p>Q. 무엇인가요?</p>"
IMG = '<img src="x.jpg" alt="설명">'


def _post(body, title="평범한 정보 정리 글"):
    return {"title": title, "content": body, "labels": []}


def test_missing_faq_is_a_suggestion_not_an_issue():
    _, issues, _, sugg = audit_post(_post(f"<p>{LONG}</p>{IMG}{SOURCES}"))
    assert issues == [], f"FAQ 없음이 지적으로 남아 있습니다: {issues}"
    assert any("FAQ" in s for s in sugg)


def test_post_with_faq_gets_no_suggestion():
    _, issues, _, sugg = audit_post(_post(f"<p>{LONG}</p>{IMG}{SOURCES}{FAQ}"))
    assert issues == [] and sugg == []


# ── 진짜 문제는 여전히 지적입니다 ─────────────────────────────────────────

def test_thin_content_is_still_an_issue():
    _, issues, _, _ = audit_post(_post(f"<p>짧은 글입니다.</p>{IMG}{SOURCES}{FAQ}"))
    assert any(i.startswith("글자수 부족") for i in issues), issues


def test_missing_sources_is_still_an_issue():
    _, issues, _, _ = audit_post(_post(f"<p>{LONG}</p>{IMG}{FAQ}"))
    assert any("출처" in i for i in issues), issues


def test_clickbait_title_is_still_an_issue():
    _, issues, _, _ = audit_post(
        _post(f"<p>{LONG}</p>{IMG}{SOURCES}{FAQ}", title="충격 실화냐 대박 정리"))
    assert any("과장" in i for i in issues), issues


def test_draft_trigger_still_reads_from_issues():
    """글자수 미달 → draft 전환 판정이 issues를 보므로 거기 남아야 합니다."""
    _, issues, _, _ = audit_post(_post(f"<p>짧음</p>{IMG}{SOURCES}{FAQ}"))
    assert any(i.startswith("글자수 부족") for i in issues)


def test_audit_post_returns_four_values():
    """호출부가 4개를 받도록 바뀌었으니 계약을 고정합니다."""
    out = audit_post(_post(f"<p>{LONG}</p>{IMG}{SOURCES}{FAQ}"))
    assert len(out) == 4
    fixes, issues, content, sugg = out
    assert isinstance(fixes, list) and isinstance(issues, list)
    assert isinstance(content, str) and isinstance(sugg, list)


def test_suggestion_alone_does_not_count_as_needing_review():
    """제안만 있는 글은 '수동확인 필요'로 세지 않아야 합니다."""
    _, issues, _, sugg = audit_post(_post(f"<p>{LONG}</p>{IMG}{SOURCES}"))
    assert sugg and not issues
