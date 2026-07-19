#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${SYNTH_REPO_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
LOCK_FILE="${SYNTH_MARKET_CANDLE_FRESHNESS_LOCK:-/tmp/synth-market-candle-freshness-writer-v1.lock}"
CONFIG_PATH="${SYNTH_MARKET_CANDLE_FRESHNESS_CONFIG:-configs/etl_bitvavo_candles.yaml}"
# Neutral, host-independent capability identity. The production_runtime_owner
# host is assigned by explicit host selection, not encoded here. See
# docs/ops/writer_capability_host_ownership_contract_v1.md.
OWNER="${SYNTH_MARKET_CANDLE_WRITER_OWNER:-public-candle-freshness-writer}"
ASSET_ARGS=("$@")
started_epoch="$(date +%s)"

echo "STARTED runner=run_market_candle_freshness_once owner=${OWNER} mode=public_market_data_write intervals=15m,1h,4h,1d,1w worker_count=1 ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 account_awareness=0"

cd "${REPO_DIR}"
if [[ -d "venv" ]]; then
  # shellcheck disable=SC1091
  source "venv/bin/activate"
elif [[ -d ".venv" ]]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
else
  echo "FAILED runner=run_market_candle_freshness_once reason=VENV_MISSING" >&2
  exit 1
fi

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "FAILED runner=run_market_candle_freshness_once reason=LOCK_HELD lock_file=${LOCK_FILE}" >&2
  exit 75
fi

repository_commit_sha="$(git rev-parse --verify HEAD)"
echo "SOURCE owner=${OWNER} repository_commit_sha=${repository_commit_sha} config=${CONFIG_PATH} lock_file=${LOCK_FILE}"

build_window_start() {
  local lookback_hours="$1"
  python - "${lookback_hours}" <<'PY'
from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

lookback_hours = int(sys.argv[1])
print((datetime.now(UTC).replace(microsecond=0) - timedelta(hours=lookback_hours)).isoformat())
PY
}

run_interval() {
  local interval_code="$1"
  local lookback_hours="$2"
  local start_ts
  start_ts="$(build_window_start "${lookback_hours}")"
  echo "PHASE_STARTED runner=run_market_candle_freshness_once interval=${interval_code} lookback_hours=${lookback_hours} start=${start_ts} ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  local status
  if python -m src.etl.bitvavo.run_candles_etl \
    --config "${CONFIG_PATH}" \
    --interval "${interval_code}" \
    --start "${start_ts}" \
    "${ASSET_ARGS[@]}"; then
    status=0
  else
    status=$?
    return "${status}"
  fi
  echo "PHASE_FINISHED runner=run_market_candle_freshness_once interval=${interval_code} ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}

run_or_fail() {
  local interval_code="$1"
  local lookback_hours="$2"
  local status
  if run_interval "${interval_code}" "${lookback_hours}"; then
    return 0
  else
    status=$?
  fi
  echo "FAILED runner=run_market_candle_freshness_once owner=${OWNER} repository_commit_sha=${repository_commit_sha} interval=${interval_code} exit_status=${status} elapsed_sec=$(( $(date +%s) - started_epoch )) ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >&2
  exit "${status}"
}

run_or_fail "15m" 72
run_or_fail "1h" 168
run_or_fail "4h" 720
run_or_fail "1d" 2160
run_or_fail "1w" 2016

echo "FINISHED runner=run_market_candle_freshness_once owner=${OWNER} repository_commit_sha=${repository_commit_sha} elapsed_sec=$(( $(date +%s) - started_epoch )) ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
