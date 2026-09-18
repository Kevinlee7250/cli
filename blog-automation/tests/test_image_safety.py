"""붙으면 안 되는 이미지를 실제로 막는지 검사합니다.

2026-09-18 드라마 회차 글 테스트에서 'two actors intense conversation drama
scene'을 검색했는데 'bikini / two piece swimwear / women' 사진이 붙었습니다.

막을 것이 두 겹 있었는데 둘 다 '실패 시 통과'였습니다.
  1) _pick_best_image: 관련성 미달이어도 후보가 있으면 최상위를 반환
  2) _filter_relevant_images: Claude 응답 파싱이 비면 원본을 그대로 반환

관련성 문제가 아니라 안전 문제입니다. AdSense 성인 인접 판정은 글 한 편이
아니라 사이트 전체에 영향을 줍니다.
"""
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from image_fetcher import _is_unsafe_image, _filter_relevant_images  # noqa: E402


def _img(title="", query="", url="https://example.com/a.jpg", tags=None):
    return {"title": title, "search_query": query, "url": url, "tags": tags or []}


def test_the_actual_image_that_slipped_through():
    """실제로 드라마 글에 붙었던 사진."""
    assert _is_unsafe_image(_img(title="bikini / two piece swimwear / women / tw"))


@pytest.mark.parametrize("field", ["title", "query", "url", "tags"])
def test_blocked_term_is_caught_in_every_field(field):
    """제목만 보면 검색어·태그로 새어 들어옵니다."""
    kwargs = {"title": "photo", "query": "drama", "url": "https://x.com/a.jpg"}
    if field == "tags":
        img = _img(**kwargs, tags=["lingerie", "model"])
    elif field == "query":
        img = _img(title="photo", query="sexy model")
    elif field == "url":
        img = _img(title="photo", url="https://x.com/swimsuit-01.jpg")
    else:
        img = _img(title="nude study")
    assert _is_unsafe_image(img)


@pytest.mark.parametrize("title", [
    "bikini beach", "two piece swimwear", "수영복 모델", "속옷 광고",
    "sexy pose", "lingerie set", "topless portrait",
])
def test_unsafe_titles(title):
    assert _is_unsafe_image(_img(title=title))


@pytest.mark.parametrize("title", [
    "swimming pool lane",        # 수영 자체는 막으면 안 됩니다
    "seoul night street",
    "gold bullion bars",
    "강원도 캠핑장 텐트",
    "two actors conversation drama scene",
    "underwater coral reef",
])
def test_safe_titles_pass(title):
    """과잉 차단은 이미지 확보율을 떨어뜨립니다."""
    assert not _is_unsafe_image(_img(title=title))


def test_claude_filter_drops_unsafe_before_asking(monkeypatch):
    """Claude 경로는 오류·파싱 실패 시 원본을 되돌려 줍니다 —
    그 전에 빼두지 않으면 차단 이미지가 되돌아옵니다."""
    import image_fetcher as mod

    def _boom(*a, **k):
        raise RuntimeError("API 장애")
    monkeypatch.setattr(mod, "_filter_relevant_images",
                        mod._filter_relevant_images)  # 원본 유지
    monkeypatch.setitem(sys.modules, "anthropic", None)  # import 실패 유도

    images = [_img(title="bikini swimwear"), _img(title="drama scene")]
    out = _filter_relevant_images(images, "포핸즈 7화", "드라마 회차 정리 본문")
    titles = [i["title"] for i in out]
    assert "bikini swimwear" not in titles, "API가 죽으면 차단 이미지가 되돌아옵니다"


def test_all_unsafe_means_no_images():
    out = _filter_relevant_images([_img(title="bikini")], "포핸즈", "본문")
    assert out == []
