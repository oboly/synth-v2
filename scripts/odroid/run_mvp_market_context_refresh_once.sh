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
VENUE="${SYNTH_MVP_DASHBOARD_VENUE:-bitvavo}"
QUOTE="${SYNTH_MARKET_PRICE_SNAPSHOT_QUOTE:-EUR}"
FAST_RECOMPUTE_REFRESH_ENABLED="${SYNTH_FAST_RECOMPUTE_REFRESH_ENABLED:-1}"
FAST_RECOMPUTE_INTERVAL="${SYNTH_FAST_RECOMPUTE_INTERVAL:-4h}"
FAST_RECOMPUTE_MAX_ASSETS="${SYNTH_FAST_RECOMPUTE_MAX_ASSETS:-8}"
STRUCTURAL_MISSING_REFRESH_ENABLED="${SYNTH_STRUCTURAL_MISSING_REFRESH_ENABLED:-1}"
STRUCTURAL_MISSING_MAX_ASSETS="${SYNTH_STRUCTURAL_MISSING_MAX_ASSETS:-8}"

echo "[MVP_MARKET_CONTEXT_REFRESH][START] $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "[MVP_MARKET_CONTEXT_REFRESH][SAFETY] live_execution=${SYNTH_LIVE_EXECUTION_PERMISSION} broker_write=${SYNTH_BROKER_WRITE_PERMISSION}"
echo "[MVP_MARKET_CONTEXT_REFRESH][SAFETY] broker_private_calls=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0 decision_gate_changes=0 execution_planner_changes=0 executor=none account_awareness=0"
echo "[MVP_MARKET_CONTEXT_REFRESH][CONFIG] venue=${VENUE} quote=${QUOTE} structural_missing_enabled=${STRUCTURAL_MISSING_REFRESH_ENABLED} structural_missing_max_assets=${STRUCTURAL_MISSING_MAX_ASSETS} fast_recompute_enabled=${FAST_RECOMPUTE_REFRESH_ENABLED} fast_recompute_interval=${FAST_RECOMPUTE_INTERVAL} fast_recompute_max_assets=${FAST_RECOMPUTE_MAX_ASSETS}"

run_step() {
  echo
  echo "[MVP_MARKET_CONTEXT_REFRESH][STEP] $*"
  "$@"
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "[MVP_MARKET_CONTEXT_REFRESH][FAIL] step failed status=$status command=$*"
    exit "$status"
  fi
}

run_step python -m src.market_data.run_market_price_snapshot_v1 \
  --venue "${VENUE}" \
  --quote "${QUOTE}" \
  --write-db \
  --output none

if [ "${STRUCTURAL_MISSING_REFRESH_ENABLED}" = "0" ]; then
  echo
  echo "[MVP_MARKET_CONTEXT_REFRESH][STRUCTURAL_MISSING] skipped SYNTH_STRUCTURAL_MISSING_REFRESH_ENABLED=0"
else
  echo
  echo "[MVP_MARKET_CONTEXT_REFRESH][STRUCTURAL_MISSING] market-only missing structural context refresh enabled"
  echo "[MVP_MARKET_CONTEXT_REFRESH][STRUCTURAL_MISSING][SAFETY] broker_private_calls=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0 decision_gate_changes=0 execution_planner_changes=0 executor=none account_awareness=0"
  run_step python -m src.advice.run_structural_missing_refresh_v1 \
    --venue "${VENUE}" \
    --interval "${FAST_RECOMPUTE_INTERVAL}" \
    --quote "${QUOTE}" \
    --max-assets "${STRUCTURAL_MISSING_MAX_ASSETS}" \
    --write-db \
    --output table
fi

if [ "${FAST_RECOMPUTE_REFRESH_ENABLED}" = "0" ]; then
  echo
  echo "[MVP_MARKET_CONTEXT_REFRESH][FAST_RECOMPUTE] skipped SYNTH_FAST_RECOMPUTE_REFRESH_ENABLED=0"
else
  echo
  echo "[MVP_MARKET_CONTEXT_REFRESH][FAST_RECOMPUTE] market-only refresh enabled"
  echo "[MVP_MARKET_CONTEXT_REFRESH][FAST_RECOMPUTE][SAFETY] broker_private_calls=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0 decision_gate_changes=0 execution_planner_changes=0 executor=none account_awareness=0"
  run_step python -m src.advice.run_fast_recompute_lifecycle_refresh_v1 \
    --venue "${VENUE}" \
    --interval "${FAST_RECOMPUTE_INTERVAL}" \
    --quote "${QUOTE}" \
    --max-assets "${FAST_RECOMPUTE_MAX_ASSETS}" \
    --write-db \
    --output table
fi

echo
echo "[MVP_MARKET_CONTEXT_REFRESH][DONE] $(date -u +%Y-%m-%dT%H:%M:%SZ)"
