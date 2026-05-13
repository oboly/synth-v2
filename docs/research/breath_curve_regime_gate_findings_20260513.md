# Breath Curve Regime Gate Findings — 2026-05-13

Status: research-only  
Layer: market-only / account-agnostic  
Broker calls: none  
Broker writes: none  
Orders: none  
Runtime impact: none  

## Purpose

Document the first Breath Curve regime-gate diagnostic.

The previous non-overlap validation showed that the ungated `0.618 selected -8 + core symbols` candidate is not generally robust.

This diagnostic tests the more precise hypothesis:

    selected -8 may work only inside a specific market regime

## Runner

    python -m src.research.run_breath_curve_regime_gate_v1 \
      --output table

Boundary:

    db_writes = 0
    broker_calls = 0
    broker_writes = 0
    order_submission = 0
    selection_engine = none
    decision_gate = none
    execution_planner = none
    executor = none

## Clean run handling

The diagnostic now excludes non-zero-post-pad broader-history runs by default.

A clean run requires:

    random_window_end == latest anchor in cohort

The diagnostic also deduplicates duplicate manifest runs by default.

This prevents reruns of the same cohort set from being counted repeatedly.

Clean comparison used:

| run | class | target edge | real eligible | random eligible | real avg to 1.000 | random avg to 1.000 |
|---|---|---:|---:|---:|---:|---:|
| breath_curve_broader_history_v1_20260513T173451Z | WINNING_REGIME | +6.9376 | 13 | 59 | 14.1259 | 7.1883 |
| breath_curve_broader_history_v1_20260513T180717Z | FAILING_REGIME | -0.6804 | 4 | 74 | 4.6915 | 5.3719 |

## Composite separation

| composite | win edge | fail edge | separation | win real | fail real | read |
|---|---:|---:|---:|---:|---:|---|
| minus8_volume_expansion_v1 | +10.5866 | -7.2378 | +17.8244 | 8 | 6 | REGIME_GATE_CANDIDATE |
| minus8_core_and_volume_expansion_v1 | +11.7508 | -4.9042 | +16.6550 | 7 | 3 | REGIME_GATE_CANDIDATE |
| early_band_core_and_bear_or_volume_v1 | +7.5752 | -0.8493 | +8.4245 | 15 | 5 | REGIME_GATE_CANDIDATE |
| minus8_core_and_bear_or_volume_v1 | +6.9374 | -0.9004 | +7.8378 | 13 | 4 | REGIME_GATE_CANDIDATE |
| minus8_core_symbols_v1 | +6.9376 | -0.6804 | +7.6180 | 13 | 4 | REGIME_GATE_CANDIDATE |
| minus8_core_and_btc_eth_bear_v1 | +7.0251 | +0.3185 | +6.7066 | 13 | 3 | WEAK_REGIME_GATE_CANDIDATE |
| minus8_core_not_btc_eth_bull_v1 | +7.0329 | +0.4753 | +6.5576 | 13 | 3 | WEAK_REGIME_GATE_CANDIDATE |
| minus8_all_v1 | +2.4034 | -2.4947 | +4.8981 | 24 | 7 | WEAK_REGIME_GATE_CANDIDATE |
| minus8_btc_eth_bear_v1 | +2.3793 | -1.3199 | +3.6992 | 24 | 4 | WEAK_REGIME_GATE_CANDIDATE |

## Target cohort details

Target:

    minus8_core_symbols_v1

| regime | cohort | edge | real eligible | real avg to 1.000 | random eligible | random avg to 1.000 |
|---|---|---:|---:|---:|---:|---:|
| WINNING | cohort_01_20260118_20260301 | +4.7679 | 5 | 12.5835 | 20 | 7.8156 |
| WINNING | cohort_02_20260208_20260322 | +9.5501 | 4 | 15.0899 | 22 | 5.5398 |
| WINNING | cohort_03_20260301_20260412 | +6.5063 | 4 | 15.0899 | 17 | 8.5836 |
| FAILING | cohort_01_20250831_20251012 | -4.3290 | 1 | 0.7446 | 25 | 5.0736 |
| FAILING | cohort_04_20251102_20251214 | +5.9967 | 1 | 11.4028 | 19 | 5.4061 |
| FAILING | cohort_07_20260104_20260215 | -2.2896 | 2 | 3.3093 | 30 | 5.5989 |

## Winning regime signature

Winning cohorts showed:

