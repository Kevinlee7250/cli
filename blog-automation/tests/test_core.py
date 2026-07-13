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


class _FakeBlock:
    def __init__(self, type_, text=""):
        self.type = type_
        self.text = text


class _FakeMessage:
    def __init__(self, text, stop_reason):
        self.content = [_FakeBlock("thinking"), _FakeBlock("text", text)]
        self.stop_reason = stop_reason


class _FakeStream:
    """client.messages.stream() 컨텍스트 매니저 스텁."""
    def __init__(self, message):
        self._message = message

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def get_final_message(self):
        return self._message


class _FakeMessages:
    """client.messages 네임스페이스 — stream()과 calls 모두 지원."""
    def __init__(self, owner):
        self._owner = owner

    def stream(self, **kwargs):
        self._owner.calls.append(kwargs)
        return _FakeStream(self._owner._responses.pop(0))


class _FakeClient:
    """messages.stream 호출마다 준비된 응답을 순서대로 반환."""
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.messages = _FakeMessages(self)


def test_claude_generate_continues_truncated_response():
    """max_tokens로 잘리면 이어쓰기 요청으로 텍스트를 이어붙인다."""
    from config import claude_generate
    client = _FakeClient([
        _FakeMessage("앞부분", "max_tokens"),
        _FakeMessage("뒷부분", "end_turn"),
    ])
    result = claude_generate(client, model="m", max_tokens=100,
                             messages=[{"role": "user", "content": "글 써줘"}])
    assert result == "앞부분뒷부분"
    # 이어쓰기 요청에 이전 assistant 블록이 그대로 포함되어야 함
    assert client.calls[1]["messages"][1]["role"] == "assistant"


def test_claude_generate_gives_up_when_still_truncated():
    """이어쓰기 후에도 잘려 있으면 빈 문자열 (잘린 글 게시 방지)."""
    from config import claude_generate
    client = _FakeClient([
        _FakeMessage("A", "max_tokens"),
        _FakeMessage("B", "max_tokens"),
        _FakeMessage("C", "max_tokens"),
    ])
    result = claude_generate(client, model="m", max_tokens=100, max_continues=2,
                             messages=[{"role": "user", "content": "글 써줘"}])
    assert result == ""


def test_adsense_min_score_default_80(monkeypatch):
    """AdSense 품질 기준 기본값은 80점 (사용자 확정 정책 — 낮추지 말 것)."""
    monkeypatch.delenv("ADSENSE_MIN_SCORE", raising=False)
    config = _reload_config(monkeypatch)
    assert config.ADSENSE_MIN_SCORE == 80


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
    # Pixabay 태그 나열 형식 (슬래시 2개 이상) → alt로 대체
    assert _safe_caption({"title": "marguerite / white petals / blossom / fl"}, "대체텍스트") == "대체텍스트"
    assert _safe_caption({"title": "heat wave / flower wallpaper / beautiful"}, "대체텍스트") == "대체텍스트"


def test_min_relevance_returns_fallback():
    """관련성 0 후보만 있어도 _fetch_best_image는 최상위 후보를 폴백으로 반환한다.
    최종 품질 게이트는 _filter_relevant_images(Claude)가 담당한다."""
    import image_fetcher as imf

    junk = {"url": "http://x/ChateauValere.jpg", "title": "Château de Valère", "width": 800, "height": 600}

    def fake_search(query, cid, csec, n, **kwargs):
        return [junk]

    orig = imf._search_all_sources
    imf._search_all_sources = fake_search
    try:
        result = imf._fetch_best_image("프리랜서 종합소득세 신고")
        # 폴백 반환: 관련성 미달이라도 후보가 있으면 반환 (Claude가 최종 필터링)
        assert result is not None
        assert result["url"] == junk["url"]
    finally:
        imf._search_all_sources = orig


# ──────────────────────────────────────────────────────────────────────────────
# content_generator — 가짜 체험담 방지 (경험 기반 1인칭 게이팅)
# ──────────────────────────────────────────────────────────────────────────────

