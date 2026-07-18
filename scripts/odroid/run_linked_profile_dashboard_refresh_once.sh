#!/usr/bin/env bash
# Canonical generic linked-profile dashboard refresh pipeline.
# Validates persisted market prices, discovers all active explicitly-linked
# profiles from DB, then renders account home + wallet + native short context +
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

phase_epoch="$(date +%s)"
echo "PHASE_STARTED phase=validate_persisted_public_prices ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
python -m src.operations.run_persisted_market_price_freshness_v1 \
  --venue "${VENUE}" \
  --quote "${QUOTE}" \
  --output table
echo "PHASE_FINISHED phase=validate_persisted_public_prices result=PASS database_writes=0 elapsed_sec=$(( $(date +%s) - phase_epoch )) ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

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

# Check 1h candle freshness before building native context.
# Stale 1h candles mean native context will also be stale.
# Non-blocking: emits a warning but does not abort the pipeline.
echo "PHASE_STARTED phase=check_1h_candle_freshness ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
phase_epoch="$(date +%s)"
python - <<'PY' || echo "[WARN] 1h_candle_freshness_check=failed — native context build may produce stale results"
from __future__ import annotations
import sys
from datetime import UTC, datetime
from pathlib import Path
from dotenv import load_dotenv
from src.common.db import get_db_connection
load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)
conn = get_db_connection()
try:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT MAX(close_ts_utc) AS latest FROM obs_market_candle "
            "WHERE venue=%s AND interval_code=%s",
            ("bitvavo", "1h"),
        )
        row = cur.fetchone() or {}
    latest = row.get("latest")
    if latest is None:
        print("candle_freshness_1h=NO_DATA")
        sys.exit(0)
    now = datetime.now(UTC).replace(tzinfo=None)
    age_hours = (now - latest).total_seconds() / 3600
    if age_hours > 3:
        print(f"[WARN] candle_freshness_1h=STALE age_hours={age_hours:.1f} latest={latest.isoformat()}")
    else:
        print(f"candle_freshness_1h=ok age_hours={age_hours:.1f} latest={latest.isoformat()}")
finally:
    conn.close()
PY
echo "PHASE_FINISHED phase=check_1h_candle_freshness elapsed_sec=$(( $(date +%s) - phase_epoch )) ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Build union native SHORT context from ALL linked profiles before any per-profile render.
# This ensures every Profit Plan reads from a complete context and prevents per-profile
# overwrites that would silently drop markets from earlier profiles.
SHARED_NATIVE_DIR="${OUTPUT_ROOT}/_runtime/native_short_context_union_v1"
SHARED_NATIVE_ROWS_PATH="${SHARED_NATIVE_DIR}/native_short_fib_context_rows_v1.csv"
all_profiles_csv="$(tr '\n' ',' <<< "${linked_profiles}" | sed 's/,$//')"
UNION_NATIVE_ROWS_PATH=""

echo "PHASE_STARTED phase=build_union_native_short_context profiles=${all_profiles_csv} ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
phase_epoch="$(date +%s)"
union_native_tmp="$(mktemp -d /tmp/native-short-union.XXXXXX)"
union_build_ok=0

if python -m src.market_data.run_native_short_fib_context_v1 \
  --account-profile "${all_profiles_csv}" \
  --venue "${VENUE}" \
  --write-files \
  --output summary \
  --output-dir "${union_native_tmp}"; then
  # Atomic publish: move new dir into place
  mkdir -p "$(dirname "${SHARED_NATIVE_DIR}")"
  if mv -T "${union_native_tmp}" "${SHARED_NATIVE_DIR}.new" 2>/dev/null && \
     rm -rf "${SHARED_NATIVE_DIR}" && \
     mv "${SHARED_NATIVE_DIR}.new" "${SHARED_NATIVE_DIR}"; then
    union_build_ok=1
  else
    rm -rf "${SHARED_NATIVE_DIR}.new" 2>/dev/null || true
  fi
fi
rm -rf "${union_native_tmp}" 2>/dev/null || true

if [[ "${union_build_ok}" == "1" && -f "${SHARED_NATIVE_ROWS_PATH}" ]]; then
  echo "union_native_short_context=ok path=${SHARED_NATIVE_ROWS_PATH}"
  UNION_NATIVE_ROWS_PATH="${SHARED_NATIVE_ROWS_PATH}"
else
  echo "[WARN] union_native_short_context=MISSING_OR_BUILD_FAILED — per-profile builds will run as fallback"
fi
echo "PHASE_FINISHED phase=build_union_native_short_context elapsed_sec=$(( $(date +%s) - phase_epoch )) ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

profile_count=0
per_profile_success=0
per_profile_failure=0

while IFS= read -r profile_code; do
  [[ -z "${profile_code}" ]] && continue
  profile_count=$(( profile_count + 1 ))
  phase_epoch="$(date +%s)"
  echo "PHASE_STARTED phase=render_profile profile=${profile_code} ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if SYNTH_ACCOUNT_WALLET_OUTPUT_ROOT="${OUTPUT_ROOT}" \
     SYNTH_ACCOUNT_WALLET_VENUE="${VENUE}" \
     SYNTH_REPO_DIR="${REPO_DIR}" \
     SYNTH_NATIVE_SHORT_ROWS_PATH="${UNION_NATIVE_ROWS_PATH}" \
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
