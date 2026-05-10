#!/usr/bin/env bash

# Re-exec with bash when invoked through sh.
# This prevents POSIX sh from breaking bash-compatible runtime behavior.
if [ -z "${BASH_VERSION:-}" ]; then
    exec bash "$0" "$@"
fi

# Prevent overlapping 1h chain runs.
# This protects DB writes and avoids duplicate/competing pipeline snapshots.
if [ "${SYNTH_CHAIN_1H_LOCKED:-0}" != "1" ]; then
    exec env SYNTH_CHAIN_1H_LOCKED=1 flock -n /tmp/synth_chain_1h.lock bash "$0" "$@"
fi

set -u

cd /home/gurk/projects/synth-v2 || exit 1

activate_runtime_venv() {
    for candidate in venv .venv; do
        if [ -f "${candidate}/bin/activate" ]; then
            # shellcheck disable=SC1090
            . "${candidate}/bin/activate"

            if python -c 'import requests, pymysql, pandas, yaml, dotenv' >/dev/null 2>&1; then
                echo "[CHAIN][1h] venv=${candidate}"
                return 0
            fi

            deactivate >/dev/null 2>&1 || true
        fi
    done

    echo "[CHAIN][1h][FAIL] no usable venv found; missing one of: requests pymysql pandas yaml dotenv"
    exit 1
}

activate_runtime_venv

run_step() {
    echo "[CHAIN][1h][STEP] $*"
    "$@"
    rc=$?
    if [ "$rc" -ne 0 ]; then
        echo "[CHAIN][1h][FAIL] rc=$rc step=$*"
        exit "$rc"
    fi
}

CHAIN_1H_END_TS="$(
    python -c 'from datetime import datetime, timezone; n=datetime.now(timezone.utc); print(n.replace(minute=0, second=0, microsecond=0).isoformat())'
)"

CHAIN_1H_ETL_START_TS="$(
    python -c 'from datetime import datetime, timezone, timedelta; n=datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0); print((n - timedelta(hours=48)).isoformat())'
)"

echo "[CHAIN][1h] START $(date -u +%F' '%T) UTC"
echo "[CHAIN][1h] repo=$(pwd)"
echo "[CHAIN][1h] python=$(command -v python)"
echo "[CHAIN][1h] ETL window start=${CHAIN_1H_ETL_START_TS} end=${CHAIN_1H_END_TS}"
echo "[CHAIN][1h] feature window lookback_hours=240 warmup_bars=300 end=${CHAIN_1H_END_TS}"

run_step python -m src.etl.bitvavo.run_candles_etl \
    --interval 1h \
    --start "$CHAIN_1H_ETL_START_TS" \
    --end "$CHAIN_1H_END_TS"

run_step python -m src.features.run_feat_candle \
    --interval 1h \
    --end "$CHAIN_1H_END_TS" \
    --lookback-hours 240 \
    --warmup-bars 300

run_step python -m src.signal_engine.run_signal_state_etl --venue bitvavo --interval 1h
run_step python -m src.advice.run_advice_engine --interval 1h
run_step python -m src.ranking.run_ranking_engine --venue bitvavo --interval 1h
run_step python -m src.measurement.run_asset_interval_quality_snapshot --venue bitvavo --write-db --output none
run_step python -m src.selection.run_selection_engine_v2 --venue bitvavo --write-db

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

run_step python -m src.strategy_runtime.run_strategy_runtime_snapshot \
    --interval 1h \
    --chain-name run_chain_1h \
    --notes "successful market-only chain run; decision/execution disabled"

echo "[CHAIN][1h] DONE  $(date -u +%F' '%T) UTC"
