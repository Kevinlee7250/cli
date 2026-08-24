"""테스트 공통 격리 설정.

문제: 일부 테스트가 실제 함수를 호출하면서 logs/ 아래 운영 상태 파일
(used_images.json, used_keywords_*.json)에 기록을 남겼음. 이 파일들은
"이 이미지·키워드를 실제로 사용했다"는 기록이라, 테스트 실행만으로
해당 키워드가 30일간 사용 금지로 잠기고 이미지가 중복 회피 대상이 된다.
실제로 세션 내내 테스트를 돌릴 때마다 git 작업 트리가 더러워졌다.

해결: 모든 테스트에서 이 경로들을 임시 디렉터리로 돌려, 테스트가 무엇을
쓰든 저장소 파일에는 닿지 않게 한다.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
def isolate_runtime_state(tmp_path, monkeypatch):
    """운영 상태 파일 경로를 테스트별 임시 경로로 치환합니다."""
    logs = tmp_path / "logs"
    logs.mkdir(exist_ok=True)

    try:
        import image_fetcher
        monkeypatch.setattr(image_fetcher, "_USED_IMAGES_FILE",
                            str(logs / "used_images.json"), raising=False)
    except ImportError:
        pass

    try:
        import keyword_collector as kc
        monkeypatch.setattr(kc, "_USED_KW_FILE", str(logs / "used_keywords.json"), raising=False)
        monkeypatch.setattr(
            kc, "_get_used_kw_file",
            lambda blog_id="": str(
                logs / (f"used_keywords_{blog_id}.json"
                        if blog_id and blog_id not in ("default", "blog1")
                        else "used_keywords.json")
            ),
            raising=False,
        )
    except ImportError:
        pass

    yield
