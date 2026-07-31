"""중복 주제 처리 3종 수정 회귀 테스트 (2026-07-31 점검에서 발견된 문제).

배경: "레버리지 ETF"·"항공권 예약" 등 거의 같은 주제가 7회 이상 반복
선정→생성→업로드 직전 중복 가드 차단→"업로드 실패"로 기록→auto-repair
critical 오탐까지 이어지는 5중 낭비가 있었음.

① 업로드 중복 차단은 실패가 아닌 "DUPLICATE" 센티널로 구분
② 키워드 선정 단계에서 변형 키워드까지 차단 (핵심 토큰·선두 2토큰 규칙)
③ 발행 이력(post_registry) 30일치를 유사도 코퍼스에 합류

실행: cd blog-automation && python -m pytest tests/test_duplicate_handling.py -v
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ──────────────────────────────────────────────────────────────────────────────
# ① upload_post 중복 센티널
# ──────────────────────────────────────────────────────────────────────────────

def test_upload_post_returns_duplicate_sentinel():
    import blogger_uploader as bu
    dup = {"title": "기존 글", "blogUrl": "http://x"}
    with patch.object(bu, "_get_access_token", return_value="tok"), \
         patch("post_manager.find_duplicate_post", return_value=dup):
        result = bu.upload_post(
            {"title": "레버리지 ETF 위험성", "content": "<p>x</p>"},
            {"id": "blog3", "blog_id": "123"},
        )
    assert result == "DUPLICATE"


def test_retry_failed_posts_skips_duplicate_without_marking_failed(monkeypatch, tmp_path):
    import post_manager as pm

    registry_file = tmp_path / "registry.json"
    monkeypatch.setattr(pm, "REGISTRY_FILE", str(registry_file))

    post_data = {"keyword": "레버리지 ETF", "title": "레버리지 ETF 위험성"}
    pid = pm.register_post(post_data, pm.Status.FAILED, blog_config={"id": "blog3"})
    pm.save_draft(pid, post_data)

    # retry_failed_posts는 blogger_uploader.upload_post를 함수 내부에서 import함
    with patch("post_manager.find_duplicate_post", return_value=None), \
         patch("blogger_uploader.upload_post", return_value="DUPLICATE"), \
         patch("time.sleep"):
        counts = pm.retry_failed_posts(blog_config={"id": "blog3"})

    registry = pm.load_registry()
    entry = next(e for e in registry if e["post_id"] == pid)
    assert entry["status"] == pm.Status.SKIPPED
    assert counts["failed"] == 0
    assert counts["skipped"] >= 1


# ──────────────────────────────────────────────────────────────────────────────
# ② 변형 키워드 차단 규칙
# ──────────────────────────────────────────────────────────────────────────────

_PUBLISHED = [
    "레버리지 ETF 투자 주의사항, 29년 뒤 원금 99% 증발 위험성",
    "여름휴가 항공권 호텔 저렴하게 예약하는 방법 총정리",
    "KBO 야구 직관 처음 가는 사람을 위한 준비물 체크리스트",
]


def test_variant_keywords_blocked():
    """실제로 7회+ 반복 발행됐던 변형 패턴들이 차단되는지."""
    from keyword_collector import _is_too_similar
    variants = [
        "레버리지 ETF, 왜 위험하다는 걸까? 2026년 달라지는 점까지 쉽게 정리",
        "레버리지 ETF 투자 위험성과 2026년 대응 전략 총정리",
        "2026년 여름휴가 항공권·숙소 저렴하게 예약하는 방법",
        "KBO 야구 직관 처음 가는 사람 준비물 정리",
    ]
    for v in variants:
        assert _is_too_similar(v, _PUBLISHED), f"차단 실패: {v}"


def test_fresh_topics_still_pass():
    """같은 단어를 일부 공유해도 다른 주제는 통과해야 함 (과차단 방지)."""
    from keyword_collector import _is_too_similar
    fresh = [
        "부산 1박2일 혼자 여행 코스",
        "ETF 월배당 포트폴리오 구성법",       # ETF 공유하지만 다른 주제
        "여름휴가 물놀이 안전수칙",           # 여름휴가 공유하지만 다른 주제
        "손흥민 결승골 경기 결과 분석",
    ]
    for f in fresh:
        assert not _is_too_similar(f, _PUBLISHED), f"과차단: {f}"


def test_lead_tokens_excludes_generic_words():
    from keyword_collector import _lead_tokens
    assert _lead_tokens("완벽 정리 레버리지 ETF 가이드") == ("레버리지", "etf")


# ──────────────────────────────────────────────────────────────────────────────
# ③ post_registry 30일 코퍼스 합류
# ──────────────────────────────────────────────────────────────────────────────

def test_registry_corpus_includes_recent_published(monkeypatch, tmp_path):
    import keyword_collector as kc
    from datetime import datetime, timedelta

    reg_file = tmp_path / "post_registry.json"
    recent = (datetime.now() - timedelta(days=5)).isoformat()
    old = (datetime.now() - timedelta(days=45)).isoformat()
    reg_file.write_text(json.dumps([
        {"status": "published", "createdAt": recent, "blogId": "blog3",
         "title": "레버리지 ETF 투자 주의사항", "keyword": "레버리지 ETF"},
        {"status": "published", "createdAt": old, "blogId": "blog3",
         "title": "오래된 글 제목", "keyword": "오래된 키워드"},
        {"status": "failed", "createdAt": recent, "blogId": "blog3",
         "title": "실패한 글", "keyword": "실패 키워드"},
        {"status": "published", "createdAt": recent, "blogId": "blog1",
         "title": "다른 블로그 글", "keyword": "다른 키워드"},
    ], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(kc, "_REGISTRY_FILE", str(reg_file))

    corpus = kc._load_registry_corpus(blog_id="blog3")
    assert "레버리지 ETF 투자 주의사항" in corpus     # 최근 발행 → 포함
    assert "오래된 글 제목" not in corpus              # 30일 초과 → 제외
    assert "실패한 글" not in corpus                   # 미발행 → 제외
    assert "다른 블로그 글" not in corpus              # 타 블로그 → 제외
