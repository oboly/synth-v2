# Breath Curve Symbol/Regime Validation v1

Status: research-only  
Layer: market-only / account-agnostic  
Broker calls: none  
Broker writes: none  
Orders: none  
Runtime impact: none  

## Purpose

Validate where the calibrated Breath Curve 0.618 early-recognition filters work and where they fail.

This runner reads generated random-anchor baseline rows and summarizes policy outcomes by symbol and optional market/feature regime buckets.

## Input

Default input:

    latest data/research/breath_curve_random_anchor_baseline_v2/*_all_rows.csv

The input should come from:

    src/research/run_breath_curve_random_anchor_baseline_v2.py

## Tested filters

Only early-available filters are evaluated:

    0618_selected_minus8_v1
    0618_selected_minus7_v1
    0618_selected_early_band_v1

Post-hoc labels are not used as filters:

    0786_ignition_band_match_v1
    extension_best_full_plus7_v1
    best_full_band
    phase_drift_bucket

## Optional DB context

By default the runner is CSV-only.

With:

    --db-context

it attempts to enrich rows from `feat_candle` using latest feature rows at or before `as_of_ts_utc`.

Optional context buckets include:

    symbol_trend_bucket
    symbol_rsi_bucket
    symbol_volume_bucket
    symbol_atr_bucket
    btc_trend_bucket
    eth_trend_bucket
    btc_eth_context_bucket

The DB context is read-only.

No DB writes are performed.

## Runner

CSV-only:

    python -m src.research.run_breath_curve_symbol_regime_validation_v1 --output table

With DB context:

    python -m src.research.run_breath_curve_symbol_regime_validation_v1 \
      --db-context \
      --output table

With explicit input:

    python -m src.research.run_breath_curve_symbol_regime_validation_v1 \
      --input-csv data/research/breath_curve_random_anchor_baseline_v2/breath_curve_random_anchor_baseline_v2_YYYYMMDDTHHMMSSZ_all_rows.csv \
      --output table

## Output

Generated CSV files are written under:

    data/research/breath_curve_symbol_regime_validation_v1/

This path should remain ignored by git.

Outputs include:

    enriched rows
    policy rows
    source summary
    symbol comparison
    symbol bucket summary
    symbol trend summary
    BTC/ETH context summary
    volume summary
    RSI summary

## Boundary

Allowed:

    research-only validation
    market-only bucketing
    DB reads from feature tables
    generated CSV outputs

Forbidden:

    selection_engine modifier
    decision_gate rule
    execution_planner instruction
    executor/order logic
    broker API call
    broker write
    live or paper execution trigger

## Interpretation rule

This runner answers:

    where does 0618_selected_minus8_v1 work?

It does not create a strategy.

Correct path:

    symbol/regime validation
    -> broader history validation
    -> optional market-only feature proposal

Incorrect path:

    good bucket
    -> BUY_READY

That would bypass the architecture.
