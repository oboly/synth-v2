#!/usr/bin/env bash

cd "$(dirname "$0")/../.."

if [ -f ".venv/bin/activate" ]; then
  . ".venv/bin/activate"
elif [ -f "venv/bin/activate" ]; then
  . "venv/bin/activate"
fi

export SYNTH_LIVE_EXECUTION_PERMISSION="${SYNTH_LIVE_EXECUTION_PERMISSION:-NOT_GRANTED}"
export SYNTH_BROKER_WRITE_PERMISSION="${SYNTH_BROKER_WRITE_PERMISSION:-NOT_GRANTED}"

echo "[MVP_ACCOUNT][START] $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "[MVP_ACCOUNT][SAFETY] live_execution=${SYNTH_LIVE_EXECUTION_PERMISSION} broker_write=${SYNTH_BROKER_WRITE_PERMISSION}"

run_step() {
  echo
  echo "[MVP_ACCOUNT][STEP] $*"
  "$@"
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "[MVP_ACCOUNT][FAIL] step failed status=$status command=$*"
    exit "$status"
  fi
}

run_step python -m src.operations.run_broker_balance_snapshot_writer_v1 \
  --account-code bitvavo_synth_read \
  --venue bitvavo \
  --write-db \
  --output none

run_step python -m src.operations.run_broker_account_position_snapshot_writer_v1 \
  --account-code bitvavo_synth_read \
  --venue bitvavo \
  --write-db \
  --output none

run_step python -m src.operations.run_decision_gate_position_source_audit_v1 \
  --account-code bitvavo_synth_read \
  --venue bitvavo \
  --output table

echo
echo "[MVP_ACCOUNT][DONE] $(date -u +%Y-%m-%dT%H:%M:%SZ)"
