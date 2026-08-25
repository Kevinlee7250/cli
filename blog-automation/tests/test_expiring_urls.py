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


# ── 채택 지점 ────────────────────────────────────────────────────────────────

def test_adopt_image_puts_a_single_image_through_the_gate(monkeypatch):
    seen = []
    monkeypatch.setattr(image_fetcher, "_self_host", lambda imgs: seen.append(imgs))
    img = {"url": LARGE, "stable_url": STABLE}
    assert image_fetcher.adopt_image(img) is img
    assert seen == [[img]]


def test_adopt_image_tolerates_nothing_found(monkeypatch):
    monkeypatch.setattr(image_fetcher, "_self_host",
                        lambda imgs: (_ for _ in ()).throw(AssertionError("불려선 안 됩니다")))
    assert image_fetcher.adopt_image(None) is None


_REPAIR_MODULES = ["fix_unlicensed_images.py", "fix_duplicate_images.py", "manage_post.py"]


@pytest.mark.parametrize("name", _REPAIR_MODULES)
def test_repair_paths_adopt_what_they_insert(name):
    """교체 이미지도 자체 호스팅 관문을 지나야 합니다.

    이걸 빠뜨리면 만료된 이미지를 '또 만료될 이미지'로 바꾸게 됩니다.
    _fetch_best_image를 쓰는 모듈은 adopt_image도 써야 합니다.
    """
    path = os.path.join(os.path.dirname(__file__), "..", name)
    with open(path, encoding="utf-8") as f:
        src = f.read()
    if "_fetch_best_image(" not in src:
        pytest.skip(f"{name}은 이미지를 직접 고르지 않습니다")
    assert "adopt_image" in src, (
        f"{name}이 이미지를 고르면서 adopt_image를 거치지 않습니다 — "
        f"교체본이 만료되는 주소로 발행 글에 박힙니다"
    )


# ── 교체 직후의 공백 ─────────────────────────────────────────────────────────

def test_replacement_keeps_the_origin_as_a_fallback():
    """복제본은 배포돼야 열립니다 — 그 사이 발행 글이 깨지면 안 됩니다."""
    import fix_unlicensed_images as fx
    out = fx._replace_image(
        '<figure><img src="https://old/x.jpg" alt="a" width="720"/></figure>',
        "https://old/x.jpg",
        {"url": "https://kevinlee7250.github.io/cli/images/ab.jpg",
         "origin_url": STABLE, "alt_text": "설명"})
    assert 'src="https://kevinlee7250.github.io/cli/images/ab.jpg"' in out
    assert f"this.src='{STABLE}'" in out
    assert out.count("<img") == 1


def test_replacement_without_a_mirror_has_no_fallback():
    """복제하지 않았다면 되돌아갈 곳이 없습니다 — 자기 자신을 예비로 두면 안 됩니다."""
    import fix_unlicensed_images as fx
    out = fx._replace_image('<img src="https://old/x.jpg" alt="a">',
                            "https://old/x.jpg",
                            {"url": STABLE, "alt_text": "설명"})
    assert "onerror=" not in out


def test_replacement_does_not_double_up_onerror():
    import fix_unlicensed_images as fx
    tag = '<img src="https://old/x.jpg" onerror="this.onerror=null;this.src=\'https://a/b.jpg\'">'
    out = fx._replace_image(tag, "https://old/x.jpg",
                            {"url": "https://kevinlee7250.github.io/cli/images/ab.jpg",
                             "origin_url": STABLE, "alt_text": "설명"})
    assert out.count(' onerror="') == 1


# ── 배포 트리거 ──────────────────────────────────────────────────────────────

def test_deploy_listens_to_both_branches():
    """워크플로를 latest에서 수동 실행하면 배포가 안 걸리던 문제.

    workflow_run의 branches 필터는 '데이터를 만든 워크플로가 어느 브랜치에서
    돌았는가'를 봅니다. 워크플로 파일은 기본 브랜치에서 읽히므로 수동 실행은
    ref가 latest가 되는데, 여기에 작업 브랜치만 적혀 있으면 그 실행은 배포를
    부르지 못합니다. 발행 글이 아직 없는 파일을 가리킨 채 남습니다.
    """
    path = os.path.join(os.path.dirname(__file__), "..", "..",
                        ".github", "workflows", "deploy-dashboard.yml")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    for line in [ln for ln in text.split("\n") if "branches:" in ln]:
        assert "latest" in line, f"배포 트리거가 latest 실행을 놓칩니다: {line.strip()}"


# ── 목록이 잘렸을 때 ─────────────────────────────────────────────────────────

def test_listing_failure_is_retried_then_raised(monkeypatch):
    """조용히 멈추면 '그 블로그에 글이 이만큼뿐'인 것처럼 보입니다.

    같은 limit 0 실행이 437 → 382 → 291편으로 줄어든 원인이 이것이었습니다.
    글이 준 게 아니라 API가 목록 요청을 거절했는데, 도구는 성공으로 끝났습니다.
    """
    import fix_unlicensed_images as fx

    class _R:
        status_code, text = 429, "rate limited"

        @staticmethod
        def json():
            return {}

    calls = []
    monkeypatch.setattr(fx.requests, "get", lambda *a, **k: calls.append(1) or _R())
    monkeypatch.setattr(fx.time, "sleep", lambda s: None)
    with pytest.raises(fx.ListingTruncated):
        list(fx._iter_posts("b1", "tok"))
    assert len(calls) == 3, "재시도 없이 바로 포기했습니다"


def test_listing_recovers_when_the_retry_succeeds(monkeypatch):
    import fix_unlicensed_images as fx

    class _Fail:
        status_code, text = 503, "busy"

    class _Ok:
        status_code = 200

        @staticmethod
        def json():
            return {"items": [{"id": "1", "title": "글"}]}

    seq = [_Fail(), _Ok()]
    monkeypatch.setattr(fx.requests, "get", lambda *a, **k: seq.pop(0))
    monkeypatch.setattr(fx.time, "sleep", lambda s: None)
    assert len(list(fx._iter_posts("b1", "tok"))) == 1


def test_report_carries_incomplete_blogs():
    """리포트가 '덜 봤다'를 말할 수 있어야 전 범위 확인을 주장할 수 있습니다."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "image_audit.py"),
               encoding="utf-8").read()
    assert '"incompleteBlogs": incomplete' in src
    assert "except ListingTruncated" in src
