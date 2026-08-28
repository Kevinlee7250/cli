"""오류를 빈 값으로 바꿔 "할 일 없음"처럼 보이게 만들지 않는지 검사합니다.

이번 세션에서 반복해 나온 형태입니다. except가 빈 목록을 돌려주면 호출부는
"대상이 없다"로 읽고, 도구는 아무것도 안 하면서 성공으로 끝납니다.
schedule_manager가 그랬고(빈 스케줄), image_audit이 그랬고(잘린 목록),
여기 모듈들도 같은 모양이었습니다.

"안 보여서 0"과 "없어서 0"이 구분되지 않는 것이 문제의 핵심이라,
최소한 로그로는 드러나야 합니다.
"""

import ast
import os

import pytest

_SRC = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

# (파일, 함수) — 실패가 곧 "대상 0건"으로 읽히는 자리
_WATCHED = [
    ("comment_manager.py", "_load_published_posts"),
    ("comment_manager.py", "_queue_comment"),
    ("post_lifecycle.py", None),          # GSC 질의 조회
    ("manage_post.py", None),
]


def _handlers(path, func_name=None):
    src = open(os.path.join(_SRC, path), encoding="utf-8").read()
    tree = ast.parse(src)
    scope = tree
    if func_name:
        scope = next(n for n in ast.walk(tree)
                     if isinstance(n, ast.FunctionDef) and n.name == func_name)
    out = []
    for n in ast.walk(scope):
        if isinstance(n, ast.ExceptHandler):
            out.append((n, ast.get_source_segment(src, n) or ""))
    return out


@pytest.mark.parametrize("path,func", [w for w in _WATCHED if w[1]],
                         ids=lambda x: x if isinstance(x, str) else "")
def test_watched_handlers_log_their_failure(path, func):
    for node, body in _handlers(path, func):
        assert "logger" in body, (
            f"{path}:{func} 줄 {node.lineno} — 실패를 조용히 삼킵니다. "
            "빈 값으로 바꾸더라도 왜 비었는지는 남겨야 합니다"
        )


def test_pending_comment_queue_is_not_silently_wiped():
    """파싱 실패 시 그대로 덮어쓰면 큐에 쌓인 댓글이 사라집니다."""
    src = open(os.path.join(_SRC, "comment_manager.py"), encoding="utf-8").read()
    fn = next(n for n in ast.parse(src).body
              if isinstance(n, ast.FunctionDef) and n.name == "_queue_comment")
    body = ast.get_source_segment(src, fn)
    assert "corrupt" in body, (
        "손상된 대기 댓글 파일을 백업하지 않고 덮어씁니다 — 최대 200건이 사라집니다"
    )
    assert "logger.error" in body


def test_gsc_query_failure_is_distinguishable_from_no_data():
    src = open(os.path.join(_SRC, "post_lifecycle.py"), encoding="utf-8").read()
    assert "성과 0으로 처리" in src, (
        "GSC 조회 실패와 '노출 없음'이 구분되지 않으면, 실패한 글이 저성과로 "
        "집계돼 삭제 대상이 될 수 있습니다"
    )
