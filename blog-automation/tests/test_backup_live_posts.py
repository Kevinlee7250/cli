"""백업이 '복원에 쓸 수 있는' 상태인지 검사합니다.

빈 본문이 섞인 백업은 백업이 아니라 함정입니다 — 그걸로 복원하면 글이
지워집니다. 그래서 저장 전에도, 복원 전에도 같은 검사를 돌립니다.
"""
import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

import backup_live_posts as mod  # noqa: E402


def _post(**kw):
    base = {"blogId": "blog1", "blog": "테스트", "postId": "1",
            "url": "https://b.com/p.html", "title": "제목",
            "content": "<p>본문</p>", "published": "", "updated": ""}
    base.update(kw)
    return base


def test_good_backup_has_no_problems():
    assert mod.verify({"posts": [_post(), _post(postId="2")]}) == []


def test_empty_backup_is_a_problem():
    assert mod.verify({"posts": []})
    assert mod.verify({})


@pytest.mark.parametrize("field", ["content", "title", "postId"])
def test_missing_field_is_a_problem(field):
    problems = mod.verify({"posts": [_post(**{field: ""})]})
    assert problems, f"{field}가 비었는데 통과시켰습니다"


def test_whitespace_only_content_is_a_problem():
    """공백만 있는 본문으로 복원하면 글이 지워집니다."""
    assert mod.verify({"posts": [_post(content="   \n  ")]})


def test_restore_refuses_a_broken_backup(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"posts": [_post(content="")]}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="온전하지"):
        mod.restore(str(bad), dry_run=True)


def test_restore_dry_run_touches_nothing(tmp_path, monkeypatch):
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"posts": [_post(), _post(postId="2")]}),
                    encoding="utf-8")
    import config
    monkeypatch.setattr(config, "get_blog_configs",
                        lambda: [{"id": "blog1", "blog_id": "X", "name": "테스트"}])

    def _boom(*a, **k):
        raise AssertionError("dry-run인데 네트워크를 호출했습니다")
    monkeypatch.setattr(mod.requests, "patch", _boom)

    res = mod.restore(str(good), dry_run=True)
    assert res == {"restored": 2, "failed": 0, "dryRun": True}


def test_restore_can_target_one_post(tmp_path, monkeypatch):
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"posts": [
        _post(url="https://b.com/a.html"), _post(postId="2", url="https://b.com/b.html"),
    ]}), encoding="utf-8")

    import config
    monkeypatch.setattr(config, "get_blog_configs",
                        lambda: [{"id": "blog1", "blog_id": "X", "name": "테스트"}])

    res = mod.restore(str(good), only_url="https://b.com/b.html/", dry_run=True)
    assert res["restored"] == 1
