"""블로그별 조회수가 블로그별 숫자인가.

왜
──
내보내기가 사이트 전체 합계를 세 블로그에 똑같이 복사하고 있었습니다.

    for blog in blogs_export:
        blog["pageviews30d"] = pv30      # 전체 합계

눈에 보이는 결과가 두 가지였습니다.

  · 블로그 카드 세 개가 전부 같은 숫자 (2,821회 ×3)
  · 대시보드는 블로그별 값을 다시 더해 전체를 내므로, 전체 조회수가
    세 배로 부풀었습니다 — 실제 4,160회가 8,463회로 표시

analytics_summary.json의 blogBreakdown에 블로그별 실측이 처음부터
있었습니다. 내보내기가 그걸 버리고 합계를 쓴 것이 문제였습니다.

여기서 지키는 것
────────────────
  1. 블로그마다 자기 숫자가 들어간다
  2. 블로그별 값을 더하면 사이트 전체와 같다 (세 배가 되지 않는다)
  3. 출처가 없는 지표(7일·어제)는 블로그에 지어내 넣지 않는다
  4. 사이트 전체 값은 따로 전달된다 — 더해서 만들 수 없으므로
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dashboard_exporter as de  # noqa: E402

_SUMMARY = {
    "generatedAt": "2026-10-12T05:26:21",
    "bloggerPageviews30d": 4160,
    "bloggerPageviews7d": 1453,
    "bloggerPageviews1d": 0,
    "blogBreakdown": {
        "blog1": {"posts": 37, "pageviews30d": 2360, "gscClicks30d": 0},
        "blog2": {"posts": 34, "pageviews30d": 722, "gscClicks30d": 0},
        "blog3": {"posts": 36, "pageviews30d": 1078, "gscClicks30d": 0},
    },
}


def _export(monkeypatch, tmp_path, summary=_SUMMARY):
    """export_dashboard를 돌리고 blogs.json / analytics.json 을 돌려줍니다."""
    docs = tmp_path / "data"
    docs.mkdir(parents=True)
    monkeypatch.setattr(de, "DOCS_DATA_DIR", str(docs))
    monkeypatch.setattr(de, "_load_analytics_summary", lambda: summary)
    monkeypatch.setattr(de, "_load_history", lambda: [
        {"runAt": "2026-10-08T02:00:00", "date": "2026-10-08", "keywords": [],
         "postsGenerated": 1, "bloggerUploaded": 1, "errors": [],
         "blogId": b, "blogName": b, "posts": [], "earnings": {}}
        for b in ("blog1", "blog2", "blog3")
    ])
    de.export_dashboard()

    def read(name):
        with open(docs / name, encoding="utf-8") as f:
            return json.load(f)
    return read("blogs.json"), read("analytics.json")


# ── 블로그마다 자기 숫자인가 ────────────────────────────────────────────────

def test_each_blog_gets_its_own_pageviews(monkeypatch, tmp_path):
    blogs, _ = _export(monkeypatch, tmp_path)
    got = {b["id"]: b.get("pageviews30d") for b in blogs if "pageviews30d" in b}
    assert got == {"blog1": 2360, "blog2": 722, "blog3": 1078}, (
        f"블로그별 조회수가 blogBreakdown과 다릅니다: {got}"
    )


def test_blogs_do_not_all_show_the_same_number(monkeypatch, tmp_path):
    """세 카드에 같은 숫자가 뜨면 합계를 복사한 것입니다."""
    blogs, _ = _export(monkeypatch, tmp_path)
    vals = [b["pageviews30d"] for b in blogs if "pageviews30d" in b]
    assert len(set(vals)) == len(vals), f"모든 블로그가 같은 값입니다: {vals}"


def test_sum_of_blogs_equals_the_site_total(monkeypatch, tmp_path):
    """대시보드는 블로그별 값을 더해 전체를 냅니다 — 세 배가 되면 안 됩니다."""
    blogs, _ = _export(monkeypatch, tmp_path)
    total = sum(b.get("pageviews30d", 0) for b in blogs)
    assert total == _SUMMARY["bloggerPageviews30d"], (
        f"블로그별 합이 사이트 전체와 다릅니다: {total} != "
        f"{_SUMMARY['bloggerPageviews30d']}"
    )


# ── 없는 값을 지어내지 않는가 ────────────────────────────────────────────────

def test_per_blog_weekly_views_are_not_invented(monkeypatch, tmp_path):
    """7일·어제 조회수는 블로그별 출처가 없습니다."""
    blogs, _ = _export(monkeypatch, tmp_path)
    for b in blogs:
        assert "pageviews7d" not in b, (
            f"{b['id']}에 출처 없는 7일 조회수가 들어갔습니다: {b.get('pageviews7d')}"
        )
        assert "pageviews1d" not in b


def test_site_totals_are_passed_separately(monkeypatch, tmp_path):
    """더해서 만들 수 없으므로 analytics.json으로 와야 합니다."""
    _, an = _export(monkeypatch, tmp_path)
    assert an.get("bloggerPageviews30d") == 4160
    assert an.get("bloggerPageviews7d") == 1453
    assert "bloggerPageviews1d" in an


# ── 데이터가 없을 때 ────────────────────────────────────────────────────────

def test_missing_breakdown_leaves_pageviews_out(monkeypatch, tmp_path):
    """blogBreakdown이 없으면 숫자를 비웁니다 — 합계로 메우지 않습니다."""
    summary = {k: v for k, v in _SUMMARY.items() if k != "blogBreakdown"}
    blogs, an = _export(monkeypatch, tmp_path, summary=summary)
    for b in blogs:
        assert "pageviews30d" not in b, (
            f"{b['id']}에 사이트 합계가 블로그 값으로 들어갔습니다"
        )
    # 전체 값은 그대로 전달돼야 합니다
    assert an.get("bloggerPageviews30d") == 4160


def test_dashboard_does_not_sum_blogs_for_weekly_views():
    """화면 쪽도 같이 고쳐져 있어야 합니다 — 안 그러면 세 배가 그대로입니다."""
    path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))), "docs", "index.html")
    with open(path, encoding="utf-8") as f:
        html = f.read()
    assert "s + (b.pageviews7d || 0)" not in html, (
        "대시보드가 아직 블로그별 7일 조회수를 더하고 있습니다"
    )
    assert "s + (b.pageviews1d || 0)" not in html
    assert "bloggerPageviews7d" in html, (
        "사이트 전체 7일 조회수를 읽는 곳이 없습니다"
    )
