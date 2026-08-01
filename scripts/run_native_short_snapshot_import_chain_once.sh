#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${SYNTH_REPO_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
LOCK_FILE="${SYNTH_NATIVE_SHORT_SNAPSHOT_IMPORT_LOCK:-/tmp/synth-native-short-snapshot-import-v1.lock}"
STAGING_DIR="${SYNTH_NATIVE_SHORT_SNAPSHOT_STAGING_DIR:-/tmp/synth-native-short-snapshot-staging-v1}"
CANONICAL_DIR="${SYNTH_NATIVE_SHORT_CONTEXT_SNAPSHOT_DIR:-/var/www/html/synth/_runtime/native_short_context_snapshot_v1}"
EXPECTED_HOST="${SYNTH_NATIVE_SHORT_SNAPSHOT_IMPORT_EXPECTED_HOST:?SYNTH_NATIVE_SHORT_SNAPSHOT_IMPORT_EXPECTED_HOST is required}"

echo "STARTED runner=run_native_short_snapshot_import_chain_once mode=filesystem_import worker_count=1 ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "staging_dir=${STAGING_DIR} canonical_dir=${CANONICAL_DIR} expected_host=${EXPECTED_HOST}"
echo "db_writes=0 broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0"
echo "decision_gate=none execution_planner=none executor=none"

cd "${REPO_DIR}" || exit 1

if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    if [[ -f "venv/bin/activate" ]]; then
        # shellcheck disable=SC1091
        source "venv/bin/activate"
    elif [[ -f ".venv/bin/activate" ]]; then
        # shellcheck disable=SC1091
        source ".venv/bin/activate"
    else
        echo "FAILED runner=run_native_short_snapshot_import_chain_once reason=VENV_MISSING exit_status=1" >&2
        exit 1
    fi
fi

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
    echo "FAILED runner=run_native_short_snapshot_import_chain_once reason=LOCK_HELD exit_status=75 lock_file=${LOCK_FILE}" >&2
    exit 75
fi

started_epoch="$(date +%s)"

if ! bash "${SCRIPT_DIR}/fetch_native_short_snapshot_from_gurkdb.sh" "${STAGING_DIR}"; then
    echo "FAILED runner=run_native_short_snapshot_import_chain_once reason=FETCH_FAILED exit_status=2" >&2
    exit 2
fi

python -m src.operations.run_native_short_context_snapshot_import_v1 \
    --staged-dir "${STAGING_DIR}" \
    --canonical-dir "${CANONICAL_DIR}" \
    --expected-host "${EXPECTED_HOST}" \
    --output summary
status=$?
elapsed_sec=$(( $(date +%s) - started_epoch ))

if [[ "${status}" -eq 0 ]]; then
    echo "FINISHED runner=run_native_short_snapshot_import_chain_once exit_status=0 elapsed_sec=${elapsed_sec} ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
else
    echo "FAILED runner=run_native_short_snapshot_import_chain_once exit_status=${status} elapsed_sec=${elapsed_sec} ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >&2
fi
exit "${status}"
