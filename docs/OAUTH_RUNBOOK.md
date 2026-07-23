# Google OAuth 재인증 런북

블로그 3개(Blogger 발행) + Search Console(사이트맵 제출·색인 검사) + Drive 백업이
전부 `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REFRESH_TOKEN` 3개
GitHub Secret을 공유합니다. 이 문서는 이 자격증명이 만료됐을 때(또는
`docs/index.html` 시스템 관리 탭의 "🔐 인증 헬스체크" 카드가 빨간불일 때)
복구하는 절차입니다.

## 왜 필요한가

- GitHub Secret은 **쓰기만 가능하고 읽을 수 없습니다** — 값이 맞는지 확인하려면
  실제로 API를 호출해보는 수밖에 없습니다.
- `Kevinlee7250/cli`는 **public 저장소**입니다. GitHub Actions 로그·아티팩트는
  public 저장소에서 누구나 볼 수 있으므로, **refresh_token을 Actions 로그나
  아티팩트로 절대 출력하면 안 됩니다.** (client_id는 공개돼도 무해합니다.)
- 이 저장소는 **fork라서 저장소 자체를 private으로 전환할 수 없습니다**
  (GitHub이 fork의 공개 여부 변경을 막음).
- 따라서 토큰 교환(2단계, client_secret + code → refresh_token)은
  **반드시 로컬 환경에서** 실행해야 합니다 — GitHub Actions에서 실행하면
  refresh_token이 public 로그에 노출됩니다.

## 증상

- 시스템 관리 탭 "🔐 인증 헬스체크" 카드가 ❌
- `gsc-indexing.yml` / `blog-run.yml` 로그에 다음 중 하나:
  - `"error": "invalid_grant"` → refresh_token 자체가 무효 (재발급 필요)
  - `"error": "invalid_client"` → client_id/client_secret이 Secret 값과 불일치
  - `GSC 권한 없음 (403)` — 이건 자격증명 문제가 아니라 GSC 속성 유형
    (도메인 속성 vs URL-프리픽스) 문제일 수 있음 → 아래 "참고" 섹션 확인

## 복구 절차

### 1. Client Secret 확인
Google Cloud Console → [API 및 서비스 → 사용자 인증 정보](https://console.cloud.google.com/apis/credentials)
→ 해당 OAuth 2.0 클라이언트 클릭 → Client Secret 값 확인 (필요하면 재발급).

### 2. 인증 URL 방문해서 새 코드 받기
아래 URL에서 `client_id=` 값을 실제 값으로 바꿔서 브라우저로 접속:

```
https://accounts.google.com/o/oauth2/auth?client_id=<CLIENT_ID>&redirect_uri=http%3A%2F%2Flocalhost&response_type=code&scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fblogger+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fwebmasters&access_type=offline&prompt=consent
```

> ⚠️ `redirect_uri=urn:ietf:wg:oauth:2.0:oob`는 **Google이 폐지**해서
> "액세스 차단됨 / 400 invalid_request"가 납니다. 반드시 `http://localhost`를
> 쓰세요.

로그인 → Blogger + Search Console 권한 동의 → 계속. 승인 후 브라우저가
`http://localhost/?code=...&scope=...`로 이동하며 **"사이트에 연결할 수 없음"**
오류 페이지가 뜹니다 (정상 — localhost에 서버가 없어서 그런 것). 주소창에서
`code=` 값을 복사합니다 (몇 분 내에 만료되고 1회용이니 바로 다음 단계로).

> `redirect_uri_mismatch` 오류가 뜨면 Google Cloud Console에서 이 OAuth
> 클라이언트의 "승인된 리디렉션 URI"에 `http://localhost`를 추가하세요.

### 3. 로컬 터미널에서 코드 교환 (절대 GitHub Actions에서 실행하지 말 것)

```bash
curl -s -X POST https://oauth2.googleapis.com/token \
  -d client_id=<CLIENT_ID> \
  -d client_secret=<CLIENT_SECRET> \
  -d code=<방금 받은 CODE> \
  -d grant_type=authorization_code \
  -d redirect_uri=http://localhost
```

응답 JSON의 `refresh_token` 필드 값만 정확히 복사 (따옴표·공백 제외).

### 4. GitHub Secret 업데이트
저장소 Settings → Secrets and variables → Actions:
- `GOOGLE_REFRESH_TOKEN` → 방금 받은 값으로 교체
- `GOOGLE_CLIENT_SECRET` → 2단계에서 쓴 값과 **반드시 동일한지** 재확인
  (`invalid_client`가 계속 나면 이 둘이 다른 값인 경우가 대부분)

### 5. 재검증
`.github/workflows/gsc-indexing.yml`의 push 트리거를 이용해 즉시 확인하거나,
다음 날 자동 수리 워크플로(`auto-repair.yml`)의 인증 헬스체크 결과를
대시보드에서 확인합니다.

## 참고 — GSC "권한 없음(403)" 별도 원인

`invalid_grant`/`invalid_client`와 무관하게, 커스텀 도메인(`hoguwhat.com`)이
Search Console에 **도메인 속성**(`sc-domain:`)으로 등록돼 있으면 URL-프리픽스
형식(`https://www.hoguwhat.com/`)으로 GSC API를 호출할 때 403이 납니다.
`blog_analytics.py`/`gsc_indexing.py`는 403을 받으면 자동으로
`sc-domain:도메인` 형식으로 재시도하도록 이미 처리돼 있습니다
(`_domain_property_for()`). 이 폴백도 실패하면 Search Console에서
실제 속성 유형을 확인하세요.

## 알려진 함정 (이번에 실제로 겪은 것들)

1. **`get_blog_configs()`의 `BLOGS_CONFIG` 병합 버그** — `BLOGS_CONFIG` Secret에
   있는 블로그 항목이 `blogs.json`의 `gsc_site_url`/`topics` 등을 통째로
   덮어써서 사라지는 버그가 있었음 (2026-07-22 필드 단위 병합으로 수정됨).
   비슷한 증상(설정값이 이유 없이 비어 보임)이 다시 나오면 이 함수부터 의심.
2. **워크플로가 에러를 삼킴** — `gsc_indexing.py`의 GSC 토큰 발급 실패는
   `GSC 토큰 발급 실패 — 색인 요청 건너뜀 (게시에는 영향 없음)`으로 로그만
   남기고 워크플로 자체는 `conclusion: success`로 끝남. **대시보드 초록불을
   맹신하지 말고, 인증 헬스체크 카드를 따로 확인할 것.**
3. **GitHub Actions 아티팩트 다운로드가 이 환경(Claude Code 세션)의 네트워크
   정책에 막힐 수 있음** — Azure Blob Storage 도메인이 프록시 허용 목록에
   없어 아티팩트 방식 대신 git 커밋 파일 또는 로그 직접 확인 방식을 써야 함
   (client_id처럼 민감하지 않은 값에 한해서만).
