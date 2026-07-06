"""핵심 로직 회귀 테스트 — config 병합, 키워드 필터, 이미지 쿼리 단순화.

실행: cd blog-automation && python -m pytest tests/ -v
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ──────────────────────────────────────────────────────────────────────────────
# config.get_blog_configs — BLOGS_CONFIG + blogs.json 병합
# ──────────────────────────────────────────────────────────────────────────────

def _reload_config(monkeypatch, blogs_config_env: str = ""):
    """환경변수를 설정하고 config 모듈을 새로 로드합니다."""
    monkeypatch.setenv("BLOGS_CONFIG", blogs_config_env)
    for mod in ("config",):
        sys.modules.pop(mod, None)
    import config
    return config


def test_merge_env_overrides_registry(monkeypatch):
    """BLOGS_CONFIG의 blog1이 blogs.json의 blog1을 덮어쓴다."""
    env = json.dumps([{"id": "blog1", "name": "ENV블로그", "blog_id": "999", "enabled": True}])
    config = _reload_config(monkeypatch, env)
    blogs = {b["id"]: b for b in config.get_blog_configs()}
    assert blogs["blog1"]["name"] == "ENV블로그"
    assert blogs["blog1"]["blog_id"] == "999"


def test_merge_keeps_registry_only_blogs(monkeypatch):
    """BLOGS_CONFIG에 없는 blog2/blog3는 blogs.json에서 유지된다."""
    env = json.dumps([{"id": "blog1", "name": "ENV블로그", "enabled": True}])
    config = _reload_config(monkeypatch, env)
    ids = {b["id"] for b in config.get_blog_configs()}
    assert {"blog1", "blog2", "blog3"} <= ids


def test_env_item_without_id_treated_as_blog1(monkeypatch):
    """id 없는 BLOGS_CONFIG 항목은 버려지지 않고 blog1으로 간주된다."""
    env = json.dumps([{"name": "ID없는블로그", "blog_id": "777", "enabled": True}])
    config = _reload_config(monkeypatch, env)
    blogs = {b["id"]: b for b in config.get_blog_configs()}
    assert blogs["blog1"]["blog_id"] == "777"


def test_registry_blogs_have_gsc_site_url(monkeypatch):
    """blogs.json 기반 설정에 gsc_site_url이 포함된다."""
    config = _reload_config(monkeypatch, "")
    for b in config.get_blog_configs():
        assert "gsc_site_url" in b, f"{b['id']}에 gsc_site_url 없음"


# ──────────────────────────────────────────────────────────────────────────────
# keyword_collector — 블로그별 이력 필터
# ──────────────────────────────────────────────────────────────────────────────

def test_corpus_blog_filter(tmp_path, monkeypatch):
    """유사도 코퍼스가 blogId별로 분리되고, default는 blog1 소속으로 간주된다."""
    import keyword_collector as kc
    history = [
        {"blogId": "blog1", "keywords": ["재테크 방법"], "posts": []},
        {"blogId": "blog2", "keywords": ["제주 여행"], "posts": []},
        {"blogId": "default", "keywords": ["ISA 계좌"], "posts": []},
        {"blogId": "blog3", "keywords": [], "posts": [
            {"blogId": "blog3", "keyword": "ETF 수수료", "title": "ETF 글"},
        ]},
    ]
    hist_file = tmp_path / "run_history.json"
    hist_file.write_text(json.dumps(history), encoding="utf-8")
    monkeypatch.setattr(kc, "_HISTORY_FILE", str(hist_file))

    blog1 = kc._load_recent_post_corpus(blog_id="blog1")
    blog2 = kc._load_recent_post_corpus(blog_id="blog2")
    blog3 = kc._load_recent_post_corpus(blog_id="blog3")

    assert "재테크 방법" in blog1 and "ISA 계좌" in blog1   # default → blog1 소속
    assert "제주 여행" not in blog1
    assert blog2 == ["제주 여행"]
    assert "ETF 수수료" in blog3 and "재테크 방법" not in blog3


def test_corpus_no_filter_returns_all(tmp_path, monkeypatch):
    """blog_id 미지정 시 전체 이력을 반환한다."""
    import keyword_collector as kc
    history = [
        {"blogId": "blog1", "keywords": ["A"], "posts": []},
        {"blogId": "blog2", "keywords": ["B"], "posts": []},
    ]
    hist_file = tmp_path / "run_history.json"
    hist_file.write_text(json.dumps(history), encoding="utf-8")
    monkeypatch.setattr(kc, "_HISTORY_FILE", str(hist_file))
    assert set(kc._load_recent_post_corpus()) == {"A", "B"}


def test_used_kw_file_per_blog():
    """blog2/blog3는 전용 used_keywords 파일, blog1/default는 공용 파일."""
    import keyword_collector as kc
    f1 = kc._get_used_kw_file("blog1")
    fd = kc._get_used_kw_file("default")
    f2 = kc._get_used_kw_file("blog2")
    f3 = kc._get_used_kw_file("blog3")
    assert f1 == fd
    assert f2 != f1 and f3 != f1 and f2 != f3


# ──────────────────────────────────────────────────────────────────────────────
# image_fetcher — 쿼리 단순화 & 캡션 안전화
# ──────────────────────────────────────────────────────────────────────────────

def test_simplify_query_strips_fluff():
    from image_fetcher import _simplify_query
    q = _simplify_query("스타벅스 사이렌오더 첫 사용 실수담 공개", 3)
    assert "실수담" not in q and "공개" not in q
    assert "스타벅스" in q


def test_simplify_query_keeps_acronyms():
    from image_fetcher import _simplify_query
    q = _simplify_query("ETF 처음 투자할 때 몰랐던 실수들", 2)
    assert "ETF" in q


def test_safe_caption_rejects_filenames():
    from image_fetcher import _safe_caption
    assert _safe_caption({"title": "MetabolismoLipidiE.png"}, "대체텍스트") == "대체텍스트"
    assert _safe_caption({"title": ""}, "대체텍스트") == "대체텍스트"
    assert _safe_caption({"title": "서울 야경 사진"}, "대체텍스트") == "서울 야경 사진"


def test_min_relevance_blocks_junk():
    """관련성 0 후보만 있으면 _fetch_best_image가 None을 반환해야 한다."""
    import image_fetcher as imf

    def fake_search(query, cid, csec, n, **kwargs):
        return [{"url": "http://x/ChateauValere.jpg", "title": "Château de Valère", "width": 800, "height": 600}]

    orig = imf._search_all_sources
    imf._search_all_sources = fake_search
    try:
        result = imf._fetch_best_image("프리랜서 종합소득세 신고")
        assert result is None
    finally:
        imf._search_all_sources = orig


# ──────────────────────────────────────────────────────────────────────────────
# dashboard_exporter — blogId 폴백
# ──────────────────────────────────────────────────────────────────────────────

def test_categorize():
    from dashboard_exporter import _categorize
    assert _categorize("ETF 투자 방법") == "금융"
    assert _categorize("제주 여행 코스") == "여행"
    assert _categorize("아무 관련 없는 주제") == "일반"
