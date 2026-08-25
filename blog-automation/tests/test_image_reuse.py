"""같은 사진이 여러 글에 반복되지 않게 — 내용 해시로 판정합니다.

URL이나 제목으로는 이 판정을 할 수 없습니다. Pixabay는 같은 사진에 매번
다른 서명 URL을 주고 태그 문자열도 조금씩 다릅니다. 2026-08-25 파일럿에서
새로 채택한 13장 중 10장이 이미 저장소에 있는 사진과 바이트 단위로
동일했고, 한 장은 61편에 들어가 있었습니다.

내려받아 해시를 계산한 뒤에야 같은 사진인 줄 알 수 있으므로, 복제기가
세어 주는 사용 횟수로 판정합니다.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import image_mirror  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(image_mirror, "MIRROR_DIR", str(tmp_path / "images"))
    monkeypatch.setattr(image_mirror, "MANIFEST_FILE", str(tmp_path / "m.json"))
    monkeypatch.setenv("IMAGE_HOST_BASE", "https://example.test/images")
    return tmp_path


class _Resp:
    status_code = 200

    def __init__(self, body=PNG):
        self.body = body
        self.headers = {"Content-Type": "image/png"}

    def raise_for_status(self):
        pass

    def iter_content(self, n):
        yield self.body


def test_same_photo_from_different_urls_counts_up(store, monkeypatch):
    """서명 URL이 달라도 내용이 같으면 같은 사진입니다."""
    monkeypatch.setattr(image_mirror.requests, "get", lambda *a, **k: _Resp())
    a = image_mirror.mirror_url("https://pixabay.com/get/sig1.jpg")
    b = image_mirror.mirror_url("https://pixabay.com/get/sig2.jpg")
    assert a["file"] == b["file"], "같은 내용인데 다른 파일로 저장됐습니다"
    assert image_mirror.times_used(b["url"]) == 2


def test_reusing_the_same_url_also_counts(store, monkeypatch):
    monkeypatch.setattr(image_mirror.requests, "get", lambda *a, **k: _Resp())
    url = "https://pixabay.com/get/sig1.jpg"
    image_mirror.mirror_url(url)
    again = image_mirror.mirror_url(url)
    assert again["reused"] is True
    assert image_mirror.times_used(again["url"]) == 2


def test_overuse_threshold(store, monkeypatch):
    monkeypatch.setattr(image_mirror.requests, "get", lambda *a, **k: _Resp())
    got = None
    for i in range(image_mirror.MAX_REUSE):
        got = image_mirror.mirror_url(f"https://pixabay.com/get/s{i}.jpg")
    assert image_mirror.is_overused(got["url"]) is False
    got = image_mirror.mirror_url("https://pixabay.com/get/extra.jpg")
    assert image_mirror.is_overused(got["url"]) is True


def test_old_records_without_uses_fall_back_to_origins(store):
    """오늘 이전 기록에는 uses가 없습니다 — origins 개수가 최소값입니다."""
    image_mirror.save_manifest({"items": {"a" * 16: {
        "file": "a" * 16 + ".jpg", "origins": ["u1", "u2", "u3", "u4"]}}})
    assert image_mirror.times_used(f"https://example.test/images/{'a' * 16}.jpg") == 4
    assert image_mirror.is_overused(f"https://example.test/images/{'a' * 16}.jpg") is True


def test_unknown_url_is_not_overused(store):
    assert image_mirror.times_used("https://example.test/images/deadbeefdeadbeef.jpg") == 0
    assert image_mirror.is_overused("https://elsewhere/x.jpg") is False


# ── 후보 재선택 ──────────────────────────────────────────────────────────────

def _wire(monkeypatch, candidates, uses_by_url):
    """검색·채택·사용횟수를 갈아 끼웁니다."""
    import fix_unlicensed_images as fx
    monkeypatch.setattr("image_fetcher._search_all_sources",
                        lambda *a, **k: [dict(c) for c in candidates])
    monkeypatch.setattr("image_fetcher.filter_license_safe", lambda imgs: imgs)
    monkeypatch.setattr("image_fetcher.is_license_safe", lambda u: True)
    monkeypatch.setattr("image_fetcher._score_title_relevance",
                        lambda img, q: img.get("score", 0))
    monkeypatch.setattr("image_fetcher.adopt_image", lambda img: img)
    monkeypatch.setattr("image_fetcher.generate_fallback_image", lambda t, k: None)
    monkeypatch.setattr(image_mirror, "times_used",
                        lambda url: uses_by_url.get(url, 0))
    return fx


def test_overused_candidate_is_skipped(monkeypatch):
    """가장 관련성 높은 후보라도 이미 많이 썼으면 다음으로 넘어갑니다."""
    fx = _wire(monkeypatch,
               [{"url": "a", "score": 1.0}, {"url": "b", "score": 0.9}],
               {"a": 99, "b": 0})
    assert fx._find_safe_replacement("어떤 글 제목")["url"] == "b"


def test_all_overused_reuses_the_least_used(monkeypatch):
    """전부 과다 사용이면 가장 덜 쓴 것 — 여기서 None을 주면 이미지가 삭제됩니다."""
    fx = _wire(monkeypatch,
               [{"url": "a", "score": 1.0}, {"url": "b", "score": 0.9}],
               {"a": 50, "b": 10})
    assert fx._find_safe_replacement("어떤 글 제목")["url"] == "b"


def test_fresh_candidate_wins_immediately(monkeypatch):
    fx = _wire(monkeypatch, [{"url": "a", "score": 1.0}], {"a": 0})
    assert fx._find_safe_replacement("어떤 글 제목")["url"] == "a"
