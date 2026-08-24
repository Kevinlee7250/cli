"""A5 ads.txt 헬스체크 / A6 이미지 출처 표기 / B2 학습→프롬프트 폐루프 테스트.

실행: cd blog-automation && python -m pytest tests/test_a5_a6_b2.py -v
"""

import json
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ──────────────────────────────────────────────────────────────────────────────
# A5 — ads.txt 헬스체크
# ──────────────────────────────────────────────────────────────────────────────

def test_publisher_id_strips_ca_prefix(monkeypatch):
    import auth_health_check as ahc
    monkeypatch.setenv("ADSENSE_CLIENT_ID", "ca-pub-1234567890123456")
    assert ahc._publisher_id() == "pub-1234567890123456"


def test_publisher_id_empty_for_placeholder(monkeypatch):
    import auth_health_check as ahc
    monkeypatch.setenv("ADSENSE_CLIENT_ID", "ca-pub-XXXXXXXXXXXXXXXXX")
    assert ahc._publisher_id() == ""


def test_ads_txt_ok_when_publisher_id_present():
    import auth_health_check as ahc
    resp = MagicMock(status_code=200, text="google.com, pub-123, DIRECT, f08c47fec0942fa0")
    with patch("requests.get", return_value=resp):
        r = ahc.check_ads_txt("https://x.com/", "블로그", "pub-123")
    assert r["ok"] is True


def test_ads_txt_fails_on_404_with_actionable_message():
    """AdSense '찾을 수 없음'의 실제 원인(Blogger 설정 미적용)을 알려줘야 함."""
    import auth_health_check as ahc
    with patch("requests.get", return_value=MagicMock(status_code=404, text="")):
        r = ahc.check_ads_txt("https://x.com/", "블로그", "pub-123")
    assert r["ok"] is False
    assert "맞춤 ads.txt" in r["error"]


def test_ads_txt_fails_when_publisher_id_mismatched():
    """다른 계정 ID가 들어간 경우 — 서빙은 되지만 내 수익으로 안 잡힘."""
    import auth_health_check as ahc
    resp = MagicMock(status_code=200, text="google.com, pub-999, DIRECT, f08c47fec0942fa0")
    with patch("requests.get", return_value=resp):
        r = ahc.check_ads_txt("https://x.com/", "블로그", "pub-123")
    assert r["ok"] is False
    assert "pub-123" in r["error"]


def test_ads_txt_handles_network_error():
    import auth_health_check as ahc
    import requests as rq
    with patch("requests.get", side_effect=rq.exceptions.Timeout("timeout")):
        r = ahc.check_ads_txt("https://x.com/", "블로그", "pub-123")
    assert r["ok"] is False


def test_check_all_ads_txt_uses_custom_domain(monkeypatch):
    """커스텀 도메인이 있으면 blogspot이 아니라 그쪽을 확인해야 함."""
    import auth_health_check as ahc
    monkeypatch.setenv("ADSENSE_CLIENT_ID", "ca-pub-123")
    blogs = [{"id": "blog1", "name": "B1", "gsc_site_url": "https://www.hoguwhat.com/"}]
    called = {}

    def fake_get(url, **kw):
        called["url"] = url
        return MagicMock(status_code=200, text="google.com, pub-123, DIRECT, x")

    with patch("config.get_blog_configs", return_value=blogs), \
         patch("requests.get", side_effect=fake_get):
        results = ahc.check_all_ads_txt()
    assert called["url"] == "https://www.hoguwhat.com/ads.txt"
    assert results[0]["ok"] is True


def test_check_all_ads_txt_without_adsense_id(monkeypatch):
    import auth_health_check as ahc
    monkeypatch.delenv("ADSENSE_CLIENT_ID", raising=False)
    results = ahc.check_all_ads_txt()
    assert results[0]["ok"] is False


# ──────────────────────────────────────────────────────────────────────────────
# A6 — 이미지 출처 표기
# ──────────────────────────────────────────────────────────────────────────────

