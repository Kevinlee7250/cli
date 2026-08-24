# 블로그 자동화 시스템 — 신규 설치 가이드

이 문서는 지금 운영 중인 것과 동일한 시스템(키워드 수집 → AI 글 생성 → Blogger 자동 발행 → 분석 → 자가 수리 → 웹 대시보드)을 **다른 사람이 자신의 블로그·계정으로 그대로 구축**할 때 따라야 할 절차입니다.

## 0. 전제 조건

- GitHub 계정 (Actions 무료 사용량으로 충분히 운영 가능)
- Google 계정 (Blogger 블로그 운영용)
- Anthropic API 키 (또는 OpenAI API 키)
- 기본적인 git 사용 경험

---

## ① 저장소 준비

이 시스템이 들어있는 원본 저장소는 npm/cli의 포크(fork)라서 무관한 npm 소스가 함께 딸려옵니다. 다른 사람은 아래 중 하나로 시작하세요.

**방법 A — 필요한 폴더만 복사 (권장)**
새 빈 GitHub 저장소를 만들고 다음 3개 폴더/설정만 복사합니다.
- `blog-automation/` (핵심 로직 전체)
- `docs/` (대시보드 + 데이터)
- `.github/workflows/` 중 블로그 자동화 관련 파일만 (`blog-*.yml`, `auto-repair.yml`, `weekly-*.yml`, `trend-preempt.yml`, `gsc-*.yml`, `adsense-*.yml`, `fix-*.yml`, `delete-low-grade-posts.yml`, `series-schedule.yml`, `shorts-generate.yml`, `collect-keywords.yml`, `manual-publish.yml`, `topic-posts.yml`, `deploy-dashboard.yml`)

**방법 B — 이 저장소를 fork**
불필요한 npm 관련 파일이 같이 오지만, 커밋 이력을 그대로 유지하고 싶을 때 사용합니다.

---

## ② 필요한 계정·API 키 발급

