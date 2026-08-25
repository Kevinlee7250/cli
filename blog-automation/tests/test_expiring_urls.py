"""만료되는 이미지 주소 — 고르지 않고, 놓치지 않습니다.

2026-08-25 소급 작업에서 발행 글 이미지 35장 중 34장이 이미 죽어 있었습니다.
전부 Pixabay의 largeImageURL(pixabay.com/get/<해시>_1280.jpg) 형태였습니다.
이 주소는 서명·만료되며, 기한이 지나면 404가 아니라 **400**을 돌려줍니다.

두 군데가 동시에 실패해서 여기까지 왔습니다.
  · image_fetcher가 화질을 이유로 만료되는 주소를 우선 골랐습니다.
  · image_audit이 400을 "일시적일 수 있음"으로 넘겨, 감사에서 broken 0건이
    나왔습니다. 도구가 초록인데 글은 깨져 있었습니다.

양쪽을 다 고정합니다.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import image_audit  # noqa: E402
import image_fetcher  # noqa: E402

LARGE = "https://pixabay.com/get/gabc123_1280.jpg"      # 만료됨
STABLE = "https://cdn.pixabay.com/photo/2020/1/1/x.jpg"  # 영구


# ── 고르기 ───────────────────────────────────────────────────────────────────

def test_pixabay_keeps_a_permanent_fallback(monkeypatch):
    """만료되는 주소를 쓰더라도 영구 주소를 함께 들고 있어야 합니다."""
    class _R:
        status_code = 200

        @staticmethod
        def json():
            return {"hits": [{"largeImageURL": LARGE, "webformatURL": STABLE,
                              "tags": "sea, sky", "imageWidth": 1280,
                              "imageHeight": 720}]}

    monkeypatch.setattr(image_fetcher.requests, "get", lambda *a, **k: _R())
    imgs = image_fetcher._pixabay_images("sea", 1, "key")
    assert imgs and imgs[0]["url"] == LARGE
    assert imgs[0]["stable_url"] == STABLE


def test_unmirrored_image_falls_back_to_the_permanent_url():
    """복제가 안 됐다면 만료되는 주소를 남겨두면 안 됩니다."""
    imgs = [{"url": LARGE, "stable_url": STABLE}]
    image_fetcher._prefer_stable_urls(imgs)
    assert imgs[0]["url"] == STABLE


def test_mirrored_image_is_left_alone():
    """복제에 성공했으면 우리 도메인을 그대로 둡니다 — 화질을 버릴 이유가 없습니다."""
    imgs = [{"url": "https://example.test/images/a.png",
             "origin_url": LARGE, "stable_url": STABLE}]
    image_fetcher._prefer_stable_urls(imgs)
    assert imgs[0]["url"] == "https://example.test/images/a.png"


def test_image_without_a_stable_url_is_untouched():
    imgs = [{"url": "https://upload.wikimedia.org/x.jpg"}]
    image_fetcher._prefer_stable_urls(imgs)
    assert imgs[0]["url"] == "https://upload.wikimedia.org/x.jpg"


# ── 잡아내기 ─────────────────────────────────────────────────────────────────

class _Head:
    def __init__(self, code):
        self.status_code = code
        self.headers = {"Content-Type": "image/jpeg"}


@pytest.fixture
def head(monkeypatch):
    def _set(code, referer_code=None):
        monkeypatch.setattr(image_audit.requests, "head",
                            lambda *a, **k: _Head(code))
        monkeypatch.setattr(image_audit.requests, "get",
                            lambda *a, **k: _Head(referer_code
                                                  if referer_code is not None else code))
    return _set


def test_expired_400_is_reported_dead(head):
    """이걸 살아있다고 보고해 온 탓에 감사가 400장을 놓쳤습니다."""
    head(400)
    alive, reason = image_audit.check_alive(LARGE)
    assert alive is False and "400" in reason


def test_hotlink_block_400_is_kept(head):
    """Referer로 통과하면 살아 있는 이미지입니다 — 지우면 안 됩니다."""
    head(400, referer_code=200)
    assert image_audit.check_alive(LARGE)[0] is True


def test_other_4xx_still_kept(head):
    """403·429는 일시적일 수 있어 판정을 미룹니다."""
    head(403)
    assert image_audit.check_alive(LARGE)[0] is True


def test_network_failure_on_retry_keeps_the_image(monkeypatch):
    """확인하지 못한 것을 근거로 멀쩡한 이미지를 지우면 안 됩니다."""
    monkeypatch.setattr(image_audit.requests, "head", lambda *a, **k: _Head(400))

    def _boom(*a, **k):
        raise image_audit.requests.exceptions.ConnectionError("끊김")
    monkeypatch.setattr(image_audit.requests, "get", _boom)
    assert image_audit.check_alive(LARGE)[0] is True


def test_healthy_image_needs_no_retry(head, monkeypatch):
    calls = []
    monkeypatch.setattr(image_audit.requests, "head", lambda *a, **k: _Head(200))
    monkeypatch.setattr(image_audit.requests, "get",
                        lambda *a, **k: calls.append(1) or _Head(200))
    assert image_audit.check_alive(LARGE)[0] is True
    assert not calls, "정상 이미지에 불필요한 재요청을 했습니다"
