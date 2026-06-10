#!/usr/bin/env bash
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
PROFILE_OUTPUT_DIR="${OUTPUT_ROOT}/accounts/${PROFILE}"
NATIVE_SHORT_RUNTIME_DIR="${PROFILE_OUTPUT_DIR}/_runtime/native_short_context_v1"
NATIVE_SHORT_ROWS_PATH="${NATIVE_SHORT_RUNTIME_DIR}/native_short_fib_context_rows_v1.csv"
# Pre-built union context from run_linked_profile_dashboard_refresh_once.sh (empty = build per-profile)
PRE_BUILT_NATIVE_ROWS_PATH="${SYNTH_NATIVE_SHORT_ROWS_PATH:-}"
LOCK_FILE="${SYNTH_ACCOUNT_WALLET_DASHBOARD_LOCK:-/tmp/synth-account-wallet-dashboard-${PROFILE}.lock}"
VENUE="${SYNTH_ACCOUNT_WALLET_VENUE:-bitvavo}"
QUOTE="${SYNTH_MARKET_PRICE_SNAPSHOT_QUOTE:-EUR}"
SKIP_MARKET_PRICE_REFRESH="${SYNTH_SKIP_MARKET_PRICE_REFRESH:-0}"

phase_start() {
  local phase="$1"
  echo "PHASE_STARTED phase=${phase} ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}

phase_finished() {
  local phase="$1"
  local started_epoch="$2"
  local ended_epoch
  ended_epoch="$(date +%s)"
  echo "PHASE_FINISHED phase=${phase} elapsed_sec=$((ended_epoch - started_epoch)) ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}

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

mkdir -p "${FAVICON_OUTPUT_DIR}"
for favicon_file in favicon.svg favicon-16x16.png favicon-32x32.png apple-touch-icon.png favicon.ico; do
  install -m 0644 "${FAVICON_SOURCE_DIR}/${favicon_file}" "${FAVICON_OUTPUT_DIR}/${favicon_file}"
done

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "Skipped: another wallet dashboard render is already running for ${PROFILE}."
  exit 0
fi

if [[ "${SKIP_MARKET_PRICE_REFRESH}" == "1" ]]; then
  echo "market_price_refresh=skipped (SYNTH_SKIP_MARKET_PRICE_REFRESH=1)"
else
  phase_epoch="$(date +%s)"
  phase_start "refresh_public_prices"
  if ! python -m src.market_data.run_market_price_snapshot_v1 \
    --venue "${VENUE}" \
    --quote "${QUOTE}" \
    --write-db \
    --output none; then
    echo "Warning: public market price refresh failed; continuing with stale-price fail-closed rendering."
  fi
  phase_finished "refresh_public_prices" "${phase_epoch}"
fi

if [[ -n "${PRE_BUILT_NATIVE_ROWS_PATH}" && -f "${PRE_BUILT_NATIVE_ROWS_PATH}" ]]; then
  echo "native_short_context=pre_built_union path=${PRE_BUILT_NATIVE_ROWS_PATH}"
  NATIVE_SHORT_ROWS_PATH="${PRE_BUILT_NATIVE_ROWS_PATH}"
else
  phase_epoch="$(date +%s)"
  phase_start "build_native_short_context"
  native_tmp_dir="$(mktemp -d /tmp/native-short-context-${PROFILE}.XXXXXX)"
  native_log_path="$(mktemp /tmp/native-short-context-log-${PROFILE}.XXXXXX)"
  cleanup_native_tmp() {
    rm -rf "${native_tmp_dir}"
    rm -f "${native_log_path}"
  }
  trap cleanup_native_tmp EXIT
  python -m src.market_data.run_native_short_fib_context_v1 \
    --account-profile "${PROFILE}" \
    --venue "${VENUE}" \
    --write-files \
    --output summary \
    --output-dir "${native_tmp_dir}" | tee "${native_log_path}"

  python - <<'PY' "${native_tmp_dir}"
import csv
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
rows_csv = root / "native_short_fib_context_rows_v1.csv"
manifest_json = root / "manifest_v1.json"
coverage_csv = root / "coverage_summary_v1.csv"
if not rows_csv.exists() or not manifest_json.exists() or not coverage_csv.exists():
    raise SystemExit("native_short_context_validation=missing_required_output")
manifest = json.loads(manifest_json.read_text(encoding="utf-8"))
with rows_csv.open(encoding="utf-8", newline="") as handle:
    rows = list(csv.DictReader(handle))
if not rows:
    raise SystemExit("native_short_context_validation=empty_rows")
required_fields = {
    "symbol",
    "context_status",
    "primary_4h_lifecycle_state",
    "supporting_1h_state",
    "active_target_levels_json",
}
if not required_fields.issubset(set(rows[0].keys())):
    raise SystemExit("native_short_context_validation=missing_required_fields")
if int(manifest.get("row_count") or 0) != len(rows):
    raise SystemExit("native_short_context_validation=row_count_mismatch")
print(f"native_short_context_validation=ok row_count={len(rows)}")
PY

  phase_finished "build_native_short_context" "${phase_epoch}"

  phase_epoch="$(date +%s)"
  phase_start "publish_native_short_context"
  mkdir -p "${PROFILE_OUTPUT_DIR}/_runtime"
  native_prev_dir=""
  native_backup_dir=""
  if [[ -d "${NATIVE_SHORT_RUNTIME_DIR}" ]]; then
    native_prev_dir="${NATIVE_SHORT_RUNTIME_DIR}"
    native_backup_dir="${NATIVE_SHORT_RUNTIME_DIR}.bak.$$"
    mv "${native_prev_dir}" "${native_backup_dir}"
  fi
  if mv "${native_tmp_dir}" "${NATIVE_SHORT_RUNTIME_DIR}"; then
    if [[ -n "${native_backup_dir}" ]]; then
      rm -rf "${native_backup_dir}"
    fi
  else
    if [[ -n "${native_backup_dir}" && -d "${native_backup_dir}" ]]; then
      mv "${native_backup_dir}" "${NATIVE_SHORT_RUNTIME_DIR}"
    fi
    echo "native_short_context_publish=failed" >&2
    exit 1
  fi
  phase_finished "publish_native_short_context" "${phase_epoch}"

  if [[ ! -f "${NATIVE_SHORT_ROWS_PATH}" ]]; then
    echo "native_short_context_publish=missing_rows_path path=${NATIVE_SHORT_ROWS_PATH}" >&2
    exit 1
  fi
fi

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

phase_epoch="$(date +%s)"
phase_start "render_profit_plan"
python -m src.reporting.run_manual_short_trader_profit_plan_v1 \
  --account-profile "${PROFILE}" \
  --venue "${VENUE}" \
  --output-root "${OUTPUT_ROOT}" \
  --native-short-context-rows "${NATIVE_SHORT_ROWS_PATH}" \
  --monitor-href "/synth/accounts/${PROFILE}/open-orders-monitor.html" \
  --output summary
phase_finished "render_profit_plan" "${phase_epoch}"

trap - EXIT
cleanup_native_tmp

echo "account_wallet_dashboard_render_once finished $(date -u +%Y-%m-%dT%H:%M:%SZ)"
