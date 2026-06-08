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
export SYNTH_ENTRY_CANDIDATE_DASHBOARD_HTML="${SYNTH_ENTRY_CANDIDATE_DASHBOARD_HTML:-/var/www/html/synth/entry-candidates.html}"
export SYNTH_COCKPIT_INDEX_HTML="${SYNTH_COCKPIT_INDEX_HTML:-/var/www/html/synth/index.html}"
export SYNTH_ABOUT_PAGE_HTML="${SYNTH_ABOUT_PAGE_HTML:-/var/www/html/synth/about.html}"
export SYNTH_ABOUT_HERO_ASSET_SOURCE="${SYNTH_ABOUT_HERO_ASSET_SOURCE:-assets/brand/synth/synth-third-faction-triptych.png}"
export SYNTH_ABOUT_HERO_ASSET_OUTPUT="${SYNTH_ABOUT_HERO_ASSET_OUTPUT:-/var/www/html/synth/assets/brand/synth-third-faction-triptych.png}"
export SYNTH_ABOUT_HERO_ASSET_HREF="${SYNTH_ABOUT_HERO_ASSET_HREF:-/synth/assets/brand/synth-third-faction-triptych.png}"
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

run_step python -m src.reporting.run_entry_candidate_static_dashboard_v1 \
  --venue "${VENUE}" \
  --interval "${FAST_RECOMPUTE_INTERVAL}" \
  --output-html "${SYNTH_ENTRY_CANDIDATE_DASHBOARD_HTML}" \
  --output summary

run_step python -m src.reporting.run_synth_about_page_v1 \
  --output-html "${SYNTH_ABOUT_PAGE_HTML}" \
  --cockpit-index-html "${SYNTH_COCKPIT_INDEX_HTML}" \
  --hero-asset-source "${SYNTH_ABOUT_HERO_ASSET_SOURCE}" \
  --hero-asset-output "${SYNTH_ABOUT_HERO_ASSET_OUTPUT}" \
  --hero-asset-href "${SYNTH_ABOUT_HERO_ASSET_HREF}" \
  --output summary

echo
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "[MVP_DASHBOARD_RENDER][STEP] linked_profile_dashboard_refresh (market prices already refreshed)"
SYNTH_SKIP_MARKET_PRICE_REFRESH=1 \
SYNTH_ACCOUNT_WALLET_VENUE="${VENUE}" \
bash "${SCRIPT_DIR}/run_linked_profile_dashboard_refresh_once.sh" || \
  echo "[MVP_DASHBOARD_RENDER][WARN] linked_profile_dashboard_refresh failed (non-fatal)"

echo
echo "[MVP_DASHBOARD_RENDER][DONE] $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "[MVP_DASHBOARD_RENDER][OUTPUT] ${SYNTH_ENTRY_CANDIDATE_DASHBOARD_HTML}"
echo "[MVP_DASHBOARD_RENDER][OUTPUT] ${SYNTH_ABOUT_PAGE_HTML}"
echo "[MVP_DASHBOARD_RENDER][OUTPUT] ${SYNTH_ABOUT_HERO_ASSET_OUTPUT}"
echo "[MVP_DASHBOARD_RENDER][OUTPUT] ${SYNTH_COCKPIT_INDEX_HTML}"
