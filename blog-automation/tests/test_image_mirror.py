"""이미지 자체 호스팅 — 원본이 사라져도 글이 안 깨지게.

지금까지 본문 이미지는 전부 남의 서버 핫링크였습니다. 원본이 지워지면
발행된 글이 조용히 깨지고, 우리 쪽에는 무엇이 있었는지도 남지 않습니다.

여기서 지키는 것은 세 가지입니다.
  1) 복제는 저작권 관문 **뒤**에서만 — 앞에서 하면 권리 없는 이미지를
     우리 도메인으로 옮겨 놓고 "우리 것이니 안전"이라고 판정하게 됩니다.
  2) 실패하면 원본 유지 — 자체 호스팅 때문에 글 생성이 멈추면 안 됩니다.
  3) 중복 방지는 원본 URL 기준 — 복제 경로로 기록하면 같은 사진이 매번
     새 이미지로 보여 중복 차단이 무력해집니다.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import image_fetcher  # noqa: E402
import image_mirror  # noqa: E402

PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(image_mirror, "MIRROR_DIR", str(tmp_path / "images"))
    monkeypatch.setattr(image_mirror, "MANIFEST_FILE", str(tmp_path / "image_mirror.json"))
    monkeypatch.setenv("IMAGE_HOST_BASE", "https://example.test/images")
    return tmp_path


class _Resp:
    # status_code 필수 — _fetch가 400대일 때만 Referer로 재시도하므로,
    # 이것이 없으면 정상 응답인지 판단할 수 없습니다.
    def __init__(self, body=PNG, mime="image/png", headers=None, status_code=200):
        self.body, self.headers = body, {"Content-Type": mime, **(headers or {})}
        self.status_code = status_code

    def raise_for_status(self):
        pass

    def iter_content(self, n):
        yield self.body


def _serve(monkeypatch, resp=None, calls=None):
    def _get(url, **kw):
        if calls is not None:
            calls.append(url)
        if isinstance(resp, Exception):
            raise resp
        return resp if resp is not None else _Resp()
    monkeypatch.setattr(image_mirror.requests, "get", _get)


# ── 복제 ─────────────────────────────────────────────────────────────────────

def test_mirror_saves_file_and_returns_public_url(store, monkeypatch):
    _serve(monkeypatch)
    got = image_mirror.mirror_url("https://pixabay.com/get/abc.jpg")
    assert got and got["url"].startswith("https://example.test/images/")
    assert got["url"].endswith(".png"), "확장자는 URL이 아니라 Content-Type으로 정해야 합니다"
    assert os.path.exists(os.path.join(image_mirror.MIRROR_DIR, got["file"]))


def test_same_origin_is_not_downloaded_twice(store, monkeypatch):
    calls = []
    _serve(monkeypatch, calls=calls)
    url = "https://pixabay.com/get/abc.jpg"
    image_mirror.mirror_url(url)
    again = image_mirror.mirror_url(url)
    assert again and again["reused"] is True
    assert len(calls) == 1, "이미 복제한 원본을 다시 내려받았습니다"


def test_identical_bytes_share_one_file(store, monkeypatch):
    _serve(monkeypatch)
    a = image_mirror.mirror_url("https://pixabay.com/get/one.jpg")
    b = image_mirror.mirror_url("https://pixabay.com/get/two.jpg")
    assert a["file"] == b["file"], "같은 내용은 한 번만 저장돼야 합니다"
    assert len(os.listdir(image_mirror.MIRROR_DIR)) == 1


def test_oversized_image_is_skipped(store, monkeypatch):
    _serve(monkeypatch, _Resp(headers={"Content-Length": str(image_mirror.MAX_BYTES + 1)}))
    assert image_mirror.mirror_url("https://pixabay.com/get/huge.jpg") is None


def test_oversized_without_content_length_is_skipped(store, monkeypatch):
    """헤더를 안 주는 서버도 있습니다 — 받으면서 끊어야 합니다."""
    _serve(monkeypatch, _Resp(body=b"x" * (image_mirror.MAX_BYTES + 10)))
    assert image_mirror.mirror_url("https://pixabay.com/get/huge.jpg") is None


def test_non_image_is_skipped(store, monkeypatch):
    _serve(monkeypatch, _Resp(body=b"<html>404</html>", mime="text/html"))
    assert image_mirror.mirror_url("https://pixabay.com/get/gone.jpg") is None


def test_download_failure_returns_none(store, monkeypatch):
    _serve(monkeypatch, RuntimeError("연결 끊김"))
    assert image_mirror.mirror_url("https://pixabay.com/get/x.jpg") is None


def test_already_mirrored_url_is_left_alone(store, monkeypatch):
    _serve(monkeypatch)
    assert image_mirror.mirror_url("https://example.test/images/abc.png") is None


def test_data_uri_is_stored_without_network(store, monkeypatch):
    """직접 만든 SVG 썸네일도 파일로 남겨야 본문이 가벼워집니다."""
    import base64
    _serve(monkeypatch, RuntimeError("네트워크를 쓰면 안 됩니다"))
    uri = "data:image/svg+xml;base64," + base64.b64encode(b"<svg/>").decode()
    got = image_mirror.mirror_url(uri)
    assert got and got["file"].endswith(".svg")


# ── 목록 치환 ────────────────────────────────────────────────────────────────

def test_mirror_images_rewrites_url_and_keeps_origin(store, monkeypatch):
    _serve(monkeypatch)
    images = [{"url": "https://pixabay.com/get/a.jpg", "title": "t"}]
    assert image_mirror.mirror_images(images) == 1
    assert images[0]["origin_url"] == "https://pixabay.com/get/a.jpg"
    assert images[0]["url"].startswith("https://example.test/images/")


def test_failed_mirror_keeps_hotlink(store, monkeypatch):
    """복제 실패가 이미지 없는 글로 이어지면 안 됩니다."""
    _serve(monkeypatch, RuntimeError("실패"))
    images = [{"url": "https://pixabay.com/get/a.jpg"}]
    assert image_mirror.mirror_images(images) == 0
    assert images[0]["url"] == "https://pixabay.com/get/a.jpg"
    assert "origin_url" not in images[0]


# ── 저작권 관문과의 순서 ─────────────────────────────────────────────────────

def test_self_host_runs_only_when_flag_is_on(store, monkeypatch):
    called = []
    monkeypatch.setattr(image_fetcher, "_self_host", lambda imgs: called.append(imgs))
    monkeypatch.setenv("FEATURE_IMAGE_SELF_HOST", "0")
    from feature_flags import is_enabled
    assert is_enabled("image_self_host") is False


def test_mirrored_url_passes_license_gate(store):
    """복제본이 화이트리스트에 막히면 다음 단계에서 전부 버려집니다."""
    assert image_fetcher.is_license_safe("https://example.test/images/abc.png") is True


def test_unsafe_host_is_still_blocked(store):
    assert image_fetcher.is_license_safe("https://imgnews.naver.net/x.jpg") is False


def test_self_host_is_called_after_the_license_gate():
    """소스 순서를 고정합니다 — 뒤집히면 무단 이미지를 우리 저장소에 복사하게 됩니다."""
    src = open(image_fetcher.__file__, encoding="utf-8").read()
    body = src[src.index("def fetch_images_for_queries("):]
    body = body[:body.index("\ndef _self_host(")]
    gate = body.rindex("filter_license_safe(images)")
    assert gate < body.index("_self_host(images)"), (
        "복제가 저작권 관문보다 먼저 일어납니다"
    )


# ── 중복 방지 ────────────────────────────────────────────────────────────────

def test_used_images_records_the_origin_not_the_mirror(store, monkeypatch, tmp_path):
    _serve(monkeypatch)
    origin = "https://pixabay.com/get/a.jpg"
    images = [{"url": origin}]
    image_mirror.mirror_images(images)

    used = tmp_path / "used_images.json"
    monkeypatch.setattr(image_fetcher, "_USED_IMAGES_FILE", str(used))
    image_fetcher.mark_images_used([images[0]["url"]])

    with open(used, encoding="utf-8") as f:
        assert json.load(f)["urls"] == [origin]


# ── 본문 HTML ────────────────────────────────────────────────────────────────

def test_img_html_falls_back_to_origin():
    """배포 시차·복제본 유실 때 원본으로 되돌아가야 글이 안 깨집니다."""
    html = image_fetcher._make_img_html(
        {"url": "https://example.test/images/a.png",
         "origin_url": "https://pixabay.com/get/a.jpg"}, "설명")
    assert "onerror=" in html and "pixabay.com/get/a.jpg" in html


def test_img_html_without_origin_has_no_onerror():
    html = image_fetcher._make_img_html({"url": "https://pixabay.com/get/a.jpg"}, "설명")
    assert "onerror=" not in html


def test_audit_treats_undeployed_mirror_as_alive(store, monkeypatch):
    """발행 ~ Pages 배포 사이의 404로 멀쩡한 글을 되돌리면 안 됩니다."""
    import image_audit
    _serve(monkeypatch)
    got = image_mirror.mirror_url("https://pixabay.com/get/a.jpg")

    def _boom(*a, **k):
        raise AssertionError("배포 전 복제본에 네트워크 확인을 하면 안 됩니다")
    monkeypatch.setattr(image_audit.requests, "head", _boom)

    alive, _ = image_audit.check_alive(got["url"])
    assert alive is True


def test_audit_still_checks_mirror_urls_without_a_file(store, monkeypatch):
    """저장소에 파일이 없다면 진짜로 확인해야 합니다 — 무조건 살아있다고 하면 안 됩니다."""
    import image_audit
    seen = []
    class _Head:
        status_code, headers = 200, {"Content-Type": "image/png"}
    monkeypatch.setattr(image_audit.requests, "head",
                        lambda *a, **k: seen.append(a) or _Head())
    image_audit.check_alive("https://example.test/images/0000000000000000.png")
    assert seen, "파일이 없는 복제본 URL을 확인 없이 통과시켰습니다"


def test_public_base_follows_the_repository(monkeypatch):
    monkeypatch.delenv("IMAGE_HOST_BASE", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", "Someone/myrepo")
    assert image_mirror.public_base() == "https://someone.github.io/myrepo/images"


# ── 400 원인 구분 ────────────────────────────────────────────────────────────

class _Coded:
    def __init__(self, code, body=PNG):
        self.status_code, self.body = code, body
        self.headers = {"Content-Type": "image/png"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise image_mirror.requests.exceptions.HTTPError(f"{self.status_code}")

    def iter_content(self, n):
        yield self.body


def test_hotlink_block_is_retried_with_a_referer(store, monkeypatch):
    """400이 핫링크 차단이면 Referer를 붙여 통과합니다 — 이미지는 살아 있습니다."""
    seen = []

    def _get(url, headers=None, **kw):
        seen.append(headers or {})
        return _Coded(200) if "Referer" in (headers or {}) else _Coded(400)

    monkeypatch.setattr(image_mirror.requests, "get", _get)
    assert image_mirror.mirror_url("https://pixabay.com/get/a.jpg") is not None
    assert len(seen) == 2 and seen[1]["Referer"] == "https://pixabay.com/"


def test_dead_url_still_fails_after_retry(store, monkeypatch):
    """재시도해도 400이면 원본이 죽은 것 — 복제할 수 없습니다."""
    monkeypatch.setattr(image_mirror.requests, "get", lambda *a, **k: _Coded(400))
    assert image_mirror.mirror_url("https://pixabay.com/get/a.jpg") is None


def test_healthy_url_is_fetched_once(store, monkeypatch):
    calls = []
    monkeypatch.setattr(image_mirror.requests, "get",
                        lambda *a, **k: calls.append(1) or _Coded(200))
    image_mirror.mirror_url("https://pixabay.com/get/a.jpg")
    assert len(calls) == 1, "정상 응답에 불필요한 재요청을 했습니다"
