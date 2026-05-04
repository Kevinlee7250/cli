# 블로그 자동화 시스템

Google AdSense 수익화를 위한 완전 자동화 블로그 운영 시스템입니다.

## 🔄 자동화 흐름

```
Google Trends + 네이버 DataLab
         ↓
   핫 키워드 분석 & 선별
         ↓
  Claude AI 블로그 포스트 작성
  (SEO + AdSense 최적화)
         ↓
  ┌──────────────────────────────┐
  │  썸네일 자동 생성 (Canvas)    │
  │  - 가로형 1280×720 (Blogger) │
  │  - 세로형 1080×1920 (SNS)    │
  └──────────────────────────────┘
         ↓
  ┌──────────────────────────────┐
  │    플랫폼별 콘텐츠 배포        │
  │  📝 Google Blogger 게시      │
  │  📸 Instagram 이미지+캡션     │
  │  🧵 Threads 연속 스레드       │
  │  🎵 TikTok 스크립트 생성      │
  └──────────────────────────────┘
```

## 📂 프로젝트 구조

```
blog-automation/
├── src/
│   ├── index.js                 # 메인 오케스트레이터
│   ├── config.js                # 환경 설정
│   ├── scrapers/
│   │   ├── google-trends.js     # Google Trends RSS/API 수집
│   │   ├── naver-trends.js      # 네이버 DataLab + 뉴스 검색
│   │   └── keyword-analyzer.js  # 통합 키워드 분석 & 점수화
│   ├── generators/
│   │   ├── blog-content.js      # Claude AI 블로그 포스트 생성
│   │   ├── social-content.js    # Instagram/Threads/TikTok 콘텐츠
│   │   └── thumbnail.js         # Canvas 썸네일 생성
│   ├── publishers/
│   │   ├── blogger.js           # Google Blogger API
│   │   ├── instagram.js         # Instagram Graph API
│   │   ├── threads.js           # Meta Threads API
│   │   └── tiktok.js            # TikTok Content Posting API
│   └── utils/
│       ├── logger.js            # Winston 로거
│       └── storage.js           # 로컬 파일 저장
├── scripts/
│   ├── test-keywords.js         # 키워드 수집 테스트
│   ├── test-content.js          # 콘텐츠 생성 테스트
│   └── test-thumbnail.js        # 썸네일 생성 테스트
├── output/
│   ├── posts/                   # 생성된 블로그 포스트 JSON
│   ├── social/                  # SNS 콘텐츠 JSON
│   └── thumbnails/              # 생성된 썸네일 이미지
├── .env.example                 # 환경 변수 예시
└── package.json
```

## ⚙️ 설치 및 설정

### 1. 의존성 설치

```bash
cd blog-automation
npm install
```

> canvas 패키지는 시스템 의존성이 필요합니다:
> - Ubuntu/Debian: `sudo apt-get install build-essential libcairo2-dev libpango1.0-dev libjpeg-dev libgif-dev librsvg2-dev`
> - macOS: `brew install pkg-config cairo pango libpng jpeg giflib librsvg`

### 2. 환경 변수 설정

```bash
cp .env.example .env
# .env 파일을 열어 API 키 입력
```

### 3. 필수 API 설정

| 서비스 | 취득 경로 | 필수 여부 |
|--------|-----------|-----------|
| **Anthropic Claude** | [console.anthropic.com](https://console.anthropic.com) | ✅ 필수 |
| **Naver API** | [developers.naver.com](https://developers.naver.com) | 권장 |
| **Google OAuth2** | [console.cloud.google.com](https://console.cloud.google.com) | Blogger 사용 시 |
| **Instagram Graph** | [developers.facebook.com](https://developers.facebook.com) | Instagram 사용 시 |
| **Threads API** | Meta Developer Portal (Instagram과 동일 앱) | Threads 사용 시 |
| **TikTok API** | [developers.tiktok.com](https://developers.tiktok.com) | TikTok 사용 시 |

## 🚀 실행 방법

### 즉시 1회 실행 (테스트용)
```bash
npm run run-once
# 또는
node src/index.js
```

### 스케줄러 실행 (매일 자동 실행)
```bash
npm run schedule
```
기본 스케줄: **매일 오전 8시** (`.env`의 `SCHEDULE_CRON`으로 변경 가능)

### 개별 기능 테스트
```bash
# 키워드 수집만 테스트
npm run test-keywords

# 콘텐츠 생성 테스트
npm run test-content "인공지능"

# 썸네일 생성 테스트
npm run test-thumbnail
```

## 📊 키워드 점수 시스템

키워드 선별 시 다음 기준으로 점수를 산정합니다:

| 요소 | 가중치 |
|------|--------|
| Google 일간 트렌드 순위 | ×5 |
| Google 실시간 트렌드 순위 | ×3 |
| 네이버 교차 검증 | +50점 |
| 검색 트래픽 규모 | +30~80점 |
| AdSense 고가치 카테고리 (금융, 건강, 기술 등) | +40점 |
| 연관 쿼리 풍부도 | ×5/개 |

## 📱 SNS 플랫폼별 콘텐츠 전략

### Instagram
- 2줄 후킹 오프닝 → 상세 내용 → 해시태그 20~30개
- 세로형 썸네일 첨부 (1080×1920)

### Threads
- 5개 연속 스레드로 정보를 단계적 전달
- 마지막 스레드에서 블로그 유입 유도

### TikTok
- 60초 영상 스크립트 (씬별 연출 지시 포함)
- 배경음악 추천 + 썸네일 텍스트 제공
- 영상 제작 후 수동 업로드 또는 영상 API 연동 필요

## 🔧 커스터마이징

### 게시 횟수 변경
`.env`에서 `POSTS_PER_RUN=5`로 설정 (최대 5개)

### 스케줄 변경
`.env`에서 `SCHEDULE_CRON="0 9 * * *"` (매일 오전 9시)

### 썸네일 크기 변경
`.env`에서 `THUMBNAIL_WIDTH=1920`, `THUMBNAIL_HEIGHT=1080`

## ⚠️ 주의사항

1. **API 사용량**: Claude API는 호출당 비용이 발생합니다. `POSTS_PER_RUN` 조정으로 비용 관리
2. **Instagram**: 이미지 업로드 시 공개 URL이 필요합니다 (`IMGBB_API_KEY` 설정 또는 직접 URL 제공)
3. **TikTok**: 영상 파일이 없는 경우 스크립트만 저장됩니다. 영상 제작 후 업로드하세요
4. **콘텐츠 검수**: AI 생성 콘텐츠는 게시 전 반드시 검수를 권장합니다
5. **API 제한**: 각 플랫폼의 일일 API 호출 한도를 확인하세요
