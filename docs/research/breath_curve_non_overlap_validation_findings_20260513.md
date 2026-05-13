# Breath Curve Non-Overlap / Older-History Validation Findings — 2026-05-13

Status: research-only  
Layer: market-only / account-agnostic  
Broker calls: none  
Broker writes: none  
Orders: none  
Runtime impact: none  

## Purpose

Validate whether the strongest Breath Curve strategy-scoring-board candidate survives non-overlapping / older-history cohorts.

Primary candidate under test:

    breath_curve.minus8_core_symbols.v1

Meaning:

    0.618 selected -8
    + symbol in [BTC, ETH, FIL, TAO]
    -> early pulse-to-1.000 candidate

## Source

Broader-history runner:

    python -m src.research.run_breath_curve_broader_history_v1

Non-overlap / older-history run:

    python -m src.research.run_breath_curve_broader_history_v1 \
      --start-anchor 2025-08-31 \
      --end-anchor 2026-04-12 \
      --cohort-size 3 \
      --cohort-stride 3 \
      --random-window-pre-pad-days 28 \
      --random-window-post-pad-days 0 \
      --random-count-per-symbol 50 \
      --output table

Strategy scoring board:

    python -m src.research.run_strategy_scoring_board_v1 \
      --non-overlapping \
      --output table

Run directory:

    data/research/breath_curve_broader_history_v1/breath_curve_broader_history_v1_20260513T180717Z/

Boundary:

    db_writes = 0
    broker_calls = 0
    broker_writes = 0
    order_submission = 0
    selection_engine = none
    decision_gate = none
    execution_planner = none
    executor = none

## Cohorts

| cohort | anchors | random window |
|---|---|---|
| cohort_01_20250831_20251012 | 2025-08-31, 2025-09-21, 2025-10-12 | 2025-08-03 .. 2025-10-12 |
| cohort_04_20251102_20251214 | 2025-11-02, 2025-11-23, 2025-12-14 | 2025-10-05 .. 2025-12-14 |
| cohort_07_20260104_20260215 | 2026-01-04, 2026-01-25, 2026-02-15 | 2025-12-07 .. 2026-02-15 |

These cohorts are non-overlapping.

## Aggregate result

| composite | real eligible | random eligible | real avg to 1.000 | random avg to 1.000 | edge to 1.000 | real worst | random worst |
|---|---:|---:|---:|---:|---:|---:|---:|
| early_band_core_and_bear_or_volume_v1 | 5 | 139 | 4.3726 | 5.2219 | -0.8493 | 0.7446 | -3.2810 |
| minus8_all_v1 | 7 | 150 | 3.6529 | 6.1476 | -2.4947 | 0.7446 | 0.2217 |
| minus8_btc_eth_bear_v1 | 4 | 115 | 5.0378 | 6.3577 | -1.3199 | 2.1298 | 0.2217 |
| minus8_core_and_bear_or_volume_v1 | 4 | 59 | 4.6915 | 5.5919 | -0.9004 | 0.7446 | 0.2217 |
| minus8_core_and_btc_eth_bear_v1 | 3 | 54 | 6.0071 | 5.6886 | +0.3185 | 2.3788 | 0.2217 |
| minus8_core_and_volume_expansion_v1 | 3 | 20 | 2.4544 | 7.3586 | -4.9042 | 0.7446 | 0.7834 |
| minus8_core_not_btc_eth_bull_v1 | 3 | 65 | 6.0071 | 5.5318 | +0.4753 | 2.3788 | 0.2217 |
| minus8_core_symbols_v1 | 4 | 74 | 4.6915 | 5.3719 | -0.6804 | 0.7446 | 0.2217 |
| minus8_volume_expansion_v1 | 6 | 36 | 2.3613 | 9.5991 | -7.2378 | 0.7446 | 0.7834 |

## Strategy scoring board result

