# Breath Curve Partial-to-Full Backtest v1

Status: research-only  
Scope: market-only / account-agnostic  
DB writes: none  
Orders: none  

## Purpose

Test whether the Breath Curve Template Matcher can recognize useful partial-cycle alignment before the later 1.000 pulse.

This is the first no-future-leakage style test for the question:

    Could the second half of the breathline have been anticipated from the 0.618 or 0.786 checkpoint?

## Method

For each symbol, anchor, and checkpoint:

1. Load full cycle candles for outcome measurement.
2. Use only candles available at the checkpoint as `as_of`.
3. Run the partial matcher with `required_ratio = checkpoint`.
4. Select the best partial offset, but only if the 1.000 target for that offset is still in the future.
5. Compare the selected offset against the retrospective full-cycle result.
6. Measure return from `as_of_close` to the selected offset's 1.000 and 1.272 markers.

## Checkpoints

Default checkpoints:

    0.618
    0.786

Interpretation:

    0.618 = second dip / higher-low checkpoint
    0.786 = ignition / pre-spike checkpoint

## Key outputs

CSV fields include:

    selected_partial_offset_days
    selected_partial_score
    future_target_is_future
    return_to_1000_pct
    return_to_1272_pct
    same_offset_full_score
    best_full_offset_days
    best_full_score
    offset_matches_best_full

## Important guard

The backtest uses a future-target guard:

    future_target_ratio = 1.000

An offset is not eligible if its 1.000 marker is already at or before the checkpoint `as_of`.

This prevents the partial matcher from winning by selecting a phase where the future pulse has already happened.

## Usage

    python -m src.research.backtest_breath_curve_partial_to_full_v1 \
      --symbols BTC,ETH,TAO,RENDER,FIL,HBAR,XLM,PEPE \
      --anchors 2026-03-01,2026-03-22,2026-04-12 \
      --checkpoints 0.618,0.786 \
      --cycle-days 21 \
      --tolerance-hours 36

## Interpretation

Potentially useful behavior:

    high partial score at 0.618 or 0.786
    1.000 target still future
    positive return to 1.000
    same offset has strong full-cycle score
    selected offset matches or is close to best full offset

Weak behavior:

    high partial score but negative return
    selected offset does not match full-cycle alignment
    selected offset only works when target is already in the past
    strong full-cycle score but poor partial recognition

## Boundary

Allowed:

    research backtest
    no-future-leakage checkpoint testing
    historical validation planning

Out of scope:

    buy/sell logic
    execution targets
    decision_gate behavior
    execution_planner behavior
    executor behavior
