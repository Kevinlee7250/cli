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


def test_same_photo_from_different_urls_is_one_file(store, monkeypatch):
    """서명 URL이 달라도 내용이 같으면 같은 사진입니다."""
    monkeypatch.setattr(image_mirror.requests, "get", lambda *a, **k: _Resp())
    a = image_mirror.mirror_url("https://pixabay.com/get/sig1.jpg")
    b = image_mirror.mirror_url("https://pixabay.com/get/sig2.jpg")
    assert a["file"] == b["file"], "같은 내용인데 다른 파일로 저장됐습니다"


def test_mirroring_does_not_count_as_using(store, monkeypatch):
    """후보로 훑어보다 버린 사진까지 세면 가드가 스스로 무너집니다.

    2026-08-26 파일럿에서 실제로 그랬습니다 — 로그에는 "다른 후보 확인"이
    찍히는데 최다 사용 사진은 61회에서 76회로 늘었습니다.
    """
    monkeypatch.setattr(image_mirror.requests, "get", lambda *a, **k: _Resp())
    got = image_mirror.mirror_url("https://pixabay.com/get/sig1.jpg")
    assert image_mirror.times_used(got["url"]) == 0
    image_mirror.mirror_url("https://pixabay.com/get/sig2.jpg")
    assert image_mirror.times_used(got["url"]) == 0, "복제만 했는데 사용으로 셌습니다"

    assert image_mirror.note_use(got["url"]) == 1
    assert image_mirror.times_used(got["url"]) == 1


def test_note_use_accumulates(store, monkeypatch):
    monkeypatch.setattr(image_mirror.requests, "get", lambda *a, **k: _Resp())
    got = image_mirror.mirror_url("https://pixabay.com/get/sig1.jpg")
    for expected in (1, 2, 3):
        assert image_mirror.note_use(got["url"]) == expected


def test_overuse_threshold(store, monkeypatch):
    monkeypatch.setattr(image_mirror.requests, "get", lambda *a, **k: _Resp())
    got = image_mirror.mirror_url("https://pixabay.com/get/s0.jpg")
    for _ in range(image_mirror.MAX_REUSE):
        image_mirror.note_use(got["url"])
    assert image_mirror.is_overused(got["url"]) is False
    image_mirror.note_use(got["url"])
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


# ── 중복 정리가 새 중복을 만들지 않게 ────────────────────────────────────────

def test_duplicate_fixer_uses_the_guarded_chooser():
    """중복을 없애면서 새 중복을 만들면 작업이 헛돕니다.

    fix_duplicate_images가 따로 이미지를 고르면 '이미 여러 글에 쓴 사진은
    건너뛴다'는 판정을 지나치게 됩니다. 선택기는 한 곳이어야 합니다.
    """
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "fix_duplicate_images.py"), encoding="utf-8").read()
    assert "_find_safe_replacement" in src, "가드가 있는 선택기를 쓰지 않습니다"
    body = src[src.index("def _find_replacement_image("):]
    body = body[:body.index("\ndef ")]
    assert "_fetch_best_image" not in body, "여전히 직접 고르고 있습니다"


def test_duplicate_fixer_can_be_limited():
    """발행 중인 글을 고치므로 나눠 돌 수 있어야 합니다."""
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "fix_duplicate_images.py"), encoding="utf-8").read()
    assert "def scan_and_fix(blogs: list[dict], dry_run: bool, limit: int = 0)" in src
    assert "if limit and fixed >= limit:" in src

    wf = open(os.path.join(os.path.dirname(__file__), "..", "..", ".github",
                           "workflows", "fix-duplicate-images.yml"), encoding="utf-8").read()
    assert "--limit ${{ inputs.limit || '20' }}" in wf, (
        "스케줄 실행이 쓰는 기본값이 없습니다 — inputs가 비면 전체가 돕니다"
    )


def test_rejected_candidates_are_not_counted(monkeypatch, tmp_path):
    """훑어보다 버린 후보는 사용 횟수에 들어가면 안 됩니다.

    이것이 무너지면 가드가 스스로 임계값을 채워, 남은 후보가 없다며 가장
    많이 쓴 사진으로 되돌아갑니다.
    """
    import fix_unlicensed_images as fx
    noted = []
    monkeypatch.setattr("image_fetcher._search_all_sources",
                        lambda *a, **k: [{"url": "over", "score": 1.0},
                                         {"url": "fresh", "score": 0.5}])
    monkeypatch.setattr("image_fetcher.filter_license_safe", lambda imgs: imgs)
    monkeypatch.setattr("image_fetcher.is_license_safe", lambda u: True)
    monkeypatch.setattr("image_fetcher._score_title_relevance",
                        lambda img, q: img.get("score", 0))
    monkeypatch.setattr("image_fetcher.adopt_image", lambda img: img)
    monkeypatch.setattr(image_mirror, "times_used",
                        lambda url: 99 if url == "over" else 0)
    monkeypatch.setattr(image_mirror, "note_use", lambda url: noted.append(url))

    assert fx._find_safe_replacement("제목")["url"] == "fresh"
    assert noted == ["fresh"], f"버린 후보까지 셌습니다: {noted}"


# ── 두 기준이 어긋나지 않게 ──────────────────────────────────────────────────

def test_duplicate_threshold_matches_the_chooser():
    """중복 판정과 선택기 허용치가 다르면 영원히 수렴하지 않습니다.

    선택기가 3편까지 허용하는데 정리 도구가 2편부터 중복으로 잡으면,
    교체해 넣은 이미지가 다음 실행에서 다시 교체 대상이 됩니다. 실제로
    2026-08-26 실행에서 중복 집계가 51 → 56으로 늘었습니다.
    """
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "fix_duplicate_images.py"), encoding="utf-8").read()
    assert "from image_mirror import MAX_REUSE" in src, "허용치를 따로 정하고 있습니다"
    assert "> MAX_REUSE" in src, "고정된 숫자로 중복을 판정합니다"
    assert ">= 2" not in src.split("dup_clusters = ")[1][:200]


def test_allowed_copies_are_left_alone():
    """허용 범위 안인 글까지 고치면 과잉 수정입니다."""
    src = open(os.path.join(os.path.dirname(__file__), "..",
                            "fix_duplicate_images.py"), encoding="utf-8").read()
    assert "keep_n = max(1, MAX_REUSE)" in src
    assert "entries[keep_n:]" in src, "여전히 1편만 남기고 전부 교체합니다"
