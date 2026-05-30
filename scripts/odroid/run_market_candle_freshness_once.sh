#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${SYNTH_REPO_DIR:-$HOME/projects/synth-v2}"
LOCK_FILE="${SYNTH_MARKET_CANDLE_FRESHNESS_LOCK:-/tmp/synth-market-candle-freshness.lock}"
CONFIG_PATH="${SYNTH_MARKET_CANDLE_FRESHNESS_CONFIG:-configs/etl_bitvavo_candles.yaml}"
ASSET_ARGS=("$@")

echo "market_candle_freshness_once starting $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "broker_private_calls=0 broker_writes=0 order_submission=0 db_writes=0"
echo "decision_gate_changes=0 execution_planner_changes=0 executor=none account_awareness=0"
echo "repo_dir=${REPO_DIR}"
echo "config_path=${CONFIG_PATH}"

cd "${REPO_DIR}"

if [[ -n "${VIRTUAL_ENV:-}" ]]; then
  echo "Using active virtualenv: ${VIRTUAL_ENV}"
elif [[ -d ".venv" ]]; then
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
  echo "Skipped: another market candle freshness run is already running."
  exit 0
fi

run_step() {
  echo "[MARKET_CANDLE_FRESHNESS][STEP] $*"
  "$@"
}

build_window_start() {
  local lookback_hours="$1"
  python - "${lookback_hours}" <<'PY'
from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

lookback_hours = int(sys.argv[1])
end = datetime.now(UTC).replace(microsecond=0)
start = end - timedelta(hours=lookback_hours)
print(start.isoformat())
PY
}

run_interval() {
  local interval_code="$1"
  local lookback_hours="$2"
  local start_ts
  start_ts="$(build_window_start "${lookback_hours}")"
  echo "interval=${interval_code} lookback_hours=${lookback_hours} start=${start_ts}"
  run_step python -m src.etl.bitvavo.run_candles_etl \
    --config "${CONFIG_PATH}" \
    --interval "${interval_code}" \
    --start "${start_ts}" \
    "${ASSET_ARGS[@]}"
}

run_interval "15m" 72
run_interval "1h" 168
run_interval "4h" 720
run_interval "1d" 2160

echo "--- latest candle freshness snapshot ---"
python - <<'PY'
from __future__ import annotations

from dotenv import load_dotenv

from src.common.db import get_db_connection

load_dotenv(dotenv_path=".env")
conn = get_db_connection()
try:
    with conn.cursor() as cur:
        for interval_code in ("15m", "1h", "4h", "1d"):
            cur.execute(
                """
                SELECT MAX(close_ts_utc) AS latest_close_ts_utc
                FROM obs_market_candle
                WHERE venue = %s AND interval_code = %s
                """,
                ("bitvavo", interval_code),
            )
            row = cur.fetchone() or {}
            print(
                f"venue=bitvavo interval={interval_code} "
                f"latest_close_ts_utc={row.get('latest_close_ts_utc') or 'not available'}"
            )
finally:
    conn.close()
PY

echo "market_candle_freshness_once finished $(date -u +%Y-%m-%dT%H:%M:%SZ)"
