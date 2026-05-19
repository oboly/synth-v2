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
export SYNTH_MARKET_PRICE_SNAPSHOT_QUOTE="${SYNTH_MARKET_PRICE_SNAPSHOT_QUOTE:-EUR}"

echo "[MVP_DASHBOARD][START] $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "[MVP_DASHBOARD][SAFETY] live_execution=${SYNTH_LIVE_EXECUTION_PERMISSION} broker_write=${SYNTH_BROKER_WRITE_PERMISSION}"
echo "[MVP_DASHBOARD][SAFETY] broker_private_calls=0 broker_writes=0 order_submission=0 executor=none"

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

run_step python -m src.reporting.run_entry_candidate_static_dashboard_v1 \
  --venue bitvavo \
  --interval 4h \
  --output-html "${SYNTH_ENTRY_CANDIDATE_DASHBOARD_HTML}" \
  --output summary

echo
echo "[MVP_DASHBOARD][DONE] $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "[MVP_DASHBOARD][OUTPUT] ${SYNTH_ROTATION_PREVIEW_DASHBOARD_HTML}"
echo "[MVP_DASHBOARD][OUTPUT] ${SYNTH_ENTRY_CANDIDATE_DASHBOARD_HTML}"
echo "[MVP_DASHBOARD][OUTPUT] $(dirname "${SYNTH_ROTATION_PREVIEW_DASHBOARD_HTML}")/index.html"
