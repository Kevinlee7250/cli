"""발행 글 무단 이미지 교체 도구 테스트.

이 도구는 라이브 글을 직접 수정하므로, 잘못 동작하면 되돌리기 어렵습니다.
특히 확인해야 할 것:
  - 안전한 이미지를 건드리지 않는가 (오탐으로 멀쩡한 글을 망치지 않는가)
  - 대체 실패 시 무단 이미지를 남기지 않는가
  - figure 제거가 다른 이미지까지 지우지 않는가
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fix_unlicensed_images import (  # noqa: E402
    _extract_unsafe_urls,
    _remove_image,
    _replace_image,
)

NAVER = "http://imgnews.naver.net/image/5567/news.png"
PIXA = "https://cdn.pixabay.com/photo/2020/safe.jpg"
WIKI = "https://upload.wikimedia.org/wikipedia/commons/a/ab/Safe.jpg"


class TestExtractUnsafeUrls:
    def test_finds_only_unsafe(self):
        content = (
            f'<p>글</p><img src="{PIXA}" alt="a">'
            f'<img src="{NAVER}" alt="b">'
            f'<img src="{WIKI}" alt="c">'
        )
        assert _extract_unsafe_urls(content) == [NAVER]

    def test_clean_content_returns_empty(self):
        content = f'<img src="{PIXA}"><img src="{WIKI}">'
        assert _extract_unsafe_urls(content) == []

    def test_data_uri_thumbnail_is_safe(self):
        """직접 만든 SVG 썸네일은 우리 것이므로 건드리면 안 됩니다."""
        content = '<img src="data:image/svg+xml;base64,PHN2Zz4=" alt="t">'
        assert _extract_unsafe_urls(content) == []

    def test_deduplicates_repeated_url(self):
        content = f'<img src="{NAVER}"><img src="{NAVER}">'
        assert _extract_unsafe_urls(content) == [NAVER]

    def test_handles_empty_and_none(self):
        assert _extract_unsafe_urls("") == []
        assert _extract_unsafe_urls(None) == []

    def test_img_without_src_is_ignored(self):
        assert _extract_unsafe_urls('<img alt="broken">') == []


class TestReplaceImage:
    def test_replaces_src_alt_title(self):
        content = f'<img src="{NAVER}" alt="옛것" title="옛것">'
        out = _replace_image(content, NAVER, {"url": PIXA, "alt_text": "새것"})
        assert PIXA in out
        assert NAVER not in out
        assert 'alt="새것"' in out
        assert 'title="새것"' in out

    def test_leaves_other_images_untouched(self):
        content = f'<img src="{PIXA}" alt="유지"><img src="{NAVER}" alt="교체">'
        out = _replace_image(content, NAVER, {"url": WIKI, "alt_text": "새것"})
        assert f'src="{PIXA}" alt="유지"' in out
        assert WIKI in out
        assert NAVER not in out

    def test_escapes_alt_text(self):
        content = f'<img src="{NAVER}" alt="x">'
        out = _replace_image(content, NAVER, {"url": PIXA, "alt_text": '따옴표" 주입'})
        assert '&quot;' in out

    def test_no_alt_attribute_still_replaces_src(self):
        content = f'<img src="{NAVER}">'
        out = _replace_image(content, NAVER, {"url": PIXA, "alt_text": "새것"})
        assert PIXA in out


class TestRemoveImage:
    def test_removes_whole_figure_with_caption(self):
        content = (
            f'<figure><img src="{NAVER}" alt="x">'
            f'<figcaption>이미지 출처: 어딘가</figcaption></figure><p>본문</p>'
        )
        out = _remove_image(content, NAVER)
        assert "figcaption" not in out, "캡션만 남으면 안 됩니다"
        assert NAVER not in out
        assert "<p>본문</p>" in out

    def test_removes_bare_img_tag(self):
        content = f'<p>앞</p><img src="{NAVER}"><p>뒤</p>'
        out = _remove_image(content, NAVER)
        assert NAVER not in out
        assert "<p>앞</p>" in out and "<p>뒤</p>" in out

    def test_keeps_other_figures(self):
        content = (
            f'<figure><img src="{PIXA}"><figcaption>유지</figcaption></figure>'
            f'<figure><img src="{NAVER}"><figcaption>삭제</figcaption></figure>'
        )
        out = _remove_image(content, NAVER)
        assert PIXA in out
        assert "유지" in out
        assert NAVER not in out
        assert "삭제" not in out

    def test_removing_absent_url_is_noop(self):
        content = f'<img src="{PIXA}">'
        assert _remove_image(content, NAVER) == content


class TestFindSafeReplacement:
    def test_rejects_unsafe_search_result(self, monkeypatch):
        """검색이 무단 URL을 돌려주면 대체로 쓰지 않아야 합니다.

        무단 이미지를 다른 무단 이미지로 바꾸는 것이 최악의 결과입니다.
        """
        import fix_unlicensed_images as fx
        import image_fetcher

        monkeypatch.setattr(image_fetcher, "_fetch_best_image",
                            lambda *a, **k: {"url": NAVER, "title": "x"})
        monkeypatch.setattr(image_fetcher, "generate_fallback_image",
                            lambda *a, **k: {"url": PIXA, "source": "generated_thumbnail"})
        out = fx._find_safe_replacement("제목")
        assert out["url"] == PIXA, "무단 검색 결과를 대체 이미지로 채택함"

    def test_returns_none_when_everything_unsafe(self, monkeypatch):
        import fix_unlicensed_images as fx
        import image_fetcher

        monkeypatch.setattr(image_fetcher, "_fetch_best_image",
                            lambda *a, **k: {"url": NAVER})
        monkeypatch.setattr(image_fetcher, "generate_fallback_image",
                            lambda *a, **k: {"url": NAVER})
        assert fx._find_safe_replacement("제목") is None

    def test_prefers_search_result_when_safe(self, monkeypatch):
        import fix_unlicensed_images as fx
        import image_fetcher

        monkeypatch.setattr(image_fetcher, "_fetch_best_image",
                            lambda *a, **k: {"url": WIKI, "title": "x"})
        monkeypatch.setattr(image_fetcher, "generate_fallback_image",
                            lambda *a, **k: {"url": PIXA})
        assert fx._find_safe_replacement("제목")["url"] == WIKI
