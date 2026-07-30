#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${SYNTH_REPO_DIR:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
LOCK_FILE="${SYNTH_SECTOR_ROTATION_DASHBOARD_LOCK:-/tmp/synth-sector-rotation-dashboard-v1.lock}"
OUTPUT_ROOT="${SYNTH_SECTOR_ROTATION_OUTPUT_ROOT:-/var/www/html/synth}"
VENUE="${SYNTH_SECTOR_ROTATION_VENUE:-bitvavo}"
started_epoch="$(date +%s)"

usage() {
    echo "usage: $0"
}

if [[ "$#" -ne 0 ]]; then
    usage >&2
    exit 2
fi

echo "STARTED runner=run_sector_rotation_dashboard_render_once mode=read_only ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "venue=${VENUE} output_root=${OUTPUT_ROOT} lock_file=${LOCK_FILE}"
echo "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0"
echo "selection_engine=none decision_gate=none execution_planner=none executor=none"
echo "db_writes=0"

cd "${REPO_DIR}"

if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    if [[ -f "venv/bin/activate" ]]; then
        # shellcheck disable=SC1091
        source "venv/bin/activate"
    elif [[ -f ".venv/bin/activate" ]]; then
        # shellcheck disable=SC1091
        source ".venv/bin/activate"
    else
        echo "FAILED runner=run_sector_rotation_dashboard_render_once reason=VENV_MISSING exit_status=1" >&2
        exit 1
    fi
fi

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
    echo "SKIPPED runner=run_sector_rotation_dashboard_render_once reason=LOCK_HELD exit_status=0"
    exit 0
fi

status=0
python -m src.reporting.run_sector_rotation_dashboard_v1 \
    --venue "${VENUE}" \
    --output-root "${OUTPUT_ROOT}" \
    --output summary || status=$?

elapsed_sec=$(( $(date +%s) - started_epoch ))
echo "FINISHED runner=run_sector_rotation_dashboard_render_once exit_status=${status} elapsed_sec=${elapsed_sec} ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
exit "${status}"
