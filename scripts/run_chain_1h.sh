#!/usr/bin/env bash
set -euo pipefail

cd /home/gurk/projects/synth-v2
source venv/bin/activate

echo "[CHAIN][1h] START $(date -u +%F' '%T) UTC"

python -m src.etl.bitvavo.run_candles_etl --interval 1h
python -m src.features.run_feat_candle --interval 1h
python -m src.signal_engine.run_signal_state_etl --venue bitvavo --interval 1h
python -m src.advice.run_advice_engine --interval 1h
python -m src.ranking.run_ranking_engine --venue bitvavo --interval 1h
python -m src.selection.run_selection_engine_v2 --venue bitvavo --write-db

python -m src.trade_setup_filter.run_trade_setup_filter_v1 \
    --venue bitvavo \
    --limit 40 \
    --asset-suitability-mode candidate_weak_set \
    --write-db \
    --output table
python -m src.plan_lifecycle.run_plan_lifecycle --account-id 1 --venue bitvavo --output table

echo "[CHAIN][1h] DONE  $(date -u +%F' '%T) UTC"
