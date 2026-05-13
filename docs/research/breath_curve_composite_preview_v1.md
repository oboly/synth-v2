# Breath Curve Composite Preview v1

Status: research-only  
Layer: market-only / account-agnostic  
Broker calls: none  
Broker writes: none  
Orders: none  
Runtime impact: none  

## Purpose

Preview composite research filters for the calibrated Breath Curve 0.618 selected -8 candidate.

This runner reads enriched symbol/regime validation rows and tests whether context filters improve precision against random anchors.

## Input

Default input:

    latest data/research/breath_curve_symbol_regime_validation_v1/*_enriched_rows.csv

Recommended input should be generated with DB context:

    python -m src.research.run_breath_curve_symbol_regime_validation_v1 \
      --db-context \
      --output table

## Composite candidates

The runner evaluates:

    minus8_all_v1
    minus8_core_symbols_v1
    minus8_btc_eth_bear_v1
    minus8_volume_expansion_v1
    minus8_core_and_btc_eth_bear_v1
    minus8_core_and_volume_expansion_v1
    minus8_core_and_bear_or_volume_v1
    early_band_core_and_bear_or_volume_v1
    minus8_core_not_btc_eth_bull_v1

Default core symbols:

    TAO
    ETH
    FIL
    BTC

## Critical boundary

These are research previews only.

They are not:

    strategy rules
    selection_engine modifiers
    decision_gate rules
    execution_planner inputs
    executor/order logic

## No post-hoc filters

The runner does not use these as filters:

    best_full_band
    phase_drift_bucket
    0786_ignition_band_match
    extension_best_full_plus7

It only uses checkpoint-time or context fields already present in enriched rows.

## Runner

Default:

    python -m src.research.run_breath_curve_composite_preview_v1 --output table

With custom core symbols:

    python -m src.research.run_breath_curve_composite_preview_v1 \
      --core-symbols TAO,ETH,FIL,BTC \
      --output table

## Output

Generated CSV files are written under:

    data/research/breath_curve_composite_preview_v1/

This path should remain ignored by git.

Outputs include:

    selected rows
    source summary
    real-vs-random comparison
    symbol summary
    BTC/ETH context summary
    volume summary
    RSI summary
    trend summary

## Interpretation rule

A composite candidate is interesting only if it improves:

    edge to 1.000
    positive rate
    worst-case return
    selection quality

It still remains research-only.

Correct path:

    composite preview
    -> broader history validation
    -> optional market-only feature proposal

Incorrect path:

    composite preview
    -> BUY_READY

That would bypass the architecture.
