#!/usr/bin/env bash
# Safe account/profile snapshot renderer.
#
# Renders only pages that read persisted DB snapshots. It deliberately does not
# build or publish native SHORT context and does not render Profit Plan until the
# native SHORT/freshness contract is persisted outside the render stage.
#
# broker_private_calls=0 broker_writes=0 order_submission=0
# live_orders=0 decision_gate=none execution_planner=none executor=none
set -euo pipefail

PROFILE="${1:-}"
if [[ -z "${PROFILE}" ]]; then
  echo "Usage: $0 <profile>" >&2
  exit 1
fi

REPO_DIR="${SYNTH_REPO_DIR:-$HOME/projects/synth-v2}"
OUTPUT_ROOT="${SYNTH_ACCOUNT_WALLET_OUTPUT_ROOT:-/var/www/html/synth}"
FAVICON_SOURCE_DIR="${SYNTH_FAVICON_SOURCE_DIR:-assets/brand/synth}"
FAVICON_OUTPUT_DIR="${OUTPUT_ROOT}/assets/brand/synth"
LOCK_FILE="${SYNTH_ACCOUNT_WALLET_SNAPSHOT_RENDER_LOCK:-/tmp/synth-account-wallet-snapshot-render-${PROFILE}.lock}"
VENUE="${SYNTH_ACCOUNT_WALLET_VENUE:-bitvavo}"

phase_start() {
  local phase="$1"
  echo "PHASE_STARTED phase=${phase} profile=${PROFILE} ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}

phase_finished() {
  local phase="$1"
  local started_epoch="$2"
  local ended_epoch
  ended_epoch="$(date +%s)"
  echo "PHASE_FINISHED phase=${phase} profile=${PROFILE} elapsed_sec=$((ended_epoch - started_epoch)) ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}

echo "account_wallet_snapshot_dashboard_render_once starting $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "profile=${PROFILE} venue=${VENUE} output_root=${OUTPUT_ROOT}"
echo "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0"
echo "decision_gate=none execution_planner=none executor=none"
echo "native_short_context_build=disabled"
echo "profit_plan_render=disabled reason=NATIVE_SHORT_SNAPSHOT_CONTRACT_NOT_PERSISTED"

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
  echo "Skipped: another safe snapshot dashboard render is already running for ${PROFILE}."
  exit 0
fi

mkdir -p "${FAVICON_OUTPUT_DIR}"
for favicon_file in favicon.svg favicon-16x16.png favicon-32x32.png apple-touch-icon.png favicon.ico; do
  if [[ -f "${FAVICON_SOURCE_DIR}/${favicon_file}" ]]; then
    install -m 0644 "${FAVICON_SOURCE_DIR}/${favicon_file}" "${FAVICON_OUTPUT_DIR}/${favicon_file}"
  fi
done

phase_epoch="$(date +%s)"
phase_start "render_wallet"
python -m src.reporting.run_account_wallet_dashboard_v1 \
  --account-profile "${PROFILE}" \
  --venue "${VENUE}" \
  --output-root "${OUTPUT_ROOT}" \
  --output summary
phase_finished "render_wallet" "${phase_epoch}"

phase_epoch="$(date +%s)"
phase_start "render_open_orders_monitor"
python -m src.reporting.run_manual_short_trader_dashboard_v1 \
  --account-profile "${PROFILE}" \
  --venue "${VENUE}" \
  --output-root "${OUTPUT_ROOT}" \
  --output summary
phase_finished "render_open_orders_monitor" "${phase_epoch}"

echo "account_wallet_snapshot_dashboard_render_once finished $(date -u +%Y-%m-%dT%H:%M:%SZ)"
