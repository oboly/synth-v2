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
export SYNTH_PROFIT_PLAN_DASHBOARD_HTML="${SYNTH_PROFIT_PLAN_DASHBOARD_HTML:-/var/www/html/synth/profit-plan.html}"
export SYNTH_PROFIT_PLAN_DASHBOARD_JSON="${SYNTH_PROFIT_PLAN_DASHBOARD_JSON:-/var/www/html/synth/profit-plan.json}"
export SYNTH_OPEN_ORDERS_MONITOR_HTML="${SYNTH_OPEN_ORDERS_MONITOR_HTML:-/var/www/html/synth/open-orders-monitor.html}"
export SYNTH_MVP_PROFIT_PLAN_SYMBOLS="${SYNTH_MVP_PROFIT_PLAN_SYMBOLS:-WLD,ONDO}"
export SYNTH_MVP_PROFIT_PLAN_MARKETS="${SYNTH_MVP_PROFIT_PLAN_MARKETS:-WLD-EUR ONDO-EUR}"
export SYNTH_MVP_FIBO_TARGET_MAP_OUTPUT_DIR="${SYNTH_MVP_FIBO_TARGET_MAP_OUTPUT_DIR:-data/research/fibo_target_map_v1}"
VENUE="${SYNTH_MVP_DASHBOARD_VENUE:-bitvavo}"
QUOTE="${SYNTH_MARKET_PRICE_SNAPSHOT_QUOTE:-EUR}"
FAST_RECOMPUTE_INTERVAL="${SYNTH_FAST_RECOMPUTE_INTERVAL:-4h}"

echo "[MVP_DASHBOARD_RENDER][START] $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "[MVP_DASHBOARD][SAFETY] live_execution=${SYNTH_LIVE_EXECUTION_PERMISSION} broker_write=${SYNTH_BROKER_WRITE_PERMISSION}"
echo "[MVP_DASHBOARD][SAFETY] broker_private_calls=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0 decision_gate_changes=0 execution_planner_changes=0 executor=none account_awareness=0"
echo "[MVP_DASHBOARD][CONFIG] venue=${VENUE} quote=${QUOTE} interval=${FAST_RECOMPUTE_INTERVAL}"
echo "[MVP_DASHBOARD][CONFIG] profit_plan_symbols=${SYNTH_MVP_PROFIT_PLAN_SYMBOLS} profit_plan_markets=${SYNTH_MVP_PROFIT_PLAN_MARKETS}"

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

run_step python -m src.research.run_fibo_target_map_v1 \
  --symbols "${SYNTH_MVP_PROFIT_PLAN_SYMBOLS}" \
  --write-files \
  --output summary \
  --output-dir "${SYNTH_MVP_FIBO_TARGET_MAP_OUTPUT_DIR}"

run_step python -m src.reporting.run_manual_short_trader_profit_plan_v1 \
  --markets ${SYNTH_MVP_PROFIT_PLAN_MARKETS} \
  --fib-map-rows "${SYNTH_MVP_FIBO_TARGET_MAP_OUTPUT_DIR}/fibo_target_map_rows_v1.csv" \
  --monitor-html "${SYNTH_OPEN_ORDERS_MONITOR_HTML}" \
  --output-html "${SYNTH_PROFIT_PLAN_DASHBOARD_HTML}" \
  --output-json "${SYNTH_PROFIT_PLAN_DASHBOARD_JSON}" \
  --output summary

echo
echo "[MVP_DASHBOARD_RENDER][DONE] $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "[MVP_DASHBOARD_RENDER][OUTPUT] ${SYNTH_ROTATION_PREVIEW_DASHBOARD_HTML}"
echo "[MVP_DASHBOARD_RENDER][OUTPUT] ${SYNTH_ENTRY_CANDIDATE_DASHBOARD_HTML}"
echo "[MVP_DASHBOARD_RENDER][OUTPUT] ${SYNTH_PROFIT_PLAN_DASHBOARD_HTML}"
echo "[MVP_DASHBOARD_RENDER][OUTPUT] ${SYNTH_PROFIT_PLAN_DASHBOARD_JSON}"
echo "[MVP_DASHBOARD_RENDER][OUTPUT] $(dirname "${SYNTH_ROTATION_PREVIEW_DASHBOARD_HTML}")/index.html"
