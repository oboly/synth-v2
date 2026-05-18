#!/usr/bin/env bash

cd "$(dirname "$0")/../.."

if [ -f ".venv/bin/activate" ]; then
  . ".venv/bin/activate"
elif [ -f "venv/bin/activate" ]; then
  . "venv/bin/activate"
fi

export SYNTH_ROTATION_PREVIEW_DASHBOARD_HTML="${SYNTH_ROTATION_PREVIEW_DASHBOARD_HTML:-/var/www/html/synth/rotation-preview.html}"

echo "[MVP_DASHBOARD][START] $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "[MVP_DASHBOARD][SAFETY] broker_writes=0 order_submission=0 executor=none"

run_step() {
  echo
  echo "[MVP_DASHBOARD][STEP] $*"
  "$@"
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "[MVP_DASHBOARD][FAIL] step failed status=$status command=$*"
    exit "$status"
  fi
}

run_step python -m src.reporting.run_position_rotation_static_dashboard_v1 \
  --venue bitvavo \
  --interval 4h \
  --trading-account-id 2 \
  --output-html "${SYNTH_ROTATION_PREVIEW_DASHBOARD_HTML}" \
  --output summary

echo
echo "[MVP_DASHBOARD][DONE] $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "[MVP_DASHBOARD][OUTPUT] ${SYNTH_ROTATION_PREVIEW_DASHBOARD_HTML}"
echo "[MVP_DASHBOARD][OUTPUT] $(dirname "${SYNTH_ROTATION_PREVIEW_DASHBOARD_HTML}")/index.html"
