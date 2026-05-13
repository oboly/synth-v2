# Breath Curve Composite Preview Findings — 2026-05-13

Status: research-only  
Layer: market-only / account-agnostic  
Broker calls: none  
Broker writes: none  
Orders: none  
Runtime impact: none  

## Purpose

Document composite research-preview results for calibrated Breath Curve 0.618 selected -8 filters.

Primary question:

    Can symbol/context filters improve the 0618_selected_minus8_v1 edge?

## Source

Runner:

    python -m src.research.run_breath_curve_composite_preview_v1

Input:

    data/research/breath_curve_symbol_regime_validation_v1/breath_curve_symbol_regime_validation_v1_20260513T145119Z_enriched_rows.csv

Run:

    python -m src.research.run_breath_curve_composite_preview_v1 \
      --output table

Core symbols:

    BTC
    ETH
    FIL
    TAO

Rows:

    ok_rows = 424
    selected_rows = 236

Boundary:

    post_hoc_fields_used_as_filters = 0
    db_writes = 0
    broker_calls = 0
    broker_writes = 0
    order_submission = 0

## Composite comparison

| composite | real eligible | real selection rate | real avg to 1.000 | real positive to 1.000 | real worst to 1.000 | random eligible | random selection rate | random avg to 1.000 | random positive to 1.000 | random worst to 1.000 | edge to 1.000 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| minus8_all_v1 | 8 | 33.33% | 9.2598 | 100.00% | 2.2444 | 52 | 13.00% | 6.6252 | 100.00% | 1.1140 | +2.6346 |
| minus8_core_symbols_v1 | 4 | 16.67% | 15.0899 | 100.00% | 4.9075 | 19 | 4.75% | 8.0116 | 100.00% | 1.2192 | +7.0783 |
| minus8_btc_eth_bear_v1 | 8 | 33.33% | 9.2598 | 100.00% | 2.2444 | 36 | 9.00% | 7.3334 | 100.00% | 1.2192 | +1.9264 |
| minus8_volume_expansion_v1 | 2 | 8.33% | 21.1316 | 100.00% | 15.6420 | 3 | 0.75% | 2.9213 | 100.00% | 2.4084 | +18.2103 |
| minus8_core_and_btc_eth_bear_v1 | 4 | 16.67% | 15.0899 | 100.00% | 4.9075 | 15 | 3.75% | 8.4780 | 100.00% | 1.2192 | +6.6119 |
| minus8_core_and_volume_expansion_v1 | 2 | 8.33% | 21.1316 | 100.00% | 15.6420 | 0 | 0.00% | n/a | n/a | n/a | n/a |
| minus8_core_and_bear_or_volume_v1 | 4 | 16.67% | 15.0899 | 100.00% | 4.9075 | 15 | 3.75% | 8.4780 | 100.00% | 1.2192 | +6.6119 |
| early_band_core_and_bear_or_volume_v1 | 5 | 20.83% | 14.0328 | 100.00% | 4.9075 | 39 | 9.75% | 5.9144 | 92.31% | -4.1306 | +8.1184 |
| minus8_core_not_btc_eth_bull_v1 | 4 | 16.67% | 15.0899 | 100.00% | 4.9075 | 16 | 4.00% | 8.5351 | 100.00% | 1.2192 | +6.5548 |

## Main finding

The best balanced candidate is:

    minus8_core_symbols_v1

Reason:

    improves avg return to 1.000 versus minus8_all_v1
    improves worst-case return
    removes weak/noisy symbols
    keeps random comparison possible
    does not rely on post-hoc fields

Current label:

    0.618 selected -8
    + core symbol subset
    = early pulse-to-1.000 research candidate

## Core-symbol candidate

Composite:

    minus8_core_symbols_v1

Core symbols:

    BTC
    ETH
    FIL
    TAO

Result:

    real eligible = 4
    random eligible = 19
    real avg to 1.000 = 15.0899
    random avg to 1.000 = 8.0116
    edge to 1.000 = +7.0783
    real worst to 1.000 = +4.9075
    random worst to 1.000 = +1.2192
    real positive to 1.000 = 100%

Interpretation:

Symbol filtering materially improves the -8 signal.

## Volume-expansion clue

Composite:

    minus8_volume_expansion_v1

Result:

    real eligible = 2
    random eligible = 3
    real avg to 1.000 = 21.1316
    random avg to 1.000 = 2.9213
    edge to 1.000 = +18.2103
    real worst to 1.000 = +15.6420

Interpretation:

Volume expansion is the strongest precision clue.

Limitation:

    sample is too small

Status:

    high-signal but under-sampled hypothesis

## Core + volume

Composite:

    minus8_core_and_volume_expansion_v1

Result:

    real eligible = 2
    random eligible = 0

Interpretation:

This may be a high-quality bucket, but there is no fair random comparison yet.

Status:

    do not promote
    validate over broader history

## BTC/ETH bearish context

Composite:

    minus8_core_and_btc_eth_bear_v1

Result:

    real eligible = 4
    random eligible = 15
    real avg to 1.000 = 15.0899
    random avg to 1.000 = 8.4780
    edge to 1.000 = +6.6119

Interpretation:

All current real core-symbol -8 cases occurred in BTC_ETH_BEAR context.

Working thesis:

    0.618 selected -8 is not a bull-continuation setup.
    It behaves more like a bearish-context rebound / early rotation pulse.

## Recall variant

Composite:

    early_band_core_and_bear_or_volume_v1

Result:

    real eligible = 5
    random eligible = 39
    real avg to 1.000 = 14.0328
    random avg to 1.000 = 5.9144
    edge to 1.000 = +8.1184
    real worst to 1.000 = +4.9075
    random worst to 1.000 = -4.1306

Interpretation:

This is the best recall-oriented variant.

Limitation:

    includes -7, which was demoted as standalone

Status:

    useful broader recall candidate
    not primary precision candidate

## Current ranking

Primary balanced candidate:

    minus8_core_symbols_v1

Precision hypothesis:

    minus8_volume_expansion_v1

High-signal but under-sampled:

    minus8_core_and_volume_expansion_v1

Context-confirming candidate:

    minus8_core_and_btc_eth_bear_v1

Recall candidate:

    early_band_core_and_bear_or_volume_v1

## Updated working thesis

Best current research hypothesis:

    0.618 selected -8
    + symbol in [BTC, ETH, FIL, TAO]
    -> early pulse-to-1.000 candidate

Additional precision clue:

    volume expansion

Context clue:

    BTC_ETH_BEAR

Target:

    return_to_1.000

Not target:

    return_to_1.272

## Next validation

Recommended next step:

    broader-history composite validation

Requirements:

    more anchors
    more market regimes
    same-symbol random baselines
    no post-hoc filters
    separate 1.000 pulse target from 1.272 extension target

Questions:

    Does minus8_core_symbols_v1 survive broader history?
    Does volume expansion remain useful with more samples?
    Does BTC_ETH_BEAR consistently improve selection quality?
    Is the edge symbol-specific or regime-specific?
    Can A+ FORMING_EARLY improve precision?

## Boundary

These findings are not strategy rules.

Forbidden downstream use:

    selection_engine modifier
    decision_gate rule
    execution_planner instruction
    executor/order logic
    live or paper execution trigger

Correct path:

    composite preview
    -> broader-history validation
    -> optional market-only feature proposal after validation
