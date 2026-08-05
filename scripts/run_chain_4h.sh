#!/usr/bin/env bash

# Re-exec with bash when invoked through sh.
# This prevents POSIX sh from breaking bash-compatible runtime behavior.
if [ -z "${BASH_VERSION:-}" ]; then
    exec bash "$0" "$@"
fi

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
unset SYNTH_REPO_DIR
unset SYNTH_CHAIN_4H_LOCKED
unset SYNTH_CHAIN_4H_LOCK_FILE
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
CHAIN_4H_LOCK_FILE="/tmp/synth_chain_4h.lock"
CONTROLLED_UNTRACKED_PATH="docs/todo/replay_parameter_study_harness_v1.md"

# Hold the outer overlap lock in this process for the complete chain. An
# inherited environment marker can neither skip nor impersonate this lock.
exec 8>"${CHAIN_4H_LOCK_FILE}"
if ! flock -n 8; then
    echo "[CHAIN][4h][FAIL] rc=75 reason=LOCK_HELD lock_file=${CHAIN_4H_LOCK_FILE}"
    exit 75
fi

cd "${REPO_DIR}" || exit 1
source scripts/synth_maintenance_guard.sh

activate_runtime_venv() {
    for candidate in venv .venv; do
        if [ -f "${candidate}/bin/activate" ]; then
            # shellcheck disable=SC1090
            . "${candidate}/bin/activate"

            if python -c 'import requests, pymysql, pandas, yaml, dotenv' >/dev/null 2>&1; then
                echo "[CHAIN][4h] venv=${candidate}"
                return 0
            fi

            deactivate >/dev/null 2>&1 || true
        fi
    done

    echo "[CHAIN][4h][FAIL] no usable venv found; missing one of: requests pymysql pandas yaml dotenv"
    exit 1
}

activate_runtime_venv

# The canonical unit and every direct invocation must carry the same closed
# chain-scoped binding. This reads no database and fails before any DB-capable
# child process when the dedicated profile or secret transport is invalid.
if ! python -m src.operations.run_synth_chain_4h_db_environment_preflight_v1 \
    --checkout-path "${REPO_DIR}"; then
    echo "[CHAIN][4h][FAIL] rc=4 reason=CHAIN_DB_BINDING_PREFLIGHT_FAILED"
    exit 4
fi

if ! python -m src.operations.run_synth_chain_4h_db_grant_preflight_v1; then
    echo "[CHAIN][4h][FAIL] rc=5 reason=CHAIN_DB_GRANT_PREFLIGHT_FAILED"
    exit 5
fi

# Fail closed before launching any write-capable chain step. Same shared
# authorization semantics as the systemd ExecStartPre guard and the Python
# mutation boundary (native SHORT fib context snapshot publication). Default
# mode is PRODUCTION so an unassigned capability fails before any write.
WRITER_CAPABILITY_ID="native_short_4h_chain"
WRITER_SERVICE="synth-chain-4h.service"
export SYNTH_WRITER_CAPABILITY_ID="${WRITER_CAPABILITY_ID}"
export SYNTH_WRITER_EXECUTION_MODE="${SYNTH_WRITER_EXECUTION_MODE:-PRODUCTION}"
export SYNTH_WRITER_ALLOWED_UNTRACKED_PATHS="${CONTROLLED_UNTRACKED_PATH}"
CHAIN_GUARD_ARGS=(--capability "${WRITER_CAPABILITY_ID}" --service "${WRITER_SERVICE}" --checkout-path "${REPO_DIR}" --mode "${SYNTH_WRITER_EXECUTION_MODE}" --allowed-untracked-path "${CONTROLLED_UNTRACKED_PATH}")
if [ -n "${SYNTH_WRITER_ACCEPTANCE_PERMIT:-}" ]; then
    CHAIN_GUARD_ARGS+=(--acceptance-permit "${SYNTH_WRITER_ACCEPTANCE_PERMIT}")
fi
if ! python -m src.operations.verify_writer_capability_authorization_v1 "${CHAIN_GUARD_ARGS[@]}"; then
    echo "[CHAIN][4h][FAIL] rc=3 reason=WRITER_AUTHORIZATION_DENIED capability=${WRITER_CAPABILITY_ID} mode=${SYNTH_WRITER_EXECUTION_MODE}"
    exit 3
fi

run_step() {
    echo "[CHAIN][4h][STEP] $*"
    "$@"
    rc=$?
    if [ "$rc" -ne 0 ]; then
        echo "[CHAIN][4h][FAIL] rc=$rc step=$*"
        exit "$rc"
    fi
}

NATIVE_SHORT_REPOSITORY_COMMIT="$(git rev-parse --verify HEAD)" || exit 2
run_step python -m src.market_data.native_short_repository_source_identity_v1 \
    --repository-commit "${NATIVE_SHORT_REPOSITORY_COMMIT}" \
    --allowed-untracked-path "${CONTROLLED_UNTRACKED_PATH}"

