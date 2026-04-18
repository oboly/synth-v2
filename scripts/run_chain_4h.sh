#!/usr/bin/env bash
set -euo pipefail

cd /home/gurk/projects/synth-v2
source venv/bin/activate

echo "[CHAIN][4h] START $(date -u +%F' '%T) UTC"

python -m src.etl.bitvavo.run_candles_etl --interval 4h
python -m src.features.run_feat_candle --interval 4h
python -m src.signal_engine.run_signal_state_etl --venue bitvavo --interval 4h
python -m src.advice.run_advice_engine --interval 4h
python -m src.ranking.run_ranking_engine --venue bitvavo --interval 4h
python -m src.selection.run_selection_engine --ranking-version v2

echo "[CHAIN][4h] DONE  $(date -u +%F' '%T) UTC"
