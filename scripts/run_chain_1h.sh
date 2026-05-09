#!/usr/bin/env bash

# Re-exec with bash if someone accidentally starts this script via sh.
if [ -z "${BASH_VERSION:-}" ]; then
    exec /usr/bin/env bash "$0" "$@"
fi

# Prevent overlapping 1h chain runs.
# This protects DB writes and avoids duplicate/competing pipeline snapshots.
if [[ "${SYNTH_CHAIN_1H_LOCKED:-0}" != "1" ]]; then
    exec env SYNTH_CHAIN_1H_LOCKED=1 flock -n /tmp/synth_chain_1h.lock "$0" "$@"
fi

set -u

cd /home/gurk/projects/synth-v2 || exit 1
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
elif [ -f venv/bin/activate ]; then
    source venv/bin/activate
else
    echo "[CHAIN][1h][FAIL] no Python venv found"
    exit 1
fi

run_step() {
    echo "[CHAIN][1h][STEP] $*"
    "$@"
    rc=$?
    if [[ "$rc" -ne 0 ]]; then
        echo "[CHAIN][1h][FAIL] rc=$rc step=$*"
        exit "$rc"
    fi
}

CHAIN_1H_END_TS="$(date -u +%Y-%m-%dT%H:00:00+00:00)"
CHAIN_1H_ETL_START_TS="$(date -u -d '48 hours ago' +%Y-%m-%dT%H:00:00+00:00)"

echo "[CHAIN][1h] START $(date -u +%F' '%T) UTC"
echo "[CHAIN][1h] ETL window start=${CHAIN_1H_ETL_START_TS} end=${CHAIN_1H_END_TS}"
echo "[CHAIN][1h] feature window lookback_hours=240 warmup_bars=300 end=${CHAIN_1H_END_TS}"

run_step python -m src.etl.bitvavo.run_candles_etl \
    --interval 1h \
    --start "$CHAIN_1H_ETL_START_TS" \
    --end "$CHAIN_1H_END_TS"

run_step python -m src.features.run_feat_candle \
    --interval 1h \
    --lookback-hours 240 \
    --warmup-bars 300 \
    --end "$CHAIN_1H_END_TS"

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

echo "[CHAIN][1h] DONE  $(date -u +%F' '%T) UTC"
