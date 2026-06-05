#!/usr/bin/env bash
set -euo pipefail

PROFILE="${1:-}"
if [[ -z "${PROFILE}" ]]; then
  echo "Usage: $0 <profile>" >&2
  exit 1
fi

REPO_DIR="${SYNTH_REPO_DIR:-$HOME/projects/synth-v2}"
OUTPUT_ROOT="${SYNTH_ACCOUNT_WALLET_OUTPUT_ROOT:-/var/www/html/synth}"
LOCK_FILE="${SYNTH_ACCOUNT_WALLET_DASHBOARD_LOCK:-/tmp/synth-account-wallet-dashboard-${PROFILE}.lock}"
VENUE="${SYNTH_ACCOUNT_WALLET_VENUE:-bitvavo}"

echo "account_wallet_dashboard_render_once starting $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "profile=${PROFILE}"
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

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "Skipped: another wallet dashboard render is already running for ${PROFILE}."
  exit 0
fi

python -m src.reporting.run_account_wallet_dashboard_v1 \
  --account-profile "${PROFILE}" \
  --venue "${VENUE}" \
  --output-root "${OUTPUT_ROOT}" \
  --output summary

python -m src.reporting.run_manual_short_trader_dashboard_v1 \
  --account-profile "${PROFILE}" \
  --venue "${VENUE}" \
  --output-root "${OUTPUT_ROOT}" \
  --output summary

python -m src.reporting.run_manual_short_trader_profit_plan_v1 \
  --account-profile "${PROFILE}" \
  --venue "${VENUE}" \
  --output-root "${OUTPUT_ROOT}" \
  --monitor-href "/synth/accounts/${PROFILE}/open-orders-monitor.html" \
  --output summary

echo "account_wallet_dashboard_render_once finished $(date -u +%Y-%m-%dT%H:%M:%SZ)"
