#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${SYNTH_REPO_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
LOCK_FILE="${SYNTH_MARKET_PRICE_SNAPSHOT_LOCK:-/tmp/synth-market-price-snapshot-writer-v1.lock}"
VENUE="${SYNTH_MARKET_PRICE_SNAPSHOT_VENUE:-bitvavo}"
QUOTE="${SYNTH_MARKET_PRICE_SNAPSHOT_QUOTE:-EUR}"
OWNER="devlap-public-market-data"
started_epoch="$(date +%s)"

echo "STARTED runner=run_market_price_snapshot_once owner=${OWNER} mode=public_market_data_write venue=${VENUE} quote=${QUOTE} worker_count=1 ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0 account_awareness=0"

cd "${REPO_DIR}"
if [[ -d "venv" ]]; then
  # shellcheck disable=SC1091
  source "venv/bin/activate"
elif [[ -d ".venv" ]]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
else
  echo "FAILED runner=run_market_price_snapshot_once reason=VENV_MISSING" >&2
  exit 1
fi

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "FAILED runner=run_market_price_snapshot_once reason=LOCK_HELD lock_file=${LOCK_FILE}" >&2
  exit 75
fi

repository_commit_sha="$(git rev-parse --verify HEAD)"
echo "SOURCE owner=${OWNER} repository_commit_sha=${repository_commit_sha} endpoint=bitvavo_public_ticker_price lock_file=${LOCK_FILE}"

if python -m src.market_data.run_market_price_snapshot_v1 \
  --venue "${VENUE}" \
  --quote "${QUOTE}" \
  --write-db \
  --output none; then
  echo "FINISHED runner=run_market_price_snapshot_once owner=${OWNER} repository_commit_sha=${repository_commit_sha} elapsed_sec=$(( $(date +%s) - started_epoch )) ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  exit 0
else
  status=$?
fi

echo "FAILED runner=run_market_price_snapshot_once owner=${OWNER} repository_commit_sha=${repository_commit_sha} exit_status=${status} elapsed_sec=$(( $(date +%s) - started_epoch )) ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >&2
exit "${status}"