| strategy | status | score | real eligible | random eligible | edge to 1.000 | blockers |
|---|---|---:|---:|---:|---:|---|
| breath_curve.minus8_core_btc_eth_bear.v1 | REJECTED | 24.57 | 3 | 54 | +0.3185 | REAL_ELIGIBLE_LT_20 |
| breath_curve.early_band_core_bear_or_volume.v1 | REJECTED | 4.98 | 5 | 139 | -0.8493 | REAL_ELIGIBLE_LT_20, EDGE_NOT_POSITIVE |
| breath_curve.minus8_all.v1 | REJECTED | 3.33 | 7 | 150 | -2.4947 | REAL_ELIGIBLE_LT_20, EDGE_NOT_POSITIVE |
| breath_curve.minus8_core_symbols.v1 | REJECTED | 1.14 | 4 | 74 | -0.6804 | REAL_ELIGIBLE_LT_20, EDGE_NOT_POSITIVE |
| breath_curve.minus8_volume_expansion.v1 | REJECTED | 0.04 | 6 | 36 | -7.2378 | REAL_ELIGIBLE_LT_20, RANDOM_ELIGIBLE_LT_50, EDGE_NOT_POSITIVE |
| breath_curve.minus8_core_volume_expansion.v1 | REJECTED | 0.00 | 3 | 20 | -4.9042 | REAL_ELIGIBLE_LT_20, RANDOM_ELIGIBLE_LT_50, EDGE_NOT_POSITIVE |

## Primary conclusion

The strongest prior candidate failed non-overlap / older-history validation.

Candidate:

    breath_curve.minus8_core_symbols.v1

Previous status:

    VALIDATION_CANDIDATE

New status:

    REJECTED for general robustness
    RESEARCH_ONLY / REGIME_SPECIFIC for further study

Reason:

    edge to 1.000 became negative
    real eligible sample stayed low
    older-history non-overlap cohorts did not confirm the Jan-Apr 2026 edge

## Cohort diagnosis for minus8_core_symbols_v1

| cohort | real eligible | random eligible | real avg to 1.000 | random avg to 1.000 | edge |
|---|---:|---:|---:|---:|---:|
| cohort_01_20250831_20251012 | 1 | 25 | 0.7446 | 5.0736 | -4.3290 |
| cohort_04_20251102_20251214 | 1 | 19 | 11.4028 | 5.4061 | +5.9967 |
| cohort_07_20260104_20260215 | 2 | 30 | 3.3093 | 5.5989 | -2.2896 |

Interpretation:

The candidate worked in one older non-overlap cohort but failed in two.

It is not generally robust.

## Updated interpretation

The Breath Curve 0.618 selected -8 pattern appears to be:

    regime-specific
    phase/local-window dependent
    not a universal early pulse strategy

The earlier positive Jan-Apr 2026 result remains useful as a regime-local research observation, but it is not enough for paper/live promotion.

## Architecture decision

No downstream promotion.

Forbidden:

    selection_engine modifier
    decision_gate rule
    execution_planner instruction
    executor/order logic
    paper execution
    live execution

Allowed:

    keep as research-only label
    test as regime-specific feature
    combine with A+ transition labels
    investigate why Jan-Apr 2026 behaved differently

## Next research questions

1. What regime feature separates the positive Jan-Apr 2026 window from the failed older windows?
2. Does A+ FORMING_EARLY rescue precision without leakage?
3. Does BTC/ETH macro context need more granular buckets than BEAR/BULL?
4. Is volume expansion only useful in specific market regimes?
5. Should Breath Curve be treated as a regime detector rather than an entry policy?

## Recommended next step

Do not tune thresholds to force promotion.

Recommended path:

    document failure
    demote candidate
    build regime-difference diagnostic
    compare winning Jan-Apr 2026 windows vs failed older windows
    optionally test A+ transition overlays as additional research labels

## Final status

Strategy scoring board:

    PASS

Breath Curve minus8_core_symbols.v1:

    fails non-overlap / older-history validation

Paper/live readiness:

    blocked
