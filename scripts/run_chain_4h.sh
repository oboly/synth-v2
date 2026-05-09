#!/usr/bin/env bash

# Re-exec with bash when accidentally invoked through sh.
if [ -z "${BASH_VERSION:-}" ]; then
    exec bash "$0" "$@"
fi

# Prevent overlapping 4h chain runs.
# This protects DB writes and avoids duplicate/competing pipeline snapshots.
if [[ "${SYNTH_CHAIN_4H_LOCKED:-0}" != "1" ]]; then
    exec env SYNTH_CHAIN_4H_LOCKED=1 flock -n /tmp/synth_chain_4h.lock "$0" "$@"
fi

set -u

cd /home/gurk/projects/synth-v2 || exit 1

if [ -d ".venv" ]; then
    source .venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "[CHAIN][4h][FAIL] no .venv or venv found"
    exit 1
fi

run_step() {
    echo "[CHAIN][4h][STEP] $*"
    "$@"
    rc=$?
    if [[ "$rc" -ne 0 ]]; then
        echo "[CHAIN][4h][FAIL] rc=$rc step=$*"
        exit "$rc"
    fi
}

CHAIN_4H_END_TS="$(
    python -c 'from datetime import datetime, timezone; n=datetime.now(timezone.utc); h=(n.hour//4)*4; print(n.replace(hour=h, minute=0, second=0, microsecond=0).isoformat())'
)"
CHAIN_4H_ETL_START_TS="$(
    python -c 'from datetime import datetime, timezone, timedelta; n=datetime.now(timezone.utc); h=(n.hour//4)*4; e=n.replace(hour=h, minute=0, second=0, microsecond=0); print((e - timedelta(days=14)).isoformat())'
)"

echo "[CHAIN][4h] START $(date -u +%F' '%T) UTC"
echo "[CHAIN][4h] ETL window start=${CHAIN_4H_ETL_START_TS} end=${CHAIN_4H_END_TS}"
echo "[CHAIN][4h] feature window lookback_hours=720 warmup_bars=300"
echo "[CHAIN][4h] decision/execution modules intentionally absent"

run_step python -m src.etl.bitvavo.run_candles_etl \
    --interval 4h \
    --start "$CHAIN_4H_ETL_START_TS" \
    --end "$CHAIN_4H_END_TS"

run_step python -m src.features.run_feat_candle \
    --interval 4h \
    --lookback-hours 720 \
    --warmup-bars 300

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

echo "[CHAIN][4h] DONE  $(date -u +%F' '%T) UTC"
