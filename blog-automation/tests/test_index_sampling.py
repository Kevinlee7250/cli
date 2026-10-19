"""색인 검사 대상을 어떻게 고르는가.

2026-10-19: 발행을 2주 더 지켜보기로 했는데, 그 전에 관찰 자체가 망가져
있던 것을 고쳤습니다. 검사 창이 고정 20건이고 세 블로그를 한 묶음으로
놓고 최근순으로 잘라서, 가장 많이 발행하는 블로그가 창을 거의 다 차지했고
애드센스 심사 대상인 blog1 글은 표본에서 빠졌습니다. 직접 다녀와서 쓴
삼양 글의 색인 상태를 보려던 실험이 이렇게 묻혔습니다.

여기 있는 시험은 두 가지를 지킵니다.
1. 블로그마다 검사 몫이 돌아간다 (발행량이 적어도 표본에 남는다)
2. 관찰 목록에 적은 글은 몫과 무관하게 항상 검사한다
"""

import json
import os
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import gsc_indexing as gi  # noqa: E402

REPO_ROOT = os.path.dirname(BASE_DIR)


def _posts(blog: str, n: int, start: int = 0) -> list[dict]:
    """같은 블로그의 글 n편. 날짜는 최신순으로 내려갑니다."""
    return [
        {"blog": blog,
         "url": f"https://{blog}.example.com/p{start + i}.html",
         "title": f"{blog} 글 {start + i}",
         "published_at": f"2026-10-{30 - (start + i) % 28:02d}"}
        for i in range(n)
    ]


