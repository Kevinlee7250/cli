# 블로그 전용 저장소 분리 가이드 (kevin-blog-os)

## 왜 분리하나

현재 블로그 시스템은 npm CLI 포크(`kevinlee7250/cli`) 안에 들어 있습니다.
npm 원본 코드(workspaces/, lib/, node_modules 등)와 섞여 있어 저장소가 무겁고,
CI 워크플로우 45개 중 30개 이상이 npm용입니다. 블로그 전용 저장소로 분리하면
코드·보안·워크플로우 관리가 단순해집니다.

## 권장 구조

```
kevin-blog-os/
├── apps/
│   ├── dashboard/        ← docs/ (index.html, data/)
│   └── worker/           ← main.py, publish_pending.py 등 실행 진입점
├── core/
│   ├── research/         ← research_collector.py, evidence_builder.py, source_validator.py
│   ├── generation/       ← content_generator.py, series_planner.py, image_fetcher.py
│   ├── verification/     ← adsense_validator.py, final_editor.py, post_verifier.py
│   ├── publishing/       ← blogger_uploader.py, social_publisher.py, internal_linker.py
│   └── analytics/        ← post_lifecycle.py, title_ab_tracker.py, gsc_optimizer.py,
│                            weekly_learning.py, blog_analytics.py, dashboard_exporter.py
├── profiles/             ← author_profile.json, blogs.json
├── data/                 ← logs/ (run_history, post_registry, evidence, backups)
├── tests/                ← tests/
└── workflows/            ← .github/workflows/ 중 블로그 관련 15개만
```

## 이관 절차 (로컬에서 실행)

```bash
# 1. 새 저장소를 GitHub에서 생성: kevinlee7250/kevin-blog-os (private 권장)

# 2. 히스토리 없이 깔끔하게 시작 (권장 — 과거 커밋에 남은 실험 데이터 제외)
git clone --branch claude/blog-automation-system-KAbtE \
    https://github.com/kevinlee7250/cli.git blog-src
mkdir kevin-blog-os && cd kevin-blog-os && git init -b main

# 3. 구조에 맞게 복사
mkdir -p apps/dashboard apps/worker core/{research,generation,verification,publishing,analytics} \
         profiles data tests workflows
cp -r ../blog-src/docs/* apps/dashboard/
cp ../blog-src/blog-automation/{main.py,publish_pending.py,fix_existing_posts.py} apps/worker/
cp ../blog-src/blog-automation/{research_collector,evidence_builder,source_validator}.py core/research/
cp ../blog-src/blog-automation/{content_generator,series_planner,image_fetcher}.py core/generation/
cp ../blog-src/blog-automation/{adsense_validator,final_editor,post_verifier}.py core/verification/
cp ../blog-src/blog-automation/{blogger_uploader,social_publisher,internal_linker}.py core/publishing/
cp ../blog-src/blog-automation/{post_lifecycle,title_ab_tracker,gsc_optimizer,weekly_learning,blog_analytics,dashboard_exporter}.py core/analytics/
cp ../blog-src/blog-automation/{author_profile.json,blogs.json} profiles/
cp -r ../blog-src/blog-automation/tests tests
# 블로그 워크플로우만 선별 복사
for f in blog-run blog-optimize blog-analytics blog-tests blog-verify blog-sitemap \
         blog-schedule-monitor collect-keywords post-lifecycle deploy-dashboard \
         manual-publish weekly-learning auto-repair fix-posts gsc-register; do
  cp "../blog-src/.github/workflows/$f.yml" workflows/ 2>/dev/null
done

# 4. import 경로는 core 패키지 기준으로 일괄 수정 필요 (sys.path 또는 패키지화)

# 5. GitHub Secrets 이전 (새 저장소 Settings → Secrets):
#    ANTHROPIC_API_KEY, GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN, BLOGGER_BLOG_ID,
#    NAVER_CLIENT_ID/SECRET, PIXABAY_API_KEY, BLOGS_CONFIG, GSC_SITE_URL
#    ⚠️ Secret 값은 파일로 옮기지 말 것 — GitHub UI에서 직접 입력

# 6. GitHub Pages: 새 저장소 Settings → Pages → apps/dashboard 기준 배포로 전환
```

## 보안 체크리스트 (이관 여부와 무관하게 유지)

- [x] 브라우저 직접 게시 제거 — Google client_secret·refresh_token을 localStorage에 저장하지 않음
- [x] API 키 관리 UI에서 Google 비밀 토큰은 GitHub Secrets 전용 (로컬 저장 금지)
- [x] 과거 localStorage에 저장된 장기 토큰 자동 삭제 (마이그레이션 코드)
- [x] 관리자 기능(실행·게시·수정)은 GitHub PAT 인증 필수 — PAT 없이는 조회만 가능
- [x] 자동 수리 전 데이터 백업 (logs/repair_backups/, 최근 10개 유지)
- [x] 수리 후 파일 손상 감지 시 백업에서 자동 롤백 + repair_history에 기록
- [x] 변경 이력: post_registry / run_history / title_changes / code_repairs / repair_history
- [ ] PAT는 fine-grained(이 저장소 한정, Actions:write + Contents:write)로 발급 권장
