#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${SYNTH_REPO_DIR:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
LOCK_FILE="${SYNTH_LIVE_LIKE_RETENTION_LOCK:-/tmp/synth-live-like-runtime-retention-v1.lock}"
RETENTION_DAYS="${SYNTH_LIVE_LIKE_RETENTION_DAYS:-7}"
MIN_RECENT_RUNS="${SYNTH_LIVE_LIKE_RETENTION_MIN_RECENT_RUNS:-288}"
APPLY="${SYNTH_LIVE_LIKE_RETENTION_APPLY:-0}"
started_epoch="$(date +%s)"

echo "STARTED runner=run_live_like_runtime_retention_once mode=dry_run_unless_apply ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "repo_dir=${REPO_DIR} retention_days=${RETENTION_DAYS} min_recent_runs=${MIN_RECENT_RUNS} apply=${APPLY} lock_file=${LOCK_FILE}"
echo "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0"
echo "decision_gate=none execution_planner=none executor=none"

cd "${REPO_DIR}"

if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    if [[ -f "venv/bin/activate" ]]; then
        # shellcheck disable=SC1091
        source "venv/bin/activate"
    elif [[ -f ".venv/bin/activate" ]]; then
        # shellcheck disable=SC1091
        source ".venv/bin/activate"
    else
        echo "FAILED runner=run_live_like_runtime_retention_once reason=VENV_MISSING exit_status=1" >&2
        exit 1
    fi
fi

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
    echo "SKIPPED runner=run_live_like_runtime_retention_once reason=LOCK_HELD exit_status=0"
    exit 0
fi

PYTHON_ARGS=(
    -m src.ops.live_like_runtime_retention_v1
    --repo-root "${REPO_DIR}"
    --retention-days "${RETENTION_DAYS}"
    --min-recent-runs "${MIN_RECENT_RUNS}"
)

if [[ "${APPLY}" == "1" ]]; then
    PYTHON_ARGS+=(--apply)
fi

set +e
python "${PYTHON_ARGS[@]}"
status=$?
set -e

elapsed_sec=$(( $(date +%s) - started_epoch ))
echo "FINISHED runner=run_live_like_runtime_retention_once exit_status=${status} elapsed_sec=${elapsed_sec} ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
exit "${status}"
