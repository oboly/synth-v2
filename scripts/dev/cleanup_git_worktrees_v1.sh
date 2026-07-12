#!/usr/bin/env bash
# Safe cleanup for explicitly allowlisted, already-integrated Git worktrees.
set -euo pipefail

REPO_ROOT="/home/gurk/projects/synth-v2"
PR79_BRANCH="feature/native-short-map-level-status-chain-v1"
BREATHLINE_V2_PATH="$REPO_ROOT/.claude/worktrees/breathline-v2-canonical-campaign-v1"
APPLY=0
ALLOWLIST=()
REMOVED=0

usage() {
    cat <<'EOF'
Usage: scripts/dev/cleanup_git_worktrees_v1.sh [--apply] --allow PATH [--allow PATH ...]

Default mode is dry-run. --apply is required to remove a worktree.
Every removal target must be supplied with --allow. Branches are never deleted.
EOF
}

log() {
    printf '%s cleanup_git_worktrees_v1: %s\n' "$(date -Is)" "$*"
}

fail() {
    log "SAFETY_FAILURE $*"
    exit 1
}

is_registered_worktree() {
    local target="$1"
    git -C "$REPO_ROOT" worktree list --porcelain | awk -v target="$target" \
        '$1 == "worktree" && substr($0, 10) == target { found = 1 } END { exit !found }'
}

has_active_cwd() {
    local target="$1" proc cwd pid
    for proc in /proc/[0-9]*; do
        pid="${proc##*/}"
        [[ "$pid" == "$$" || "$pid" == "$PPID" ]] && continue
        cwd=$(readlink "$proc/cwd" 2>/dev/null || true)
        [[ "$cwd" == "$target" || "$cwd" == "$target"/* ]] && return 0
    done
    return 1
}

is_protected_path() {
    local target="$1"
    case "$target" in
        "$REPO_ROOT"|"$BREATHLINE_V2_PATH"|/home/gurk/releases/*)
            return 0
            ;;
        /home/gurk/projects/synth-v2-breathline-baseline-replay|\
        /home/gurk/projects/synth-v2-map-lifecycle-audit-core|\
        /home/gurk/projects/synth-v2-map-rollover|\
        /home/gurk/projects/synth-v2-native-short-map-audit-v1|\
        /home/gurk/projects/synth-v2-native-short-map-materializer-v1|\
        /home/gurk/projects/synth-v2-native-short-health-a3|\
        /tmp/synth-v2-pr79-post-merge-acceptance)
            return 0
            ;;
    esac
    return 1
}

verify_target() {
    local target="$1" head branch
    [[ "$target" = /* ]] || fail "allowlist path must be absolute: $target"
    [[ -d "$target" ]] || fail "path does not exist: $target"
    is_registered_worktree "$target" || fail "path is not a registered worktree: $target"
    is_protected_path "$target" && fail "protected path: $target"
    [[ -z "$(git -C "$target" status --porcelain)" ]] || fail "dirty worktree: $target"
    has_active_cwd "$target" && fail "active process cwd under worktree: $target"

    head=$(git -C "$target" rev-parse HEAD)
    branch=$(git -C "$target" symbolic-ref --quiet --short HEAD 2>/dev/null || true)
    if [[ -n "$branch" ]]; then
        [[ "$branch" != "$PR79_BRANCH" ]] || fail "PR #79 branch: $target"
        git -C "$REPO_ROOT" show-ref --verify --quiet "refs/heads/$branch" || fail "missing local branch: $branch"
        git -C "$REPO_ROOT" merge-base --is-ancestor "$branch" origin/main || \
            fail "branch is not merged into origin/main: $branch"
        [[ -z "$(git -C "$REPO_ROOT" rev-list origin/main.."$branch")" ]] || \
            fail "branch has commits absent from origin/main: $branch"
        log "VERIFIED merged branch path=$target branch=$branch head=$head"
    else
        git -C "$REPO_ROOT" merge-base --is-ancestor "$head" origin/main || \
            fail "detached HEAD is not an ancestor of origin/main: $target"
        log "VERIFIED detached ancestor path=$target head=$head"
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --apply) APPLY=1 ;;
        --allow)
            [[ $# -ge 2 ]] || fail "--allow requires an absolute path"
            ALLOWLIST+=("$2")
            shift
            ;;
        -h|--help) usage; exit 0 ;;
        *) fail "unknown argument: $1" ;;
    esac
    shift
done

[[ "$(pwd -P)" == "$REPO_ROOT" ]] || fail "run only from repository root: $REPO_ROOT"
[[ ${#ALLOWLIST[@]} -gt 0 ]] || fail "at least one explicit --allow path is required"

log "STARTED mode=$([[ $APPLY -eq 1 ]] && printf apply || printf dry-run) allowlist_count=${#ALLOWLIST[@]}"
git fetch --prune origin

for target in "${ALLOWLIST[@]}"; do
    verify_target "$target"
    if [[ "$APPLY" -eq 0 ]]; then
        log "DRY_RUN would_remove=$target"
        continue
    fi
    git -C "$REPO_ROOT" worktree remove "$target"
    REMOVED=$((REMOVED + 1))
    log "REMOVED path=$target"
done

if [[ "$APPLY" -eq 1 && "$REMOVED" -gt 0 ]]; then
    git -C "$REPO_ROOT" worktree prune
    log "PRUNED metadata after_removed=$REMOVED"
fi

log "FINISHED mode=$([[ $APPLY -eq 1 ]] && printf apply || printf dry-run) removed=$REMOVED"
