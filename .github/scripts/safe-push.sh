#!/usr/bin/env bash
# 자동화 기록 커밋을 안전하게 push합니다 (AIOPS-59).
#
# 2026-11-25 blog3 (#390): 역방향 내부 링크 워크플로가 같은 순간에 push →
# rebase 충돌 → rebase를 중단하지 않아 2·3차 재시도가 "unmerged files"로
# 즉시 실패했습니다.
#
#   1) 매 시도 전후로 진행 중인 rebase를 정리합니다.
#   2) 다음 실행에서 다시 만들어지는 리포트만 충돌 시 원격 최신본을 씁니다.
#   3) 그 밖의 충돌은 임의로 해결하지 않고 실패하며, 커밋을 패치로 남깁니다.
#
# 사용: bash .github/scripts/safe-push.sh [브랜치]   (성공 0 / 실패 1)
set -u

BRANCH="${1:-latest}"
MAX="${PUSH_MAX_ATTEMPTS:-5}"
WAIT="${PUSH_RETRY_WAIT:-5}"
PATCH_PATH="${UNPUSHED_PATCH:-blog-automation/logs/unpushed-record.patch}"
# 전체 글을 다시 훑어 새로 쓰는 파일만 넣으세요. 누적 기록(post_registry 등)은 금지.
REGENERABLE="docs/data/internal_links.json docs/data/inbound_links.json"

rebasing() {
  [ -d "$(git rev-parse --git-path rebase-merge)" ] ||
    [ -d "$(git rev-parse --git-path rebase-apply)" ]
}

abort_rebase() {
  if rebasing; then git rebase --abort >/dev/null 2>&1 || true; fi
}

resolve_regenerable() {
  local files f
  files="$(git -c core.quotePath=false diff --name-only --diff-filter=U)"
  [ -n "$files" ] || return 1
  while IFS= read -r f; do
    case " $REGENERABLE " in
      *" $f "*) ;;
      *) echo "자동 해결 대상이 아닌 충돌: $f"; return 1 ;;
    esac
  done <<<"$files"
  while IFS= read -r f; do
    # rebase 중의 --ours 는 올라타는 쪽(원격 최신본)입니다.
    git checkout --ours -- "$f" && git add -f -- "$f" || return 1
    echo "재생성 가능한 리포트 충돌 — 원격 최신본 사용: $f"
  done <<<"$files"
  if git diff --cached --quiet; then
    git rebase --skip
  else
    GIT_EDITOR=true git rebase --continue
  fi
}

# autostash 복원이 충돌하면 unmerged 상태가 남아 다음 시도가 막힙니다.
# 커밋 대상이 아닌 작업 트리 잔여물이므로 HEAD 상태로 되돌립니다(stash에는 남음).
clear_unmerged() {
  git -c core.quotePath=false diff --name-only --diff-filter=U |
    while IFS= read -r f; do
      git reset -q HEAD -- "$f" && git checkout -q -- "$f"
    done
}

for i in $(seq 1 "$MAX"); do
  abort_rebase
  if git fetch -q origin "$BRANCH"; then
    if git rebase --autostash "origin/$BRANCH" || resolve_regenerable; then
      if ! rebasing; then
        clear_unmerged
        if git push origin "HEAD:$BRANCH"; then
          echo "push 성공 (시도 $i/$MAX)"
          exit 0
        fi
      fi
    fi
  fi
  abort_rebase
  echo "push 재시도 $i/$MAX..."
  [ "$i" -lt "$MAX" ] && sleep $((i * WAIT))
done

mkdir -p "$(dirname "$PATCH_PATH")"
git format-patch --stdout "origin/$BRANCH..HEAD" >"$PATCH_PATH" 2>/dev/null &&
  echo "push하지 못한 커밋을 패치로 저장: $PATCH_PATH"
echo "push ${MAX}회 실패"
exit 1
