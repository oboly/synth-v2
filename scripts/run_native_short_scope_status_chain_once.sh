#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${SYNTH_REPO_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
LOCK_FILE="${SYNTH_NATIVE_SHORT_SCOPE_STATUS_LOCK:-/tmp/synth-native-short-scope-status-chain-v1.lock}"
started_epoch="$(date +%s)"

echo "STARTED runner=run_native_short_scope_status_chain_once mode=market_data_write worker_count=1 ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "scope_default=venue:bitvavo,quote_currency:EUR,fib_trading_horizon:SHORT,primary_interval:4h,supporting_interval:1h"
echo "scope_selection=persisted_supported_scopes optional_args=$*"
echo "lock_file=${LOCK_FILE}"
echo "broker_private_calls=0 broker_writes=0 order_submission=0 live_orders=0"
echo "decision_gate=none execution_planner=none executor=none"

cd "${REPO_DIR}" || exit 1

REPOSITORY_COMMIT="${SYNTH_NATIVE_SHORT_REPOSITORY_COMMIT:-}"
if [[ -z "${REPOSITORY_COMMIT}" ]]; then
    if ! REPOSITORY_COMMIT="$(git rev-parse --verify HEAD 2>/dev/null)"; then
        echo "FAILED runner=run_native_short_scope_status_chain_once reason=REPOSITORY_COMMIT_UNAVAILABLE exit_status=2" >&2
        exit 2
    fi
fi
WRITER_ENTRYPOINT="${SYNTH_NATIVE_SHORT_WRITER_ENTRYPOINT:-scripts/run_native_short_scope_status_chain_once.sh}"
TRIGGER_REF="${SYNTH_NATIVE_SHORT_TRIGGER_REF:-scripts/run_native_short_scope_status_chain_once.sh}"

if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    if [[ -f "venv/bin/activate" ]]; then
        # shellcheck disable=SC1091
        source "venv/bin/activate"
    elif [[ -f ".venv/bin/activate" ]]; then
        # shellcheck disable=SC1091
        source ".venv/bin/activate"
    else
        echo "FAILED runner=run_native_short_scope_status_chain_once reason=VENV_MISSING exit_status=1" >&2
        exit 1
    fi
fi

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
    echo "FAILED runner=run_native_short_scope_status_chain_once reason=LOCK_HELD exit_status=75 lock_file=${LOCK_FILE}" >&2
    exit 75
fi

python -m src.market_data.run_native_short_scope_status_chain_v1 \
    --venue bitvavo \
    --quote-currency EUR \
    --fib-trading-horizon SHORT \
    --primary-interval 4h \
    --supporting-interval 1h \
    --execution-mode CHAIN \
    --writer-entrypoint "${WRITER_ENTRYPOINT}" \
    --repository-commit "${REPOSITORY_COMMIT}" \
    --trigger-type REPOSITORY_4H_MARKET_CHAIN \
    --trigger-ref "${TRIGGER_REF}" \
    --output summary \
    "$@"
status=$?
elapsed_sec=$(( $(date +%s) - started_epoch ))

if [[ "${status}" -eq 0 ]]; then
    echo "FINISHED runner=run_native_short_scope_status_chain_once exit_status=0 elapsed_sec=${elapsed_sec} ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
else
    echo "FAILED runner=run_native_short_scope_status_chain_once exit_status=${status} elapsed_sec=${elapsed_sec} ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >&2
fi
exit "${status}"
