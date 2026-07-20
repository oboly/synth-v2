#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${SYNTH_REPO_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
LOCK_FILE="${SYNTH_ROTATION_PRESSURE_LOCK:-/tmp/synth-market-rotation-pressure-v1.lock}"
VENUE="${SYNTH_ROTATION_PRESSURE_VENUE:-bitvavo}"
started_epoch="$(date +%s)"

usage() {
    echo "usage: $0 --write-db"
}

if [[ "${1:-}" != "--write-db" || "$#" -ne 1 ]]; then
    usage >&2
    exit 2
fi

echo "STARTED runner=run_market_rotation_pressure_once mode=market_data_write ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "venue=${VENUE} lock_file=${LOCK_FILE}"
echo "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0"
echo "selection_engine=none decision_gate=none execution_planner=none executor=none"
echo "reporting=none dashboard_publish=none"

cd "${REPO_DIR}" || exit 1

if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    if [[ -f "venv/bin/activate" ]]; then
        # shellcheck disable=SC1091
        source "venv/bin/activate"
    elif [[ -f ".venv/bin/activate" ]]; then
        # shellcheck disable=SC1091
        source ".venv/bin/activate"
    else
        echo "FAILED runner=run_market_rotation_pressure_once reason=VENV_MISSING exit_status=1" >&2
        exit 1
    fi
fi

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
    echo "FAILED runner=run_market_rotation_pressure_once reason=LOCK_HELD exit_status=75" >&2
    exit 75
fi

run_step() {
    local label="$1"
    shift
    local step_started
    local status
    step_started="$(date +%s)"
    echo "PHASE_STARTED phase=${label}"
    "$@"
    status=$?
    if [[ "${status}" -ne 0 ]]; then
        echo "PHASE_FAILED phase=${label} exit_status=${status} elapsed_sec=$(( $(date +%s) - step_started ))" >&2
        return "${status}"
    fi
    echo "PHASE_FINISHED phase=${label} exit_status=0 elapsed_sec=$(( $(date +%s) - step_started ))"
}

# Fail closed before launching the write-capable rotation writers. Same shared
# authorization semantics as the Python mutation boundary in the rotation
# history/pressure runners.
WRITER_CAPABILITY_ID="market_rotation_pressure"
WRITER_SERVICE="synth-market-rotation-pressure-writer.service"
export SYNTH_WRITER_CAPABILITY_ID="${WRITER_CAPABILITY_ID}"
export SYNTH_WRITER_EXECUTION_MODE="${SYNTH_WRITER_EXECUTION_MODE:-PRODUCTION}"
GUARD_ARGS=(--capability "${WRITER_CAPABILITY_ID}" --service "${WRITER_SERVICE}" --checkout-path "${REPO_DIR}" --mode "${SYNTH_WRITER_EXECUTION_MODE}")
if [[ -n "${SYNTH_WRITER_ACCEPTANCE_PERMIT:-}" ]]; then
    GUARD_ARGS+=(--acceptance-permit "${SYNTH_WRITER_ACCEPTANCE_PERMIT}")
fi
if ! python -m src.operations.verify_writer_capability_authorization_v1 "${GUARD_ARGS[@]}"; then
    echo "FAILED runner=run_market_rotation_pressure_once reason=WRITER_AUTHORIZATION_DENIED capability=${WRITER_CAPABILITY_ID} mode=${SYNTH_WRITER_EXECUTION_MODE}" >&2
    exit 3
fi

status=0
run_step rotation_history \
    python -m src.research.run_market_rotation_history_v1 \
    --venue "${VENUE}" \
    --write-db || status=$?

if [[ "${status}" -eq 0 ]]; then
    run_step rotation_pressure \
        python -m src.research.run_market_rotation_pressure_v1 \
        --venue "${VENUE}" \
        --write-db || status=$?
fi

elapsed_sec=$(( $(date +%s) - started_epoch ))
if [[ "${status}" -eq 0 ]]; then
    echo "FINISHED runner=run_market_rotation_pressure_once exit_status=0 elapsed_sec=${elapsed_sec} ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
else
    echo "FAILED runner=run_market_rotation_pressure_once exit_status=${status} elapsed_sec=${elapsed_sec} ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >&2
fi
exit "${status}"
