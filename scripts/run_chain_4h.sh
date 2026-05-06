#!/usr/bin/env bash

# Prevent overlapping 4h chain runs.
# This protects DB writes and avoids duplicate/competing pipeline snapshots.
if [[ "${SYNTH_CHAIN_4H_LOCKED:-0}" != "1" ]]; then
    exec env SYNTH_CHAIN_4H_LOCKED=1 flock -n /tmp/synth_chain_4h.lock "$0" "$@"
fi

set -u

cd /home/gurk/projects/synth-v2 || exit 1
source venv/bin/activate

run_step() {
    echo "[CHAIN][4h][STEP] $*"
    "$@"
    rc=$?
    if [[ "$rc" -ne 0 ]]; then
        echo "[CHAIN][4h][FAIL] rc=$rc step=$*"
        exit "$rc"
    fi
}

echo "[CHAIN][4h] START $(date -u +%F' '%T) UTC"

run_step python -m src.etl.bitvavo.run_candles_etl --interval 4h
run_step python -m src.features.run_feat_candle --interval 4h
run_step python -m src.signal_engine.run_signal_state_etl --venue bitvavo --interval 4h
run_step python -m src.advice.run_advice_engine --interval 4h
run_step python -m src.ranking.run_ranking_engine --venue bitvavo --interval 4h
run_step python -m src.measurement.run_asset_interval_quality_snapshot --venue bitvavo --write-db --output none
run_step python -m src.selection.run_selection_engine_v2 --venue bitvavo --write-db

run_step python -m src.trade_setup_filter.run_trade_setup_filter_v1 \
    --venue bitvavo \
    --limit 40 \
    --asset-suitability-mode candidate_weak_set \
    --write-db \
    --output table

run_step python -m src.zone.run_zone_engine_v1 \
    --venue bitvavo \
    --interval 4h \
    --sleeve-code SWING_STRUCTURAL \
    --lookback-candles 300 \
    --limit-assets 100 \
    --write-db \
    --output table

echo "[CHAIN][4h] DONE  $(date -u +%F' '%T) UTC"
