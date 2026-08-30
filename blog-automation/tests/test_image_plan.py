"""이미지가 글의 그 대목과 맞는가.

왜
──
검색어는 H2 제목과 본문 명사를 기계적으로 조합해 만들었고(_extract_section_
queries), 배치는 순서로만 정했습니다(첫 <p> 뒤, 2·4번째 H2 앞). 그래서

  · 섹션 A용으로 찾은 그림이 섹션 B 앞에 놓였습니다 — 관련성 필터·중복
    제거로 목록이 줄면 순서가 밀립니다
  · alt에 3단어로 줄인 검색어가 그대로 나갔습니다 ('발리 겨울방학',
    '중개형 ISA', '경기도 여름' — 실제 발행 글에서 확인)

글은 그 섹션에서 무엇을 보여 줘야 하는지 알고 있습니다. 이제 생성 프롬프트가
image_plan(heading·subject·search_en·alt)을 함께 내놓고, 검색과 배치가 그것을
따릅니다. 계획이 없거나 깨진 글은 예전 방식으로 돌아갑니다 — 계획이 없다고
이미지가 아예 안 붙으면 안 됩니다.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import content_generator as cg  # noqa: E402
import image_fetcher as imf  # noqa: E402

_CG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "content_generator.py")

_HTML = (
    "<p>도입부입니다.</p>"
    "<h2>패키지 선택이 어려운 이유</h2><p>가</p>"
    "<h2>공항 수속 실제 순서</h2><p>나</p>"
    "<h2>예약 전 체크리스트</h2><p>다</p>"
)


def _img(query, heading="", alt=""):
    img = {"url": "https://cdn.pixabay.com/x.jpg", "title": "t", "search_query": query}
    if heading:
        img["plan_heading"] = heading
    if alt:
        img["plan_alt"] = alt
    return img


def _next_h2_after(content, pos):
    """이미지 뒤에 처음 나오는 H2 제목 — 이미지는 그 섹션 바로 앞에 놓입니다."""
    m = re.search(r"<h2[^>]*>(.*?)</h2>", content[pos:], re.S)
    return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else ""


def _section_of(content, img_pos):
    """그 이미지가 어느 H2 아래 놓였는지."""
    before = content[:img_pos]
    h2s = re.findall(r"<h2[^>]*>(.*?)</h2>", before, re.S)
    return re.sub(r"<[^>]+>", "", h2s[-1]).strip() if h2s else "(도입부)"


# ── 프롬프트 ────────────────────────────────────────────────────────────────

def test_every_generation_schema_asks_for_an_image_plan():
    with open(_CG, encoding="utf-8") as f:
        src = f.read()
    # 스키마마다 붙어 있지 않으면 그 프롬프트로 쓴 글만 조용히 옛 방식이 됩니다
    assert src.count('  "image_plan": [') == src.count('  "meta_description":')


def test_plan_asks_for_the_heading_verbatim():
    with open(_CG, encoding="utf-8") as f:
        src = f.read()
    assert "글자 그대로 같아야" in src
    assert "verbatim from your HTML" in src


# ── 계획 해석 ────────────────────────────────────────────────────────────────

def test_plan_prefers_the_english_search_phrase():
    """무료 이미지 소스 제목이 대부분 영어라, 한국어로 찾으면 번역 추정을 거칩니다."""
    got = cg._plan_queries({"image_plan": [
        {"heading": "H", "subject": "공항 셀프체크인 기계", "search_en": "airport self check-in", "alt": "A"},
    ]})
    assert got == [("airport self check-in", "H", "A")]


def test_plan_falls_back_to_subject_when_no_english():
    got = cg._plan_queries({"image_plan": [{"subject": "공항 셀프체크인", "alt": "A"}]})
    assert got[0][0] == "공항 셀프체크인"


def test_broken_plan_is_ignored_not_fatal():
    for bad in (None, "계획", [], [None, 3, {}], [{"search_en": ""}]):
        assert cg._plan_queries({"image_plan": bad}) == []


def test_plan_is_capped():
    plan = [{"search_en": f"q{i}"} for i in range(9)]
    assert len(cg._plan_queries({"image_plan": plan})) == cg._MAX_IMAGES_PER_POST


# ── 배치 ────────────────────────────────────────────────────────────────────

def test_image_lands_under_its_planned_heading():
    out = imf.inject_images_into_content(
        _HTML, [_img("checklist", "예약 전 체크리스트", "체크리스트 사진")], "키워드")
    # H2 바로 앞에 넣으므로, 이미지 뒤에 처음 나오는 H2가 계획한 그 섹션이어야 합니다
    assert _next_h2_after(out, out.index("<img")) == "예약 전 체크리스트"


def test_two_planned_images_do_not_swap_sections():
    """예전 방식은 순서로 자리를 정해, 목록이 줄면 서로 자리가 바뀌었습니다."""
    out = imf.inject_images_into_content(_HTML, [
        _img("checklist", "예약 전 체크리스트", "체크리스트"),
        _img("airport", "공항 수속 실제 순서", "공항"),
    ], "키워드")
    positions = [m.start() for m in re.finditer(r"<img", out)]
    assert len(positions) == 2
    after = [_next_h2_after(out, p) for p in positions]
    assert after[0] == "공항 수속 실제 순서", f"앞쪽 이미지가 공항 섹션이 아닙니다: {after}"
    assert after[1] == "예약 전 체크리스트"


def test_unknown_heading_falls_back_instead_of_dropping():
    """제목이 안 맞는다고 이미지를 버리면 글에 그림이 사라집니다."""
    out = imf.inject_images_into_content(
        _HTML, [_img("q", "본문에 없는 제목", "대체")], "키워드")
    assert out.count("<img") == 1


def test_post_without_a_plan_still_gets_images():
    out = imf.inject_images_into_content(_HTML, [_img("q1"), _img("q2")], "키워드")
    assert out.count("<img") == 2


# ── alt ─────────────────────────────────────────────────────────────────────

def test_alt_uses_the_planned_text_not_the_truncated_query():
    out = imf.inject_images_into_content(
        _HTML, [_img("bali winter", "예약 전 체크리스트", "체크리스트를 적은 노트")], "발리")
    assert 'alt="체크리스트를 적은 노트"' in out
    assert 'alt="bali winter"' not in out


def test_alt_falls_back_to_query_when_no_plan():
    out = imf.inject_images_into_content(_HTML, [_img("발리 겨울방학")], "발리")
    assert 'alt="발리 겨울방학"' in out
