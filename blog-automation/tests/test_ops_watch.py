"""운영 감시 도구 3종의 판정 규칙을 고정합니다 (2026-11-29 · 결재 사무실 기능 4·5·6).

주의: 03 업무 매뉴얼 '테스트 중단 규칙'에 따라 이 테스트는 작성만 했고 실행하지
않았습니다. 실행은 오너 승인 뒤에 합니다.
"""

from datetime import datetime, timezone

import link_policy_audit as L
import silent_failure_watch as S

AFF = '<a href="https://link.coupang.com/a/gLrJSuycxM">상품</a>'
DISC = "<p>이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.</p>"


def _post(blog, html):
    return {"blogId": blog, "url": f"https://x/{blog}", "title": "t", "content": html}


def test_unregistered_blog_coupang_link_is_flagged():
    """2026-11-29: blog2 KBO 직관 글(공개 중)에 쿠팡 링크 — blog2는 파트너스 미등록 채널."""
    r = L.check_post(_post("blog2", AFF + DISC))
    assert [i["rule"] for i in r["issues"]] == ["R1"]


def test_registered_blog_with_disclosure_passes():
    assert L.check_post(_post("blog1", AFF + DISC)) is None


def test_missing_disclosure_is_flagged():
    r = L.check_post(_post("blog1", AFF))
    assert "R3" in [i["rule"] for i in r["issues"]]


def test_naver_link_on_blogger_is_flagged():
    r = L.check_post(_post("blog1", '<a href="https://naver.me/G6Rsg8Iy">샵</a>'))
    assert [i["rule"] for i in r["issues"]] == ["R2"]


def test_banned_word_only_near_link():
    """'항공권 최저가 검색법' 같은 정보성 문장은 링크와 멀면 걸지 않습니다."""
    far = "<p>항공권 최저가 검색법</p>" + "<p>" + "가" * 2000 + "</p>" + AFF + DISC
    assert L.check_post(_post("blog1", far)) is None
    near = "<p>오늘만 최저가!</p>" + AFF + DISC
    assert "R4" in [i["rule"] for i in L.check_post(_post("blog1", near))["issues"]]


def test_plain_coupang_url_is_not_affiliate():
    assert L.check_post(_post("blog2", '<a href="https://www.coupang.com/vp/products/1">x</a>')) is None


def test_parse_ts_variants():
    want = datetime(2026, 11, 28, 5, 35, 55, tzinfo=timezone.utc)
    for s in ("2026-11-28T05:35:55Z", "2026-11-28T05:35:55+00:00", "2026-11-28T05:35:55+0000", "2026-11-28T05:35:55"):
        assert S.parse_ts(s) == want


def test_stale_file_is_reported(tmp_path, monkeypatch):
    """2026-11-06~07: 자동화가 오류 없이 멈춰 13일간 몰랐던 사고."""
    (tmp_path / "index_status.json").write_text('{"checked_at":"2026-11-06T00:00:00+00:00"}', encoding="utf-8")
    monkeypatch.setattr(S.post_sources, "DOCS_DATA", str(tmp_path))
    monkeypatch.setattr(S, "FRESHNESS", [("index_status.json", "checked_at", S.DAY * 2, "테스트")])
    out = S.check_freshness(datetime(2026, 11, 19, tzinfo=timezone.utc))
    assert out[0]["status"] == "stale"
