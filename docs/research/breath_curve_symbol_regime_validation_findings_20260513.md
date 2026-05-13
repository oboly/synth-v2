# Breath Curve Symbol/Regime Validation Findings — 2026-05-13

Status: research-only  
Layer: market-only / account-agnostic  
Broker calls: none  
Broker writes: none  
Orders: none  
Runtime impact: none  

## Purpose

Document symbol/regime validation for calibrated Breath Curve random-anchor baseline v2.

Primary focus:

    0618_selected_minus8_v1

Current label:

    early pulse-to-1.000 candidate

## Source

Runner:

    python -m src.research.run_breath_curve_symbol_regime_validation_v1

Input:

    data/research/breath_curve_random_anchor_baseline_v2/breath_curve_random_anchor_baseline_v2_20260513T143849Z_all_rows.csv

DB-context run:

    python -m src.research.run_breath_curve_symbol_regime_validation_v1 \
      --db-context \
      --output table

Rows:

    ok_rows = 424
    policy_rows = 282

Boundary:

    post_hoc_fields_used_as_filters = 0
    db_writes = 0
    broker_calls = 0
    broker_writes = 0
    order_submission = 0

## Global source summary

| policy | source | eval | eligible | selection rate | avg to 1.000 | positive to 1.000 | worst to 1.000 | avg to 1.272 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 0618_selected_minus8_v1 | real | 24 | 8 | 33.33% | 9.2598 | 100.00% | 2.2444 | 7.2601 |
| 0618_selected_minus8_v1 | random | 400 | 52 | 13.00% | 6.6252 | 100.00% | 1.1140 | 8.2763 |
| 0618_selected_minus7_v1 | real | 24 | 4 | 16.67% | 5.0171 | 100.00% | 2.4194 | 1.8931 |
| 0618_selected_minus7_v1 | random | 400 | 77 | 19.25% | 4.7196 | 87.01% | -4.1306 | 8.7367 |
| 0618_selected_early_band_v1 | real | 24 | 12 | 50.00% | 7.8456 | 100.00% | 2.2444 | 5.4711 |
| 0618_selected_early_band_v1 | random | 400 | 129 | 32.25% | 5.4878 | 92.25% | -4.1306 | 8.5511 |

## Primary candidate

### 0618_selected_minus8_v1

Classification:

    primary early pulse-to-1.000 research candidate

Findings:

    real avg to 1.000 > random avg to 1.000
    real selection rate > random selection rate
    real worst return to 1.000 > random worst return to 1.000
    real positive rate to 1.000 = 100%

Interpretation:

0.618 selected -8 remains the strongest calibrated Breath Curve early-recognition filter.

## Symbol bucket findings

For 0618_selected_minus8_v1:

| symbol | real eligible | real avg to 1.000 | random eligible | random avg to 1.000 | edge |
|---|---:|---:|---:|---:|---:|
| TAO | 1 | 26.6212 | 3 | 9.8667 | +16.7545 |
| ETH | 1 | 13.1889 | 5 | 6.2144 | +6.9745 |
| FIL | 1 | 15.6420 | 6 | 11.4728 | +4.1692 |
| BTC | 1 | 4.9075 | 5 | 4.5423 | +0.3652 |
| HBAR | 2 | 4.1750 | 7 | 6.2481 | -2.0731 |
| PEPE | 1 | 3.1242 | 10 | 5.8161 | -2.6919 |
| XLM | 1 | 2.2444 | 7 | 4.8059 | -2.5615 |
| RENDER | 0 | n/a | 9 | 6.3056 | n/a |

Interpretation:

The -8 edge is not universal.

Promising symbols:

    TAO
    ETH
    FIL
    BTC

Weak/noisy symbols:

    HBAR
    PEPE
    XLM

Unknown in real anchors:

    RENDER

## BTC/ETH context findings

For 0618_selected_minus8_v1:

| BTC/ETH context | source | eval | eligible | selection rate | avg to 1.000 | worst to 1.000 |
|---|---|---:|---:|---:|---:|---:|
| BTC_ETH_BEAR | real | 16 | 8 | 50.00% | 9.2598 | 2.2444 |
| BTC_ETH_BEAR | random | 259 | 36 | 13.90% | 7.3334 | 1.2192 |
| BTC_ETH_BULL | real | 8 | 0 | 0.00% | n/a | n/a |
| BTC_ETH_BULL | random | 128 | 14 | 10.94% | 4.5224 | 1.1140 |

