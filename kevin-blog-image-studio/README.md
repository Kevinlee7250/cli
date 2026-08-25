# Kevin Blog Image Studio

Google Blogger 글을 선택해 제목과 본문을 불러오고, OpenAI 이미지 API로 대표 이미지 1장·본문 이미지 2장·요약 인포그래픽 1장을 생성한 뒤 검토하여 원문 게시글에 저장하는 반자동 웹앱입니다.

## 주요 기능

- Google OAuth 로그인
- 내 Blogger 블로그와 최근 게시글 선택
- 게시글 제목·본문 자동 불러오기
- GPT Image 기반 WebP 이미지 4장 생성
- ALT 텍스트와 SEO 파일명 편집
- 선택한 Blogger 게시글 업데이트
- 모바일·데스크톱 반응형 UI

## 환경변수

`.env.local` 파일을 만들고 아래 값을 설정하세요. 실제 키와 OAuth JSON은 저장소에 커밋하지 마세요.

```env
OPENAI_API_KEY=
OPENAI_IMAGE_MODEL=gpt-image-2
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
SESSION_SECRET=
APP_URL=http://localhost:3000
```

Google Cloud OAuth 승인 리디렉션 URI는 `APP_URL/api/auth/google/callback` 형식으로 등록합니다. Blogger API v3도 활성화해야 합니다.

## 실행

```bash
npm ci
npm run dev
```

## 검증

```bash
npm run build
```

## 보안

`.env*`, `client_secret*.json`, 빌드 산출물과 런타임 캐시는 Git에서 제외됩니다.
