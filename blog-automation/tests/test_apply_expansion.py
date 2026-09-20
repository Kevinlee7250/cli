"""보강 원고 반영 도구를 검사합니다.

분량이 모자란 글을 AI로 자동 증량하는 기능은 일부러 만들지 않았습니다.
"글자수를 채워라"만큼 지어내기를 부르는 지시도 없고, 그게 바로
2026-09-12 AdSense 거절 사유였습니다.

이 도구는 사람이 검증해 git에 넣은 원고를 옮겨 붙이기만 합니다.
그 경계를 코드가 지키는지 보는 파일입니다.
"""
import glob
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from apply_expansion import expand, load_expansions  # noqa: E402

BODY = ("<p>앞부분입니다.</p>\n<h2>결론</h2>\n<p>맺음말입니다.</p>")
EXP = {
    "anchor": "<h2>결론</h2>",
    "marker": "새로 넣은 절",
    "html": "<h2>새로 넣은 절</h2>\n<p>공식 발표 기준으로 정리한 내용입니다.</p>",
}


def test_inserted_before_the_anchor():
    new, why = expand(BODY, EXP)
    assert why == ""
    assert new.index("새로 넣은 절") < new.index("<h2>결론</h2>")
    assert "앞부분입니다" in new and "맺음말입니다" in new


def test_running_twice_changes_nothing():
    once, _ = expand(BODY, EXP)
    twice, why = expand(once, EXP)
    assert twice == once and why == "이미 반영됨"


def test_ambiguous_anchor_is_refused():
    """앵커가 여러 번이면 엉뚱한 자리에 들어갑니다 — 중단해야 합니다."""
    body = BODY + "\n<h2>결론</h2>"
    new, why = expand(body, EXP)
    assert new == body and "앵커" in why


def test_missing_anchor_is_refused():
    new, why = expand("<p>앵커가 없는 본문</p>", EXP)
    assert new == "<p>앵커가 없는 본문</p>" and "앵커" in why


def test_empty_manuscript_is_refused():
    new, why = expand(BODY, dict(EXP, html=""))
    assert new == BODY and "비어" in why


def test_manuscript_claiming_experience_is_refused():
    """사람이 쓴 원고라도 경험 주장이 있으면 올리지 않습니다."""
    bad = dict(EXP, html="<h2>새로 넣은 절</h2><p>제가 직접 써본 후기입니다.</p>")
    new, why = expand(BODY, bad)
    assert new == BODY and "경험 주장" in why


def test_appends_when_no_anchor_given():
    new, why = expand(BODY, dict(EXP, anchor=""))
    assert why == "" and new.startswith(BODY)


# ── 저장소에 든 실제 원고 ────────────────────────────────────────────────

def test_every_manuscript_has_its_provenance():
    """어디서 온 내용인지 적혀 있지 않으면 나중에 검증할 수 없습니다."""
    for e in load_expansions():
        assert e.get("blog") and e.get("url"), e["slug"]
        assert e.get("why"), f"{e['slug']}: 왜 보강하는지 없음"
        assert e.get("sources"), f"{e['slug']}: 출처 없음"
        assert e.get("verifiedAt"), f"{e['slug']}: 확인 날짜 없음"


def test_every_manuscript_passes_the_experience_audit():
    from experience_audit import analyze_text, _strip_html
    for e in load_expansions():
        hits = analyze_text(_strip_html(e["html"]))
        assert not hits, f"{e['slug']}: {[h['label'] for h in hits]}"


def test_manuscripts_are_substantial():
    """한두 줄 붙여 글자수만 채우는 용도가 아닙니다."""
    for e in load_expansions():
        from experience_audit import _strip_html
        assert len(_strip_html(e["html"])) >= 400, e["slug"]
