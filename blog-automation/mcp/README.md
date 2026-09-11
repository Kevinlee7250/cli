# Claude Desktop MCP 연결 설정

이 저장소를 Claude Desktop에서 다룰 수 있도록 **기존 MCP 서버들을 연결**하는 설정이다.
새로 만드는 MCP 서버는 없고, 이미 공개된 서버를 이 저장소에 맞게 묶어둔 것이다.

| 파일 | 용도 |
|------|------|
| `claude_desktop_config.example.json` | Claude Desktop 설정 템플릿 |
| `setup_claude_desktop.py` | 템플릿을 실제 설정 파일에 병합하는 스크립트 |

---

## 1. 준비물

| 서버 | 필요한 실행 파일 | 설치 |
|------|------------------|------|
| filesystem, memory, sequential-thinking | `npx` | [Node.js](https://nodejs.org) 20 이상 |
| git, fetch | `uvx` | [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh \| sh`) |
| github | `docker` | [Docker Desktop](https://www.docker.com/products/docker-desktop/) |

`npx`와 `uvx`는 첫 실행 때 패키지를 자동으로 내려받으므로 미리 설치할 필요는 없다.

---

## 2. 설정 파일 위치

Claude Desktop은 OS마다 다른 경로를 쓴다.

| OS | 경로 |
|----|------|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

---

## 3. 설치

### 스크립트로 설치 (권장)

```bash
cd blog-automation/mcp

# 무엇이 바뀌는지 먼저 확인
python setup_claude_desktop.py --dry-run

# 실제 적용
python setup_claude_desktop.py

# GitHub 서버까지 포함
python setup_claude_desktop.py --github-token ghp_xxxxxxxx

# 원하는 서버만
python setup_claude_desktop.py --servers filesystem,git,fetch
```

스크립트의 동작:

- 저장소 절대경로를 자동으로 넣는다 (`__REPO_PATH__` 치환).
- **기존 설정을 덮어쓰지 않는다.** 이미 있는 이름은 건너뛰며, 바꾸려면 `--force`.
- 파일을 고치기 전 항상 `claude_desktop_config.<날짜>.bak.json` 백업을 남긴다.
- 토큰이 없으면 `github` 서버는 자동으로 빠진다.
- 같은 명령을 다시 실행해도 안전하다 (변경 없으면 아무것도 쓰지 않음).

### 직접 설치

`claude_desktop_config.example.json`을 위 경로에 복사한 뒤 두 자리를 바꾼다.

- `__REPO_PATH__` → 이 저장소의 절대경로 (예: `C:\\Users\\kevin\\cli`)
- `__GITHUB_TOKEN__` → GitHub 개인 액세스 토큰 (안 쓰면 `github` 블록째로 삭제)

> Windows 경로는 JSON에서 역슬래시를 두 번(`\\`) 쓰거나 슬래시(`/`)를 쓴다.

설치 후 **Claude Desktop을 완전히 종료했다가 다시 실행**해야 반영된다.
창만 닫으면 트레이에 남아 있어 설정을 다시 읽지 않는다.

---

## 4. 연결되는 서버

이 저장소(`blog-automation` 중심)에서 실제로 쓸모 있는 것만 골랐다.

| 서버 | 하는 일 | 이 저장소에서 쓰는 이유 |
|------|---------|------------------------|
| **filesystem** | 지정 경로의 파일 읽기·쓰기·검색 | `blog-automation/logs`, 생성된 포스트, 워크플로 파일을 직접 열어볼 수 있다 |
| **git** | 로컬 커밋 이력·diff·검색 | 워크플로와 스크립트 변경 이력을 추적 |
| **fetch** | 웹 페이지를 받아 텍스트로 변환 | `research_collector.py`, `source_validator.py`가 하는 출처 확인을 대화 중에 수행 |
| **github** | 이슈·PR·Actions 조회 및 실행 | 이 저장소 자동화가 전부 GitHub Actions로 돌아간다 |
| **memory** | 대화 간 지식 그래프 유지 | 블로그 주제·시리즈 맥락을 세션 사이에 유지 |
| **sequential-thinking** | 단계적 사고 도구 | 시리즈 기획처럼 여러 단계를 거치는 작업 |

`filesystem`은 설정에 적은 경로 **밖으로는 접근하지 못한다.** 저장소 하나만 열어두는 것이 안전하다.

---

## 5. 동작 확인

Claude Desktop을 다시 켜면 입력창 아래 도구(슬라이더) 아이콘에 서버 목록이 뜬다.
"이 저장소의 워크플로 파일 목록을 보여줘" 같은 요청으로 확인할 수 있다.

로그 위치:

- macOS: `~/Library/Logs/Claude/mcp*.log`
- Windows: `%APPDATA%\Claude\logs\mcp*.log`

---

## 6. 자주 겪는 문제

**서버가 목록에 안 뜬다**
Claude Desktop을 트레이/독에서까지 완전히 종료했는지 확인한다. JSON 문법 오류도 흔한 원인이다.

```bash
python -m json.tool "$HOME/.config/Claude/claude_desktop_config.json"
```

**Windows에서 `npx` 서버만 실패한다**
Claude Desktop 버전에 따라 `npx`를 직접 못 찾는 경우가 있다. 해당 서버의 `command`를 다음처럼 바꾼다.

```json
"command": "cmd",
"args": ["/c", "npx", "-y", "@modelcontextprotocol/server-filesystem", "C:/Users/kevin/cli"]
```

**`uvx` 서버가 실패한다**
설치 후 PATH 반영을 위해 터미널이 아니라 **Claude Desktop 자체를** 재시작해야 한다.

**`github` 서버가 실패한다**
Docker Desktop이 실행 중이어야 한다. 토큰 권한은 `repo`, `workflow`가 필요하다.

---

## 7. 보안

- **토큰을 커밋하지 말 것.** `claude_desktop_config.json`은 저장소 밖(OS 설정 폴더)에 있으므로 기본적으로 안전하지만, 예제 파일에 실제 토큰을 넣고 커밋하지 않도록 주의한다.
- GitHub 토큰은 필요한 최소 권한만 준다. 만료일을 설정하는 것을 권장한다.
- `filesystem` 경로에 홈 디렉터리 전체(`/Users/이름`)를 지정하지 않는다.

---

## 8. 패키지 선택 근거

npm에 있던 일부 공식 서버는 **지원이 중단**되어 쓰지 않았다 (2026-08 기준 npm 레지스트리 확인).

| 예전 패키지 | 상태 | 대체 |
|-------------|------|------|
| `@modelcontextprotocol/server-github` | deprecated | `ghcr.io/github/github-mcp-server` (Docker) |
| `@modelcontextprotocol/server-gdrive` | deprecated | Claude Desktop 내장 Google Drive 커넥터 |
| `@modelcontextprotocol/server-puppeteer` | deprecated | 미사용 |
| `@modelcontextprotocol/server-fetch` | npm에 없음 | PyPI `mcp-server-fetch` (`uvx`) |

Google Drive(`backup_to_drive.py`가 쓰는 곳)는 별도 MCP 서버 대신
Claude Desktop의 **Settings → Connectors**에 있는 내장 커넥터를 쓰는 편이 낫다.
