"""이미지 저작권 화이트리스트 회귀 테스트.

2026-08-19 감사에서 발행된 이미지 835장 중 71%가 무단 저작물로 확인됐습니다
(imgnews.naver.net 299장 등). AdSense 정책상 저작권은 즉시 탈락 요건이므로,
이 파일은 "다시는 그 상태로 돌아가지 않는다"를 지키는 안전장치입니다.

실제로 있었던 위반 URL을 그대로 넣어두었습니다 — 나중에 누군가
화이트리스트를 느슨하게 만들면 여기서 먼저 깨집니다.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from image_fetcher import (  # noqa: E402
    _ko_to_en_query,
    filter_license_safe,
    is_license_safe,
)

# 2026-08-19 감사에서 실제로 본문에 삽입돼 있던 무단 이미지들
VIOLATING_URLS = [
    "http://imgnews.naver.net/image/5567/2026/07/06/0000193968_002.png",  # 언론사 뉴스 사진
    "https://img1.daumcdn.net/thumb/R750x0/example.jpg",                  # 다음 CDN
    "https://dthumb-phinf.pstatic.net/example.jpg",                       # 네이버 썸네일
    "https://scs-phinf.pstatic.net/example.jpg",                          # 네이버 블로그
    "https://pup-post-phinf.pstatic.net/example.jpg",                     # 네이버 포스트
    "https://shop1.phinf.naver.net/example.jpg",                          # 네이버 쇼핑
    "https://influencer-phinf.pstatic.net/example.jpg",                   # 네이버 인플루언서
    "https://i.pinimg.com/564x/example.jpg",                              # 핀터레스트
    "https://i.ytimg.com/vi/abc/hqdefault.jpg",                           # 유튜브 썸네일
    "https://i.namu.wiki/i/example.png",                                  # 나무위키
    "https://img.hankyung.com/photo/example.jpg",                         # 한국경제
    "https://dimg.donga.com/example.jpg",                                 # 동아일보
    "https://file3.instiz.net/data/example.jpg",                          # 인스티즈
    "https://cdn2.ppomppu.co.kr/example.jpg",                             # 뽐뿌
    "https://file1.bobaedream.co.kr/example.jpg",                         # 보배드림
    "https://velog.velcdn.com/images/example.png",                        # velog
    "https://cdn.pgr21.com/pb/data/example.png",                          # PGR21
]

SAFE_URLS = [
    "https://cdn.pixabay.com/photo/2020/01/01/sample.jpg",
    "https://pixabay.com/get/sample.jpg",
    "https://upload.wikimedia.org/wikipedia/commons/a/ab/Sample.jpg",
    "https://images.unsplash.com/photo-123",
    "https://source.unsplash.com/800x600/?finance",
    "https://i.ibb.co/abc123/generated-thumb.png",  # 우리가 업로드한 AI 이미지
    "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=",   # 직접 만든 SVG 썸네일
]


@pytest.mark.parametrize("url", VIOLATING_URLS)
def test_violating_urls_are_blocked(url):
    """실제로 있었던 무단 출처는 전부 차단돼야 합니다."""
    assert is_license_safe(url) is False, f"차단됐어야 할 URL이 통과함: {url}"


@pytest.mark.parametrize("url", SAFE_URLS)
def test_safe_urls_are_allowed(url):
    """라이선스를 확인한 출처는 통과해야 합니다."""
    assert is_license_safe(url) is True, f"허용됐어야 할 URL이 차단됨: {url}"


def test_hostname_is_not_matched_as_substring():
    """도메인이 경로에 들어 있을 뿐인 URL을 통과시키면 안 됩니다.

    `endswith` 대신 단순 `in` 비교를 쓰면 아래가 전부 뚫립니다.
    """
    assert is_license_safe("https://evil.example.com/pixabay.com/x.jpg") is False
    assert is_license_safe("https://pixabay.com.attacker.net/x.jpg") is False
    assert is_license_safe("https://notpixabay.com/x.jpg") is False


def test_subdomain_of_allowed_host_is_allowed():
    assert is_license_safe("https://cdn.pixabay.com/x.jpg") is True


def test_empty_and_malformed_urls_are_blocked():
    for bad in ["", "   ", None, "not-a-url", "ftp://pixabay.com/x.jpg"]:
        assert is_license_safe(bad) is False


def test_filter_license_safe_keeps_only_safe():
    images = (
        [{"url": u, "source": "naver"} for u in VIOLATING_URLS]
        + [{"url": u, "source": "pixabay"} for u in SAFE_URLS]
    )
    kept = filter_license_safe(images)
    assert len(kept) == len(SAFE_URLS)
    assert all(is_license_safe(i["url"]) for i in kept)


def test_filter_license_safe_handles_empty():
    assert filter_license_safe([]) == []
    assert filter_license_safe(None) == []


def test_search_all_sources_never_calls_naver_or_ddg(monkeypatch):
    """네이버·DDG는 검색 경로에서 완전히 빠져야 합니다.

    함수 자체는 남아 있지만(호환용), 검색 체인이 호출하면 안 됩니다.
    """
    import image_fetcher

    called = []
    monkeypatch.setattr(image_fetcher, "_naver_images",
                        lambda *a, **k: called.append("naver") or [])
    monkeypatch.setattr(image_fetcher, "_ddg_images",
                        lambda *a, **k: called.append("ddg") or [])
    monkeypatch.setattr(image_fetcher, "_pixabay_images", lambda *a, **k: [])
    monkeypatch.setattr(image_fetcher, "_wikimedia_images", lambda *a, **k: [])

    image_fetcher._search_all_sources(
        "테스트 쿼리",
        naver_client_id="id", naver_client_secret="secret",
        n_candidates=4, pixabay_api_key="key",
    )
    assert called == [], f"제거됐어야 할 소스가 호출됨: {called}"


def test_search_all_sources_filters_unsafe_results(monkeypatch):
    """허용 소스가 무단 URL을 돌려줘도 걸러져야 합니다 (2중 방어)."""
    import image_fetcher

    monkeypatch.setattr(image_fetcher, "_pixabay_images", lambda *a, **k: [
        {"url": "http://imgnews.naver.net/leaked.jpg", "source": "pixabay"},
        {"url": "https://cdn.pixabay.com/ok.jpg", "source": "pixabay"},
    ])
    out = image_fetcher._search_all_sources("q", pixabay_api_key="key")
    assert [i["url"] for i in out] == ["https://cdn.pixabay.com/ok.jpg"]


def test_source_labels_have_no_search_engine_entries():
    """'네이버 이미지 검색'은 출처가 아니라 검색 경로입니다 — 라벨에 남으면 안 됩니다."""
    from image_fetcher import _SOURCE_LABELS

    assert "naver" not in _SOURCE_LABELS
    assert "ddg" not in _SOURCE_LABELS
    for label in _SOURCE_LABELS.values():
        assert "검색" not in label, f"검색 경로를 출처처럼 표기함: {label}"


class TestKoreanToEnglishQuery:
    """Pixabay 적중률 = 이미지 확보율이 됐으므로 변환 실패가 곧 이미지 없음입니다.

    아래 키워드는 전부 2026-08-19 이전에 빈 문자열을 반환해
    네이버 뉴스 사진으로 떨어졌던 실제 사례입니다.
    """

    @pytest.mark.parametrize("query,expect_word", [
        ("2026 종부세 개편 1주택자 절세법", "property tax"),
        ("가계부채 2000조 시대 내 대출 관리", "household debt"),
        ("미국 국채 금리 5.3% 급등", "government bonds"),
        ("전세의 월세화 시대 임차인", "rental housing"),
        ("2026 은행 적금 금리 비교", "savings account"),
        ("그린벨트 해제 지역 공급대책", "green belt land"),
        ("추석 연휴 여행지 추천", "harvest festival"),
        ("수영 1km 완주 8주 훈련 계획", "swimming"),
    ])
    def test_previously_failing_queries_now_resolve(self, query, expect_word):
        result = _ko_to_en_query(query)
        assert result, f"빈 문자열 반환 — 네이버로 떨어지던 그 경로: {query}"
        assert expect_word in result, f"{query!r} → {result!r} (기대: {expect_word})"

    def test_longer_key_wins_over_shorter(self):
        """'가계부채'가 '가계부'로 잘못 매칭되면 안 됩니다."""
        assert "household debt" in _ko_to_en_query("가계부채 증가")

    def test_suffixed_words_still_match(self):
        """조사·접미사가 붙어도 매칭돼야 합니다."""
        assert _ko_to_en_query("절세법 총정리")
        assert _ko_to_en_query("금리는 어디로")

    def test_unmappable_query_returns_empty(self):
        """매핑 없는 쿼리는 빈 문자열 — 범용어로 검색하면 모든 글에 같은 사진이 붙습니다."""
        assert _ko_to_en_query("퓨퓨퓨 뷁뷁") == ""

    def test_english_words_take_priority(self):
        assert _ko_to_en_query("ETF 투자 전략") == "ETF"

    def test_at_most_two_terms(self):
        result = _ko_to_en_query("여행 금리 건강 스포츠 요리")
        assert len(result.split()) <= 4  # 최대 2개 표제어 (표제어당 최대 2단어)
