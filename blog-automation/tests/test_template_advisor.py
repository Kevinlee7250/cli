"""글 템플릿 추천 테스트 (2026-08-22).

수동 발행에서 사람이 구조를 고를 수 있게 하는 기능입니다. 판정 규칙이
content_generator 한 곳에만 살아야 하고, 사람이 고른 값은 그 실행에서만
유효해야 합니다.

실행: cd blog-automation && python -m pytest tests/test_template_advisor.py -v
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import content_generator as cg  # noqa: E402
import template_advisor as ta  # noqa: E402


def _registry(tmp_path, types, blog_id="blog1"):
    rows = [{"status": "published", "blogId": blog_id, "articleType": t}
            for t in types]
    p = tmp_path / "reg.json"
    p.write_text(json.dumps(rows), encoding="utf-8")
    return str(p)


# ── 추천 ─────────────────────────────────────────────────────────────────────

def test_auto_detected_type_is_recommended():
    r = ta.recommend("벌초 대행 서비스 비용 비교", registry_path="/없음")
    assert r["recommended"] == "comparison"
    assert r["autoDetected"] == "comparison"


def test_candidates_carry_a_reason():
    r = ta.recommend("제주 여행 코스 추천", registry_path="/없음")
    assert r["candidates"], "후보가 비면 사람이 고를 수 없습니다"
    assert all(c["why"] for c in r["candidates"])


def test_overused_template_is_flagged(tmp_path):
    """같은 구조만 반복하면 AI 템플릿 패턴으로 감점됩니다."""
    reg = _registry(tmp_path, ["comparison"] * 10 + ["how_to", "review"])
    r = ta.recommend("요금제 비교", "blog1", registry_path=reg)
    comp = next(c for c in r["candidates"] if c["id"] == "comparison")
    assert "반복 주의" in comp["why"]


def test_overuse_does_not_silently_replace_the_fit(tmp_path):
    """다양화보다 키워드 적합성이 우선입니다 — 경고만 하고 바꾸지 않습니다."""
    reg = _registry(tmp_path, ["comparison"] * 12)
    r = ta.recommend("A vs B 비교 장단점", "blog1", registry_path=reg)
    assert r["autoDetected"] == "comparison"


def test_missing_registry_is_not_an_error():
    r = ta.recommend("아무 키워드", registry_path="/존재하지/않는/파일.json")
    assert r["recommended"] and r["recentUsage"] == {}


def test_recent_usage_is_scoped_to_the_blog(tmp_path):
    reg = _registry(tmp_path, ["comparison"] * 10, blog_id="blog2")
    r = ta.recommend("요금제 비교", "blog1", registry_path=reg)
    assert r["recentUsage"] == {}, "다른 블로그 이력이 섞이면 안 됩니다"


# ── 내보내기 (대시보드가 규칙을 다시 구현하지 않도록) ────────────────────────

def test_export_contains_signals_and_meta(tmp_path):
    out = ta.export_templates(str(tmp_path / "templates.json"))
    data = json.loads(open(out, encoding="utf-8").read())
    assert data["defaultType"] == cg.DEFAULT_ARTICLE_TYPE
    assert set(data["templates"]) == set(ta.TEMPLATE_META)
    assert data["templates"]["comparison"]["signals"], "판정 신호가 함께 나가야 합니다"
    assert data["templates"]["comparison"]["name"]


def test_every_signal_type_has_meta():
    """규칙에 있는 유형인데 설명이 없으면 사람이 고를 수 없습니다."""
    for tid, _ in cg.TYPE_SIGNALS:
        assert tid in ta.TEMPLATE_META, f"{tid} 설명 누락"
    assert cg.DEFAULT_ARTICLE_TYPE in ta.TEMPLATE_META


# ── 사람이 고른 값 적용 ──────────────────────────────────────────────────────

def test_override_forces_the_chosen_template():
    with cg.article_type_override("comparison"):
        assert cg._detect_article_type("제주 여행 코스") == "comparison"


def test_override_is_released_after_the_block():
    with cg.article_type_override("comparison"):
        pass
    assert cg._detect_article_type("제주 여행 코스") == "travel_guide"


def test_auto_means_no_override():
    with cg.article_type_override("auto"):
        assert cg._detect_article_type("제주 여행 코스") == "travel_guide"


def test_override_is_restored_even_on_error():
    """예외로 빠져나가도 다음 글까지 끌고 가면 안 됩니다."""
    try:
        with cg.article_type_override("comparison"):
            raise RuntimeError("중단")
    except RuntimeError:
        pass
    assert cg._detect_article_type("제주 여행 코스") == "travel_guide"
