#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${SYNTH_REPO_DIR:-$HOME/projects/synth-v2}"
LOCK_FILE="${SYNTH_PAPER_ADVICE_LIFECYCLE_LOCK:-/tmp/synth-paper-advice-lifecycle-refresh.lock}"
VENUE="${SYNTH_PAPER_ADVICE_VENUE:-bitvavo}"
LIFECYCLE_CANDLE_INTERVAL="${SYNTH_PAPER_ADVICE_LIFECYCLE_INTERVAL:-15m}"

echo "paper_advice_lifecycle_refresh_once starting $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0"
echo "decision_gate_changes=0 execution_planner_changes=0 executor_changes=0"
echo "repo_dir=${REPO_DIR}"
echo "lifecycle_candle_interval=${LIFECYCLE_CANDLE_INTERVAL}"

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
  echo "Skipped: another paper advice lifecycle refresh is already running."
  exit 0
fi

# P0-A: deterministic disk/log health check before running any candle ETL.
# Root cause of the 2026-07-05 incident was the Odroid root filesystem
# reaching 100% full; this check makes that condition explicit and
# fail-visible (non-zero exit, clear log line) instead of letting the run
# continue and silently contribute more log volume to an already-full disk.
# Read-only: no DB access, no network call, no broker call, no deletion.
DISK_HEALTH_PATH="${SYNTH_DISK_HEALTH_PATH:-${REPO_DIR}}"
DISK_HEALTH_WARN_PCT="${SYNTH_DISK_HEALTH_WARN_PCT:-85}"
DISK_HEALTH_CRITICAL_PCT="${SYNTH_DISK_HEALTH_CRITICAL_PCT:-95}"
DISK_HEALTH_LOG_PATH_ARGS=()
DISK_HEALTH_LOG_THRESHOLD_ARGS=()
if [[ -n "${SYNTH_DISK_HEALTH_LOG_PATH:-}" ]]; then
  DISK_HEALTH_LOG_PATH_ARGS=(--log-path "${SYNTH_DISK_HEALTH_LOG_PATH}")
fi
if [[ -n "${SYNTH_DISK_HEALTH_LOG_WARN_BYTES:-}" ]]; then
  DISK_HEALTH_LOG_THRESHOLD_ARGS+=(--log-warn-bytes "${SYNTH_DISK_HEALTH_LOG_WARN_BYTES}")
fi
if [[ -n "${SYNTH_DISK_HEALTH_LOG_CRITICAL_BYTES:-}" ]]; then
  DISK_HEALTH_LOG_THRESHOLD_ARGS+=(--log-critical-bytes "${SYNTH_DISK_HEALTH_LOG_CRITICAL_BYTES}")
fi

echo "PHASE_STARTED phase=disk_log_health ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
if ! python -m src.operations.run_runtime_disk_log_health_v1 \
  --path "${DISK_HEALTH_PATH}" \
  --warn-pct "${DISK_HEALTH_WARN_PCT}" \
  --critical-pct "${DISK_HEALTH_CRITICAL_PCT}" \
  "${DISK_HEALTH_LOG_PATH_ARGS[@]}" \
  "${DISK_HEALTH_LOG_THRESHOLD_ARGS[@]}" \
  --output table; then
  echo "[DISK_HEALTH][CRITICAL] aborting before candle ETL — see above disk/log health output." >&2
  echo "paper_advice_lifecycle_refresh_once finished $(date -u +%Y-%m-%dT%H:%M:%SZ) result=aborted_disk_health_critical"
  exit 1
fi
echo "PHASE_FINISHED phase=disk_log_health ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

WINDOW_HOURS="6"
if [[ "${LIFECYCLE_CANDLE_INTERVAL}" == "5m" ]]; then
  WINDOW_HOURS="4"
elif [[ "${LIFECYCLE_CANDLE_INTERVAL}" == "15m" ]]; then
  WINDOW_HOURS="6"
fi

read -r START END < <(
  python - "${WINDOW_HOURS}" <<'PY'
from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

window_hours = int(sys.argv[1])
end = datetime.now(UTC).replace(microsecond=0)
start = end - timedelta(hours=window_hours)
print(start.isoformat(), end.isoformat())
PY
)

echo "etl_window_start=${START}"
echo "etl_window_end=${END}"

python -m src.etl.bitvavo.run_candles_etl \
  --interval "${LIFECYCLE_CANDLE_INTERVAL}" \
  --start "${START}" \
  --end "${END}"

echo "--- lifecycle candle freshness ---"
python - "${VENUE}" "${LIFECYCLE_CANDLE_INTERVAL}" <<'PY'
from __future__ import annotations

import sys

from dotenv import load_dotenv

from src.common.db import get_db_connection

venue = sys.argv[1]
interval_code = sys.argv[2]

load_dotenv(dotenv_path=".env")
conn = get_db_connection()
try:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT MAX(close_ts_utc) AS latest_close_ts_utc
            FROM obs_market_candle
            WHERE venue = %s AND interval_code = %s
            """,
            (venue, interval_code),
        )
        row = cur.fetchone() or {}
        print(
            "global latest obs_market_candle "
            f"venue={venue} interval={interval_code} "
            f"close_ts_utc={row.get('latest_close_ts_utc') or 'not available'}"
        )

        for symbol in ("HYPE", "HBAR"):
            cur.execute(
                """
                SELECT MAX(c.close_ts_utc) AS latest_close_ts_utc
                FROM obs_market_candle c
                JOIN asset a ON a.asset_id = c.asset_id
                WHERE c.venue = %s
                  AND c.interval_code = %s
                  AND UPPER(a.symbol) = %s
                """,
                (venue, interval_code, symbol),
            )
            row = cur.fetchone() or {}
            print(
                f"{symbol} latest obs_market_candle "
                f"venue={venue} interval={interval_code} "
                f"close_ts_utc={row.get('latest_close_ts_utc') or 'not available'}"
            )
finally:
    conn.close()
PY

echo "paper_advice_lifecycle_refresh_once finished $(date -u +%Y-%m-%dT%H:%M:%SZ)"
