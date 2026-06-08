#!/usr/bin/env bash
# Canonical generic linked-profile dashboard refresh pipeline.
# Refreshes market prices once, discovers all active explicitly-linked profiles
# from DB, then renders account home + wallet + native short context +
# open orders monitor + profit plan for each profile independently.
# One profile failure does not abort the pipeline.
#
# broker_private_calls=0 broker_writes=0 order_submission=0
# live_orders=0 decision_gate=none execution_planner=none executor=none
set -euo pipefail

REPO_DIR="${SYNTH_REPO_DIR:-$HOME/projects/synth-v2}"
OUTPUT_ROOT="${SYNTH_ACCOUNT_WALLET_OUTPUT_ROOT:-/var/www/html/synth}"
VENUE="${SYNTH_ACCOUNT_WALLET_VENUE:-bitvavo}"
QUOTE="${SYNTH_MARKET_PRICE_SNAPSHOT_QUOTE:-EUR}"
SKIP_MARKET_PRICE_REFRESH="${SYNTH_SKIP_MARKET_PRICE_REFRESH:-0}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "linked_profile_dashboard_refresh_once starting $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "venue=${VENUE} output_root=${OUTPUT_ROOT}"
echo "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0"
echo "decision_gate=none execution_planner=none executor=none"

cd "${REPO_DIR}"

if [[ -d ".venv" ]]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
elif [[ -d "venv" ]]; then
  # shellcheck disable=SC1091
  source "venv/bin/activate"
else
  echo "No .venv or venv found under ${REPO_DIR}" >&2
  exit 1
fi

if [[ "${SKIP_MARKET_PRICE_REFRESH}" == "1" ]]; then
  echo "market_price_refresh=skipped (SYNTH_SKIP_MARKET_PRICE_REFRESH=1)"
else
  phase_epoch="$(date +%s)"
  echo "PHASE_STARTED phase=refresh_public_prices ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if ! python -m src.market_data.run_market_price_snapshot_v1 \
    --venue "${VENUE}" \
    --quote "${QUOTE}" \
    --write-db \
    --output none; then
    echo "Warning: public market price refresh failed; continuing with stale-price fail-closed rendering."
  fi
  echo "PHASE_FINISHED phase=refresh_public_prices elapsed_sec=$(( $(date +%s) - phase_epoch )) ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
fi

echo "PHASE_STARTED phase=discover_linked_profiles ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
phase_epoch="$(date +%s)"
linked_profiles="$(python -m src.account.run_linked_profile_dashboard_refresh_v1 \
  --venue "${VENUE}" \
  --output profile-list)" || {
  echo "[error] profile discovery failed" >&2
  exit 1
}
echo "PHASE_FINISHED phase=discover_linked_profiles elapsed_sec=$(( $(date +%s) - phase_epoch )) ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

if [[ -z "${linked_profiles}" ]]; then
  echo "linked_profile_count=0 nothing_to_refresh"
  echo "linked_profile_dashboard_refresh_once finished $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  exit 0
fi

profile_count=0
per_profile_success=0
per_profile_failure=0

while IFS= read -r profile_code; do
  [[ -z "${profile_code}" ]] && continue
  profile_count=$(( profile_count + 1 ))
  phase_epoch="$(date +%s)"
  echo "PHASE_STARTED phase=render_profile profile=${profile_code} ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if SYNTH_SKIP_MARKET_PRICE_REFRESH=1 \
     SYNTH_ACCOUNT_WALLET_OUTPUT_ROOT="${OUTPUT_ROOT}" \
     SYNTH_ACCOUNT_WALLET_VENUE="${VENUE}" \
     SYNTH_REPO_DIR="${REPO_DIR}" \
     bash "${SCRIPT_DIR}/run_account_wallet_dashboard_render_once.sh" "${profile_code}"; then
    per_profile_success=$(( per_profile_success + 1 ))
    echo "PHASE_FINISHED phase=render_profile profile=${profile_code} result=ok elapsed_sec=$(( $(date +%s) - phase_epoch )) ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  else
    per_profile_failure=$(( per_profile_failure + 1 ))
    echo "PHASE_FINISHED phase=render_profile profile=${profile_code} result=failed elapsed_sec=$(( $(date +%s) - phase_epoch )) ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  fi
done <<< "${linked_profiles}"

echo "linked_profile_count=${profile_count} success=${per_profile_success} failure=${per_profile_failure}"
echo "linked_profile_dashboard_refresh_once finished $(date -u +%Y-%m-%dT%H:%M:%SZ)"