# Capture one canonical UTC instant/boundary in a single Python invocation and
# derive every representation from it. Calling datetime.now() separately per
# variable could let a run that happens to straddle a 4h boundary between
# calls produce inconsistent freshness-gate and feature-window timestamps.
#
# CHAIN_4H_CLOSED_CANDLE_TS(_Z): identity of the just-closed 4h candle. The
# freshness gate below requires a persisted candle whose close_ts_utc equals
# this value exactly -- it is a point-in-time identity, not a window bound,
# and must never be reused directly as an exclusive ETL upper bound.
#
# CHAIN_4H_FEATURE_WINDOW_END_EXCLUSIVE_TS: the feat_candle runner's --end is
# a half-open (exclusive) upper bound (see
# docs/todo/replay_parameter_study_harness_v1.md's documented [start, end)
# contract for the same underlying etl_candle_feat.load_candles/
# filter_write_window functions). Passing the closed-candle identity directly
# as --end would silently exclude the just-closed candle from feat_candle for
# every asset, so this is derived as the same closed-candle boundary plus one
# interval, from the same captured instant.
CHAIN_4H_BOUNDARY_OUTPUT="$(
    python -c 'from datetime import datetime, timezone, timedelta; n=datetime.now(timezone.utc); h=(n.hour//4)*4; closed=n.replace(hour=h, minute=0, second=0, microsecond=0); feature_end=closed+timedelta(hours=4); print(closed.isoformat()); print(closed.strftime("%Y-%m-%dT%H:%M:%SZ")); print(feature_end.isoformat())'
)"
readarray -t CHAIN_4H_BOUNDARY_VALUES <<< "$CHAIN_4H_BOUNDARY_OUTPUT"
CHAIN_4H_CLOSED_CANDLE_TS="${CHAIN_4H_BOUNDARY_VALUES[0]:-}"
CHAIN_4H_CLOSED_CANDLE_TS_Z="${CHAIN_4H_BOUNDARY_VALUES[1]:-}"
CHAIN_4H_FEATURE_WINDOW_END_EXCLUSIVE_TS="${CHAIN_4H_BOUNDARY_VALUES[2]:-}"
if [ "${#CHAIN_4H_BOUNDARY_VALUES[@]}" -ne 3 ] \
    || [ -z "${CHAIN_4H_CLOSED_CANDLE_TS}" ] \
    || [ -z "${CHAIN_4H_CLOSED_CANDLE_TS_Z}" ] \
    || [ -z "${CHAIN_4H_FEATURE_WINDOW_END_EXCLUSIVE_TS}" ]; then
    echo "[CHAIN][4h][FAIL] rc=2 reason=BOUNDARY_DERIVATION_FAILED"
    exit 2
fi

echo "[CHAIN][4h] START $(date -u +%F' '%T) UTC"
echo "[CHAIN][4h] persisted public-price freshness gate venue=bitvavo quote=EUR"
echo "[CHAIN][4h] persisted candle boundary=${CHAIN_4H_CLOSED_CANDLE_TS}"
echo "[CHAIN][4h] feature window lookback_hours=720 warmup_bars=300 end_exclusive=${CHAIN_4H_FEATURE_WINDOW_END_EXCLUSIVE_TS}"

run_step python -m src.operations.run_persisted_market_price_freshness_v1 \
    --venue bitvavo \
    --quote EUR \
    --output table

run_step python -m src.operations.run_persisted_market_candle_freshness_v1 \
    --venue bitvavo \
    --interval 4h \
    --expected-close-ts "$CHAIN_4H_CLOSED_CANDLE_TS_Z"

run_step env \
    SYNTH_NATIVE_SHORT_REPOSITORY_COMMIT="${NATIVE_SHORT_REPOSITORY_COMMIT}" \
    SYNTH_NATIVE_SHORT_WRITER_ENTRYPOINT="scripts/run_chain_4h.sh" \
    SYNTH_NATIVE_SHORT_TRIGGER_REF="scripts/run_chain_4h.sh" \
    bash scripts/run_native_short_scope_status_chain_once.sh \
    --allowed-untracked-path "${CONTROLLED_UNTRACKED_PATH}"

run_step python -m src.market_data.run_native_short_fib_context_snapshot_v1 \
    --publish \
    --output summary

run_step python -m src.features.run_feat_candle \
    --interval 4h \
    --end "$CHAIN_4H_FEATURE_WINDOW_END_EXCLUSIVE_TS" \
    --lookback-hours 720 \
    --warmup-bars 300

run_step python -m src.market_data.run_canonical_fib_zone_map_v1 \
    --venue bitvavo \
    --quote EUR \
    --interval 4h \
    --publish \
    --output summary

run_step python -m src.signal_engine.run_signal_state_etl --venue bitvavo --interval 4h
run_step python -m src.advice.run_advice_engine --interval 4h
run_step python -m src.ranking.run_ranking_engine --venue bitvavo --interval 4h
run_step python -m src.measurement.run_asset_interval_quality_snapshot --venue bitvavo --write-db --output none
run_step python -m src.selection.run_selection_engine_v2 --venue bitvavo --write-db

run_step python -m src.zone.run_zone_engine_v1 \
    --venue bitvavo \
    --interval 4h \
    --lookback-candles 120 \
    --swing-window 5 \
    --write-db \
    --output table

run_step python -m src.trade_setup_filter.run_trade_setup_filter_v1 \
    --venue bitvavo \
    --limit 40 \
    --asset-suitability-mode candidate_weak_set \
    --write-db \
    --output table

run_step python -m src.research.run_trade_setup_filter_policy_preview_v1 \
    --venue bitvavo \
    --target-horizon 24H \
    --write-db \
    --output table

run_step python -m src.advice.run_paper_advice_policy_v1 \
  --venue bitvavo \
  --interval 4h \
  --write-db \
  --output table

run_step python -m src.strategy_runtime.run_strategy_runtime_snapshot \
    --interval 4h \
    --chain-name run_chain_4h \
    --notes "successful market-only chain run; decision/execution disabled"

echo "[CHAIN][4h] DONE  $(date -u +%F' '%T) UTC"
