# Breath Curve Calibrated Policy Backtest v1

Status: research-only  
Layer: market-only / account-agnostic  
Broker calls: none  
Broker writes: none  
Orders: none  
Runtime impact: none  

## Purpose

Apply calibrated Breath Curve research-policy filters using band and phase-drift metrics instead of brittle exact offset equality.

This runner converts partial-to-full Breath Curve rows into annotated calibrated research rows and reports policy buckets.

## Input

The runner consumes CSV output from:

    src/research/backtest_breath_curve_partial_to_full_v1.py

Expected relevant columns include:

    status
    symbol
    anchor_ts_utc
    checkpoint_ratio
    selected_partial_offset_days
    selected_partial_score
    best_full_offset_days
    offset_matches_best_full
    return_to_1000_pct
    return_to_1272_pct

## Derived fields

The runner adds:

    selected_offset_days
    best_full_offset_days
    offset_distance_days
    offset_distance_bucket
    selected_band_w0_5
    selected_band_w1_0
    selected_band_w1_5
    best_full_band_w0_5
    best_full_band_w1_0
    best_full_band_w1_5
    band_match_1_0
    band_match_1_5
    phase_drift_days
    phase_drift_bucket
    offset_match_legacy

`offset_match_legacy` is retained as a diagnostic only.

It is not the primary quality filter.

## Policies

### 0618_selected_early_band_v1

Purpose:

    early measured recognition / forming structure

Gate:

    checkpoint_ratio = 0.618
    selected_band_w1_0 in [-8, -7]

### 0786_ignition_band_match_v1

Purpose:

    ignition / overflow confirmation

Gate:

    checkpoint_ratio = 0.786
    band_match_1_0 = true OR band_match_1_5 = true

### extension_best_full_plus7_v1

Purpose:

    extension / overflow path research

Gate:

    best_full_band_w1_0 = +7

## Runner

    python -m src.research.run_breath_curve_calibrated_policy_backtest_v1 \
      --input-csv data/research/breath_curve_template_matcher_v1/breath_curve_partial_to_full_v1_YYYYMMDDTHHMMSSZ.csv \
      --output table

Optional:

    --bands "-10.5,-9,-8,-7,-5,-3,0,3,5,7,9,10.5"
    --out-dir data/research/breath_curve_calibrated_policy_backtest_v1

## Output

Generated CSV files are written under:

    data/research/breath_curve_calibrated_policy_backtest_v1/

The output includes:

    annotated rows
    policy rows
    policy summary
    policy by-symbol summary
    policy by-selected-band summary
    policy by-best-full-band summary
    policy by-phase-drift summary

## Boundary

Allowed:

    research filtering
    market-only measurement
    calibrated phase bucket reporting
    future random-anchor comparison

Forbidden:

    selection_engine modifier
    decision_gate rule
    execution_planner instruction
    executor/order logic
    broker API call
    broker write
    live or paper execution trigger

## Interpretation rule

These outputs are not strategy rules.

They are candidate research labels only.

Correct downstream path:

    calibrated research policy
    -> same-symbol random-anchor baseline
    -> regime bucket validation
    -> optional market-only feature proposal after validation

Incorrect downstream path:

    calibrated policy
    -> BUY_READY

That would bypass the architecture.
