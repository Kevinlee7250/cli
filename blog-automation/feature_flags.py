"""기능 on/off 스위치.

기능을 삭제하지 않고 잠시 꺼두기 위한 곳입니다. 코드를 지웠다가 나중에
되살리면 그 사이 바뀐 부분과 어긋나므로, 코드는 그대로 두고 실행만 막습니다.

켜고 끄는 법
────────────
1. `feature_flags.json`에서 값을 true/false로 바꾸고 커밋 — 기본 방법
2. 환경변수 `FEATURE_<대문자 이름>=true|false` — 그 실행에서만 덮어씀
   (예: `FEATURE_COMMENT_AUTOMATION=true python comment_manager.py --seed`)

정의되지 않은 플래그는 켜진 것으로 봅니다. 새 기능이 파일에 이름을 적지
않았다고 조용히 죽는 일이 없어야 하기 때문입니다.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

FLAGS_PATH = os.path.join(os.path.dirname(__file__), "feature_flags.json")

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def load_flags(path: str = FLAGS_PATH) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def is_enabled(name: str, path: str = FLAGS_PATH) -> bool:
    """기능이 켜져 있는지. 환경변수가 파일보다 우선합니다."""
    env = os.getenv(f"FEATURE_{name.upper()}")
    if env is not None:
        low = env.strip().lower()
        if low in _TRUE:
            return True
        if low in _FALSE:
            return False
    value = load_flags(path).get(name)
    return True if value is None else bool(value)


def require(name: str, path: str = FLAGS_PATH) -> bool:
    """꺼져 있으면 이유를 로그로 남기고 False. CLI 진입점에서 씁니다."""
    if is_enabled(name, path):
        return True
    logger.info(
        f"'{name}' 기능이 꺼져 있어 실행하지 않습니다 — "
        f"다시 켜려면 feature_flags.json에서 \"{name}\": true 로 바꾸거나 "
        f"FEATURE_{name.upper()}=true 로 실행하세요"
    )
    return False


def main() -> int:
    """워크플로가 `python feature_flags.py <이름>`으로 상태를 묻습니다."""
    import sys
    if len(sys.argv) < 2:
        print(json.dumps(load_flags(), ensure_ascii=False, indent=2))
        return 0
    print("true" if is_enabled(sys.argv[1]) else "false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
