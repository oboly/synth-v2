# Breath Curve Broader-History Validation Findings — 2026-05-13

Status: research-only  
Layer: market-only / account-agnostic  
Broker calls: none  
Broker writes: none  
Orders: none  
Runtime impact: none  

## Purpose

Document broader-history validation for the calibrated Breath Curve composite candidates.

This run validates whether the strongest composite candidates survive across rolling 21-day anchor cohorts with same-symbol random-anchor baselines.

## Source

Runner:

    python -m src.research.run_breath_curve_broader_history_v1

Run:

    python -m src.research.run_breath_curve_broader_history_v1 \
      --output table

Anchor grid:

    2026-01-18
    2026-02-08
    2026-03-01
    2026-03-22
    2026-04-12

Cohorts:

    cohort_01_20260118_20260301
    cohort_02_20260208_20260322
    cohort_03_20260301_20260412

Random windows:

    28-day pre-pad
    0-day post-pad

This avoids sampling random anchors after the latest real cohort anchor and reduces forward-data incompleteness risk.

Core symbols:

    BTC
    ETH
    FIL
    TAO

Boundary:

    post_hoc_fields_used_as_filters = 0
    db_writes = 0
    broker_calls = 0
    broker_writes = 0
    order_submission = 0

## Important limitation

The rolling cohorts overlap.

Therefore aggregate rows are not fully independent observations.

This run is a strong robustness preview, not final out-of-sample proof.

## Aggregate comparison

| composite | cohorts | real eligible | real selection rate | real avg to 1.000 | real positive to 1.000 | real worst to 1.000 | random eligible | random selection rate | random avg to 1.000 | random positive to 1.000 | random worst to 1.000 | edge to 1.000 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| early_band_core_and_bear_or_volume_v1 | 3 | 15 | 20.83% | 13.5497 | 100.00% | 2.5578 | 149 | 12.42% | 5.9745 | 90.60% | -4.1306 | +7.5752 |
| minus8_all_v1 | 3 | 24 | 33.33% | 9.2715 | 100.00% | 2.2444 | 142 | 11.83% | 6.8681 | 100.00% | 0.8000 | +2.4034 |
| minus8_btc_eth_bear_v1 | 3 | 24 | 33.33% | 9.2715 | 100.00% | 2.2444 | 116 | 9.67% | 6.8922 | 100.00% | 0.8000 | +2.3793 |
| minus8_core_and_bear_or_volume_v1 | 3 | 13 | 18.06% | 14.1259 | 100.00% | 2.5578 | 52 | 4.33% | 7.1885 | 100.00% | 0.8000 | +6.9374 |
| minus8_core_and_btc_eth_bear_v1 | 3 | 13 | 18.06% | 14.1259 | 100.00% | 2.5578 | 51 | 4.25% | 7.1008 | 100.00% | 0.8000 | +7.0251 |
| minus8_core_and_volume_expansion_v1 | 3 | 7 | 9.72% | 18.4782 | 100.00% | 2.5578 | 12 | 1.00% | 6.7274 | 100.00% | 1.9253 | +11.7508 |
| minus8_core_not_btc_eth_bull_v1 | 3 | 13 | 18.06% | 14.1259 | 100.00% | 2.5578 | 56 | 4.67% | 7.0930 | 100.00% | 0.8000 | +7.0329 |
| minus8_core_symbols_v1 | 3 | 13 | 18.06% | 14.1259 | 100.00% | 2.5578 | 59 | 4.92% | 7.1883 | 100.00% | 0.8000 | +6.9376 |
| minus8_volume_expansion_v1 | 3 | 8 | 11.11% | 16.6022 | 100.00% | 2.5578 | 29 | 2.42% | 6.0156 | 100.00% | 1.9253 | +10.5866 |

## Main finding

The broader-history validation supports the core thesis:

    0.618 selected -8
    + symbol in [BTC, ETH, FIL, TAO]
    -> early pulse-to-1.000 research candidate

This candidate survived all three rolling cohorts.

## Primary balanced candidate

Composite:

    minus8_core_symbols_v1

Aggregate:

    real eligible = 13
    random eligible = 59
    real avg to 1.000 = 14.1259
    random avg to 1.000 = 7.1883
    edge to 1.000 = +6.9376
    real worst to 1.000 = +2.5578
    random worst to 1.000 = +0.8000
    real positive to 1.000 = 100.00%

Cohort details:

