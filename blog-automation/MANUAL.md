# 블로그 자동화 시스템 사용 설명서

> **버전**: Python 3.11 | **저장소**: kevinlee7250/cli | **브랜치**: claude/blog-automation-system-KAbtE

---

## 목차

1. [시스템 개요](#1-시스템-개요)
2. [동작 구조](#2-동작-구조)
3. [초기 설정](#3-초기-설정)
4. [환경 변수 설명](#4-환경-변수-설명)
5. [실행 방법](#5-실행-방법)
6. [GitHub Actions 자동화](#6-github-actions-자동화)
7. [대시보드 사용법](#7-대시보드-사용법)
8. [Google OAuth 토큰 갱신](#8-google-oauth-토큰-갱신)
9. [트러블슈팅](#9-트러블슈팅)
10. [파일 구조](#10-파일-구조)

---

## 1. 시스템 개요

**오늘의 핫이슈 블로그 자동화 시스템**은 매일 자동으로 트렌드 키워드를 수집하고 Claude AI가 SEO 최적화 블로그 포스트를 생성해 Blogger에 자동 게시하는 시스템입니다.

### 주요 기능

| 기능 | 설명 |
|------|------|
| 트렌드 키워드 수집 | 네이버 DataLab / Google Trends 기반 실시간 인기 키워드 |
| AI 포스트 생성 | Claude Sonnet — SEO 최적화, FAQ, 출처 링크 자동 포함 |
| 이미지 자동 삽입 | 네이버 → DuckDuckGo → Wikimedia Commons 3단계 폴백 |
| AdSense 광고 삽입 | 본문 내 전략적 위치에 6개 광고 슬롯 자동 삽입 |
| Blogger 자동 게시 | Google Blogger API v3로 즉시 게시 또는 임시저장 |
| 구조화 데이터 | Article + FAQPage JSON-LD 스키마 자동 생성 |
| 목차 자동 생성 | H2 섹션 기반 TOC 자동 삽입 |
| 대시보드 | GitHub Pages 정적 대시보드로 실행 현황 모니터링 |

---

## 2. 동작 구조

```
[1] 트렌드 키워드 수집 (keyword_collector.py)
     └─ 네이버 DataLab API → Google Trends RSS → Claude 폴백

[2] SEO 포스트 생성 (content_generator.py)
     └─ Claude Sonnet API → 제목/본문/FAQ/태그/출처 JSON 반환

[3] 이미지 검색 & 삽입 (image_fetcher.py)
     └─ 네이버 이미지 API → DuckDuckGo → Wikimedia Commons

[4] Blogger 업로드 (blogger_uploader.py)
     └─ Google OAuth2 토큰 발급 → Blogger API POST
     └─ 광고 슬롯 6개 + 목차 + 구조화 데이터 + 태그/출처 섹션 조립

[5] 대시보드 업데이트 (dashboard_exporter.py)
     └─ logs/run_history.json 누적 저장
     └─ docs/data/ → posts.json / runs.json / analytics.json / meta.json
```

---

## 3. 초기 설정

### 3-1. 저장소 클론 및 의존성 설치

```bash
git clone https://github.com/kevinlee7250/cli.git
cd cli/blog-automation
pip install -r requirements.txt
```

### 3-2. .env 파일 생성

```bash
cp .env.example .env   # .env.example이 없으면 아래 내용으로 직접 생성
```

`.env` 파일 내용:

```env
# ---- Claude API ----
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxxxxx

# ---- Naver API (이미지 검색) ----
NAVER_CLIENT_ID=xxxxxxxxxxxxxxxx
NAVER_CLIENT_SECRET=xxxxxxxxxx

# ---- Google / Blogger API ----
GOOGLE_CLIENT_ID=xxxxxxxxxxxx-xxxxxxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxxxxxxxxxxxxxxx
GOOGLE_REFRESH_TOKEN=1//xxxxxxxxxxxxxxxxxxxxxxxx
BLOGGER_BLOG_ID=xxxxxxxxxxxxxxxxxxx

# ---- AdSense (선택) ----
ADSENSE_CLIENT_ID=ca-pub-xxxxxxxxxxxxxxxx
ADSENSE_SLOT_IDS=1234567890,0987654321,1122334455

# ---- 실행 설정 ----
POSTS_PER_RUN=3
POST_STATUS=live
BLOG_LANGUAGE=ko
TREND_COUNTRY=KR
LOG_LEVEL=info
LOG_FILE=./logs/automation.log
```

### 3-3. GitHub Secrets 등록 (Actions 실행용)

GitHub 저장소 → **Settings → Secrets and variables → Actions** → New repository secret:

| Secret 이름 | 값 출처 |
|-------------|---------|
| `ANTHROPIC_API_KEY` | Anthropic Console |
| `NAVER_CLIENT_ID` | 네이버 개발자 센터 |
| `NAVER_CLIENT_SECRET` | 네이버 개발자 센터 |
| `GOOGLE_CLIENT_ID` | Google Cloud Console |
| `GOOGLE_CLIENT_SECRET` | Google Cloud Console |
| `GOOGLE_REFRESH_TOKEN` | `get_refresh_token.py` 실행으로 발급 |
| `BLOGGER_BLOG_ID` | Blogger 대시보드 URL에서 확인 |
| `ADSENSE_CLIENT_ID` | AdSense 계정 (선택) |
| `ADSENSE_SLOT_IDS` | AdSense 광고 슬롯 ID 목록 (선택) |

---

## 4. 환경 변수 설명

| 변수 | 필수 | 기본값 | 설명 |
|------|------|--------|------|
| `ANTHROPIC_API_KEY` | ✅ | — | Claude API 키 |
| `GOOGLE_CLIENT_ID` | ✅ | — | Google OAuth 클라이언트 ID |
| `GOOGLE_CLIENT_SECRET` | ✅ | — | Google OAuth 클라이언트 시크릿 |
| `GOOGLE_REFRESH_TOKEN` | ✅ | — | Blogger API 접근용 Refresh Token |
| `BLOGGER_BLOG_ID` | ✅ | — | Blogger 블로그 ID |
| `NAVER_CLIENT_ID` | 권장 | — | 네이버 이미지 검색 API (없으면 DDG 사용) |
| `NAVER_CLIENT_SECRET` | 권장 | — | 네이버 이미지 검색 API |
| `ADSENSE_CLIENT_ID` | 선택 | — | AdSense 퍼블리셔 ID (없으면 광고 미삽입) |
| `ADSENSE_SLOT_IDS` | 선택 | — | 쉼표 구분 광고 슬롯 ID 목록 |
| `POSTS_PER_RUN` | — | `3` | 1회 실행당 생성할 포스트 수 (1~10) |
| `POST_STATUS` | — | `live` | `live` (즉시 게시) / `draft` (임시저장) |
| `BLOG_LANGUAGE` | — | `ko` | `ko` (한국어) / `en` (영어) |
| `TREND_COUNTRY` | — | `KR` | `KR` / `US` / `JP` |
| `LOG_LEVEL` | — | `info` | `debug` / `info` / `warning` / `error` |
| `LOG_FILE` | — | `./logs/automation.log` | 로그 파일 경로 |
| `CLAUDE_MODEL` | — | `claude-sonnet-4-6` | 사용할 Claude 모델 |

---

## 5. 실행 방법

### 5-1. 테스트 모드 (API 키 없이 확인)

```bash
cd blog-automation
python main.py --test
```

- Blogger 업로드 없이 글만 생성
- Claude API 키만 있으면 동작
- 생성된 포스트 제목/글자수/이미지 수 확인 가능

### 5-2. 특정 키워드로 즉시 실행

```bash
python main.py --once --keyword "재테크 방법"
# 여러 키워드 (쉼표 구분)
python main.py --once --keyword "재테크,주식,ETF"
```

### 5-3. 트렌드 자동 수집 후 즉시 실행

```bash
python main.py --once
```

### 5-4. 테스트 모드 + 특정 키워드

```bash
python main.py --test --keyword "주식 투자"
```

### 5-5. 스케줄 모드 (로컬 서버 상시 실행)

```bash
python main.py
# SCHEDULE_CRON 환경 변수 기준으로 매일 자동 실행
# 기본값: 09:00 매일 (0 9 * * *)
```

> **권장**: 로컬 스케줄보다 GitHub Actions를 사용하세요 (무중단, 무료).

---

## 6. GitHub Actions 자동화

### 6-1. 자동 실행 스케줄

`.github/workflows/blog-run.yml`에 정의된 스케줄:

| 실행 시각 | Cron (UTC) | KST |
|-----------|------------|-----|
| 오전 실행 | `0 22 * * *` | 오전 7시 |
| 오후 실행 | `0 10 * * *` | 오후 7시 |

### 6-2. 수동 실행 (workflow_dispatch)

1. **GitHub → Actions → 블로그 자동화 실행** 클릭
2. **Run workflow** 클릭
3. 옵션 설정:

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `keyword` | 키워드 (쉼표 구분, 비워두면 자동 수집) | — |
| `posts_per_run` | 생성할 포스트 수 (1~5) | `3` |
| `mode` | `live` / `draft` / `test` | `live` |

### 6-3. 실행 모드 설명

| 모드 | 동작 |
|------|------|
| `live` | Blogger에 즉시 게시 |
| `draft` | Blogger에 임시저장 (게시 안 함) |
| `test` | 글만 생성, 업로드 없음 (API 키 검증용) |

### 6-4. 실행 결과 확인

- **Actions 탭** → 해당 워크플로우 실행 클릭 → 로그 확인
- **Artifacts** → `automation-logs-{번호}` 다운로드 → 상세 로그 확인
- **대시보드** → `https://kevinlee7250.github.io/cli/` 접속

---

## 7. 대시보드 사용법

**URL**: `https://kevinlee7250.github.io/cli/`

### 7-1. 탭 설명

| 탭 | 내용 |
|----|------|
| 포스트 | 생성된 전체 포스트 목록, 키워드/날짜 필터, CSV 내보내기 |
| 실행 이력 | 날짜별 실행 결과 (생성 수/업로드 수/오류 수) |
| 수익 분석 | AdSense 예상 수익 차트, 카테고리별 분포 |

### 7-2. 포스트 상세 보기

포스트 행 클릭 → 모달창에서 확인 가능:
- 전체 제목 / 키워드 / 생성일
- 본문 미리보기 / 글자 수 / 이미지 수
- FAQ 목록 (5개)
- 출처 링크 목록
- 관련 태그
- Blogger 원문 링크

### 7-3. 필터 및 내보내기

- **키워드 검색**: 제목·키워드 실시간 검색
- **날짜 범위**: 시작일~종료일 필터
- **카테고리**: 금융/건강/기술 등
- **CSV 내보내기**: 포스트 목록 / 실행 이력 엑셀 호환 다운로드

---

## 8. Google OAuth 토큰 갱신

### 언제 필요한가?

- GitHub Actions 로그에 `invalid_grant` 오류 발생 시
- OAuth 앱이 **"테스트"** 상태이면 Refresh Token이 **7일마다 만료**됨
- OAuth 앱을 **"프로덕션"**으로 게시하면 토큰이 만료되지 않음

### 8-1. 토큰 갱신 절차

**방법: Google OAuth Playground 사용**

1. **[OAuth Playground](https://developers.google.com/oauthplayground)** 접속
2. 오른쪽 상단 ⚙️(설정) 클릭
   - "본인이 직접 OAuth 자격증명을 사용하세요" 체크
   - OAuth 클라이언트 ID / 클라이언트 비밀 입력
3. 왼쪽 목록에서 **Blogger API v3** → `https://www.googleapis.com/auth/blogger` 선택
4. **"API 권한 부여"** 클릭 → Google 계정 로그인 & 권한 허용
5. **Step 2** → **"Exchange authorization code for tokens"** 클릭
6. **"Refresh token"** 필드 값 복사

> **주의**: Refresh token 필드가 비어있으면 [Google 계정 권한](https://myaccount.google.com/permissions)에서 앱 액세스 권한을 취소 후 재시도

### 8-2. 새 토큰 등록

1. **[GitHub Secrets](https://github.com/kevinlee7250/cli/settings/secrets/actions)** 접속
2. `GOOGLE_REFRESH_TOKEN` → **"Update"**
3. 새 Refresh Token 붙여넣기 → **"Update secret"**

### 8-3. 영구 해결 (권장)

OAuth 동의 화면을 "프로덕션"으로 게시하면 토큰이 만료되지 않습니다:

1. **[Google Cloud Console](https://console.cloud.google.com/apis/credentials/consent)** → OAuth 동의 화면
2. **"앱 게시"** 버튼 클릭
3. 확인 → 게시 완료

---

## 9. 트러블슈팅

### ❌ `invalid_grant` — Refresh Token 만료

```
토큰 발급 실패: 400 {"error": "invalid_grant"}
```

**원인**: Google OAuth Refresh Token 만료 (테스트 앱 7일 제한)
**해결**: [섹션 8](#8-google-oauth-토큰-갱신) 참고하여 토큰 갱신

---

### ❌ `ANTHROPIC_API_KEY 미설정`

```
⚠️ 설정 누락: ANTHROPIC_API_KEY 미설정
```

**원인**: `.env` 파일 없거나 키 미입력
**해결**: `.env` 파일 확인, GitHub Secret 등록 확인

---

### ❌ 이미지가 삽입되지 않음

```
이미지 없음 — 텍스트만으로 업로드 진행
```

**원인**: 네이버 API 키 미설정 + DDG 검색 실패 + Wikimedia 결과 없음
**해결**:
- `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` 설정 확인
- 네이버 개발자 센터에서 "이미지 검색" 권한 활성화 확인

---

### ❌ 업로드 실패: HTTP 401

```
업로드 실패: 401 {"error": {"code": 401, "message": "Request had invalid authentication credentials"}}
```

**원인**: Access Token 발급 실패 (Refresh Token 문제)
**해결**: Refresh Token 갱신 후 GitHub Secret 업데이트

---

### ❌ JSON 파싱 실패 — 재시도

```
JSON 파싱 실패 — 재시도 1/3
```

**원인**: Claude 응답이 완전한 JSON이 아닌 경우 (드물게 발생)
**해결**: 자동으로 최대 3회 재시도함. 지속 발생 시 `CLAUDE_MODEL` 확인

---

### ❌ 대시보드 데이터가 업데이트되지 않음

**확인 사항**:
1. GitHub Actions 로그의 "대시보드 데이터 커밋 & 푸시" 스텝 확인
2. `docs/data/` 폴더가 브랜치에 존재하는지 확인
3. GitHub Pages 설정: 브랜치 `claude/blog-automation-system-KAbtE` / 폴더 `/docs`

---

## 10. 파일 구조

```
blog-automation/
├── main.py                  # 메인 실행 파일 (CLI 진입점)
├── config.py                # 환경 변수 로딩 및 설정값 정의
├── content_generator.py     # Claude API로 포스트 생성
├── keyword_collector.py     # 트렌드 키워드 수집
├── image_fetcher.py         # 이미지 검색 및 본문 삽입
├── blogger_uploader.py      # Blogger API 업로드 (광고/목차/스키마 포함)
├── dashboard_exporter.py    # 실행 이력 저장 및 대시보드 데이터 내보내기
├── get_refresh_token.py     # Google OAuth Refresh Token 발급 스크립트
├── requirements.txt         # Python 의존성 패키지
├── logs/
│   ├── automation.log       # 실행 로그
│   ├── run_history.json     # 누적 실행 이력 (최대 100개)
│   └── used_keywords.json   # 중복 키워드 방지용 사용 이력
└── docs/
    └── data/
        ├── posts.json       # 대시보드용 포스트 목록
        ├── runs.json        # 대시보드용 실행 이력
        ├── analytics.json   # 수익 분석 데이터
        └── meta.json        # 시스템 메타 정보

.github/
└── workflows/
    └── blog-run.yml         # GitHub Actions 자동화 워크플로우
```

---

## 빠른 참조

| 작업 | 명령 / URL |
|------|-----------|
| 로컬 테스트 | `python main.py --test` |
| 즉시 1회 실행 | `python main.py --once` |
| 특정 키워드 | `python main.py --once --keyword "키워드"` |
| Actions 수동 실행 | GitHub → Actions → Run workflow |
| 대시보드 | https://kevinlee7250.github.io/cli/ |
| Secrets 관리 | https://github.com/kevinlee7250/cli/settings/secrets/actions |
| 토큰 갱신 | https://developers.google.com/oauthplayground |
| 권한 취소 | https://myaccount.google.com/permissions |