def _by_blog(picked: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for p in picked:
        out[p["blog"]] = out.get(p["blog"], 0) + 1
    return out


# ── 블로그별 몫 나누기 ───────────────────────────────────────────────────────

def test_몫이_블로그마다_고르게_나뉜다():
    items = _posts("blog1", 30) + _posts("blog2", 50) + _posts("blog3", 90)
    picked = gi._allocate_by_blog(items, 45)
    assert len(picked) == 45
    assert _by_blog(picked) == {"blog1": 15, "blog2": 15, "blog3": 15}


def test_발행량_많은_블로그가_창을_독점하지_못한다():
    """이번에 고친 실제 증상입니다.

    blog3 가 90편, blog1 이 30편일 때 최근순으로 20건을 자르면 blog3 글만
    담겼습니다. 블로그별로 나누면 blog1 도 반드시 남습니다.
    """
    items = _posts("blog1", 30) + _posts("blog3", 90)
    picked = gi._allocate_by_blog(items, 20)
    counts = _by_blog(picked)
    assert counts.get("blog1", 0) >= 10, f"blog1 이 또 밀려났습니다: {counts}"


def test_글이_적은_블로그가_남긴_자리는_다른_블로그가_쓴다():
    """blog1 에 2편뿐이면 몫 15를 다 쓸 수 없습니다. 창을 비우지 않습니다."""
    items = _posts("blog1", 2) + _posts("blog2", 50) + _posts("blog3", 90)
    picked = gi._allocate_by_blog(items, 45)
    assert len(picked) == 45
    counts = _by_blog(picked)
    assert counts["blog1"] == 2
    assert counts["blog2"] + counts["blog3"] == 43


def test_글이_몫보다_적으면_있는_만큼만():
    items = _posts("blog1", 3) + _posts("blog2", 4)
    picked = gi._allocate_by_blog(items, 45)
    assert len(picked) == 7  # 무한 반복 없이 끝나야 합니다


@pytest.mark.parametrize("limit", [0, -1])
def test_몫이_0이면_아무것도_검사하지_않는다(limit):
    assert gi._allocate_by_blog(_posts("blog1", 10), limit) == []


def test_빈_목록은_빈_결과():
    assert gi._allocate_by_blog([], 20) == []


def test_몫이_블로그_수보다_작아도_넘치지_않는다():
    """limit 2 에 블로그 3개. 블로그마다 1건씩 주면 3건이 되어 창을 넘깁니다."""
    items = _posts("blog1", 5) + _posts("blog2", 5) + _posts("blog3", 5)
    picked = gi._allocate_by_blog(items, 2)
    assert len(picked) == 2


def test_블로그_이름이_없어도_떨어지지_않는다():
    items = [{"url": "https://x.example.com/1.html", "title": "이름 없음"}]
    assert len(gi._allocate_by_blog(items, 5)) == 1


# ── 관찰 목록 ────────────────────────────────────────────────────────────────

@pytest.fixture
def watchlist(tmp_path, monkeypatch):
    """임시 관찰 목록 파일을 쓰는 도구. 실제 파일은 건드리지 않습니다."""
    def _write(payload):
        path = tmp_path / "index_watchlist.json"
        if payload is not None:
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(gi, "WATCHLIST_PATH", str(path))
        return path
    return _write


def test_목록이_없으면_빈_목록(watchlist):
    watchlist(None)  # 파일을 만들지 않습니다
    assert gi.load_watchlist() == []


def test_목록_파일이_깨져도_떨어지지_않는다(tmp_path, monkeypatch):
    path = tmp_path / "index_watchlist.json"
    path.write_text("{ 이건 json 이 아닙니다", encoding="utf-8")
    monkeypatch.setattr(gi, "WATCHLIST_PATH", str(path))
    assert gi.load_watchlist() == []


@pytest.mark.parametrize("payload", [
    {"urls": "문자열 하나"},       # 목록이 아님
    {"urls": None},
    {},                            # urls 키 자체가 없음
    {"urls": [1, 2, None, "  "]},  # 쓸 수 있는 주소가 없음
])
def test_이상한_목록은_무시한다(watchlist, payload):
    watchlist(payload)
    assert gi.load_watchlist() == []


def test_공백은_잘라서_읽는다(watchlist):
    watchlist({"urls": ["  https://a.example.com/1.html  ", "", "  "]})
    assert gi.load_watchlist() == ["https://a.example.com/1.html"]


def test_목록에_적은_글은_앞으로_빠진다(watchlist):
    items = _posts("blog1", 5)
    watchlist({"urls": [items[3]["url"]]})
    pinned, rest = gi._split_watchlist(items)
    assert [p["url"] for p in pinned] == [items[3]["url"]]
    assert len(rest) == 4
    assert items[3]["url"] not in [r["url"] for r in rest]


def test_목록이_비면_전부_나머지로(watchlist):
    items = _posts("blog1", 5)
    watchlist({"urls": []})
    pinned, rest = gi._split_watchlist(items)
    assert pinned == []
    assert rest == items


def test_끝에_붙은_슬래시는_같은_주소로_본다(watchlist):
    items = [{"blog": "blog1", "url": "https://a.example.com/1.html", "title": "ㄱ"}]
    watchlist({"urls": ["https://a.example.com/1.html/"]})
    pinned, _ = gi._split_watchlist(items)
    assert len(pinned) == 1


def test_목록에_있는_글은_창이_좁아도_살아남는다(watchlist, monkeypatch):
    """이번 실험이 묻힌 바로 그 상황입니다.

    blog1 의 오래된 글 하나를 보려는데 새 글이 계속 쌓이는 경우.
    창이 3건뿐이어도 목록에 적힌 글은 들어가야 합니다.
    """
    old = _posts("blog1", 1, start=99)[0]
    old["published_at"] = "2026-01-01"  # 가장 오래된 글
    items = _posts("blog3", 90) + [old]
    watchlist({"urls": [old["url"]]})
    pinned, rest = gi._split_watchlist(items)
    picked = pinned + gi._allocate_by_blog(rest, 3 - len(pinned))
    assert old["url"] in [p["url"] for p in picked]
    assert len(picked) == 3


# ── 실제 설정 파일 점검 ──────────────────────────────────────────────────────

def test_실제_관찰_목록이_읽히는_모양이다():
    """목록 파일을 손으로 고치다 깨뜨리면 조용히 빈 목록이 됩니다.

    load_watchlist 는 일부러 떨어지지 않게 만들어 뒀으므로, 파일이 망가진
    것을 알려줄 곳이 여기뿐입니다.
    """
    if not os.path.exists(gi.WATCHLIST_PATH):
        pytest.skip("관찰 목록 파일이 없습니다 (없어도 정상입니다)")
    with open(gi.WATCHLIST_PATH, encoding="utf-8") as f:
        data = json.load(f)  # 깨졌으면 여기서 실패합니다
    urls = data.get("urls", [])
    assert isinstance(urls, list)
    for u in urls:
        assert isinstance(u, str) and u.startswith("http"), f"주소가 아닙니다: {u!r}"
    assert len(urls) <= 10, (
        f"관찰 목록이 {len(urls)}건입니다 — 길어지면 나머지 글 검사 몫이 "
        "줄어듭니다. 다 본 글은 지우세요"
    )


def test_워크플로_기본_검사량이_블로그_수보다_넉넉하다():
    """2026-10-19: 기본값이 20이던 때 blog1 이 표본에서 빠졌습니다.

    블로그 3개에 블로그당 10건 이상은 되어야 '색인 0건'이 무슨 뜻인지
    말할 수 있습니다. 누군가 기본값을 다시 내리면 여기서 걸립니다.
    """
    path = os.path.join(REPO_ROOT, ".github", "workflows", "gsc-indexing.yml")
    text = open(path, encoding="utf-8").read()
    import re
    defaults = re.findall(r"inspect_count[^}]*?default:\s*'(\d+)'", text, re.S)
    assert defaults, "gsc-indexing.yml 에서 inspect_count 기본값을 찾지 못했습니다"
    assert int(defaults[0]) >= 30, f"기본 검사량이 {defaults[0]}건으로 너무 적습니다"


# ── 몫이 1건일 때 (2026-10-19 에 터진 자리) ──────────────────────────────────

@pytest.mark.parametrize("total,limit", [(5, 1), (2, 1), (90, 1), (100, 2)])
def test_몫이_한두_건이어도_떨어지지_않는다(total, limit):
    """_sample_spread 가 0으로 나누던 자리입니다.

    블로그별로 몫을 나누기 시작하면서 몫이 1이 되는 경우가 생겼습니다.
    전에는 항상 20건으로만 불러서 드러나지 않았습니다.
    """
    picked = gi._sample_spread(_posts("blog1", total), limit)
    assert len(picked) == limit


def test_몫이_1건이면_최신_글을_본다():
    items = _posts("blog1", 5)
    assert gi._sample_spread(items, 1) == [items[0]]
