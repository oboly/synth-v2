#!/usr/bin/env bash

cd "$(dirname "$0")/../.."

if [ -f ".venv/bin/activate" ]; then
  . ".venv/bin/activate"
elif [ -f "venv/bin/activate" ]; then
  . "venv/bin/activate"
fi

export SYNTH_LIVE_EXECUTION_PERMISSION="${SYNTH_LIVE_EXECUTION_PERMISSION:-NOT_GRANTED}"
export SYNTH_BROKER_WRITE_PERMISSION="${SYNTH_BROKER_WRITE_PERMISSION:-NOT_GRANTED}"
export SYNTH_BROKER_PRIVATE_READ_PERMISSION="${SYNTH_BROKER_PRIVATE_READ_PERMISSION:-I_UNDERSTAND_THIS_READS_PRIVATE_ACCOUNT_DATA}"

if [ -z "${SYNTH_MVP_ACCOUNT_CODE:-}" ]; then
  echo "[MVP_ACCOUNT][FAIL] SYNTH_MVP_ACCOUNT_CODE must be set to an exact trading_account.account_code" >&2
  exit 1
fi

if [ -z "${SYNTH_ACCOUNT_CREDENTIAL_MASTER_KEY:-}" ]; then
  echo "[MVP_ACCOUNT][FAIL] SYNTH_ACCOUNT_CREDENTIAL_MASTER_KEY must be loaded from a host-local EnvironmentFile" >&2
  exit 1
fi

echo "[MVP_ACCOUNT][START] $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "[MVP_ACCOUNT][SAFETY] live_execution=${SYNTH_LIVE_EXECUTION_PERMISSION} broker_write=${SYNTH_BROKER_WRITE_PERMISSION}"
echo "[MVP_ACCOUNT][ACCOUNT] account_code=${SYNTH_MVP_ACCOUNT_CODE} venue=bitvavo"

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
  --account-code "${SYNTH_MVP_ACCOUNT_CODE}" \
  --venue bitvavo \
  --write-db \
  --output none

run_step python -m src.operations.run_broker_account_position_snapshot_writer_v1 \
  --account-code "${SYNTH_MVP_ACCOUNT_CODE}" \
  --venue bitvavo \
  --write-db \
  --output none

run_step python -m src.operations.run_decision_gate_position_source_audit_v1 \
  --account-code "${SYNTH_MVP_ACCOUNT_CODE}" \
  --venue bitvavo \
  --output table

echo
echo "[MVP_ACCOUNT][DONE] $(date -u +%Y-%m-%dT%H:%M:%SZ)"
