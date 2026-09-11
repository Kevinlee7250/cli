#!/usr/bin/env python3
"""Claude Desktop에 이 저장소용 MCP 서버 설정을 병합한다.

기존 claude_desktop_config.json을 덮어쓰지 않고 mcpServers 항목만 병합하며,
변경 전 항상 백업을 남긴다.

사용법:
    python setup_claude_desktop.py --dry-run
    python setup_claude_desktop.py --github-token ghp_xxx
    python setup_claude_desktop.py --servers filesystem,git,fetch
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
EXAMPLE = HERE / "claude_desktop_config.example.json"

REPO_PLACEHOLDER = "__REPO_PATH__"
TOKEN_PLACEHOLDER = "__GITHUB_TOKEN__"

# 각 서버가 실제로 필요로 하는 실행 파일
REQUIRED_COMMAND = {
    "filesystem": "npx",
    "memory": "npx",
    "sequential-thinking": "npx",
    "git": "uvx",
    "fetch": "uvx",
    "github": "docker",
}


def config_path() -> Path:
    """OS별 Claude Desktop 설정 파일 경로."""
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if system == "Windows":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "Claude" / "claude_desktop_config.json"
    # Linux
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def load_json(path: Path) -> dict:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        sys.exit(
            f"[!] 기존 설정 파일이 올바른 JSON이 아닙니다: {path}\n"
            f"    {exc}\n"
            f"    파일을 고치거나 옮긴 뒤 다시 실행하세요."
        )
    if not isinstance(data, dict):
        sys.exit(f"[!] 설정 파일의 최상위가 객체가 아닙니다: {path}")
    return data


def render_template(github_token: str | None) -> dict:
    raw = EXAMPLE.read_text(encoding="utf-8")
    raw = raw.replace(REPO_PLACEHOLDER, str(REPO_ROOT))
    template = json.loads(raw)
    servers = template.get("mcpServers", {})

    if github_token:
        servers["github"]["env"]["GITHUB_PERSONAL_ACCESS_TOKEN"] = github_token
    return servers


def check_prerequisites(names: list[str]) -> list[str]:
    """실행 파일이 없는 서버 이름 목록을 돌려준다."""
    missing = []
    for name in names:
        cmd = REQUIRED_COMMAND.get(name)
        if cmd and shutil.which(cmd) is None:
            missing.append(f"{name} (필요: {cmd})")
    return missing


def backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = path.with_name(f"{path.stem}.{stamp}.bak{path.suffix}")
    shutil.copy2(path, dest)
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Claude Desktop MCP 서버 설정을 병합합니다.",
    )
    parser.add_argument(
        "--github-token",
        default=os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN"),
        help="GitHub PAT. 생략하면 환경변수 GITHUB_PERSONAL_ACCESS_TOKEN을 사용합니다.",
    )
    parser.add_argument(
        "--servers",
        help="쉼표로 구분한 설치 대상 서버. 생략하면 전부 설치합니다.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="설정 파일 경로를 직접 지정합니다.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="같은 이름의 기존 서버 설정을 덮어씁니다.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="파일을 쓰지 않고 결과만 출력합니다.",
    )
    args = parser.parse_args()

    if not EXAMPLE.exists():
        sys.exit(f"[!] 템플릿을 찾을 수 없습니다: {EXAMPLE}")

    target = args.config or config_path()
    servers = render_template(args.github_token)

    if args.servers:
        wanted = [s.strip() for s in args.servers.split(",") if s.strip()]
        unknown = [s for s in wanted if s not in servers]
        if unknown:
            sys.exit(
                f"[!] 알 수 없는 서버: {', '.join(unknown)}\n"
                f"    사용 가능: {', '.join(servers)}"
            )
        servers = {k: v for k, v in servers.items() if k in wanted}

    if "github" in servers:
        token = servers["github"]["env"]["GITHUB_PERSONAL_ACCESS_TOKEN"]
        if token == TOKEN_PLACEHOLDER:
            print(
                "[i] GitHub 토큰이 없어 github 서버는 건너뜁니다.\n"
                "    --github-token 옵션이나 GITHUB_PERSONAL_ACCESS_TOKEN 환경변수로 지정하세요."
            )
            del servers["github"]

    if not servers:
        sys.exit("[!] 설치할 서버가 없습니다.")

    missing = check_prerequisites(list(servers))
    if missing:
        print("[i] 아래 실행 파일이 PATH에 없습니다. 해당 서버는 Claude Desktop에서 연결에 실패합니다:")
        for item in missing:
            print(f"    - {item}")

    config = load_json(target)
    existing = config.get("mcpServers")
    if existing is None:
        existing = {}
    elif not isinstance(existing, dict):
        sys.exit(f"[!] 기존 mcpServers 항목이 객체가 아닙니다: {target}")

    added, skipped, replaced = [], [], []
    for name, spec in servers.items():
        if name in existing and not args.force:
            skipped.append(name)
            continue
        if name in existing:
            replaced.append(name)
        else:
            added.append(name)
        existing[name] = spec

    config["mcpServers"] = existing

    print(f"\n설정 파일 : {target}")
    print(f"저장소    : {REPO_ROOT}")
    if added:
        print(f"추가      : {', '.join(added)}")
    if replaced:
        print(f"교체      : {', '.join(replaced)}")
    if skipped:
        print(f"유지      : {', '.join(skipped)}  (덮어쓰려면 --force)")

    if args.dry_run:
        print("\n--- dry-run: 아래 내용이 기록될 예정입니다 ---")
        print(json.dumps(config, indent=2, ensure_ascii=False))
        return 0

    if not added and not replaced:
        print("\n변경할 내용이 없습니다.")
        return 0

    saved = backup(target)
    if saved:
        print(f"백업      : {saved}")

    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print("\n완료. Claude Desktop을 완전히 종료한 뒤 다시 실행하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
