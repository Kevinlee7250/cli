"""소셜 콘텐츠 스위치 — 꺼져 있으면 생성 자체를 하지 않습니다.

지금까지는 SOCIAL_AUTO_PUBLISH=false여도 콘텐츠는 매번 만들어 두고 게시만
건너뛰었습니다. 실제 데이터에서 50건 중 39건이 전부
{"skipped": true, "reason": "SOCIAL_AUTO_PUBLISH=false"} 였고 게시는 0건인데,
생성에 드는 Claude 호출과 356KB는 계속 나갔습니다.

'게시하지 않는다'와 '만들지도 않는다'는 다른 결정이라 스위치를 따로 뒀습니다.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import feature_flags  # noqa: E402


def _flags(tmp_path, data):
    p = tmp_path / "flags.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


def test_social_content_off_is_respected(tmp_path, monkeypatch):
    monkeypatch.delenv("FEATURE_SOCIAL_CONTENT", raising=False)
    path = _flags(tmp_path, {"social_content": False})
    assert feature_flags.is_enabled("social_content", path) is False


def test_social_content_on_is_respected(tmp_path, monkeypatch):
    monkeypatch.delenv("FEATURE_SOCIAL_CONTENT", raising=False)
    path = _flags(tmp_path, {"social_content": True})
    assert feature_flags.is_enabled("social_content", path) is True


def test_shipped_flags_include_social_content():
    """스위치 파일에 항목이 있어야 대시보드에 나옵니다."""
    flags = feature_flags.load_flags()
    assert "social_content" in flags, "feature_flags.json에 social_content가 없습니다"
    assert isinstance(flags["social_content"], bool)


def test_publish_flow_checks_the_flag():
    """main.py가 실제로 스위치를 읽는지 — 아무도 안 읽는 스위치는 장식입니다."""
    path = os.path.join(os.path.dirname(__file__), "..", "main.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    assert '_flag("social_content")' in src, "발행 흐름이 social_content를 확인하지 않습니다"
    # 확인이 생성보다 먼저여야 합니다 — 만들고 나서 버리면 비용은 이미 나갑니다
    check_at = src.index('_flag("social_content")')
    gen_at = src.index("generate_social_content(post_data")
    assert check_at < gen_at, "생성 전에 스위치를 확인해야 합니다"


def test_dashboard_labels_cover_shipped_flags():
    """화면에 이름 없이 raw 키만 뜨는 스위치가 없도록."""
    import re
    dash = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "index.html")
    with open(dash, encoding="utf-8") as f:
        html = f.read()
    block = html[html.index("const FEATURE_LABELS = {"):]
    block = block[:block.index("\n}")]
    labelled = set(re.findall(r"^\s*([a-z_]+):", block, re.M))
    for name in feature_flags.load_flags():
        assert name in labelled, f"{name}에 화면 표시용 이름이 없습니다"


def test_freshness_meta_flag_names_are_real():
    """SOURCE_META가 가리키는 스위치가 실제로 존재해야 합니다.

    이름이 틀리면 연결이 조용히 끊기고, 일부러 끈 기능의 파일이 다시
    빨간 '중단' 경고로 뜹니다 — 진짜 고장과 구분이 안 되는 상태로 돌아갑니다.
    """
    import re
    dash = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "index.html")
    with open(dash, encoding="utf-8") as f:
        html = f.read()
    block = html[html.index("const SOURCE_META = {"):]
    block = block[:block.index("\n}")]
    referenced = set(re.findall(r"\[\s*'[^']*',\s*\d+\s*,\s*'([a-z_]+)'\s*\]", block))
    known = set(feature_flags.load_flags())
    assert referenced, "스위치와 연결된 항목이 하나도 없습니다 — 연결이 사라졌는지 확인하세요"
    unknown = referenced - known
    assert not unknown, f"SOURCE_META가 없는 스위치를 가리킵니다: {unknown}"


def test_social_json_is_linked_to_its_flag():
    """소셜 파일이 스위치와 이어져 있어야 꺼졌을 때 오경보가 안 납니다."""
    dash = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "index.html")
    with open(dash, encoding="utf-8") as f:
        html = f.read()
    assert "'social.json':             ['소셜 콘텐츠', 24, 'social_content']" in html
