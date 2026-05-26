#!/usr/bin/env bash

REPO_DIR="${SYNTH_REPO_DIR:-$HOME/projects/synth-v2}"
CHAIN_OUTPUT_ROOT="${SYNTH_LIVE_LIKE_SHADOW_CHAIN_OUTPUT_ROOT:-data/research/live_like_shadow_chain_v1}"
OUTPUT_HTML="${SYNTH_LIVE_LIKE_SHADOW_DASHBOARD_HTML:-/var/www/html/synth/live-like-shadow-chain.html}"
MARKET="${SYNTH_LIVE_LIKE_SHADOW_MARKET:-NEAR-EUR}"
SYMBOL="${SYNTH_LIVE_LIKE_SHADOW_SYMBOL:-NEAR}"

echo "live_like_shadow_heartbeat_once starting $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "repo_dir=${REPO_DIR}"
echo "market=${MARKET}"
echo "symbol=${SYMBOL}"
echo "output_html=${OUTPUT_HTML}"
echo "broker_private_calls=0 broker_writes=0 order_submission=0"
echo "decision_gate_changes=0 execution_planner_changes=0 executor=none"

if [ ! -d "${REPO_DIR}" ]; then
  echo "FAIL repo_dir_missing=${REPO_DIR}" >&2
  exit 1
fi

cd "${REPO_DIR}" || {
  echo "FAIL cd_repo_dir=${REPO_DIR}" >&2
  exit 1
}

if [ -n "${VIRTUAL_ENV:-}" ]; then
  echo "Using active virtualenv: ${VIRTUAL_ENV}"
elif [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  . ".venv/bin/activate"
elif [ -d "venv" ]; then
  # shellcheck disable=SC1091
  . "venv/bin/activate"
else
  echo "Using system python from PATH"
fi

run_step() {
  echo
  echo "[STEP] $*"
  "$@"
  status=$?
  if [ "${status}" -ne 0 ]; then
    echo "[FAIL] step failed status=${status} command=$*" >&2
    exit "${status}"
  fi
}

run_step python -m src.research.run_live_like_shadow_chain_v1 \
  --market "${MARKET}" \
  --symbol "${SYMBOL}" \
  --write-files

LATEST_RUN_DIR="$(find "${CHAIN_OUTPUT_ROOT}" -maxdepth 1 -type d -name 'run_*' | sort | tail -n 1)"
find_status=$?
if [ "${find_status}" -ne 0 ]; then
  echo "FAIL latest_run_dir_lookup_status=${find_status}" >&2
  exit "${find_status}"
fi

if [ -z "${LATEST_RUN_DIR}" ]; then
  echo "FAIL latest_run_dir_not_found under ${CHAIN_OUTPUT_ROOT}" >&2
  exit 1
fi

if [ ! -f "${LATEST_RUN_DIR}/chain_summary_v1.json" ]; then
  echo "FAIL missing_chain_summary=${LATEST_RUN_DIR}/chain_summary_v1.json" >&2
  exit 1
fi

echo "latest_run_dir=${LATEST_RUN_DIR}"

run_step python -m src.reporting.run_live_like_shadow_chain_static_dashboard_v1 \
  --chain-run-dir "${LATEST_RUN_DIR}" \
  --output-html "${OUTPUT_HTML}" \
  --output table

if [ ! -f "${OUTPUT_HTML}" ]; then
  echo "FAIL missing_output_html=${OUTPUT_HTML}" >&2
  exit 1
fi

echo
echo "live_like_shadow_heartbeat_once finished $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "dashboard_html=${OUTPUT_HTML}"
echo "broker_writes=0"
echo "order_submission=0"
echo "executor=none"
echo "no_order_submitted=true"