def _write_author_profile(tmp_path, monkeypatch, experiences):
    """임시 author_profile.json을 만들어 config에 주입합니다."""
    import config
    profile_file = tmp_path / "author_profile.json"
    profile_file.write_text(
        json.dumps({"name": "마린파파", "experiences": experiences}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "_AUTHOR_PROFILE_FILE", str(profile_file))


def test_match_experience_ignores_examples(tmp_path, monkeypatch):
    """'예: ' 접두 항목은 템플릿 예시이므로 매칭되지 않는다."""
    from content_generator import _match_experience
    _write_author_profile(tmp_path, monkeypatch, [
        {"topics": ["예: ISA 계좌"], "blogs": ["blog1"], "summary": "예시"},
    ])
    assert _match_experience("ISA 계좌 개설 방법", "blog1") is None


def test_match_experience_topic_and_blog_filter(tmp_path, monkeypatch):
    """실제 topics는 부분 일치로 매칭되고, blogs 필터가 적용된다."""
    from content_generator import _match_experience
    _write_author_profile(tmp_path, monkeypatch, [
        {"topics": ["ISA 계좌"], "blogs": ["blog1"], "summary": "2023년부터 운용 중"},
    ])
    hit = _match_experience("ISA 계좌 수익률 정리", "blog1")
    assert hit is not None and hit["summary"] == "2023년부터 운용 중"
    assert _match_experience("ISA 계좌 수익률 정리", "blog2") is None
    assert _match_experience("제주 여행 코스", "blog1") is None


def test_style_block_without_experience_bans_fake_claims(tmp_path, monkeypatch):
    """경험 자료가 없으면 조사형 지시 + 경험 주장 금지 문구가 포함된다."""
    from content_generator import _experience_style_block
    _write_author_profile(tmp_path, monkeypatch, [])
    block = _experience_style_block("전세 보증금 반환", "blog1")
    assert "조사·분석형" in block
    assert "직접 사용해봤습니다" in block  # 금지 예시 명시
    assert "실제 수익을 공개합니다" in block


def test_style_block_with_experience_injects_material(tmp_path, monkeypatch):
    """경험 자료가 있으면 자료가 주입되고 범위 제한 경고가 포함된다."""
    from content_generator import _experience_style_block
    _write_author_profile(tmp_path, monkeypatch, [
        {"topics": ["ISA 계좌"], "blogs": [], "summary": "2023년부터 ISA 운용", "detail": "연 수익률 기록 있음"},
    ])
    block = _experience_style_block("ISA 계좌 후기", "blog1")
    assert "2023년부터 ISA 운용" in block
    assert "지어내지 마세요" in block


# ──────────────────────────────────────────────────────────────────────────────
# dashboard_exporter — blogId 폴백
# ──────────────────────────────────────────────────────────────────────────────

def test_categorize():
    from dashboard_exporter import _categorize
    assert _categorize("ETF 투자 방법") == "금융"
    assert _categorize("제주 여행 코스") == "여행"
    assert _categorize("아무 관련 없는 주제") == "일반"


def test_assess_risk_level():
    """YMYL 위험도 분류: 금융·건강·법률=high, 엔터·여행=low, 그 외=medium."""
    from content_generator import _assess_risk_level
    assert _assess_risk_level("ETF 투자 방법") == "high"
    assert _assess_risk_level("당뇨 식단 관리") == "high"
    assert _assess_risk_level("전세 계약 주의사항") == "high"
    assert _assess_risk_level("제주 여행 코스") == "low"
    assert _assess_risk_level("넷플릭스 드라마 추천") == "low"
    assert _assess_risk_level("노션 사용법 정리") == "medium"


def test_score_relevance_article_type_bonus():
    """같은 articleType 후보는 관련도 점수 +1 보너스를 받는다."""
    from internal_linker import _score_relevance
    cand = {"tags": ["ETF"], "keyword": "etf 투자", "articleType": "how_to"}
    base = _score_relevance(cand, {"ETF"}, "etf 투자")
    boosted = _score_relevance(cand, {"ETF"}, "etf 투자", current_article_type="how_to")
    assert boosted == base + 1


# ──────────────────────────────────────────────────────────────────────────────
# post_manager — 제목 중복 감지
# ──────────────────────────────────────────────────────────────────────────────

def _make_registry(entries: list[dict], tmp_path, monkeypatch):
    """임시 post_registry.json을 생성하고 post_manager에 주입합니다."""
    import post_manager as pm
    reg_file = tmp_path / "post_registry.json"
    reg_file.write_text(json.dumps(entries), encoding="utf-8")
    monkeypatch.setattr(pm, "REGISTRY_FILE", str(reg_file))
    return pm


def test_find_duplicate_exact_match(tmp_path, monkeypatch):
    """완전히 동일한 제목은 중복으로 감지된다."""
    pm = _make_registry(
        [{"post_id": "x", "title": "ETF 투자 방법", "status": "published", "blogId": "blog1"}],
        tmp_path, monkeypatch,
    )
    dup = pm.find_duplicate_post("ETF 투자 방법", blog_id="blog1")
    assert dup is not None
    assert dup["post_id"] == "x"


def test_find_duplicate_similar_title(tmp_path, monkeypatch):
    """단어 겹침이 60% 이상인 유사 제목도 중복으로 감지된다."""
    pm = _make_registry(
        [{"post_id": "y", "title": "ETF 투자 처음 입문 주의사항 정리", "status": "published", "blogId": "blog1"}],
        tmp_path, monkeypatch,
    )
    dup = pm.find_duplicate_post("ETF 투자 처음 입문 주의사항", blog_id="blog1")
    assert dup is not None


def test_find_duplicate_different_blog_no_match(tmp_path, monkeypatch):
    """다른 블로그의 동일 제목은 중복으로 잡지 않는다."""
    pm = _make_registry(
        [{"post_id": "z", "title": "ETF 투자 방법", "status": "published", "blogId": "blog2"}],
        tmp_path, monkeypatch,
    )
    dup = pm.find_duplicate_post("ETF 투자 방법", blog_id="blog1")
    assert dup is None


def test_find_duplicate_pending_not_blocked(tmp_path, monkeypatch):
    """pending 상태 포스트는 기본 필터(published)에 걸리지 않는다."""
    pm = _make_registry(
        [{"post_id": "p", "title": "ETF 투자 방법", "status": "pending", "blogId": "blog1"}],
        tmp_path, monkeypatch,
    )
    dup = pm.find_duplicate_post("ETF 투자 방법", blog_id="blog1")
    assert dup is None


def test_find_duplicate_no_match(tmp_path, monkeypatch):
    """주제가 완전히 다른 제목은 중복으로 판단하지 않는다."""
    pm = _make_registry(
        [{"post_id": "q", "title": "제주도 여행 코스 추천", "status": "published", "blogId": "blog1"}],
        tmp_path, monkeypatch,
    )
    dup = pm.find_duplicate_post("ETF 투자 방법 완전 정리", blog_id="blog1")
    assert dup is None


# ──────────────────────────────────────────────────────────────────────────────
# 자료 조사 엔진 — 자료팩 생성·검증·프롬프트 주입
# ──────────────────────────────────────────────────────────────────────────────

def test_format_evidence_without_pack_bans_fabricated_numbers():
    """자료팩이 없으면 임의 수치·날짜·정책 작성 금지 폴백 규칙이 들어간다."""
    from evidence_builder import format_evidence_for_prompt
    block = format_evidence_for_prompt(None)
    assert "임의로 만들어 쓰지 마세요" in block
    assert "자료팩 없음" in block


def test_format_evidence_with_pack_injects_facts():
    """검증된 사실이 자료팩 블록에 출처와 함께 포함된다."""
    from evidence_builder import format_evidence_for_prompt
    pack = {"keyword": "ISA", "facts": [
        {"claim": "2026년 납입 한도 4천만원", "source_title": "기재부 보도자료",
         "source_url": "https://moef.go.kr/a", "published_at": "2026-01-02", "verified": True},
        {"claim": "미검증 사실", "source_title": "x", "source_url": "https://x.com/1",
         "published_at": "", "verified": False},
    ]}
    block = format_evidence_for_prompt(pack)
    assert "2026년 납입 한도 4천만원" in block
    assert "https://moef.go.kr/a" in block
    assert "미검증 사실" not in block  # verified 사실이 있으면 그것만 사용
    assert "자료팩에 있는 것만 사용" in block


def test_validate_pack_sets_verified(monkeypatch):
    """접속 가능 여부에 따라 verified가 설정된다 (네트워크 모킹)."""
    import source_validator as sv
    monkeypatch.setattr(sv, "_fetch_page", lambda url, timeout=10: {
        "ok": "good" in url, "text": "본문", "published_at": "", "publisher": ""})
    monkeypatch.setattr(sv, "_verify_claims_with_claude", lambda facts, p: [])
    pack = {"facts": [
        {"claim": "a", "source_url": "https://good.example/1", "verified": False},
        {"claim": "b", "source_url": "https://dead.example/1", "verified": False},
    ]}
    result = sv.validate_pack(pack)
    assert result["facts"][0]["verified"] is True
    assert result["facts"][1]["verified"] is False


def test_merge_evidence_prioritizes_verified_sources():
    """자료팩 검증 출처가 sources 앞쪽에 병합되고 evidence 통계가 기록된다."""
    from content_generator import _merge_evidence
    post = {"sources": [{"title": "모델 생성 출처", "url": "https://model.example"}]}
    pack = {"facts": [
        {"claim": "a", "source_title": "공식", "source_url": "https://gov.example", "verified": True},
        {"claim": "b", "source_title": "미검증", "source_url": "https://un.example", "verified": False},
    ]}
    _merge_evidence(post, pack)
    assert post["sources"][0]["url"] == "https://gov.example"
    assert any(s["url"] == "https://model.example" for s in post["sources"])
    assert post["evidence"] == {"used": True, "facts": 2, "verified": 1}


def test_merge_evidence_without_pack():
    from content_generator import _merge_evidence
    post = {"sources": []}
    _merge_evidence(post, None)
    assert post["evidence"]["used"] is False


# ──────────────────────────────────────────────────────────────────────────────
# source_validator — 출처 신뢰도 등급·최신성·주장 대조
# ──────────────────────────────────────────────────────────────────────────────

def test_grade_source():
    """도메인 기반 A/B/C/D 등급 분류."""
    from source_validator import grade_source
    assert grade_source("https://www.moef.go.kr/press/1") == "A"
    assert grade_source("https://www.yna.co.kr/view/AKR123") == "B"
    assert grade_source("https://www.snu.ac.kr/research") == "B"
    assert grade_source("https://www.etnews.com/2026") == "C"
    assert grade_source("https://blog.naver.com/someone/1") == "D"
    assert grade_source("not-a-url") == "X"


def test_is_stale():
    from source_validator import is_stale
    assert is_stale("2020-01-01", max_age_days=730) is True
    from datetime import datetime, timezone
    recent = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert is_stale(recent, max_age_days=730) is False
    assert is_stale("", max_age_days=730) is False  # 날짜 불명은 통과


def test_validate_pack_excludes_dead_and_unsupported(monkeypatch):
    """접속 불가(X) / 내용 불일치는 제외, 나머지는 등급과 함께 통과."""
    import source_validator as sv
    pages = {
        "https://moef.go.kr/ok": {"ok": True, "text": "납입 한도 4천만원", "published_at": "2026-01-05", "publisher": "기획재정부"},
        "https://dead.example/x": {"ok": False, "text": "", "published_at": "", "publisher": ""},
        "https://yna.co.kr/wrong": {"ok": True, "text": "무관한 내용", "published_at": "2026-02-01", "publisher": "연합뉴스"},
    }
    monkeypatch.setattr(sv, "_fetch_page", lambda url, timeout=10: pages[url])
    monkeypatch.setattr(sv, "_verify_claims_with_claude", lambda facts, p: [
        {"index": 0, "supported": True, "conflicts_with": []},
        {"index": 2, "supported": False, "conflicts_with": []},
    ])
    pack = {"facts": [
        {"claim": "한도 4천만원", "source_url": "https://moef.go.kr/ok"},
        {"claim": "접속 불가 출처", "source_url": "https://dead.example/x"},
        {"claim": "내용 불일치", "source_url": "https://yna.co.kr/wrong"},
    ]}
    result = sv.validate_pack(pack)
    f0, f1, f2 = result["facts"]
    assert f0["verified"] is True and f0["grade"] == "A" and f0["publisher"] == "기획재정부"
    assert f1["verified"] is False and f1["grade"] == "X"
    assert f2["verified"] is False and f2["grade"] == "X"  # 내용 불일치 → 제외


def test_format_evidence_requires_ab_grade_for_critical_facts():
    """중요 수치·정책 사실은 A/B 등급 출처가 있어야 자료팩 블록에 포함된다."""
    from evidence_builder import format_evidence_for_prompt
    pack = {"keyword": "ISA", "facts": [
        {"claim": "납입 한도 4천만원으로 변경", "source_title": "기재부", "grade": "A",
         "source_url": "https://moef.go.kr/1", "published_at": "2026-01-01", "verified": True},
        {"claim": "세율 15% 인하 예정", "source_title": "개인 블로그", "grade": "D",
         "source_url": "https://blog.naver.com/x", "published_at": "", "verified": True},
        {"claim": "가입 절차는 비대면으로 가능", "source_title": "블로그", "grade": "D",
         "source_url": "https://blog.naver.com/y", "published_at": "", "verified": True},
    ]}
    block = format_evidence_for_prompt(pack)
    assert "납입 한도 4천만원" in block          # 중요 + A등급 → 포함
    assert "세율 15% 인하" not in block          # 중요 + D등급 → 제외
    assert "비대면으로 가능" in block            # 비중요 + D등급 → 포함
    assert "[등급 A]" in block


# ──────────────────────────────────────────────────────────────────────────────
# 글 유형별 구조 재설계 — 유형 감지·구조 변주·FAQ 스키마
# ──────────────────────────────────────────────────────────────────────────────

def test_detect_new_article_types():
    """투자형·뉴스해설 유형이 감지된다."""
    from content_generator import _detect_article_type
    assert _detect_article_type("삼성전자 주가 전망") == "investment"
    assert _detect_article_type("2026 최저임금 인상 발표") == "news_analysis"
    assert _detect_article_type("ISA 계좌 개설 방법") == "how_to"


def test_structure_guide_has_all_types():
    """모든 유형에 권장 구조가 정의되어 있다."""
    from content_generator import _STRUCTURE_GUIDE, _detect_article_type
    for t in ["how_to", "review", "comparison", "explainer", "analysis",
              "investment", "news_analysis", "drama_review", "travel_guide", "sports_review"]:
        assert t in _STRUCTURE_GUIDE, f"{t} 구조 없음"
    assert "준비 → 단계" in _STRUCTURE_GUIDE["how_to"] or "준비:" in _STRUCTURE_GUIDE["how_to"]
    assert "시나리오" in _STRUCTURE_GUIDE["investment"]
    assert "향후 관찰점" in _STRUCTURE_GUIDE["news_analysis"]


def test_structure_variation_deterministic_but_diverse():
    """같은 키워드는 같은 변주, 다른 키워드들은 서로 다른 변주가 나온다."""
    from content_generator import _structure_variation
    a1 = _structure_variation("ISA 계좌 개설")
    a2 = _structure_variation("ISA 계좌 개설")
    assert a1 == a2  # 재시도 시 일관성
    assert "구조 변주" in a1
    # 여러 키워드에서 H2 개수·도입부 스타일이 다양하게 분포하는지
    variations = {_structure_variation(f"키워드{i}") for i in range(12)}
    assert len(variations) >= 4


def test_faq_schema_disabled_by_default(monkeypatch):
    """FAQPage 구조화 데이터는 기본 비활성 — Article·Breadcrumb 중심."""
    monkeypatch.delenv("FAQ_SCHEMA", raising=False)
    import importlib
    import schema_generator as sg
    importlib.reload(sg)
    types = sg._detect_types({
        "title": "테스트", "keyword": "테스트",
        "faq": [{"q": "질문", "a": "답변"}],
    })
    assert "FAQPage" not in types
    assert "BlogPosting" in types and "BreadcrumbList" in types
    # 환경변수로 재활성화 가능
    monkeypatch.setenv("FAQ_SCHEMA", "true")
    types2 = sg._detect_types({
        "title": "테스트", "keyword": "테스트",
        "faq": [{"q": "질문", "a": "답변"}],
    })
    assert "FAQPage" in types2
