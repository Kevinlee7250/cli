#!/usr/bin/env bash
# 게시 기록 커밋을 latest에 올립니다 (AIOPS-59). 호출 전에 커밋은 끝나 있어야 합니다.
#
# 왜: 2026-11-25 run 45548904567 — 게시는 성공했는데 inbound-links 워크플로가
# 먼저 push했고, rebase가 보고서 JSON 2개에서 충돌했습니다. rebase를 abort하지
# 않아 2·3차 재시도는 "unmerged files"로 아무것도 못 한 채 job이 실패했습니다.
#
# 종료 코드: 0 = push 성공, 또는 "게시는 성공 · 기록만 실패"(record_failed=true 출력)
#            1 = 게시 0건(또는 확인 불가)인데 push도 실패
set -uo pipefail

# 매번 통째로 다시 만드는 보고서만 자동 해결합니다. 누적 기록(레지스트리·발행
# 대기 등)은 자동으로 덮어쓰지 않습니다.
AUTO_RESOLVE="docs/data/inbound_links.json docs/data/internal_links.json"

rebasing() {
  [ -d "$(git rev-parse --git-path rebase-merge)" ] || [ -d "$(git rev-parse --git-path rebase-apply)" ]
}

unmerged() { git diff --name-only --diff-filter=U; }

# 충돌 파일이 모두 허용 목록이면 우리 커밋 쪽을 채택하고 rebase를 이어갑니다.
resolve_rebase() {
  local files f
  while rebasing; do
    files="$(unmerged)"
    [ -n "$files" ] || return 1
    for f in $files; do
      case " $AUTO_RESOLVE " in
        *" $f "*) ;;
        *) echo "자동 해결 대상이 아닌 충돌: $f"; return 1 ;;
      esac
    done
    for f in $files; do
      # rebase 중 theirs = 지금 다시 얹는 우리 커밋
      git checkout --theirs -- "$f" && git add -f -- "$f" || return 1
      echo "충돌 자동 해결(이번 실행 보고서 채택): $f"
    done
    if ! GIT_EDITOR=true git rebase --continue; then
      rebasing || return 1
      # 해결 결과가 원격과 같아 빈 커밋이면 건너뜁니다. 새 충돌이면 다음 반복에서 처리.
      if [ -z "$(unmerged)" ] && git diff --cached --quiet; then
        git rebase --skip || true
      fi
    fi
  done
}

# autostash 복원이 충돌하면 미병합 파일이 남아 다음 시도를 막습니다.
# 해당 파일만 HEAD로 되돌립니다 (원래 변경은 stash에 남습니다).
clear_unmerged() {
  local f
  for f in $(unmerged); do
    echo "autostash 복원 충돌 — HEAD로 되돌림: $f"
    git reset -q HEAD -- "$f"
    git checkout -q HEAD -- "$f"
  done
}

main() {
  local label="${1:-blog}" branch="${PUSH_BRANCH:-latest}" max="${PUSH_MAX_TRIES:-5}"
  local backoff="${PUSH_BACKOFF_SEC:-5}" published ok=0 i
  # git 작업이 파일을 바꾸기 전에 읽습니다. 확인 못 하면 0 (= 실패로 처리).
  published="$(python3 -c "import json;print(int(json.load(open('blog-automation/logs/last_publish_summary.json'))['published']))" 2>/dev/null || echo 0)"

  for i in $(seq 1 "$max"); do
    if ! git pull --rebase --autostash origin "$branch"; then
      if rebasing && ! resolve_rebase; then
        git rebase --abort || true
      fi
    fi
    clear_unmerged
    if ! rebasing && git push origin "HEAD:$branch"; then
      # push가 "up-to-date"여도 우리 커밋이 빠진 상태일 수는 없습니다(abort 시 push 거부).
      ok=1
      break
    fi
    echo "push 재시도 $i/$max..."
    [ "$i" -lt "$max" ] && sleep $((i * backoff + RANDOM % (backoff + 1)))
  done

  [ "$ok" = "1" ] && return 0

  if [ "$published" -gt 0 ]; then
    local msg="$label 게시 ${published}건 성공 · 기록 커밋 실패. 같은 글이 다시 올라갈 수 있으니 재실행하지 말고, 첨부 artifact로 기록을 반영하세요."
    echo "::warning title=발행 성공 · 기록 커밋 실패::$msg"
    echo "### ⚠️ $msg" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
    echo "record_failed=true" >> "${GITHUB_OUTPUT:-/dev/null}"
    echo "published=$published" >> "${GITHUB_OUTPUT:-/dev/null}"
    return 0
  fi
  echo "::error title=기록 커밋 실패::$label push ${max}회 실패 (게시 0건 또는 확인 불가)"
  return 1
}

main "$@"; exit $?
