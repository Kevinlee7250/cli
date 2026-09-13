"""제목 경험 주장 가드레일 테스트 (2026-09-12).

본문 가드레일(`_experience_style_block`)은 2026-08-26에 들어갔지만 제목은
무방비였고, 그 결과 가드레일 이후인 9월 발행분에도 "직접 써본 후기" 같은
제목이 나갔습니다. AdSense 거절 사유에 직접 해당하므로 회귀를 막습니다.

핵심 확인:
  - 실제로 나갔던 제목이 전부 걸리는가
  - 정상적인 조사형 제목을 막지 않는가 (막으면 재시도 3회를 낭비하고
    멀쩡한 제목이 sanitize로 망가집니다)
  - author_profile에 자료가 있으면 통과시키는가
  - sanitize 결과가 다시 위반이 아닌가 (무한 루프 방지)
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from title_policy import (  # noqa: E402
    check_title,
    sanitize_title,
    title_escalation_note,
)

# 2026-09-12 실제 발행돼 있던 제목들
SHIPPED_FABRICATED = [
    "멜론 vs 지니 vs 유튜브뮤직 요금 비교, 3개월 직접 써본 후기",
    "해외에서 사고 났을 때 대사관 신고, 제가 겪은 실제 절차",
    "여수 밤바다 오션뷰 숙소 가성비 비교, 직접 예약해봤더니",
    "자전거 출퇴근 3개월 해본 솔직 장단점 정리 (따릉이 vs 개인 자전거)",
    "홈트레이닝 기구 6개월 써본 솔직한 후기, 콰트 바로보드 총정리",
    "제주 한 달 살기, 한 달 지내며 정산한 실제 생활비와 숙소 비용 공개",
    "패키지여행 계약서 환불 조항, 직접 읽어보고 알게 된 것",
    "항공권 취소·지연 보상 직접 청구해보니 알게 된 것들 총정리",
    "서울 근교 드라이브 코스, 직접 가본 솔직 평가 총정리",
    "경주 당일치기 코스, 놓치면 후회하는 곳 직접 다녀와서 정리",
    "수영 초보 시작 계기, 물 공포증 극복하려다 겪은 첫 좌절 [1편]",
]

# 조사형 — 생성기가 지시하는 정상 문체. 여기가 걸리면 멀쩡한 제목이 망가집니다.
LEGITIMATE_TITLES = [
    "2026 통신 요금제 3종 비교, 가격 차이 정리",
    "이용자 후기를 종합한 노트북 추천 5선",
    "제주 한 달 살기 생활비, 공개된 사례 종합",
    "종부세 개편 1주택자 절세법, 공식 안내 기준 정리",
    "국내 여행지 추천 10곳과 예상 경비",
    "ETF 수수료 비교, 운용사별 차이 한눈에",
    "공식 발표 기준 2026 최저임금 정리",
    "전세 계약 전 확인할 체크리스트 7가지",
]


class TestShippedTitlesAreCaught:
    @pytest.mark.parametrize("title", SHIPPED_FABRICATED)
    def test_flagged(self, title):
        v = check_title(title)
        assert v, f"실제 나갔던 경험 주장 제목을 놓침: {title}"
        assert any(x.startswith("경험 주장") for x in v), \
            f"경험 주장으로 분류되지 않음: {title} → {v}"


class TestLegitimateTitlesPass:
    @pytest.mark.parametrize("title", LEGITIMATE_TITLES)
    def test_not_flagged(self, title):
        assert check_title(title) == [], f"정상 조사형 제목을 오탐: {title}"


class TestAllowExperience:
    def test_real_experience_bypasses(self):
        """author_profile에 자료가 있는 글은 1인칭이 정당합니다."""
        t = "골프장 직접 다녀온 후기"
        assert check_title(t) != []
        assert check_title(t, allow_experience=True) == []

    def test_clickbait_still_blocked_with_experience(self):
        """경험이 진짜여도 과장 표현은 여전히 막아야 합니다."""
        v = check_title("충격! 골프장 직접 다녀온 후기", allow_experience=True)
        assert "충격" in v

    def test_sanitize_respects_allow_experience(self):
        t = "골프장 3개월 직접 써본 후기"
        assert sanitize_title(t, allow_experience=True) == t


class TestSanitizeProducesCleanTitles:
    @pytest.mark.parametrize("title", SHIPPED_FABRICATED)
    def test_sanitized_title_no_longer_violates(self, title):
        """순화 결과가 또 위반이면 재시도 루프가 의미를 잃습니다."""
        out = sanitize_title(title)
        assert check_title(out) == [], f"{title!r} → {out!r} 가 여전히 위반"

    @pytest.mark.parametrize("title", SHIPPED_FABRICATED)
    def test_sanitized_title_stays_meaningful(self, title):
        out = sanitize_title(title)
        assert len(out) >= 10, f"너무 짧아짐: {title!r} → {out!r}"

    def test_no_repeated_filler(self):
        """치환이 겹쳐 '총정리 정리 총정리'가 되지 않아야 합니다."""
        out = sanitize_title("서울 근교 드라이브 코스, 직접 가본 솔직 평가 총정리")
        for filler in ("총정리", "정리"):
            assert out.count(filler) <= 2, f"상투어 반복: {out}"

    def test_period_phrase_rewritten_as_unit(self):
        """'3개월 직접 써본 후기' 가 '3개월 총정리 후기'가 되면 안 됩니다."""
        out = sanitize_title("멜론 요금 비교, 3개월 직접 써본 후기")
        assert "3개월 사용 후기" in out, out

    def test_legitimate_title_untouched(self):
        t = "2026 통신 요금제 3종 비교, 가격 차이 정리"
        assert sanitize_title(t) == t


class TestEscalationNote:
    def test_experience_only_still_returns_guidance(self):
        """초판에서 괄호 위치 때문에 경험 주장만 있으면 빈 문자열이 나왔습니다."""
        note = title_escalation_note(["경험 주장: 직접 ~해봤"])
        assert note.strip(), "경험 주장 안내가 비어 있음"
        assert "경험 주장 제목 금지" in note

    def test_clickbait_only(self):
        note = title_escalation_note(["충격"])
        assert "클릭 유도" in note
        assert "경험 주장 제목 금지" not in note

    def test_both_kinds_present(self):
        note = title_escalation_note(["충격", "경험 주장: 솔직 후기"])
        assert "경험 주장 제목 금지" in note and "클릭 유도" in note

    def test_empty_violations(self):
        assert title_escalation_note([]) == ""

    def test_good_example_is_not_itself_a_claim(self):
        """안내문의 '좋은 예'가 경험 주장이면 모델에게 잘못 가르칩니다.

        초판의 좋은 예가 "실제로 비교해보니 가격 차이가 3배였다" 였습니다.
        """
        note = title_escalation_note(["충격"])
        for line in note.splitlines():
            if "좋은 예" in line:
                example = line.split("좋은 예:")[-1]
                assert check_title(example) == [], f"안내문의 좋은 예가 위반: {example}"


class TestAuditAgreement:
    """감사(experience_audit)와 생성 가드레일(title_policy)이 같은 판정이어야 합니다."""

    @pytest.mark.parametrize("title", SHIPPED_FABRICATED + LEGITIMATE_TITLES)
    def test_same_verdict(self, title):
        from experience_audit import analyze_text
        audit_flagged = bool(analyze_text(title, title_mode=True))
        policy_flagged = any(v.startswith("경험 주장") for v in check_title(title))
        assert audit_flagged == policy_flagged, (
            f"판정 불일치: {title!r} — 감사={audit_flagged}, 정책={policy_flagged}. "
            "한쪽만 잡으면 생성은 통과시키고 감사만 지적하게 됩니다."
        )
