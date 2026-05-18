#!/usr/bin/env bash

cd "$(dirname "$0")/../.."

if [ -f ".venv/bin/activate" ]; then
  . ".venv/bin/activate"
elif [ -f "venv/bin/activate" ]; then
  . "venv/bin/activate"
fi

export SYNTH_LIVE_EXECUTION_PERMISSION="${SYNTH_LIVE_EXECUTION_PERMISSION:-NOT_GRANTED}"
export SYNTH_BROKER_WRITE_PERMISSION="${SYNTH_BROKER_WRITE_PERMISSION:-NOT_GRANTED}"
export SYNTH_PAPER_ADVICE_DASHBOARD_HTML="${SYNTH_PAPER_ADVICE_DASHBOARD_HTML:-/var/www/html/synth/paper-advice.html}"
export SYNTH_ROTATION_PREVIEW_DASHBOARD_HTML="${SYNTH_ROTATION_PREVIEW_DASHBOARD_HTML:-/var/www/html/synth/rotation-preview.html}"
export SYNTH_MVP_RUN_MARKET_CHAIN="${SYNTH_MVP_RUN_MARKET_CHAIN:-0}"
export SYNTH_MVP_WRITE_PAPER_ADVICE="${SYNTH_MVP_WRITE_PAPER_ADVICE:-0}"
export SYNTH_MVP_RENDER_PAPER_DASHBOARD="${SYNTH_MVP_RENDER_PAPER_DASHBOARD:-0}"
export SYNTH_MARKET_PRICE_SNAPSHOT_QUOTE="${SYNTH_MARKET_PRICE_SNAPSHOT_QUOTE:-EUR}"

echo "[MVP][START] $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "[MVP][SAFETY] live_execution=${SYNTH_LIVE_EXECUTION_PERMISSION} broker_write=${SYNTH_BROKER_WRITE_PERMISSION}"

run_step() {
  echo
  echo "[MVP][STEP] $*"
  "$@"
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "[MVP][FAIL] step failed status=$status command=$*"
    exit "$status"
  fi
}

if [ "${SYNTH_MVP_RUN_MARKET_CHAIN}" = "1" ]; then
  run_step bash scripts/run_chain_4h.sh
else
  echo "[MVP][SKIP] market chain skipped; set SYNTH_MVP_RUN_MARKET_CHAIN=1 to run scripts/run_chain_4h.sh"
fi

run_step python -m src.operations.run_broker_balance_snapshot_writer_v1 \
  --account-code bitvavo_synth_read \
  --venue bitvavo \
  --write-db \
  --output none

run_step python -m src.operations.run_broker_account_position_snapshot_writer_v1 \
  --account-code bitvavo_synth_read \
  --venue bitvavo \
  --write-db \
  --output none

run_step python -m src.operations.run_decision_gate_position_source_audit_v1 \
  --account-code bitvavo_synth_read \
  --venue bitvavo \
  --output table

if [ "${SYNTH_MVP_WRITE_PAPER_ADVICE}" = "1" ]; then
  run_step python -m src.advice.run_paper_advice_policy_v1 \
    --venue bitvavo \
    --interval 4h \
    --write-db \
    --output none
else
  echo "[MVP][SKIP] paper advice policy write skipped; lifecycle/4h chain owns paper advice by default"
fi

if [ "${SYNTH_MVP_RENDER_PAPER_DASHBOARD}" = "1" ]; then
  if [ -f "scripts/odroid/run_paper_advice_dashboard_refresh_once.sh" ]; then
    run_step bash scripts/odroid/run_paper_advice_dashboard_refresh_once.sh
  else
    echo "[MVP][WARN] paper advice dashboard refresh script not found; skipping paper dashboard render"
  fi
else
  echo "[MVP][SKIP] paper advice dashboard render skipped; lifecycle runner owns paper-advice.html by default"
fi

run_step python -m src.market_data.run_market_price_snapshot_v1 \
  --venue bitvavo \
  --quote "${SYNTH_MARKET_PRICE_SNAPSHOT_QUOTE}" \
  --write-db \
  --output none

run_step python -m src.reporting.run_position_rotation_static_dashboard_v1 \
  --venue bitvavo \
  --quote "${SYNTH_MARKET_PRICE_SNAPSHOT_QUOTE}" \
  --interval 4h \
  --trading-account-id 2 \
  --output-html "${SYNTH_ROTATION_PREVIEW_DASHBOARD_HTML}" \
  --output summary

echo
echo "[MVP][DONE] $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "[MVP][OUTPUT] ${SYNTH_PAPER_ADVICE_DASHBOARD_HTML}"
echo "[MVP][OUTPUT] ${SYNTH_ROTATION_PREVIEW_DASHBOARD_HTML}"
echo "[MVP][OUTPUT] $(dirname "${SYNTH_ROTATION_PREVIEW_DASHBOARD_HTML}")/index.html"
