# 인수인계 — 2026-08-18 시점 (2차 갱신)

> **⚠️ 이 문서의 초판에 있던 "원인 후보 A(client_id가 낡은 값)"는 반증되었습니다.**
> 아래 [원인 후보 재검증](#원인-후보-재검증-2026-08-18-2차) 절을 먼저 읽으세요.
> **GitHub Secrets의 `GOOGLE_CLIENT_ID`를 바꾸지 마세요.** 현재 값은 정상 동작 중입니다.

새 세션(Cowork 포함)이 이 문서만 읽고 작업을 이어갈 수 있도록 정리했습니다.

- 저장소: `Kevinlee7250/cli` (npm/cli의 **공개 포크**)
- 작업 브랜치: `claude/blog-automation-system-KAbtE`
- 기본 브랜치: `latest`
- 테스트: `cd blog-automation && python -m pytest tests/ -q` → **322건 통과**

---

## ⛔ 절대 지켜야 할 제약

1. **이 저장소는 공개입니다.** `GOOGLE_REFRESH_TOKEN`, `GOOGLE_CLIENT_SECRET`을
   GitHub Actions 로그·아티팩트·커밋에 절대 노출하지 마세요.
   OAuth 코드→토큰 교환은 **로컬에서만** 합니다.
   (이 규칙을 어기던 `get-oauth-token.yml`은 2026-08-18에 삭제했습니다.)
   `client_id`는 공개 식별자이므로 노출돼도 무방합니다.

2. **워크플로의 `schedule`·`workflow_dispatch`는 기본 브랜치(`latest`)의
   파일만 인식합니다.** 기능 브랜치만 고치면 스케줄이 돌지 않고 대시보드
   버튼은 404가 납니다. → PR #12로 동기화 중.

3. **`docs/.gitignore`(npm/cli 템플릿)가 `docs/*`를 무시합니다.**
   워크플로에서 docs 파일을 커밋하려면 반드시 `git add -f`. 빠뜨리면
   조용히 누락됩니다(`analytics_summary.json`이 몇 주간 그랬습니다).

4. 테스트가 `blog-automation/logs/used_images.json`을 오염시킵니다.
   커밋 전 `git checkout -- blog-automation/logs/used_images.json`.

---

## 🎯 지금 풀고 있는 문제: AdSense 승인이 안 됨

**AdSense는 아직 미승인 상태입니다.** 따라서 `ADSENSE_CLIENT_ID` 시크릿이
비어 있는 것은 정상이며, 실측 수익 연동(`adsense_revenue.py`)은 승인 후에
자동으로 동작합니다 — 지금 건드릴 필요 없습니다.

### 승인의 최대 걸림돌: 구글이 글을 색인하지 않음

`docs/data/index_status.json` (2026-08-18):
- 색인 0 / 미색인 20
- 상당수 `URL is unknown to Google`, `lastCrawlTime` 전부 비어 있음

⚠️ **단, 이 표본은 편향돼 있었습니다.** 검사 대상이 전부 1~2일 된 글이라
발행 직후 미색인은 정상입니다. `_sample_spread()`로 최신 절반 + 오래된 글
절반을 검사하도록 고쳤으니, **다음 실행 결과부터 진짜 상태**를 볼 수 있습니다.

### 원인 후보 재검증 (2026-08-18 2차)

초판의 후보 A·B·C를 실제 산출물로 대조한 결과입니다.

| 후보 | 초판 판정 | **재검증 결과** | 근거 |
|---|---|---|---|
| A. client_id가 낡은 값 | "가장 유력" | ❌ **반증** | `docs/data/auth_health.json` (08-17 17:21) → `google_oauth: ok=true` |
| B. 토큰에 webmasters 쓰기 권한 없음 | "불확실" | ⚠️ **읽기는 확인, 쓰기는 미확인** | `docs/data/gsc.json` (08-18 11:02) 정상 수집 → readonly 이상 보유 |
| C. GSC 속성 미등록 | "확인 안 됨" | ⚠️ **blog1만 누락** | `gsc.json`의 `sites`에 blog2·blog3만 있고 blog1 없음 |

#### A가 반증된 이유

`auth_health_check.py`의 `check_google_oauth()`는 **GitHub Secrets의
`GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` + `GOOGLE_REFRESH_TOKEN`으로
실제 `grant_type=refresh_token` 교환을 시도**하고 200일 때만 `ok=true`를
씁니다. 즉 `ok=true`는 세 값이 **서로 정합하고 클라이언트가 살아 있다**는
직접 증거입니다. Actions의 구글 작업이 인증 단계에서 실패해 왔다는
초판의 추론은 성립하지 않습니다.

#### 클라이언트가 2개 존재합니다 (혼동의 실제 원인)

같은 GCP 프로젝트(`310114393483`)에 OAuth 클라이언트가 둘 있습니다.

| 구분 | client_id | 상태 |
|---|---|---|
| **Actions에서 동작 중** | `310114393483-rtotnsftmbbat8l3pua3suer3juv91o6...` | ✅ 정상 (`auth_health.json`에 기록됨) |
| 콘솔 화면에서 본 값 | `310114393483-gtn7a6736ilf1kisdv0j6rse27gct2sn...` | 별개 클라이언트 |

사용자 로컬에서 난 `invalid_client`는 **`gtn7a...` ID에 다른 클라이언트의
secret을 짝지어 넣어서** 생긴 불일치입니다. 클라이언트가 낡아서가 아닙니다.

> **로컬 검증 시에는 `rtotns...` 쪽을 쓰세요.** 콘솔 값을 쓰면 secret이
> 맞지 않아 같은 오류가 반복됩니다.

#### 그래서 색인 실패의 진짜 원인은 인증이 아닙니다

`index_status.json`의 20건은 전부 `Discovered - currently not indexed`입니다.
이 문자열은 **구글이 URL을 이미 알고 있다**는 뜻입니다 — 사이트맵 제출이
실패했다면 나올 수 없는 값입니다. 즉 발견 단계가 아니라 **크롤 우선순위
단계에서 밀리고 있는 것**이며, 사이트맵 권한(후보 B)을 고쳐도 해결되지
않습니다. 콘텐츠 품질신호 쪽에서 원인을 찾아야 합니다.

관측된 품질신호 문제:

- **blog1·blog2의 `topics`가 거의 동일** (국내여행·해외여행·드라마·영화·
  연예·K-POP 6개 중복). 자기 블로그끼리 같은 주제로 경쟁하는 구조 →
  중복성 신호. `blogs.json`에서 주제 분리 필요.
- blog3에 **FAQ 없는 글 58건**.
- GSC 30일 노출: blog2 **3회**, blog3 **0회**, blog1 **데이터 없음**.

---

## 🔜 다음 할 일 (순서대로)

### 1. 색인 검사 재실행 — 판단 근거 확보 (최우선)

현재 `index_status.json`은 **08-18 00:31** 것으로, 표본 편향을 고친
커밋 `7ed742f3`보다 **먼저** 생성됐습니다. 즉 "색인 0/20"은 발행 직후
글만 본 결과라 신뢰할 수 없습니다.

```
GitHub → Actions → gsc-indexing → Run workflow
```

`_sample_spread()` 적용 후 결과가 나와야 **진짜 색인율**을 알 수 있습니다.
이 수치 없이 다음 판단을 하지 마세요.

### 1-B. (선택) 토큰 쓰기 권한 확인 — 로컬

```
python setup_google_auth.py --check
```

`rtotns...` client_id를 사용하세요(콘솔의 `gtn7a...` 아님).
읽기 권한은 이미 확인됐으므로, 이 검사는 **사이트맵 제출용 쓰기 권한**
유무만 판별하는 용도입니다. 색인 문제의 주원인은 아니므로 우선순위 낮음.

재발급이 필요할 경우 사전 준비: 콘솔의 **승인된 리디렉션 URI**에
`http://localhost:8080` 추가 (현재 `http://localhost`와 github.io 주소만
등록돼 있음). 기존 보안 비밀번호는 다시 볼 수 없으므로 필요 시 새로 발급.

### 2. PR #12 머지 (사용자 승인 필요)

https://github.com/Kevinlee7250/cli/pull/12 — 초안, `mergeable_state: clean`

기본 브랜치에 반영돼야 하는 것들:
- `pending-cleanup.yml`, `alert-watchdog.yml` (신규, 스케줄 미동작 중)
- `blog-analytics.yml` (`git add -f` 누락 수정 + 수익 수집 단계)
- `gsc-indexing.yml` (진단 단계 추가)
- `get-oauth-token.yml` **삭제** (보안)

### 3. FAQ 없는 글 보강

금융NEWS(blog3)에 FAQ 없는 글 58건. 도구는 이미 있습니다.
대시보드 → AdSense 감사 → **🔍 미리보기**(글 수정 없음)로 대상 확인 후
**✨ FAQ·출처 보강** 실행. 건수 지정 가능.

### 4. 필수 페이지 확인

소개·개인정보처리방침·문의 페이지가 3개 블로그 전부에 있는지
(`page_creator.py` 존재). AdSense 승인 요건.

### 5. blog1·blog2 주제 중복 해소 (신규 — 2차에서 발견)

`blogs.json`에서 두 블로그의 `topics`가 6개 겹칩니다
(국내여행·해외여행·드라마·영화·연예·K-POP). 같은 운영자의 두 사이트가
같은 키워드로 경쟁하면 중복성 신호가 되어 색인·순위 모두 불리합니다.

권고: blog1은 여행 전담, blog2는 스포츠·연예 전담처럼 **배타적으로 분리**.
이미 발행된 중복 주제 글은 `migrate_offtopic.py` 참고.

### 6. blog1의 GSC 데이터 누락 확인 (신규 — 2차에서 발견)

`gsc.json`의 `sites`에 blog2·blog3만 있고 **blog1이 없습니다**.
`blogs.json`의 blog1 `gsc_site_url`은 `https://www.hoguwhat.com/`
(커스텀 도메인)인데, 과거 인시던트에 **도메인 속성(`sc-domain:`)을
URL-프리픽스로 조회하면 403**이 난 기록이 있습니다.
`_domain_property_for()` 헬퍼가 blog1에 실제로 적용되는지 확인 필요.

---

## 📌 이번 세션에서 고친 것 (모두 커밋·푸시됨)

| 커밋 | 내용 |
|---|---|
| `5c6817b` | Blogger 조회수가 항상 0이던 파싱 버그 (요청 `30DAYS` vs 응답 `THIRTY_DAYS`) |
| `8d283c7` | `pending_manager.py` — 152건 2.2MB "글 무덤" 정리 |
| `7405201` | `alert_notifier.py` — 전체 워크플로 실패 감시 워치독 |
| `96ad753` | `adsense_revenue.py` — 실측 RPM 연동 (승인 후 동작) |
| `87eb4d81` | **발행이 posts.json의 등급을 매번 지우던 버그** |
| `ff444177` | `gsc_diagnose.py` + 사이트맵 403 원인 구분 |
| `4a39c349` | **공개 저장소에서 토큰 교환하던 워크플로 삭제** |
| `7ed742f3` | `index_priority.py` + 색인 검사 표본 편향 수정 |
| `3568151a` | `setup_google_auth.py --check` |

### 2차 세션에서 한 것 (2026-08-18, 코드 변경 없음)

산출물 대조로 **원인 후보 A를 반증**하고, 색인 실패의 성격을
"인증 실패"에서 "크롤 우선순위 밀림"으로 재정의했습니다.
신규 발견 2건(주제 중복, blog1 GSC 누락)을 다음 할 일 5·6번에 추가.

### 아직 유효한 관찰

- **추정 수익이 자릿수 단위로 과대**: 조회수 3,081회에 $118.94 → 함의 RPM $38.61.
  한국어 블로그 실제 RPM은 $0.5~3. 가정 CTR 2.5%·CPC $1~3이 원인이며
  AdSense 승인 후 실측이 들어와야 정상화됩니다.
- **GSC 매칭률 4%**, URL 없는 글 11건.
- 자동수리 건강점수 97/100, ads.txt 3개 블로그 정상.

### 색인 요청 자동화는 불가능합니다

Google Indexing API는 문서상 **채용공고·방송이벤트 전용**이고, Search Console
API에는 색인 요청 엔드포인트가 없습니다(웹 UI 버튼뿐, 속성당 하루 10건 내외).
그래서 `index_priority.py`로 **우선순위만** 정합니다. 자동화하는 코드를
만들지 마세요.
