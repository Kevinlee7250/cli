"""사이트 재편(소규모 정예) 도구 테스트.

이 도구는 발행된 글 400편 가까이를 한 번에 내립니다. 되돌릴 수는 있지만
(임시저장 전환이라 삭제가 아닙니다) 사람이 400편을 눈으로 검수하지는
못하므로, 계획이 조용히 틀리는 것이 가장 큰 위험입니다. 그래서 아래
네 가지를 봅니다.

  1. **아무 글도 잃지 않는가** — 감사에 오른 글은 rewrite 아니면
     unpublish, 정확히 한 번씩. 분류에서 새는 글은 계획에도 안 잡히고
     사이트에도 남아 조작 글이 그대로 공개됩니다.
  2. **밀도로 판단하는가** — 첫 판은 문제 문단 '개수'만 봐서 3,000자
     드라마 회차 리뷰가 4,900자 연금 가이드를 이겼습니다. AdSense
     심사에서 정확히 반대 방향이라 회귀하면 안 됩니다.
  3. **정원을 채우려고 쓰레기를 넣지 않는가** — 25편을 채우는 것이
     목표가 아니라 25편이 쓸 만한 것이 목표입니다.
  4. **dry-run이 정말 아무것도 안 바꾸는가**.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import curate_site as cs  # noqa: E402


def audit_item(**kw):
    base = {"title": "제목", "url": "https://ex.com/a.html", "blog": "블로그A",
            "blogId": "blog1", "severity": "high", "body_hit_count": 3}
    base.update(kw)
    return base


def meta(**kw):
    base = {"wordCount": 3500, "faqCount": 3, "articleType": "analysis",
            "status": "published", "blogName": "블로그A"}
    base.update(kw)
    return base


# ──────────────────────────────────────────────────────────────
# 점수 — 무엇을 살릴 만하다고 보는가
# ──────────────────────────────────────────────────────────────

class TestSalvageScore:

    def test_density_beats_raw_hit_count(self):
        """같은 문제 문단 2개라도 4,900자 가이드가 2,600자 리뷰보다 위여야 합니다.

        이 순서가 뒤집혔던 것이 첫 판의 실제 버그입니다.
        """
        long_guide, _ = cs.salvage_score(
            audit_item(severity="critical", body_hit_count=2),
            meta(wordCount=4900, articleType="investment"),
            "퇴직연금 수익률 높이는 운용 방법 2026")
        short_recap, _ = cs.salvage_score(
            audit_item(severity="medium", body_hit_count=2),
            meta(wordCount=2600, articleType="drama_review"),
            "김부장 9화 리뷰")
        assert long_guide > short_recap, (long_guide, short_recap)

    def test_scattered_fabrication_is_rejected(self):
        """조작이 글 전체에 퍼져 있으면 분량이 길어도 살리지 않습니다."""
        localized, _ = cs.salvage_score(
            audit_item(severity="critical", body_hit_count=2), meta(wordCount=5000))
        skeletal, _ = cs.salvage_score(
            audit_item(severity="critical", body_hit_count=15), meta(wordCount=5000))
        assert localized - skeletal >= 60

    def test_episodic_title_penalised_despite_misleading_type(self):
        """레지스트리가 드라마 리뷰에 news_analysis를 붙여 놓은 경우가 있습니다."""
        plain, _ = cs.salvage_score(
            audit_item(), meta(articleType="news_analysis"), "2026 기준금리 인상 체크리스트")
        recap, _ = cs.salvage_score(
            audit_item(), meta(articleType="news_analysis"), "[1편] 김부장 첫인상 리뷰")
        assert recap < plain

    @pytest.mark.parametrize("title", [
        "사랑이 온다 등장인물 관계도", "김부장 9화 리뷰", "수현 근황과 최근 작품",
        "재벌X형사2 결말 총평", "드라마 출연진 총정리",
    ])
    def test_episodic_titles_detected(self, title):
        assert cs._EPISODIC_TITLE.search(title), title

    @pytest.mark.parametrize("title", [
        "2026 종부세 개편 1주택자 절세법", "전세값 상승기 계약 전 체크리스트",
        "채권 투자 5:4:1 포트폴리오 전략", "제주도 렌터카 보험 옵션 고르는 법",
    ])
    def test_informational_titles_not_flagged_as_episodic(self, title):
        assert not cs._EPISODIC_TITLE.search(title), title

    def test_no_double_penalty_for_episodic(self):
        """articleType과 제목이 둘 다 회차 리뷰여도 감점은 한 번뿐입니다."""
        type_only, _ = cs.salvage_score(
            audit_item(), meta(articleType="drama_review"), "무난한 제목")
        both, _ = cs.salvage_score(
            audit_item(), meta(articleType="drama_review"), "김부장 9화 리뷰")
        assert type_only == both

    def test_unknown_metadata_scores_below_verified_equivalent(self):
        """분량을 모르는 옛 글이 검증된 긴 가이드를 이기면 안 됩니다."""
        unknown, why = cs.salvage_score(
            audit_item(severity="medium", body_hit_count=1), {}, "무난한 제목")
        verified, _ = cs.salvage_score(
            audit_item(severity="high", body_hit_count=2),
            meta(wordCount=4600, articleType="investment"), "무난한 제목")
        assert unknown < verified
        assert any("미상" in w for w in why), why

    def test_reasons_are_always_given(self):
        """점수만 있고 이유가 없으면 사람이 계획을 검수할 수 없습니다."""
        _, why = cs.salvage_score(audit_item(), meta(), "무난한 제목")
        assert why and all(w.strip() for w in why)

    def test_missing_fields_do_not_crash(self):
        score, why = cs.salvage_score({}, {}, "")
        assert isinstance(score, int) and isinstance(why, list)


# ──────────────────────────────────────────────────────────────
# 계획 — 분류가 새지 않는가
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def planned(tmp_path, monkeypatch):
    """작은 가짜 사이트로 계획을 세웁니다."""
    items, reg = [], []
    for i in range(12):
        url = f"https://ex.com/{i}.html"
        items.append(audit_item(
            title=f"금융 가이드 {i}", url=url,
            severity="medium" if i < 6 else "critical",
            body_hit_count=1 if i < 6 else 9))
        reg.append({**meta(), "blogUrl": url, "wordCount": 4600 - i * 300})
    # 감사를 통과한 깨끗한 글 2편
    for i in range(2):
        reg.append({**meta(), "blogUrl": f"https://ex.com/clean{i}.html"})

    audit_path = tmp_path / "experience_audit.json"
    audit_path.write_text(json.dumps(
        {"auditedAt": "2026-09-12T16:07:00+00:00", "scanned": 20,
         "flagged": len(items), "items": items}, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "post_registry.json").write_text(
        json.dumps(reg, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(cs, "_DOCS_DATA", str(tmp_path))
    monkeypatch.setattr(cs, "AUDIT_PATH", str(audit_path))
    monkeypatch.setattr(cs, "PLAN_PATH", str(tmp_path / "curation_plan.json"))
    return cs.build_plan(keep_per_blog=6, min_score=0), tmp_path, items


class TestBuildPlan:

    def test_every_flagged_post_is_classified_exactly_once(self, planned):
        """가장 중요한 방어선 — 새는 글은 조작 상태로 계속 공개됩니다."""
        rep, _, items = planned
        urls = [i["url"] for i in rep["rewrite"]] + [i["url"] for i in rep["unpublish"]]
        assert sorted(urls) == sorted(i["url"] for i in items)
        assert len(urls) == len(set(urls)), "같은 글이 두 갈래에 들어갔습니다"

    def test_clean_posts_count_against_the_quota(self, planned):
        """감사 통과 글도 공개 글이므로 정원에서 빼야 합니다."""
        rep, _, _ = planned
        assert rep["cleanByBlog"]["블로그A"] == 2
        assert len(rep["rewrite"]) == 6 - 2

    def test_rewrite_holds_the_higher_scores(self, planned):
        rep, _, _ = planned
        assert min(i["score"] for i in rep["rewrite"]) >= \
               max(i["score"] for i in rep["unpublish"])

    def test_untracked_clean_posts_are_reported(self, planned):
        """레지스트리에 없는 옛 글 때문에 최종 편수를 과소 보고하면 안 됩니다."""
        rep, _, _ = planned
        c = rep["counts"]
        assert c["cleanTotal"] == 20 - 12
        assert c["cleanUntracked"] == c["cleanTotal"] - c["clean"]

    def test_plan_is_written_to_disk(self, planned):
        rep, tmp_path, _ = planned
        saved = json.loads((tmp_path / "curation_plan.json").read_text(encoding="utf-8"))
        assert saved["counts"] == rep["counts"]

    def test_empty_audit_returns_nothing(self, tmp_path, monkeypatch):
        p = tmp_path / "experience_audit.json"
        p.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(cs, "AUDIT_PATH", str(p))
        assert cs.build_plan() == {}


class TestMinScoreFloor:

    def test_floor_leaves_seats_empty_rather_than_filling_with_junk(
            self, tmp_path, monkeypatch):
        items, reg = [], []
        for i in range(10):
            url = f"https://ex.com/{i}.html"
            items.append(audit_item(title=f"김부장 {i}화 리뷰", url=url,
                                    severity="critical", body_hit_count=12))
            reg.append({**meta(), "blogUrl": url, "wordCount": 2200,
                        "articleType": "drama_review"})
        p = tmp_path / "experience_audit.json"
        p.write_text(json.dumps({"scanned": 10, "flagged": 10, "items": items},
                                ensure_ascii=False), encoding="utf-8")
        (tmp_path / "post_registry.json").write_text(
            json.dumps(reg, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(cs, "_DOCS_DATA", str(tmp_path))
        monkeypatch.setattr(cs, "AUDIT_PATH", str(p))
        monkeypatch.setattr(cs, "PLAN_PATH", str(tmp_path / "plan.json"))

        rep = cs.build_plan(keep_per_blog=8, min_score=40)
        assert rep["rewrite"] == [], "기준 미달인데 정원을 채웠습니다"
        assert len(rep["unpublish"]) == 10
        assert rep["shortfall"]["블로그A"] == 8, "빈 정원을 보고하지 않았습니다"


# ──────────────────────────────────────────────────────────────
# 실행 — dry-run이 정말 아무것도 안 바꾸는가
# ──────────────────────────────────────────────────────────────

class TestApplyUnpublish:

    @pytest.fixture(autouse=True)
    def _stub_blogger(self, monkeypatch):
        self.posted = []
        monkeypatch.setitem(
            sys.modules, "blogger_uploader",
            type(sys)("blogger_uploader"))
        sys.modules["blogger_uploader"]._get_access_token = lambda cfg: "tok"
        monkeypatch.setitem(sys.modules, "config", type(sys)("config"))
        sys.modules["config"].get_blog_configs = lambda: [
            {"id": "blog1", "name": "블로그A", "blog_id": "111"}]
        monkeypatch.setattr(cs, "_post_id_index",
                            lambda cfg, tok: {"https://ex.com/a.html": "p1",
                                              "https://ex.com/b.html": "p2"})
        monkeypatch.setattr(cs.requests, "post",
                            lambda *a, **k: self.posted.append(a) or _ok())
        monkeypatch.setattr(cs.time, "sleep", lambda s: None)

    def _plan(self, n=2):
        urls = ["https://ex.com/a.html", "https://ex.com/b.html"]
        return {"unpublish": [
            {"url": u, "title": "t", "blogId": "blog1", "severity": "critical",
             "score": -10} for u in urls[:n]]}

    def test_dry_run_sends_no_request(self):
        res = cs.apply_unpublish(self._plan(), dry_run=True)
        assert self.posted == [], "dry-run인데 요청을 보냈습니다"
        assert res["unpublished"] == 2 and res["dryRun"] is True

    def test_apply_sends_one_revert_per_post(self):
        res = cs.apply_unpublish(self._plan(), dry_run=False)
        assert len(self.posted) == 2
        assert all("/revert" in a[0] for a in self.posted)
        assert res["unpublished"] == 2 and res["failed"] == 0

    def test_limit_stops_early(self):
        res = cs.apply_unpublish(self._plan(), limit=1, dry_run=False)
        assert len(self.posted) == 1 and res["unpublished"] == 1

    def test_missing_post_id_is_skipped_not_failed(self, monkeypatch):
        """이미 내려간 글은 실패가 아닙니다 — 재실행이 안전해야 합니다."""
        monkeypatch.setattr(cs, "_post_id_index", lambda cfg, tok: {})
        res = cs.apply_unpublish(self._plan(), dry_run=False)
        assert self.posted == []
        assert res["unpublished"] == 0 and res["failed"] == 0


class _ok:
    status_code = 200
    text = "{}"
