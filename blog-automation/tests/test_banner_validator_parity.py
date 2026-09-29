# -*- coding: utf-8 -*-
"""대시보드(JS)와 발행(Python)의 배너 검사 규칙이 같은지 확인합니다.

같은 규칙을 두 언어로 적어 두었습니다. 대시보드는 저장 전에 걸러 주기
위해, 파이썬은 발행 직전 최종 판정을 위해서입니다. 한쪽만 고치면
"대시보드에서는 저장됐는데 글에는 안 들어가는" 상태가 되고, 원인을
찾기가 아주 어렵습니다. 그래서 같은 입력에 같은 답을 내는지 봅니다.

node가 없는 환경에서는 건너뜁니다.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import coupang_affiliate as ca  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_INDEX = os.path.join(_ROOT, "docs", "index.html")

CASES = [
    ('<iframe src="https://ads-partners.coupang.com/widgets.html?id=1"></iframe>', True),
    ('<script src="https://ads-partners.coupang.com/g.js"></script>'
     '<script>new PartnersCoupang.G({"id":1});</script>', True),
    ('<a href="https://link.coupang.com/a/x"><img src="https://image6.coupangcdn.com/a.jpg"></a>', True),
    ('<iframe src="//ads-partners.coupang.com/widgets.html?id=1"></iframe>', True),
    ('<iframe src="https://evil.example.com/x.html"></iframe>', False),
    ('<iframe src="https://ads-partners.coupang.com.evil.kr/x.html"></iframe>', False),
    ('<div onclick="alert(1)"><img src="https://image6.coupangcdn.com/a.jpg"></div>', False),
    ('<form action="https://link.coupang.com/a/x"></form>', False),
    ('<script>fetch("https://evil.example.com")</script>', False),
    ('<script>new PartnersCoupang.G({});document.write("x")</script>', False),
    ('<p>여기 배너 넣어주세요</p>', False),
    ('', False),
]


def _extract_js() -> str:
    """index.html에서 검사에 필요한 함수들만 뽑아 옵니다."""
    html = open(_INDEX, encoding="utf-8").read()
    wanted = ["AFF_ALLOWED_HOSTS", "AFF_ALLOWED_TAGS", "AFF_SCRIPT_DENY"]
    out = []
    for name in wanted:
        m = re.search(rf"^const {name} = .*?(?=\n(?:const|function)\s)", html, re.S | re.M)
        assert m, f"{name}를 index.html에서 찾지 못했습니다"
        out.append(m.group(0))
    for fn in ["affHostAllowed", "validateBannerHtml"]:
        m = re.search(rf"^function {fn}\(.*?\n\}}", html, re.S | re.M)
        assert m, f"{fn}을 index.html에서 찾지 못했습니다"
        out.append(m.group(0))
    return "\n\n".join(out)


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_js_and_python_agree():
    import json

    js = _extract_js() + "\n" + (
        "const CASES = " + json.dumps([c[0] for c in CASES], ensure_ascii=False) + ";\n"
        "console.log(JSON.stringify(CASES.map(c => validateBannerHtml(c)[0])));\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False,
                                     encoding="utf-8") as f:
        f.write(js)
        path = f.name
    try:
        r = subprocess.run([shutil.which("node"), path], capture_output=True,
                           text=True, encoding="utf-8", timeout=30)
    finally:
        os.unlink(path)

    assert r.returncode == 0, f"node 실행 실패: {r.stderr[:500]}"
    js_verdicts = json.loads(r.stdout.strip().splitlines()[-1])
    py_verdicts = [ca.validate_banner_html(c)[0] for c, _ in CASES]
    expected = [want for _, want in CASES]

    mismatches = [
        (CASES[i][0][:60], expected[i], py_verdicts[i], js_verdicts[i])
        for i in range(len(CASES))
        if not (expected[i] == py_verdicts[i] == js_verdicts[i])
    ]
    assert not mismatches, "규칙이 어긋납니다 (입력, 기대, 파이썬, JS):\n" + "\n".join(
        f"  {m}" for m in mismatches
    )


def test_python_side_matches_expectations():
    """node가 없어도 파이썬 쪽 기대값은 항상 검사합니다."""
    for html, want in CASES:
        got = ca.validate_banner_html(html)[0]
        assert got is want, f"{html[:60]!r} → {got}, 기대 {want}"