Interpretation:

The real -8 edge occurred inside BTC_ETH_BEAR context, not BTC_ETH_BULL context.

Working thesis:

    0.618 selected -8 may be an early rebound / rotation pulse inside bearish BTC/ETH context.

This should be validated on broader history before any feature proposal.

## Symbol trend findings

For 0618_selected_minus8_v1:

| symbol trend | source | eval | eligible | selection rate | avg to 1.000 |
|---|---|---:|---:|---:|---:|
| TREND_BEAR | real | 14 | 7 | 50.00% | 6.7796 |
| TREND_BEAR | random | 305 | 43 | 14.10% | 7.0851 |
| TREND_BULL | real | 10 | 1 | 10.00% | 26.6212 |
| TREND_BULL | random | 95 | 9 | 9.47% | 4.4280 |

Interpretation:

Trend bucket alone is not enough.

The single TREND_BULL real -8 case appears strong but sample-thin.

TREND_BEAR improves real selection rate but not average return versus random.

## Volume findings

For 0618_selected_minus8_v1:

| volume bucket | source | eval | eligible | selection rate | avg to 1.000 | worst to 1.000 |
|---|---|---:|---:|---:|---:|---:|
| VOLUME_EXPANSION | real | 2 | 2 | 100.00% | 21.1316 | 15.6420 |
| VOLUME_EXPANSION | random | 63 | 3 | 4.76% | 2.9213 | 2.4084 |
| VOLUME_NORMAL | real | 13 | 4 | 30.77% | 5.3585 | 2.2444 |
| VOLUME_NORMAL | random | 167 | 23 | 13.77% | 7.8542 | 1.2192 |
| VOLUME_THIN | real | 9 | 2 | 22.22% | 5.1905 | 4.9075 |
| VOLUME_THIN | random | 170 | 26 | 15.29% | 5.9654 | 1.1140 |

Interpretation:

The strongest regime clue is:

    0618 selected -8 + volume expansion

This bucket is sample-thin but materially stronger than random in both selection frequency and average return.

## RSI findings

For 0618_selected_minus8_v1:

| RSI bucket | source | eval | eligible | selection rate | avg to 1.000 |
|---|---|---:|---:|---:|---:|
| RSI_HIGH | real | 8 | 1 | 12.50% | 26.6212 |
| RSI_LOW | real | 2 | 1 | 50.00% | 2.8766 |
| RSI_MID | real | 14 | 6 | 42.86% | 7.4301 |
| RSI_EXTREME | random | 8 | 1 | 12.50% | 9.3919 |
| RSI_HIGH | random | 67 | 5 | 7.46% | 3.8270 |
| RSI_LOW | random | 69 | 13 | 18.84% | 9.8892 |
| RSI_MID | random | 256 | 33 | 12.89% | 5.6795 |

Interpretation:

RSI_MID appears supportive for real -8 selection frequency.

RSI_HIGH contains the strongest real return but is sample-thin.

RSI_LOW is not obviously useful.

## Updated working thesis

Primary candidate:

    0618_selected_minus8_v1

Best current context hypothesis:

    0618 selected -8
    + BTC_ETH_BEAR context
    + volume expansion
    + symbol subset TAO / ETH / FIL / BTC

Meaning:

    early pulse-to-1.000 candidate
    not a 1.272 extension candidate

Demoted:

    0618_selected_minus7_v1

Broader recall candidate:

    0618_selected_early_band_v1

## Next validation

Recommended next step:

    build composite bucket report / rule preview

Candidate research preview only:

    0618_selected_minus8_v1
    symbol in [TAO, ETH, FIL, BTC]
    volume_bucket = VOLUME_EXPANSION or BTC_ETH_BEAR
    target = return_to_1.000

Questions to test:

    Does volume expansion improve -8 edge over broader history?
    Does BTC_ETH_BEAR context consistently improve selection quality?
    Does the symbol subset survive more anchors?
    Can A+ FORMING_EARLY improve precision?
    Can 0.786 ignition labels predict 1.272 extension separately?

## Boundary

These findings are not strategy rules.

Forbidden downstream use:

    selection_engine modifier
    decision_gate rule
    execution_planner instruction
    executor/order logic
    live or paper execution trigger

Correct path:

    symbol/regime validation
    -> composite research preview
    -> broader history validation
    -> optional market-only feature proposal after validation