def test_attribution_for_known_sources():
    from image_fetcher import _attribution_text
    assert "Pixabay" in _attribution_text({"source": "pixabay"})
    assert "Wikimedia" in _attribution_text({"source": "wikimedia"})


def test_attribution_empty_for_unknown_source():
    """소스를 모르면 지어내지 않고 표기 생략."""
    from image_fetcher import _attribution_text
    assert _attribution_text({}) == ""
    assert _attribution_text({"source": "이상한값"}) == ""


def test_img_html_includes_attribution_with_caption():
    from image_fetcher import _make_img_html
    html = _make_img_html({"url": "http://x/a.jpg", "source": "pixabay"}, "설명", "캡션")
    assert "캡션" in html and "이미지 출처: Pixabay" in html


def test_img_html_shows_attribution_without_caption():
    """캡션이 없어도 출처는 표기되어야 함."""
    from image_fetcher import _make_img_html
    html = _make_img_html({"url": "http://x/a.jpg", "source": "pixabay"}, "설명", "")
    assert "이미지 출처: Pixabay" in html
    assert "<figcaption" in html


def test_img_html_no_figcaption_when_nothing_to_show():
    from image_fetcher import _make_img_html
    html = _make_img_html({"url": "http://x/a.jpg"}, "설명", "")
    assert "<figcaption" not in html


def test_img_html_links_attribution_only_with_page_url():
    """실제 자료 페이지가 있을 때만 링크 — 관련 없는 페이지 연결은 정책 위반."""
    from image_fetcher import _make_img_html
    linked = _make_img_html(
        {"url": "http://x/a.jpg", "source": "wikimedia",
         "page_url": "https://commons.wikimedia.org/wiki/File:A"}, "설명", "")
    plain = _make_img_html({"url": "http://x/a.jpg", "source": "pixabay"}, "설명", "")
    assert 'rel="nofollow noopener"' in linked
    assert "<a href" not in plain


def test_img_html_escapes_caption():
    from image_fetcher import _make_img_html
    html = _make_img_html({"url": "http://x/a.jpg", "source": "pixabay"}, "alt", "<script>x</script>")
    assert "<script>" not in html


# ──────────────────────────────────────────────────────────────────────────────
# B2 — 주간 학습 → 프롬프트 자동 주입
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def tips_file(tmp_path):
    return str(tmp_path / "learned_writing_tips.json")


def _write_tips(path, guidelines, days_ago=0):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": (datetime.now() - timedelta(days=days_ago)).isoformat(),
            "guidelines": guidelines,
        }, f, ensure_ascii=False)


def test_learned_guidelines_injected(tips_file):
    import content_generator as cg
    _write_tips(tips_file, ["도입부에 구체적 수치를 넣을 것", "표를 1개 이상 사용할 것"])
    with patch.object(cg, "_WRITING_TIPS_FILE", tips_file):
        block = cg._learned_guidelines_block()
    assert "구체적 수치" in block and "표를 1개 이상" in block


def test_learned_guidelines_ignored_when_stale(tips_file):
    """오래된 판단이 계속 남아 글쓰기를 왜곡하지 않도록 만료 처리."""
    import content_generator as cg
    _write_tips(tips_file, ["낡은 지침"], days_ago=60)
    with patch.object(cg, "_WRITING_TIPS_FILE", tips_file):
        assert cg._learned_guidelines_block() == ""


def test_learned_guidelines_empty_when_no_file():
    """학습 데이터가 없어도 글 생성은 평소대로 동작해야 함."""
    import content_generator as cg
    with patch.object(cg, "_WRITING_TIPS_FILE", "/nonexistent/tips.json"):
        assert cg._learned_guidelines_block() == ""


def test_learned_guidelines_survives_corrupt_file(tmp_path):
    import content_generator as cg
    bad = tmp_path / "bad.json"
    bad.write_text("{깨진 JSON", encoding="utf-8")
    with patch.object(cg, "_WRITING_TIPS_FILE", str(bad)):
        assert cg._learned_guidelines_block() == ""


