"""posts.json 재생성 시 분석 필드가 지워지던 문제 회귀 테스트 (2026-08-18 점검).

blog_analytics는 주 1회 등급을 붙이는데, 발행은 하루 3회 돌면서 posts.json을
실행 이력에서 통째로 다시 만듭니다. 그때 등급을 옮겨 담지 않아 103개 포스트
전부 등급이 사라져 있었습니다.

실행: cd blog-automation && python -m pytest tests/test_analytics_persistence.py -v
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _setup(tmp_path, monkeypatch, history, existing_posts=None, archive=None):
    import dashboard_exporter as de
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(de, "DOCS_DATA_DIR", str(data_dir))
    monkeypatch.setattr(de, "_load_history", lambda: history)
    if existing_posts is not None:
        (data_dir / "posts.json").write_text(
            json.dumps(existing_posts, ensure_ascii=False), encoding="utf-8")
    if archive is not None:
        (data_dir / "posts_archive.json").write_text(
            json.dumps(archive, ensure_ascii=False), encoding="utf-8")
    return de, data_dir


def _history(title="테스트 글"):
    return [{
        "runAt": "2026-08-18T10:00:00", "date": "2026-08-18",
        "blogId": "blog1", "blogName": "블로그1",
        "keywords": ["키워드"], "postsGenerated": 1, "errors": [],
        "posts": [{"title": title, "keyword": "키워드", "wordCount": 3000,
                   "blogUrl": "https://a.com/x.html"}],
    }]


def _written_posts(data_dir):
    return json.loads((data_dir / "posts.json").read_text(encoding="utf-8"))


def test_grade_survives_posts_regeneration(tmp_path, monkeypatch):
    de, data_dir = _setup(tmp_path, monkeypatch, _history())
    de.export_dashboard()                      # 1회차: 등급 없음
    posts = _written_posts(data_dir)
    assert "grade" not in posts[0]

    posts[0].update({"grade": "A", "gradeScore": 77,
                     "estimatedPageviews30d": 1205, "estimatedRevenue30d": 1.5})
    (data_dir / "posts.json").write_text(json.dumps(posts, ensure_ascii=False),
                                         encoding="utf-8")

    de.export_dashboard()                      # 2회차: 발행이 다시 덮어씀
    after = _written_posts(data_dir)
    assert after[0]["grade"] == "A"
    assert after[0]["gradeScore"] == 77
    assert after[0]["estimatedPageviews30d"] == 1205


def test_publish_fields_are_still_refreshed(tmp_path, monkeypatch):
    """분석 필드만 이어붙여야 하고, 발행 정보는 최신 이력으로 갱신돼야 함."""
    stale = [{"id": "x", "title": "테스트 글", "wordCount": 1,
              "grade": "C", "gradeScore": 3}]
    de, data_dir = _setup(tmp_path, monkeypatch, _history(), existing_posts=stale)
    de.export_dashboard()
    after = _written_posts(data_dir)
    assert after[0]["wordCount"] == 3000       # 이력 값으로 갱신
    assert "grade" not in after[0]             # id가 달라 이어붙일 대상 아님


def test_analytics_restored_from_archive(tmp_path, monkeypatch):
    """오래된 글은 posts_archive.json으로 밀려나므로 거기서도 복원해야 함."""
    de, data_dir = _setup(tmp_path, monkeypatch, _history())
    de.export_dashboard()
    pid = _written_posts(data_dir)[0]["id"]

    (data_dir / "posts.json").write_text("[]", encoding="utf-8")
    (data_dir / "posts_archive.json").write_text(
        json.dumps([{"id": pid, "grade": "S", "gradeScore": 210}]), encoding="utf-8")

    de.export_dashboard()
    assert _written_posts(data_dir)[0]["grade"] == "S"


def test_first_run_without_previous_file(tmp_path, monkeypatch):
    de, data_dir = _setup(tmp_path, monkeypatch, _history())
    de.export_dashboard()                       # 예외 없이 통과해야 함
    assert len(_written_posts(data_dir)) == 1


def test_corrupt_previous_file_does_not_break_export(tmp_path, monkeypatch):
    """이전 파일이 깨져 있어도 내보내기 자체는 계속돼야 함."""
    de, data_dir = _setup(tmp_path, monkeypatch, _history())
    (data_dir / "posts.json").write_text("{ 깨진 json", encoding="utf-8")
    de.export_dashboard()
    assert len(_written_posts(data_dir)) == 1
