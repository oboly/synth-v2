#!/usr/bin/env bash
# Locked wrapper: fetch gurkdb's published native SHORT snapshot into a
# temporary staging directory, then validate and atomically install it into
# the local canonical path via the Python importer. Consumer-side only.
#
# No database, broker, account, decision, planning, execution, or canonical
# market-truth writes happen here or in either step it calls.
#
# Required environment:
#   SYNTH_NATIVE_SHORT_SNAPSHOT_IMPORT_EXPECTED_HOST   must equal this host's hostname
#   SYNTH_NATIVE_SHORT_SNAPSHOT_SOURCE_HOST            ssh host/alias for gurkdb
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${SYNTH_REPO_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
LOCK_FILE="${SYNTH_NATIVE_SHORT_SNAPSHOT_IMPORT_LOCK:-/tmp/synth-native-short-snapshot-import-v1.lock}"
CANONICAL_DIR="${SYNTH_NATIVE_SHORT_CONTEXT_SNAPSHOT_DIR:-/var/www/html/synth/_runtime/native_short_context_snapshot_v1}"
EXPECTED_HOST="${SYNTH_NATIVE_SHORT_SNAPSHOT_IMPORT_EXPECTED_HOST:?SYNTH_NATIVE_SHORT_SNAPSHOT_IMPORT_EXPECTED_HOST is required}"

ACTUAL_HOST="$(hostname)"
if [[ "${ACTUAL_HOST}" != "${EXPECTED_HOST}" ]]; then
    echo "FAILED runner=run_native_short_snapshot_import_chain_once reason=WRONG_HOST expected_host=${EXPECTED_HOST} actual_host=${ACTUAL_HOST} exit_status=4" >&2
    exit 4
fi

STAGING_DIR=""
LOCK_FD=9

cleanup() {
    local exit_status=$?
    if [[ -n "${STAGING_DIR}" && -d "${STAGING_DIR}" ]]; then
        rm -rf -- "${STAGING_DIR}"
    fi
    exec 9>&- || true
    return "${exit_status}"
}
trap cleanup EXIT

STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/synth-native-short-snapshot-staging-v1.XXXXXXXX")"

echo "STARTED runner=run_native_short_snapshot_import_chain_once mode=filesystem_import worker_count=1 ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "staging_dir=${STAGING_DIR} canonical_dir=${CANONICAL_DIR} expected_host=${EXPECTED_HOST} actual_host=${ACTUAL_HOST}"
echo "db_writes=0 broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0"
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
        echo "FAILED runner=run_native_short_snapshot_import_chain_once reason=VENV_MISSING exit_status=1" >&2
        exit 1
    fi
fi

exec 9>"${LOCK_FILE}"
if ! flock -n "${LOCK_FD}"; then
    echo "FAILED runner=run_native_short_snapshot_import_chain_once reason=LOCK_HELD exit_status=75 lock_file=${LOCK_FILE}" >&2
    exit 75
fi

STARTED_EPOCH="$(date +%s)"

if ! bash "${SCRIPT_DIR}/fetch_native_short_snapshot_from_gurkdb.sh" "${STAGING_DIR}"; then
    echo "FAILED runner=run_native_short_snapshot_import_chain_once reason=FETCH_FAILED exit_status=2" >&2
    exit 2
fi

set +e
python -m src.operations.run_native_short_context_snapshot_import_v1 \
    --staged-dir "${STAGING_DIR}" \
    --canonical-dir "${CANONICAL_DIR}" \
    --expected-host "${EXPECTED_HOST}" \
    --output summary
STATUS=$?
set -e

ELAPSED_SEC=$(( $(date +%s) - STARTED_EPOCH ))

if [[ "${STATUS}" -eq 0 ]]; then
    echo "FINISHED runner=run_native_short_snapshot_import_chain_once exit_status=0 elapsed_sec=${ELAPSED_SEC} ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
else
    echo "FAILED runner=run_native_short_snapshot_import_chain_once exit_status=${STATUS} elapsed_sec=${ELAPSED_SEC} ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >&2
fi

exit "${STATUS}"
