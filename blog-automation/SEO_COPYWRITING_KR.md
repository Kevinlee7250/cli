# SEO Copywriting KR — Blogger 연결

Notion 원본 스킬: https://app.notion.com/p/421f5be9f28f81be8f7fea0c59e8ad68

이 저장소에 새 SEO 검수기를 비활성 기본값으로 추가한다. 원본 프로젝트의 키워드 수집, 본문 생성, 기존 AdSense 검증, `final_editor.py`, Blogger 업로드 동작은 그대로 유지한다.

## 활성화 (별도 운영 승인 후)

`SEO_KR_PREFLIGHT=1` 을 명시한 경우에만 `main.py`의 **최종 편집 후, 초안 레지스트리 저장 전**에 한국어 SEO 구조 점검을 수행한다. 명백한 구조적 오류(제목/본문 부재, 빈 링크 등)는 기존 `pending` 흐름으로 보류한다. 키워드·메타·H2·이미지 ALT 미흡은 경고로 표시하되 정상적인 짧은 글을 자의적으로 막지 않는다.

이 검수기는 실제 Google 검색 결과와 GSC 수치를 수집하지 않으며 검색 순위나 AdSense 정책 통과 여부를 판정하지 않는다. 원본 `write-blog-content`의 출처·경험 검수와 기존 `adsense_validator.py`는 계속 적용한다.

테스트: `cd blog-automation && python -m unittest tests.test_seo_kr_preflight` (환경에 따라 `python -m unittest discover -s tests -p 'test_seo_kr_preflight.py'`).

코드 통합은 기능 플래그로만 이뤄지며, PR 병합·실운영 환경변수 변경·Blogger 게시·예약은 수행하지 않는다.

관련 파일: `seo_kr_preflight.py`, `tests/test_seo_kr_preflight.py`, `main.py`. 최초 설계 2026-11-23. 원본 참고: https://github.com/judicael-s/copywriting-skill/blob/HEAD/skills%2Fseo-copywriting%2FSKILL.md