| dimension | bucket | eligible | avg to 1.000 | worst to 1.000 | selection rate |
|---|---|---:|---:|---:|---:|
| BTC/ETH context | BTC_ETH_BEAR | 14 | 13.9314 | 2.5578 | 15.91% |
| RSI | RSI_HIGH | 3 | 26.6212 | 26.6212 | 21.43% |
| RSI | RSI_MID | 10 | 11.2618 | 4.9075 | 19.61% |
| Symbol | BTC | 3 | 4.9075 | 4.9075 | 25.00% |
| Symbol | ETH | 3 | 13.1889 | 13.1889 | 25.00% |
| Symbol | FIL | 3 | 15.6420 | 15.6420 | 25.00% |
| Symbol | TAO | 5 | 18.7648 | 2.5578 | 41.67% |
| Trend | TREND_BEAR | 11 | 10.4705 | 2.5578 | 13.92% |
| Trend | TREND_BULL | 3 | 26.6212 | 26.6212 | 17.65% |
| Volume | VOLUME_EXPANSION | 7 | 18.4782 | 2.5578 | 43.75% |
| Volume | VOLUME_NORMAL | 4 | 12.7424 | 11.4028 | 11.76% |
| Volume | VOLUME_THIN | 3 | 4.9075 | 4.9075 | 6.52% |

## Failing regime signature

Failing cohorts showed:

| dimension | bucket | eligible | avg to 1.000 | worst to 1.000 | selection rate |
|---|---|---:|---:|---:|---:|
| BTC/ETH context | BTC_ETH_BEAR | 2 | 3.3093 | 2.3788 | 8.33% |
| BTC/ETH context | BTC_ETH_BULL | 1 | 0.7446 | 0.7446 | 4.17% |
| RSI | RSI_HIGH | 1 | 0.7446 | 0.7446 | 7.14% |
| RSI | RSI_LOW | 2 | 3.3093 | 2.3788 | 15.38% |
| Symbol | BTC | 2 | 1.5617 | 0.7446 | 33.33% |
| Symbol | ETH | 1 | 4.2397 | 4.2397 | 16.67% |
| Symbol | FIL | 0 | none | none | 0.00% |
| Symbol | TAO | 0 | none | none | 0.00% |
| Trend | TREND_BEAR | 2 | 3.3093 | 2.3788 | 6.67% |
| Trend | TREND_BULL | 1 | 0.7446 | 0.7446 | 5.56% |
| Volume | VOLUME_EXPANSION | 3 | 2.4544 | 0.7446 | 20.00% |
| Volume | VOLUME_NORMAL | 0 | none | none | 0.00% |
| Volume | VOLUME_THIN | 0 | none | none | 0.00% |

## Main finding

The selected -8 signal is not dead.

The ungated selected -8 candidate is not robust, but the regime-gated version remains interesting.

The key difference is not merely BTC_ETH_BEAR or volume expansion alone.

The winning regime appears to require broader alt-core participation.

Most important observed differences:

    TAO participates in winning cohorts
    FIL participates in winning cohorts
    ETH participates strongly in winning cohorts
    BTC_ETH_BEAR is present in winning cohorts
    volume expansion is much stronger in winning cohorts
    RSI_MID / RSI_HIGH works better in winning cohorts

Failing cohorts were mostly BTC/ETH-only and lacked TAO/FIL participation.

## Working hypothesis

Breath Curve selected -8 is best interpreted as:

    a pulse trigger inside an alt-core rotation regime

not:

    a standalone entry policy

Current regime-gate hypothesis:

    selected -8
    + core symbols [BTC, ETH, FIL, TAO]
    + BTC_ETH_BEAR context
    + alt-core breadth / participation, especially TAO and FIL
    + volume expansion or RSI_MID/HIGH confirmation

## Important caution

This is still sample-thin.

The clean comparison currently has:

    1 winning broader-history run
    1 failing broader-history run

Therefore this is not paper-ready.

It is a regime-gate research hypothesis.

## Architecture decision

Allowed:

    keep selected -8 as regime-specific research label
    build regime-gated preview candidate
    test alt-core breadth filters
    test A+ transition labels as extra confirmation

Forbidden:

    selection_engine modifier
    decision_gate rule
    execution_planner instruction
    executor/order logic
    paper execution
    live execution

## Next step

Build:

    breath_curve_regime_gated_policy_preview_v1

Purpose:

    test explicit pre-measurable gates

Candidate gates:

    1. selected -8 + core symbols + BTC_ETH_BEAR
    2. selected -8 + core symbols + volume expansion
    3. selected -8 + core symbols + BTC_ETH_BEAR + volume expansion
    4. selected -8 + core symbols + RSI_MID/HIGH
    5. selected -8 + core symbols + alt-core breadth proxy
    6. selected -8 + core symbols + A+ FORMING_EARLY / transition support, if available

The next validation must avoid post-hoc labels and must remain research-only.
