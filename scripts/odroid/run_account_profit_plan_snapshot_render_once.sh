#!/usr/bin/env bash
# Safe persisted-snapshot Profit Plan render owner. No independent scheduler.
# broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0
# decision_gate=none execution_planner=none executor=none
set -euo pipefail

PROFILE="${1:-}"
if [[ -z "${PROFILE}" ]]; then
  echo "Usage: $0 <profile>" >&2
  exit 1
fi

REPO_DIR="${SYNTH_REPO_DIR:-$HOME/projects/synth-v2}"
OUTPUT_ROOT="${SYNTH_ACCOUNT_WALLET_OUTPUT_ROOT:-/var/www/html/synth}"
VENUE="${SYNTH_ACCOUNT_WALLET_VENUE:-bitvavo}"
NATIVE_SHORT_SNAPSHOT_ROOT="${SYNTH_NATIVE_SHORT_CONTEXT_SNAPSHOT_DIR:-/var/www/html/synth/_runtime/native_short_context_snapshot_v1}"
# Default lock lives under $HOME (not /tmp): the canonical scheduled render
# owner runs with PrivateTmp=true, which gives /tmp a per-service namespace
# that a manual same-host invocation does not share. $HOME is not
# namespaced by PrivateTmp, so this path resolves to the same inode for
# both. See docs/ops/synth_runtime_runners_v1.md.
LOCK_FILE="${SYNTH_ACCOUNT_PROFIT_PLAN_RENDER_LOCK:-${HOME}/.local/state/synth/runtime/locks/account-profit-plan-snapshot-render-${PROFILE}.lock}"
METADATA_PATH="${SYNTH_ACCOUNT_PROFIT_PLAN_RENDER_METADATA_PATH:-${OUTPUT_ROOT}/accounts/${PROFILE}/_runtime/profit_plan_render_owner_v1/latest_run.json}"

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

python -m src.reporting.run_account_profit_plan_snapshot_render_owner_v1 \
  --account-profile "${PROFILE}" \
  --venue "${VENUE}" \
  --output-root "${OUTPUT_ROOT}" \
  --native-short-snapshot-root "${NATIVE_SHORT_SNAPSHOT_ROOT}" \
  --monitor-href "/synth/accounts/${PROFILE}/open-orders-monitor.html" \
  --lock-file "${LOCK_FILE}" \
  --metadata-path "${METADATA_PATH}" \
  --output summary
