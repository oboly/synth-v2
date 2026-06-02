#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

if [ -f ".venv/bin/activate" ]; then
  . ".venv/bin/activate"
elif [ -f "venv/bin/activate" ]; then
  . "venv/bin/activate"
fi

export SYNTH_LIVE_EXECUTION_PERMISSION="${SYNTH_LIVE_EXECUTION_PERMISSION:-NOT_GRANTED}"
export SYNTH_BROKER_WRITE_PERMISSION="${SYNTH_BROKER_WRITE_PERMISSION:-NOT_GRANTED}"
export SYNTH_ROTATION_PREVIEW_DASHBOARD_HTML="${SYNTH_ROTATION_PREVIEW_DASHBOARD_HTML:-/var/www/html/synth/rotation-preview.html}"
export SYNTH_ENTRY_CANDIDATE_DASHBOARD_HTML="${SYNTH_ENTRY_CANDIDATE_DASHBOARD_HTML:-/var/www/html/synth/entry-candidates.html}"
VENUE="${SYNTH_MVP_DASHBOARD_VENUE:-bitvavo}"
QUOTE="${SYNTH_MARKET_PRICE_SNAPSHOT_QUOTE:-EUR}"
FAST_RECOMPUTE_INTERVAL="${SYNTH_FAST_RECOMPUTE_INTERVAL:-4h}"

echo "[MVP_DASHBOARD_RENDER][START] $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "[MVP_DASHBOARD][SAFETY] live_execution=${SYNTH_LIVE_EXECUTION_PERMISSION} broker_write=${SYNTH_BROKER_WRITE_PERMISSION}"
echo "[MVP_DASHBOARD][SAFETY] broker_private_calls=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0 decision_gate_changes=0 execution_planner_changes=0 executor=none account_awareness=0"
echo "[MVP_DASHBOARD][CONFIG] venue=${VENUE} quote=${QUOTE} interval=${FAST_RECOMPUTE_INTERVAL}"

run_step() {
  echo
  echo "[MVP_DASHBOARD_RENDER][STEP] $*"
  "$@"
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "[MVP_DASHBOARD_RENDER][FAIL] step failed status=$status command=$*"
    exit "$status"
  fi
}

run_step python -m src.reporting.run_position_rotation_static_dashboard_v1 \
  --venue "${VENUE}" \
  --quote "${QUOTE}" \
  --interval "${FAST_RECOMPUTE_INTERVAL}" \
  --trading-account-id 2 \
  --output-html "${SYNTH_ROTATION_PREVIEW_DASHBOARD_HTML}" \
  --output summary

run_step python -m src.reporting.run_entry_candidate_static_dashboard_v1 \
  --venue "${VENUE}" \
  --interval "${FAST_RECOMPUTE_INTERVAL}" \
  --output-html "${SYNTH_ENTRY_CANDIDATE_DASHBOARD_HTML}" \
  --output summary

echo
echo "[MVP_DASHBOARD_RENDER][DONE] $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "[MVP_DASHBOARD_RENDER][OUTPUT] ${SYNTH_ROTATION_PREVIEW_DASHBOARD_HTML}"
echo "[MVP_DASHBOARD_RENDER][OUTPUT] ${SYNTH_ENTRY_CANDIDATE_DASHBOARD_HTML}"
echo "[MVP_DASHBOARD_RENDER][OUTPUT] $(dirname "${SYNTH_ROTATION_PREVIEW_DASHBOARD_HTML}")/index.html"
