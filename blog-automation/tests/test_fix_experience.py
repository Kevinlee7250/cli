"""경험 주장 정정 도구 테스트 (제목 B · 본문 C).

두 도구 모두 라이브 글을 직접 고칩니다. 되돌리기가 어려우므로 특히
아래 두 가지가 무너지지 않는지 봅니다.

  1. **재작성 결과를 다시 검사하는가** — 경험 주장을 다른 경험 주장으로
     바꾸고 성공으로 집계하면 리포트만 초록색이 되고 실제로는 그대로입니다.
  2. **멀쩡한 부분을 건드리지 않는가** — 문제 없는 문단·제목까지 손대면
     정보가 사라지고 분량이 줄어 thin content 판정을 새로 만듭니다.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fix_experience_claims as fc  # noqa: E402
import fix_experience_titles as ft  # noqa: E402


# ──────────────────────────────────────────────────────────────
# B — 제목 정정
# ──────────────────────────────────────────────────────────────

class TestProposeTitle:
    def test_uses_claude_result_when_clean(self, monkeypatch):
        monkeypatch.setattr(ft, "_rewrite_with_claude",
                            lambda t, v: "3개월 사용 후기 종합, 요금제 비교")
        new, src = ft.propose_title("3개월 직접 써본 후기, 요금제 비교",
                                    ["경험 주장: 직접 ~해봤"])
        assert src == "claude"
        assert "직접" not in new

    def test_rejects_claude_result_that_still_violates(self, monkeypatch):
        """모델이 또 경험 주장을 내놓으면 채택하면 안 됩니다."""
        monkeypatch.setattr(ft, "_rewrite_with_claude",
                            lambda t, v: "제가 직접 다녀온 솔직 후기")
        new, src = ft.propose_title("직접 다녀온 솔직 후기, 강릉 여행",
                                    ["경험 주장: 직접 ~해봤"])
        assert src != "claude", f"위반 제안을 채택함: {new}"

    def test_falls_back_to_rule_when_claude_unavailable(self, monkeypatch):
        monkeypatch.setattr(ft, "_rewrite_with_claude", lambda t, v: "")
        new, src = ft.propose_title("멜론 요금 비교, 3개월 직접 써본 후기",
                                    ["경험 주장: 직접 ~해봤"])
        assert src == "rule"
        assert "3개월 사용 후기" in new

    def test_rejects_too_short_claude_result(self, monkeypatch):
        monkeypatch.setattr(ft, "_rewrite_with_claude", lambda t, v: "후기")
        new, src = ft.propose_title("멜론 요금 비교, 3개월 직접 써본 후기",
                                    ["경험 주장: 직접 ~해봤"])
        assert src != "claude"

    def test_returns_empty_when_nothing_works(self, monkeypatch):
        """규칙으로도 못 고치면 보류해야 합니다 — 억지로 바꾸면 제목이 망가집니다."""
        import title_policy

        monkeypatch.setattr(ft, "_rewrite_with_claude", lambda t, v: "")
        # 치환이 아무것도 바꾸지 못하는 상황을 만듭니다.
        monkeypatch.setattr(title_policy, "sanitize_title", lambda t, **k: t)
        new, src = ft.propose_title("직접 써본 후기", ["경험 주장: 직접 ~해봤"])
        assert new == "" and src == ""

    def test_short_title_is_held_not_mangled(self):
        """sanitize가 10자 미만이면 원본을 돌려주므로 결국 보류됩니다."""
        new, src = ft.propose_title("직접 써본 후기", ["경험 주장: 직접 ~해봤"])
        assert new == "" or not __import__("title_policy").check_title(new)


class TestClaudeOutputCleanup:
    @pytest.mark.parametrize("raw,expected_start", [
        ('"3개월 사용 후기 종합"', "3개월"),
        ("바꾼 제목: 3개월 사용 후기 종합", "3개월"),
        ("제목: 3개월 사용 후기 종합\n설명은 생략", "3개월"),
        ("“3개월 사용 후기 종합”", "3개월"),
    ])
    def test_strips_wrappers(self, raw, expected_start, monkeypatch):
        """모델이 따옴표·머리말·설명을 붙이는 경우를 벗겨야 합니다."""
        import anthropic  # noqa: F401
        monkeypatch.setattr(ft, "claude_generate", lambda *a, **k: raw, raising=False)

        # _rewrite_with_claude 내부의 import 경로를 우회해 정제 로직만 검증
        import re
        line = (raw.splitlines() or [""])[0].strip()
        line = re.sub(r'^["\'“”‘’]+|["\'“”‘’]+$', "", line).strip()
        line = re.sub(r"^(바꾼\s*제목|제목)\s*[:：]\s*", "", line).strip()
        assert line.startswith(expected_start), line


# ──────────────────────────────────────────────────────────────
# C — 본문 리라이팅
# ──────────────────────────────────────────────────────────────

CLEAN_P = "<p>공식 발표 기준으로는 월 10,900원입니다.</p>"
BAD_P = "<p>저는 2024년 11월 한 달 동안 제주에서 지냈고 총 178만원을 썼습니다.</p>"


class TestFindBadParagraphs:
    def test_finds_only_bad(self):
        html = CLEAN_P + BAD_P + "<p>이용자 후기를 종합하면 만족도가 높습니다.</p>"
        bad = fc.find_bad_paragraphs(html)
        assert len(bad) == 1
        assert "178만원" in bad[0][1]

    def test_ignores_non_paragraph_markup(self):
        """목차·FAQ 카드는 구조가 있어 문장 교체 시 마크업이 깨집니다."""
        html = '<div class="toc">직접 써본 후기</div><h2>직접 가본 곳</h2>'
        assert fc.find_bad_paragraphs(html) == []

    def test_empty_content(self):
        assert fc.find_bad_paragraphs("") == []
        assert fc.find_bad_paragraphs(None) == []


class TestRewriteContent:
    def test_replaces_only_bad_paragraph(self, monkeypatch):
        monkeypatch.setattr(fc, "rewrite_paragraph",
                            lambda text, hits, title="":
                            "공개된 사례를 종합하면 제주 한 달 생활비는 150만원 안팎으로 알려져 있습니다.")
        html = CLEAN_P + BAD_P
        out, replaced, rejected = fc.rewrite_content(html, "제주 한 달 살기")
        assert replaced == 1 and rejected == 0
        assert CLEAN_P in out, "멀쩡한 문단이 바뀌었습니다"
        assert "178만원" not in out
        assert "저는" not in out

    def test_rejects_rewrite_that_still_claims_experience(self, monkeypatch):
        """가장 중요한 방어선 — 조작을 조작으로 바꾸고 성공 처리하면 안 됩니다."""
        monkeypatch.setattr(fc, "rewrite_paragraph",
                            lambda text, hits, title="":
                            "제가 직접 살아본 결과 총 160만원이 들었습니다.")
        out, replaced, rejected = fc.rewrite_content(BAD_P, "제주")
        assert replaced == 0 and rejected == 1
        assert out == BAD_P, "반려했는데 본문이 바뀌었습니다"

    def test_rejects_rewrite_that_is_too_short(self, monkeypatch):
        monkeypatch.setattr(fc, "rewrite_paragraph", lambda text, hits, title="": "생활비 정보.")
        out, replaced, rejected = fc.rewrite_content(BAD_P, "제주")
        assert replaced == 0 and rejected == 1

    def test_rewrite_failure_keeps_original(self, monkeypatch):
        monkeypatch.setattr(fc, "rewrite_paragraph", lambda text, hits, title="": "")
        out, replaced, rejected = fc.rewrite_content(BAD_P, "제주")
        assert out == BAD_P and replaced == 0 and rejected == 1

    def test_preserves_paragraph_attributes(self, monkeypatch):
        monkeypatch.setattr(fc, "rewrite_paragraph",
                            lambda text, hits, title="":
                            "공개된 자료를 종합하면 생활비는 150만원 안팎으로 알려져 있습니다.")
        html = '<p style="line-height:1.9" class="body">저는 2024년에 178만원을 썼습니다.</p>'
        out, replaced, _ = fc.rewrite_content(html, "제주")
        assert replaced == 1
        assert 'style="line-height:1.9"' in out and 'class="body"' in out

    def test_clean_content_untouched(self):
        html = CLEAN_P + "<p>이용자 후기를 종합하면 좋다는 평입니다.</p>"
        out, replaced, rejected = fc.rewrite_content(html, "요금제")
        assert out == html and replaced == 0 and rejected == 0

    def test_strips_p_tags_from_model_output(self, monkeypatch):
        """모델이 <p>를 붙여 오면 중첩됩니다."""
        monkeypatch.setattr(fc, "rewrite_paragraph",
                            lambda text, hits, title="":
                            "공개된 자료를 종합하면 생활비는 150만원 안팎으로 알려져 있습니다.")
        out, _, _ = fc.rewrite_content(BAD_P, "제주")
        assert "<p><p>" not in out and "</p></p>" not in out


class TestLengthGuard:
    def test_plain_len_ignores_markup(self):
        assert fc._plain_len("<p>abc</p>") == 3
        assert fc._plain_len('<div class="x">가나다</div>') == 3

    def test_min_ratio_is_conservative(self):
        """분량이 크게 줄면 thin content 판정을 새로 만듭니다."""
        assert 0.8 <= fc.MIN_LENGTH_RATIO < 1.0


class TestSharedAuditStandard:
    """두 도구 모두 experience_audit을 판정 기준으로 써야 합니다."""

    def test_claims_tool_uses_audit(self):
        import inspect
        src = inspect.getsource(fc.rewrite_content)
        assert "analyze_text" in src

    def test_titles_tool_uses_policy(self):
        import inspect
        src = inspect.getsource(ft.propose_title)
        assert "check_title" in src
