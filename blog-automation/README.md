# 블로그 자동화 시스템

Claude AI + Google Blogger + AdSense 수익 극대화 완전 자동화 시스템.

## 🔄 자동화 흐름

```
Google Trends RSS / 네이버 DataLab
          ↓
    트렌드 키워드 자동 수집
          ↓
  Claude AI 블로그 포스트 작성
  (SEO + AdSense 최적화 + 이미지 자동 삽입)
          ↓
  Google Blogger 자동 업로드
  (구조화 데이터 + 목차 + 광고 슬롯 6개)
```

## 📂 파일 구조

```
blog-automation/
├── main.py                # 메인 실행 파일
├── config.py              # 환경 변수 설정
├── keyword_collector.py   # 트렌드 키워드 수집
├── content_generator.py   # Claude AI 포스트 생성
├── image_fetcher.py       # 이미지 자동 검색 & 삽입
├── blogger_uploader.py    # Blogger API 업로드
├── requirements.txt       # Python 의존성
├── .env.example           # 환경 변수 예시
└── test_image.py          # 이미지 기능 테스트
```

---

## 🚀 GitHub Actions에서 실행하기

### 1단계 — GitHub Secrets 등록

저장소 → **Settings → Secrets and variables → Actions → New repository secret**

| Secret 이름 | 설명 | 취득 방법 |
|-------------|------|-----------|
| `ANTHROPIC_API_KEY` | Claude API 키 | [console.anthropic.com](https://console.anthropic.com) |
| `GOOGLE_CLIENT_ID` | Blogger OAuth 클라이언트 ID | Google Cloud Console |
| `GOOGLE_CLIENT_SECRET` | Blogger OAuth 클라이언트 시크릿 | Google Cloud Console |
| `GOOGLE_REFRESH_TOKEN` | Blogger OAuth 리프레시 토큰 | OAuth 인증 후 취득 |
| `BLOGGER_BLOG_ID` | 블로그 ID | Blogger 대시보드 URL의 숫자 |
| `NAVER_CLIENT_ID` | 네이버 이미지 검색 API ID | [developers.naver.com](https://developers.naver.com/apps/) |
| `NAVER_CLIENT_SECRET` | 네이버 이미지 검색 API 시크릿 | 동일 |
| `ADSENSE_CLIENT_ID` | AdSense 게시자 ID | AdSense 관리자 → 계정 정보 |
| `ADSENSE_SLOT_IDS` | 광고 슬롯 ID 6개 (쉼표 구분) | AdSense → 광고 → 광고 단위 |

### 2단계 — 워크플로우 수동 실행

1. GitHub 저장소 → **Actions** 탭
2. **블로그 자동화 실행** 선택
3. **Run workflow** 클릭
4. 옵션 설정:
   - **키워드**: 비워두면 Google Trends 자동 수집
   - **포스트 수**: 1~5 (기본 3)
   - **모드**: `live`(즉시 게시) / `draft`(임시저장) / `test`(업로드 없이 확인)

### 자동 실행 스케줄

매일 **오전 9시 (KST)** 자동 실행 (`.github/workflows/blog-run.yml`의 cron 설정).

---

## 💻 로컬에서 실행하기

### 설치

```bash
cd blog-automation
pip install -r requirements.txt
cp .env.example .env
# .env 파일에 API 키 입력
```

### 실행 명령어

```bash
# 테스트 (업로드 없이 글만 생성)
python main.py --test

# 특정 키워드로 테스트
python main.py --test --keyword "재테크 방법,주식 투자"

# 즉시 1회 실행 (Blogger 업로드)
python main.py --once

# 특정 키워드로 1회 실행
python main.py --once --keyword "재테크 방법"

# 스케줄 모드 (매일 오전 9시 자동 실행)
python main.py

# 이미지 기능 테스트
python test_image.py "오늘 핫이슈"
```

---

## ⚙️ Blogger OAuth 설정 방법

1. [Google Cloud Console](https://console.cloud.google.com) → 새 프로젝트 생성
2. **API 및 서비스 → 라이브러리** → "Blogger API v3" 사용 설정
3. **사용자 인증 정보 → OAuth 클라이언트 ID 만들기** (유형: 웹 애플리케이션)
4. 리디렉션 URI 추가: `https://developers.google.com/oauthplayground`
5. [OAuth 2.0 Playground](https://developers.google.com/oauthplayground) 접속
   - 오른쪽 상단 설정 아이콘 → "Use your own OAuth credentials" 체크
   - Client ID / Secret 입력
   - Step 1: `https://www.googleapis.com/auth/blogger` 입력 후 Authorize
   - Step 2: Exchange authorization code for tokens
   - **Refresh token** 복사 → `GOOGLE_REFRESH_TOKEN`에 입력
6. Blogger 블로그 URL에서 Blog ID 확인: `https://www.blogger.com/blog/posts/{BLOG_ID}`

---

## 🔧 환경 변수 (`.env`)

```env
# Claude API
ANTHROPIC_API_KEY=sk-ant-...

# Google Blogger OAuth2
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REFRESH_TOKEN=...
BLOGGER_BLOG_ID=...

# AdSense
ADSENSE_CLIENT_ID=ca-pub-XXXXXXXXXXXXXXXX
ADSENSE_SLOT_IDS=1111111111,2222222222,3333333333,4444444444,5555555555,6666666666

# 네이버 이미지 검색 (선택)
NAVER_CLIENT_ID=...
NAVER_CLIENT_SECRET=...

# 실행 설정
POSTS_PER_RUN=3
POST_STATUS=live         # live | draft
BLOG_LANGUAGE=ko         # ko | en
TREND_COUNTRY=KR         # KR | US
SCHEDULE_CRON=0 9 * * *  # 매일 오전 9시
```
