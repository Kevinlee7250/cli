"""조작 체험담 감사 도구 테스트.

이 도구의 판정이 곧 "어떤 글을 내리고 어떤 글을 고칠지"가 되므로,
두 방향의 실수가 모두 비쌉니다:

  - 오탐: 멀쩡한 조사형 글을 리라이팅 대상으로 몰아 멀쩡한 글을 망침
  - 누락: 지어낸 체험담이 그대로 남아 AdSense 재거절

그래서 실제 발행글에서 가져온 문장을 양쪽 모두 고정해 둡니다.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from experience_audit import (  # noqa: E402
    _strip_html,
    _worst,
    analyze_text,
    audit_post,
)


# 2026-09-12 hoguwhat.com 실제 발행 제목 — 전부 지어낸 경험입니다
REAL_FABRICATED_TITLES = [
    "제주 한 달 살기, 한 달 지내며 정산한 실제 생활비와 숙소 비용 공개",
    "여수 밤바다 오션뷰 숙소 가성비 비교, 직접 예약해봤더니",
    "멜론 vs 지니 vs 유튜브뮤직 요금 비교, 3개월 직접 써본 후기",
    "해외에서 사고 났을 때 대사관 신고, 제가 겪은 실제 절차",
    "항공권 취소·지연 보상 직접 청구해보니 알게 된 것들 총정리",
    "자전거 출퇴근 3개월 해본 솔직 장단점 정리 (따릉이 vs 개인 자전거)",
    "홈트레이닝 기구 6개월 써본 솔직한 후기, 콰트 바로보드 총정리",
    "패키지여행 계약서 환불 조항, 직접 읽어보고 알게 된 것",
    "수영 초보 시작 계기, 물 공포증 극복하려다 겪은 첫 좌절 [1편]",
    "서울 근교 드라이브 코스, 직접 가본 솔직 평가 총정리",
]

# 조사·분석형 — 생성기 가드레일이 지시하는 정상 문체입니다
LEGITIMATE_RESEARCH = [
    "이용자 후기를 종합하면 배터리 지속시간이 짧다는 평이 많습니다.",
    "공식 발표 기준으로는 월 10,900원입니다.",
    "자료를 조사해보니 평균 생활비는 150만원 수준으로 알려져 있습니다.",
    "리뷰를 종합하면 가성비는 좋다는 평가가 우세합니다.",
    "국토교통부 자료에 따르면 공급 물량은 23만호입니다.",
    "이용자 반응은 크게 두 갈래로 갈립니다.",
]


class TestFabricatedClaimsAreCaught:
    @pytest.mark.parametrize("title", REAL_FABRICATED_TITLES)
    def test_real_titles_flagged(self, title):
        hits = analyze_text(title, title_mode=True)
        assert hits, f"지어낸 경험 주장을 놓침: {title}"

    def test_jeju_post_is_critical(self):
        """구체적 금액·시점이 붙은 것이 가장 위험합니다."""
        body = "저는 2024년 11월 한 달 동안 제주시 이도동의 원룸 오피스텔에서 지냈습니다."
        assert _worst(analyze_text(body)) == "critical"

    def test_amount_before_pronoun_also_critical(self):
        """어순이 뒤집혀도 잡아야 합니다."""
        assert _worst(analyze_text("총 178만원을 제가 지출했습니다.")) == "critical"

    @pytest.mark.parametrize("text,label_part", [
        ("직접 읽어보고 알게 된 것", "직접"),
        ("6개월 써본 솔직한 후기", "기간"),
        ("물 공포증 극복하려다 겪은 첫 좌절", "겪은"),
        ("제 경험상 이 방법이 가장 빨랐습니다.", "경험"),
    ])
    def test_specific_phrasings(self, text, label_part):
        hits = analyze_text(text, title_mode=True)
        assert hits, f"놓침: {text}"
        assert any(label_part in h["label"] for h in hits), \
            f"{text} → {[h['label'] for h in hits]}"


class TestResearchFramingIsNotFlagged:
    @pytest.mark.parametrize("text", LEGITIMATE_RESEARCH)
    def test_no_false_positive(self, text):
        assert analyze_text(text) == [], f"조사형 문장을 오탐: {text}"

    def test_bogo_as_ordinary_verb(self):
        """'보고'가 경험이 아닌 일상 동사로 쓰인 경우."""
        assert analyze_text("보고서를 정리했습니다.") == []
        assert analyze_text("직접 보고 판단하세요.") == []

    def test_review_summary_phrase(self):
        assert analyze_text("후기를 종합하면 만족도가 높습니다.") == []

    def test_research_framing_does_not_shield_critical(self):
        """조사형 표현이 있어도 구체 수치 + 1인칭은 여전히 위험합니다.

        "자료를 조사해보니 저는 2024년에 …" 처럼 섞어 쓰면 안 됩니다.
        """
        text = "자료를 조사해보니 제가 2024년 3월에 쓴 금액은 180만원이었습니다."
        assert _worst(analyze_text(text)) == "critical"


class TestSeverityOrdering:
    def test_worst_picks_highest(self):
        hits = [{"severity": "medium"}, {"severity": "critical"}, {"severity": "high"}]
        assert _worst(hits) == "critical"

    def test_empty_is_ok(self):
        assert _worst([]) == "ok"


class TestStripHtml:
    def test_removes_tags_and_scripts(self):
        html = '<p>본문</p><script>var x="직접 써봤";</script><style>.a{}</style>'
        out = _strip_html(html)
        assert "본문" in out
        assert "직접 써봤" not in out, "스크립트 안의 문자열이 본문으로 새면 오탐"
        assert "<" not in out

    def test_handles_empty(self):
        assert _strip_html("") == ""
        assert _strip_html(None) == ""


class TestAuditPost:
    def test_title_and_body_combined(self):
        res = audit_post("멜론 3개월 직접 써본 후기",
                         "<p>이용자 후기를 종합하면 가성비가 좋습니다.</p>")
        assert res["severity"] == "high", "제목의 경험 주장이 본문에 가려지면 안 됨"
        assert res["title_hits"]

    def test_clean_post_is_ok(self):
        res = audit_post("2026 통신 요금제 비교",
                         "<p>공식 발표 기준으로는 월 10,900원입니다.</p>")
        assert res["severity"] == "ok"
        assert res["title_hits"] == [] and res["body_hits"] == []

    def test_real_experience_exempts(self, monkeypatch):
        """author_profile에 자료가 있으면 1인칭이 정당하므로 감점하지 않습니다."""
        import experience_audit as ea
        monkeypatch.setattr(ea, "_has_real_experience", lambda k, b: True)
        res = ea.audit_post("골프장 직접 다녀온 후기", "<p>제가 라운딩해보니</p>",
                            keyword="골프", blog_id="blog2")
        assert res["severity"] == "ok"
        assert "author_profile" in res["reason"]

    def test_body_hits_are_capped(self):
        """리포트가 비대해지지 않도록 상위 8개만 싣되 총 건수는 보존합니다."""
        body = "".join(f"<p>직접 써봤습니다 {i}.</p>" for i in range(20))
        res = audit_post("제목", body)
        assert len(res["body_hits"]) <= 8
        assert res["body_hit_count"] >= 15


class TestGeneratorGuardrailAgreement:
    """감사와 생성기가 같은 기준을 써야 합니다.

    생성기가 허용한 표현을 감사가 지적하면 고칠 수 없는 지적이 쌓이고,
    반대면 조작이 새어 나갑니다.
    """

    def test_uses_generator_match_experience(self):
        import inspect

        import experience_audit as ea
        src = inspect.getsource(ea._has_real_experience)
        assert "_match_experience" in src, \
            "감사가 독자적 판정을 쓰면 생성기와 어긋납니다"