| 용도 | 발급처 | 필수 여부 |
|---|---|---|
| 글 작성 AI | [Anthropic Console](https://console.anthropic.com) → API 키 발급 | 필수 (`ANTHROPIC_API_KEY`) |
| 글 작성 AI (대안) | [OpenAI Platform](https://platform.openai.com) | 선택 (`OPENAI_API_KEY`, `AI_PROVIDER=openai`로 전환 시) |
| Blogger 발행 | [Google Cloud Console](https://console.cloud.google.com) → OAuth 2.0 클라이언트 ID 생성 + Blogger API 활성화 | 필수 (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`) |
| 블로그 자체 | [blogger.com](https://blogger.com)에서 블로그 개설 → URL의 blog_id 확인 | 필수 |
| 광고 수익화 | [Google AdSense](https://adsense.google.com) 승인 후 클라이언트 ID·슬롯 ID | 선택 |
| 실시간 뉴스/트렌드 | [네이버 개발자센터](https://developers.naver.com) → 애플리케이션 등록 | 선택 (`NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`) |
| 이미지 자동 삽입 | [Pixabay API](https://pixabay.com/api/docs/) 또는 [ImgBB](https://api.imgbb.com) | 선택 |
| SNS 자동 발행 | Meta for Developers (Instagram/Threads) | 선택 |

### GOOGLE_REFRESH_TOKEN 발급 (직접 진행 필요)

이건 API 키처럼 그냥 복사하는 값이 아니라 **OAuth 동의 절차를 1회 완료**해야 얻을 수 있습니다. 상세 절차와 흔한 함정(OOB redirect_uri 폐지, invalid_grant/invalid_client 구분, GSC 도메인 속성 403 등)은 [`OAUTH_RUNBOOK.md`](./OAUTH_RUNBOOK.md)에 정리돼 있습니다 — 처음 세팅할 때 반드시 참고하세요.

**절대 GitHub Actions 안에서 이 토큰 교환을 실행하지 마세요.** public 저장소라면 로그에 노출될 수 있습니다. 반드시 로컬 환경(본인 컴퓨터)에서만 진행하세요.

---

## ③ GitHub 저장소 설정

### Secrets 등록
Settings → Secrets and variables → Actions에서 아래 값들을 등록합니다. (✅ 필수 / ⬜ 선택)

```
✅ ANTHROPIC_API_KEY
✅ GOOGLE_CLIENT_ID
✅ GOOGLE_CLIENT_SECRET
✅ GOOGLE_REFRESH_TOKEN
✅ BLOGGER_BLOG_ID          (블로그가 1개뿐이면 이것만, 여러 개면 BLOGS_CONFIG 사용)
⬜ BLOGS_CONFIG             (JSON 배열 — 여러 블로그를 credential 단위로 관리할 때)
⬜ ADSENSE_CLIENT_ID
⬜ ADSENSE_SLOT_IDS
⬜ NAVER_CLIENT_ID / NAVER_CLIENT_SECRET
⬜ PIXABAY_API_KEY / IMGBB_API_KEY
⬜ OPENAI_API_KEY / OPENAI_MODEL / AI_PROVIDER
⬜ INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_ACCOUNT_ID
⬜ THREADS_ACCESS_TOKEN / THREADS_USER_ID / THREADS_HANDLE
⬜ TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID  (알림용)
⬜ GOOGLE_DRIVE_REFRESH_TOKEN  (자동 백업용, Blogger 토큰과 별개 발급 가능)
⬜ SOCIAL_AUTO_PUBLISH
```

### 워크플로 브랜치명 수정
`.github/workflows/*.yml` 안에 있는 `ref: claude/blog-automation-system-KAbtE`를 본인이 실제로 개발할 브랜치명으로 전부 바꿉니다 (찾아바꾸기 한 번으로 충분).

---

## ④ 블로그 설정 (`blog-automation/blogs.json`)

블로그 1개당 하나의 객체로 등록합니다.

```json
[
  {
    "id": "blog1",
    "name": "내 블로그 이름",
    "blog_id": "Blogger에서 확인한 숫자 ID",
    "language": "ko",
    "post_status": "live",
    "enabled": true,
    "topics": ["주제1", "주제2", "주제3"],
    "naver_api_queries": ["실시간 뉴스 검색에 쓸 쿼리1", "쿼리2"],
    "gsc_site_url": "https://내블로그도메인.com/"
  }
]
```

`BLOGS_CONFIG` Secret을 쓰는 경우, credential(민감 정보)만 담고 `blogs.json`의 나머지 필드(topics 등)와 **필드 단위로 병합**됩니다 — 이 병합 로직(`config.py`)이 과거에 버그였던 적이 있으니 credential만 최소로 넣고 topics 등은 `blogs.json`에 두는 걸 권장합니다.

### 콘텐츠 카테고리 커스터마이징
지금 시스템은 여행/스포츠/드라마·연예/금융 4개 카테고리에 맞춰 도입부 후킹 스타일과 전문용어 사전이 구성돼 있습니다(`content_generator.py`의 `_detect_content_category()`, `readability_checker.py`). 다른 주제를 다룬다면 이 부분의 키워드 사전을 본인 주제에 맞게 고쳐야 카테고리별 최적화가 제대로 동작합니다.

---

## ⑤ 대시보드 활성화 (GitHub Pages)

1. Settings → Pages에서 소스를 `docs/` 폴더로 지정
2. `docs/index.html` 상단의 다음 상수를 본인 정보로 변경

```js
const GH_OWNER = '본인 GitHub 아이디'
const GH_REPO = '본인 저장소 이름'
const GH_BRANCH = '본인 개발 브랜치명'
```

3. GitHub 개인 액세스 토큰(PAT, `repo` + `workflow` 권한)을 발급해 대시보드 "API 키 관리" 탭에 등록 — 대시보드 버튼으로 워크플로를 수동 실행하려면 필요합니다
4. 여러 기기에서 쓰려면 PC에서 PAT 등록 후 "📱 다른 기기로 보내기" QR 기능으로 모바일에 전송 가능

---

## ⑥ 첫 실행 테스트

로컬에서 먼저 확인하는 것을 권장합니다.

```bash
cd blog-automation
pip install -r requirements.txt
cp .env.example .env   # 위에서 발급한 키 채워 넣기
python main.py --test --keyword "테스트 키워드"   # 업로드 없이 글만 생성해 확인
python auth_health_check.py                        # OAuth 자격증명 정상인지 확인
python -m pytest tests/ -v                          # 전체 회귀 테스트 (100개+) 통과 확인
```

문제없으면 GitHub Actions에서 `blog-run.yml`을 workflow_dispatch로 수동 실행해 실제 발행까지 확인합니다.

---

## 참고 문서

- [`OAUTH_RUNBOOK.md`](./OAUTH_RUNBOOK.md) — Google OAuth 재인증 절차, 알려진 함정
- `blog-automation/README.md` — 로컬 실행 명령어, 환경 변수 상세
- `blog-automation/incident_log.py` — 과거 장애 사례 검색 (`python incident_log.py --search "키워드"`)
