#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${SYNTH_REPO_DIR:-$HOME/projects/synth-v2}"
OUTPUT_HTML="${SYNTH_PAPER_ADVICE_DASHBOARD_HTML:-/var/www/html/synth/paper-advice.html}"
LOCK_FILE="${SYNTH_PAPER_ADVICE_DASHBOARD_LOCK:-/tmp/synth-paper-advice-dashboard-refresh.lock}"
VENUE="${SYNTH_PAPER_ADVICE_VENUE:-bitvavo}"
ADVICE_INTERVAL="${SYNTH_PAPER_ADVICE_INTERVAL:-4h}"
LIFECYCLE_CANDLE_INTERVAL="${SYNTH_PAPER_ADVICE_LIFECYCLE_INTERVAL:-1h}"
LIMIT="${SYNTH_PAPER_ADVICE_LIMIT:-40}"

echo "paper_advice_dashboard_refresh_once starting $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "broker_calls=0 broker_writes=0 order_submission=0 live_orders=0"
echo "repo_dir=${REPO_DIR}"
echo "output_html=${OUTPUT_HTML}"
echo "advice_interval=${ADVICE_INTERVAL}"
echo "lifecycle_candle_interval=${LIFECYCLE_CANDLE_INTERVAL}"

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
  echo "Skipped: another paper advice dashboard refresh is already running."
  exit 0
fi

python -m src.reporting.run_paper_advice_static_dashboard_v1 \
  --venue "${VENUE}" \
  --interval "${ADVICE_INTERVAL}" \
  --limit "${LIMIT}" \
  --lifecycle-candle-interval "${LIFECYCLE_CANDLE_INTERVAL}" \
  --output-html "${OUTPUT_HTML}" \
  --output table

echo "--- lifecycle badge sample ---"
grep -n -E "REACTION RETEST AFTER ENTRY|POST-ENTRY BOUNCE|DOWNSIDE ENTRY REACHED|RECOMPUTE NEEDED|INVALIDATED|SETUP FAILED|NO EDGE" "${OUTPUT_HTML}" | head -40 || true

echo "paper_advice_dashboard_refresh_once finished $(date -u +%Y-%m-%dT%H:%M:%SZ)"
