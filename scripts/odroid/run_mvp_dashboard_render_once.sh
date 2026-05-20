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
FAST_RECOMPUTE_REFRESH_ENABLED="${SYNTH_FAST_RECOMPUTE_REFRESH_ENABLED:-1}"
FAST_RECOMPUTE_INTERVAL="${SYNTH_FAST_RECOMPUTE_INTERVAL:-4h}"
FAST_RECOMPUTE_MAX_ASSETS="${SYNTH_FAST_RECOMPUTE_MAX_ASSETS:-8}"

echo "[MVP_DASHBOARD][START] $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "[MVP_DASHBOARD][SAFETY] live_execution=${SYNTH_LIVE_EXECUTION_PERMISSION} broker_write=${SYNTH_BROKER_WRITE_PERMISSION}"
echo "[MVP_DASHBOARD][SAFETY] broker_private_calls=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0 decision_gate_changes=0 execution_planner_changes=0 executor=none account_awareness=0"
echo "[MVP_DASHBOARD][CONFIG] venue=${VENUE} quote=${QUOTE} fast_recompute_enabled=${FAST_RECOMPUTE_REFRESH_ENABLED} fast_recompute_interval=${FAST_RECOMPUTE_INTERVAL} fast_recompute_max_assets=${FAST_RECOMPUTE_MAX_ASSETS}"

run_step() {
  echo
  echo "[MVP_DASHBOARD][STEP] $*"
  "$@"
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "[MVP_DASHBOARD][FAIL] step failed status=$status command=$*"
    exit "$status"
  fi
}

run_step python -m src.market_data.run_market_price_snapshot_v1 \
  --venue "${VENUE}" \
  --quote "${QUOTE}" \
  --write-db \
  --output none

if [ "${FAST_RECOMPUTE_REFRESH_ENABLED}" = "0" ]; then
  echo
  echo "[MVP_DASHBOARD][FAST_RECOMPUTE] skipped SYNTH_FAST_RECOMPUTE_REFRESH_ENABLED=0"
else
  echo
  echo "[MVP_DASHBOARD][FAST_RECOMPUTE] market-only refresh enabled; running before dashboard render"
  echo "[MVP_DASHBOARD][FAST_RECOMPUTE][SAFETY] broker_private_calls=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0 decision_gate_changes=0 execution_planner_changes=0 executor=none account_awareness=0"
  run_step python -m src.advice.run_fast_recompute_lifecycle_refresh_v1 \
    --venue "${VENUE}" \
    --interval "${FAST_RECOMPUTE_INTERVAL}" \
    --quote "${QUOTE}" \
    --max-assets "${FAST_RECOMPUTE_MAX_ASSETS}" \
    --write-db \
    --output table
fi

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
echo "[MVP_DASHBOARD][DONE] $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "[MVP_DASHBOARD][OUTPUT] ${SYNTH_ROTATION_PREVIEW_DASHBOARD_HTML}"
echo "[MVP_DASHBOARD][OUTPUT] ${SYNTH_ENTRY_CANDIDATE_DASHBOARD_HTML}"
echo "[MVP_DASHBOARD][OUTPUT] $(dirname "${SYNTH_ROTATION_PREVIEW_DASHBOARD_HTML}")/index.html"