| cohort | real eligible | real avg to 1.000 | real worst to 1.000 | random eligible | random avg to 1.000 | random worst to 1.000 | edge to 1.000 |
|---|---:|---:|---:|---:|---:|---:|---:|
| cohort_01_20260118_20260301 | 5 | 12.5835 | 2.5578 | 20 | 7.8156 | 0.8000 | +4.7679 |
| cohort_02_20260208_20260322 | 4 | 15.0899 | 4.9075 | 22 | 5.5398 | 0.8000 | +9.5501 |
| cohort_03_20260301_20260412 | 4 | 15.0899 | 4.9075 | 17 | 8.5836 | 1.2192 | +6.5063 |

Interpretation:

The core-symbol filter materially improves the original -8 signal and remains positive across all tested cohorts.

Status:

    primary balanced research candidate

## Precision candidate

Composite:

    minus8_core_and_volume_expansion_v1

Aggregate:

    real eligible = 7
    random eligible = 12
    real avg to 1.000 = 18.4782
    random avg to 1.000 = 6.7274
    edge to 1.000 = +11.7508
    real worst to 1.000 = +2.5578
    random worst to 1.000 = +1.9253

Interpretation:

Volume expansion remains the strongest precision clue after broader-history validation.

Status:

    high-priority precision hypothesis

Limitation:

    still sample-thin

## Volume expansion candidate

Composite:

    minus8_volume_expansion_v1

Aggregate:

    real eligible = 8
    random eligible = 29
    real avg to 1.000 = 16.6022
    random avg to 1.000 = 6.0156
    edge to 1.000 = +10.5866

Interpretation:

Volume expansion improves the -8 signal, but it should remain a research filter until tested over more anchors.

## BTC/ETH bear context

Composite:

    minus8_core_and_btc_eth_bear_v1

Aggregate:

    real eligible = 13
    random eligible = 51
    real avg to 1.000 = 14.1259
    random avg to 1.000 = 7.1008
    edge to 1.000 = +7.0251

Interpretation:

BTC_ETH_BEAR context supports the current working thesis.

The setup appears more like a bearish-context rebound / early rotation pulse than a bull-continuation setup.

## Recall candidate

Composite:

    early_band_core_and_bear_or_volume_v1

Aggregate:

    real eligible = 15
    random eligible = 149
    real avg to 1.000 = 13.5497
    random avg to 1.000 = 5.9745
    edge to 1.000 = +7.5752
    real worst to 1.000 = +2.5578
    random worst to 1.000 = -4.1306

Interpretation:

This is the strongest recall-oriented candidate.

Limitation:

    includes selected -7, which was demoted as a standalone signal

Status:

    useful recall candidate
    not the cleanest precision candidate

## Updated research ranking

Primary balanced candidate:

    minus8_core_symbols_v1

Precision candidate:

    minus8_core_and_volume_expansion_v1

Context-confirming candidate:

    minus8_core_and_btc_eth_bear_v1

Recall candidate:

    early_band_core_and_bear_or_volume_v1

Baseline candidate:

    minus8_all_v1

## Current working thesis

Best current hypothesis:

    0.618 selected -8
    + core symbols [BTC, ETH, FIL, TAO]
    -> early pulse-to-1.000 candidate

Precision overlay hypothesis:

    + volume expansion

Context overlay hypothesis:

    + BTC_ETH_BEAR

Target:

    return_to_1.000

Not target:

    return_to_1.272

## Architecture boundary

These findings are not strategy rules.

Forbidden downstream use:

    selection_engine modifier
    decision_gate rule
    execution_planner instruction
    executor/order logic
    live or paper execution trigger

Correct path:

    broader-history validation
    -> broader non-overlapping / older-history validation
    -> optional market-only feature proposal after validation

## Next validation

Recommended next step:

    non-overlapping / older-history validation

Reason:

    current cohorts overlap
    current data window is still narrow
    more regimes are needed before feature proposal

Candidate settings:

    start-anchor before 2026-01-18
    end-anchor 2026-04-12
    cohort stride = 3
    more non-overlapping cohorts if data supports it

Questions:

    Does minus8_core_symbols_v1 survive non-overlapping cohorts?
    Does volume expansion remain a precision filter?
    Does BTC_ETH_BEAR remain supportive across older regimes?
    Does the edge hold outside the January-April 2026 structure?
    Can A+ FORMING_EARLY improve precision without introducing leakage?
