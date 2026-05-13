# Breath Curve Random-Anchor Baseline Findings — 2026-05-13

Status: research-only  
Layer: market-only / account-agnostic  
Broker calls: none  
Broker writes: none  
Orders: none  
Runtime impact: none  

## Purpose

Document the first same-symbol random-anchor baseline v2 run for calibrated 0.618 Breath Curve early-recognition filters.

This test checks whether the calibrated early filters outperform random anchors sampled from the same symbol universe and a broader same-regime window.

## Source

Runner:

    python -m src.research.run_breath_curve_random_anchor_baseline_v2

Run:

    python -m src.research.run_breath_curve_random_anchor_baseline_v2 \
      --random-window-start 2026-02-01 \
      --random-window-end 2026-04-20 \
      --random-count-per-symbol 50 \
      --output table

Configuration:

    real anchors: 2026-03-01, 2026-03-22, 2026-04-12
    random window: 2026-02-01 .. 2026-04-20
    random count per symbol: 50
    symbols: BTC, ETH, TAO, RENDER, FIL, HBAR, XLM, PEPE
    checkpoint: 0.618
    post-hoc fields used as filters: 0

Rows:

    total evaluated rows: 424
    policy rows: 282
    real evaluated rows: 24
    random evaluated rows: 400

## Tested filters

Only early-available filters were tested:

    0618_selected_minus8_v1
    0618_selected_minus7_v1
    0618_selected_early_band_v1

Post-hoc labels were not used as filters:

    0786_ignition_band_match_v1
    extension_best_full_plus7_v1
    best_full_band
    phase_drift_bucket

## Main comparison

| policy | real eligible | real selection rate | real avg to 1.000 | real positive to 1.000 | real worst to 1.000 | random eligible | random selection rate | random avg to 1.000 | random positive to 1.000 | random worst to 1.000 | edge to 1.000 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0618_selected_minus8_v1 | 8 | 33.33% | 9.2598 | 100.00% | 2.2444 | 52 | 13.00% | 6.6252 | 100.00% | 1.1140 | +2.6346 |
| 0618_selected_minus7_v1 | 4 | 16.67% | 5.0171 | 100.00% | 2.4194 | 77 | 19.25% | 4.7196 | 87.01% | -4.1306 | +0.2975 |
| 0618_selected_early_band_v1 | 12 | 50.00% | 7.8456 | 100.00% | 2.2444 | 129 | 32.25% | 5.4878 | 92.25% | -4.1306 | +2.3578 |

## Interpretation

### 0618_selected_minus8_v1

Classification:

    primary early-recognition candidate

Findings:

    real_avg1000 > random_avg1000
    real selection rate > random selection rate
    real worst1000 > random worst1000
    real positive rate = 100%

Interpretation:

0.618 selected -8 survived the broader same-symbol random-anchor baseline.

The edge compressed relative to the smaller smoke run but remained positive.

Current label:

    early pulse-to-1.000 candidate

Important limitation:

This is not currently an extension-to-1.272 candidate.

### 0618_selected_early_band_v1

Classification:

    broader early-recognition candidate

Findings:

    real_avg1000 = 7.8456
    random_avg1000 = 5.4878
    edge1000 = +2.3578
    real worst1000 = +2.2444
    random worst1000 = -4.1306

Interpretation:

The combined -7/-8 early band remains useful but appears weaker than pure -8.

### 0618_selected_minus7_v1

Classification:

    demoted / secondary candidate

Findings:

    edge1000 = +0.2975
    real selection rate = 16.67%
    random selection rate = 19.25%

Interpretation:

0.618 selected -7 does not currently justify standalone use.

It may remain as a supportive or broader-band component, but not as the primary early-recognition filter.

## 1.272 target warning

The random baseline performed better on average return to 1.272 for the main early filters:

| policy | real avg to 1.272 | random avg to 1.272 |
|---|---:|---:|
| 0618_selected_minus8_v1 | 7.2601 | 8.2763 |
| 0618_selected_early_band_v1 | 5.4711 | 8.5511 |

Interpretation:

The 0.618 selected -8 edge is currently about the move toward 1.000, not the 1.272 extension.

Do not use 0.618 selected -8 as an extension target rule.

Extension remains a separate outcome-class problem.

## Symbol-level notes

For 0618_selected_minus8_v1, real anchors outperformed random on:

| symbol | real avg to 1.000 | random avg to 1.000 |
|---|---:|---:|
| BTC | 4.9075 | 4.5423 |
| ETH | 13.1889 | 6.2144 |
| FIL | 15.6420 | 11.4728 |
| TAO | 26.6212 | 9.8667 |

Real anchors underperformed random on:

| symbol | real avg to 1.000 | random avg to 1.000 |
|---|---:|---:|
| HBAR | 4.1750 | 6.2481 |
| PEPE | 3.1242 | 5.8161 |
| XLM | 2.2444 | 4.8059 |

RENDER had random -8 selections but no real -8 selection in this anchor set.

Interpretation:

The -8 edge is not universal.

Next validation must include symbol and regime buckets.

## Current research state

Primary candidate:

    0618_selected_minus8_v1

Broader candidate:

    0618_selected_early_band_v1

Demoted:

    0618_selected_minus7_v1

Post-hoc labels, not filters:

    0786_ignition_band_match_v1
    extension_best_full_plus7_v1

## Next validation

Recommended next step:

    symbol/regime bucket comparison

Questions to answer:

    Does 0618 selected -8 work only in specific symbols?
    Does it depend on market regime?
    Does it work when BTC/ETH context is neutral or only during rotation expansion?
    Can A+ forming early labels improve selection quality?
    Can 1.272 extension outcomes be predicted by later 0.786 ignition labels?

## Boundary

These findings are not strategy rules.

Forbidden downstream use:

    selection_engine modifier
    decision_gate rule
    execution_planner instruction
    executor/order logic
    live or paper execution trigger

Correct path:

    random-anchor baseline
    -> symbol/regime validation
    -> broader history
    -> optional market-only feature proposal after validation
