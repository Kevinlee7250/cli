"""도입부 후킹 실험(content_category) 태그가 등록·집계 파이프라인 전체에
끊기지 않고 전달되는지 확인하는 회귀 테스트.

실행: cd blog-automation && python -m pytest tests/test_content_category_tracking.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_register_post_carries_content_category(monkeypatch, tmp_path):
    import post_manager as pm

    registry_file = tmp_path / "post_registry.json"
    monkeypatch.setattr(pm, "REGISTRY_FILE", str(registry_file))

    post_data = {"keyword": "ETF 월배당 포트폴리오", "title": "제목", "content_category": "finance"}
    post_manager_id = pm.register_post(post_data, pm.Status.PUBLISHED, blog_config={"id": "blog3", "name": "금융NEWS"})

    registry = pm.load_registry()
    entry = next(e for e in registry if e["post_id"] == post_manager_id)
    assert entry["contentCategory"] == "finance"


def test_log_run_carries_content_category(monkeypatch, tmp_path):
    import dashboard_exporter as de

    history_file = tmp_path / "run_history.json"
    monkeypatch.setattr(de, "HISTORY_FILE", str(history_file))

    results = [{
        "title": "손흥민 결승골 경기 결과",
        "keyword": "손흥민 결승골",
        "content_category": "sports",
        "word_count": 3000,
        "images_inserted": 2,
    }]
    de.log_run(keywords=["손흥민 결승골"], results=results, blogger_uploaded=1, errors=0,
               blog_config={"id": "blog2", "name": "HOGU"})

    history = de._load_history()
    assert history[0]["posts"][0]["contentCategory"] == "sports"
    assert history[0]["outcome"] == "published"


def test_log_run_marks_quality_hold_separately_from_failure(monkeypatch, tmp_path):
    import dashboard_exporter as de

    monkeypatch.setattr(de, "HISTORY_FILE", str(tmp_path / "run_history.json"))
    de.log_run(
        keywords=["금리"],
        results=[{"title": "보류된 글", "keyword": "금리", "status": "pending",
                  "word_count": 1200}],
        blogger_uploaded=0,
        errors=0,
        blog_config={"id": "blog3", "name": "금융NEWS"},
    )
    de.log_run(
        keywords=["금리"],
        results=[],
        blogger_uploaded=0,
        errors=1,
        blog_config={"id": "blog3", "name": "금융NEWS"},
    )
    history = de._load_history()
    by_outcome = {h["outcome"] for h in history}
    assert by_outcome == {"held", "failed"}
    held = next(h for h in history if h["outcome"] == "held")
    assert held["pendingReview"] == 1 and held["errors"] == 0