def test_build_prompt_contains_learned_guidelines(tips_file):
    import content_generator as cg
    _write_tips(tips_file, ["숫자로 시작할 것"])
    with patch.object(cg, "_WRITING_TIPS_FILE", tips_file):
        prompt = cg._build_prompt("부산 여행", "N/A", {"id": "blog1", "topics": ["여행"]})
    assert "숫자로 시작할 것" in prompt


def test_weekly_learning_saves_guidelines(tmp_path, monkeypatch):
    import weekly_learning as wl
    tips = tmp_path / "tips.json"
    monkeypatch.setattr(wl, "WRITING_TIPS_FILE", str(tips))
    monkeypatch.setattr(wl, "LEARNED_KW_FILE", str(tmp_path / "kw.json"))

    applied = wl._auto_apply({
        "writing_guidelines": ["지침A", "지침B"],
        "guidelines_reason": "S등급 글의 공통점",
    })

    saved = json.loads(tips.read_text(encoding="utf-8"))
    assert saved["guidelines"] == ["지침A", "지침B"]
    assert saved["reason"] == "S등급 글의 공통점"
    assert any("글쓰기 지침" in a for a in applied)


def test_weekly_learning_skips_empty_guidelines(tmp_path, monkeypatch):
    import weekly_learning as wl
    tips = tmp_path / "tips.json"
    monkeypatch.setattr(wl, "WRITING_TIPS_FILE", str(tips))
    monkeypatch.setattr(wl, "LEARNED_KW_FILE", str(tmp_path / "kw.json"))

    wl._auto_apply({"writing_guidelines": ["", "  "]})
    assert not tips.exists()


# ── A5 추가: 일시적 응답(429/5xx) 구분 (2026-08-10 점검에서 발견) ────────────────

def test_ads_txt_429_marked_transient_not_config_error():
    """429는 설정 문제가 아님 — 멀쩡한 설정을 건드리게 만드는 오안내 방지."""
    import auth_health_check as ahc
    resp = MagicMock(status_code=429, text="")
    with patch("requests.get", return_value=resp), patch("time.sleep"):
        r = ahc.check_ads_txt("https://x.com/", "블로그", "pub-123")
    assert r["ok"] is False
    assert r.get("transient") is True
    assert "설정 문제 아님" in r["error"]


def test_ads_txt_retries_once_on_429():
    import auth_health_check as ahc
    responses = [MagicMock(status_code=429, text=""),
                 MagicMock(status_code=200, text="google.com, pub-123, DIRECT, x")]
    with patch("requests.get", side_effect=responses), patch("time.sleep"):
        r = ahc.check_ads_txt("https://x.com/", "블로그", "pub-123")
    assert r["ok"] is True


def test_ads_txt_404_still_reports_config_action():
    """404는 진짜 미설정 — 조치 안내가 나와야 함."""
    import auth_health_check as ahc
    with patch("requests.get", return_value=MagicMock(status_code=404, text="")), \
         patch("time.sleep"):
        r = ahc.check_ads_txt("https://x.com/", "블로그", "pub-123")
    assert r.get("transient") is not True
    assert "맞춤 ads.txt" in r["error"]


def test_run_all_ok_ignores_transient_failures(monkeypatch, tmp_path):
    """레이트 리밋 때문에 '인증 문제 감지' 경보가 뜨면 안 됨."""
    import auth_health_check as ahc
    monkeypatch.setattr(ahc, "_DOCS_DATA", str(tmp_path))
    with patch.object(ahc, "check_google_oauth", return_value={"name": "google_oauth", "ok": True, "error": None}), \
         patch.object(ahc, "check_all_ads_txt", return_value=[
             {"name": "ads_txt:A", "ok": True, "error": None},
             {"name": "ads_txt:B", "ok": False, "transient": True, "error": "HTTP 429"},
         ]):
        report = ahc.run()
    assert report["all_ok"] is True

