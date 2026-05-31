# Fib Detector Visual Compare V1

## Purpose

`fib_detector_visual_compare_v1` renders a single static HTML page that stacks
multiple long-swing pivot detectors vertically for one symbol and timeframe.

The goal is visual review before choosing a detector for long fib leg-pair
multiplier research.

This is a detector-comparison tool, not a strategy tool.

## Why Long Swings Need Multi-Scale Detector Comparison

Long-swing multiplier research depends on which pivots are accepted as the
basis, correction, and continuation structure.

Different detectors will produce different pivot spacing:

- tighter local windows produce more pivots
- wider local windows produce fewer pivots
- percent zigzag detectors respond to reversal size rather than fixed candle
  count

Before promoting any detector into a wider research lane, the swing structure
should be reviewed visually on the same symbol and timeframe.

## Local Pivot Window Detector

`LOCAL_PIVOT_WINDOW_N` uses strict local highs and lows:

- pivot high if `high[i]` is strictly greater than `N` candles left and `N`
  candles right
- pivot low if `low[i]` is strictly lower than `N` candles left and `N`
  candles right

After raw detection, consecutive pivots with the same type are compressed:

- consecutive `HIGH` pivots keep the higher high
- consecutive `LOW` pivots keep the lower low

This produces a cleaner alternating pivot sequence for visual review.

## Percent ZigZag Detector

`ZIGZAG_PERCENT_X` uses close prices for both pivot tracking and reversal
confirmation.

This is intentional for v1:

- one price basis only
- deterministic behavior
- simple interpretation

Model:

- start from the first candle close as the initial candidate
- wait until price moves at least `X%` away from that candidate to establish the
  first direction
- once direction exists, keep tracking the latest extreme in that direction
- confirm a pivot when price reverses by at least `X%` from the latest extreme
- emit alternating highs and lows

This avoids extra future-looking beyond the reversal confirmation inherent to a
ZigZag model.

## P0/P1/P2/P3 Model

Each detector section highlights the latest complete four-pivot sequence:

- `P0`
- `P1`
- `P2`
- `P3`

Interpretation:

- `P0 -> P1` = basis move
- `P1 -> P2` = correction move
- `P2 -> P3` = continuation move

If a detector does not have at least four confirmed pivots, the section reports
that no complete sequence exists yet.

## Correction Multiplier

`correction_multiplier` is:

```text
abs(P2 - P1) / abs(P1 - P0)
```

It measures how large the correction was relative to the basis move.

## Continuation Multiplier

`continuation_multiplier` is:

```text
abs(P3 - P2) / abs(P1 - P0)
```

It measures how large the continuation was relative to the same basis move.

## Why Charts Are Stacked Vertically

The charts are stacked vertically instead of side by side so the reviewer can
compare detector behavior against the same full-width price history without
shrinking the horizontal time axis.

For long swings, horizontal compression hides important differences in pivot
placement. Vertical stacking preserves time readability.

## Visual Review Workflow

Recommended workflow:

1. open the generated HTML
2. compare pivot density across detector sections
3. inspect whether each detector is selecting meaningful long swings
4. review the latest `P0/P1/P2/P3` sequence for each detector
5. compare correction and continuation multipliers
6. decide which detector family is most useful for the next long-swing research
   step

This is a visual decision aid for detector choice only.

## Included Sections

V1 includes:

1. `LOCAL_PIVOT_WINDOW_10`
2. `LOCAL_PIVOT_WINDOW_20`
3. `ZIGZAG_PERCENT_10`
4. `ZIGZAG_PERCENT_20`
5. `ZIGZAG_PERCENT_30`

`ATR_ZIGZAG_20_3` is not included in v1.

Reason:

- the local-window and percent-zigzag families already provide a clean first
  comparison set
- ATR-based reversal logic would add extra implementation and calibration
  decisions
- it is better handled as a future extension after the first visual review pass

## Boundaries

This runner is visual review only.

It does not:

- write to the database
- create migrations
- use targets
- test fib levels
- create strategy advice
- use account-aware logic
- call broker APIs
- create orders

It reads only:

- `obs_market_candle`
- `asset`

It does not use:

- `paper_advice_observation`
- `canonical_fib_zone_map_v1`
- `selection_engine`
- `decision_gate`
- `execution_planner`
- `executor`

That keeps the lane aligned with the measurement-first fib research direction.

##############################################
RESULTS

Initial visual review notes:

- BTC 1d:
  - ZIGZAG_PERCENT_20 visually appears to capture the macro swing structure best in the first review.
  - This is useful for long-swing / macro-wave context.
  - This is only a visual observation, not validated.

- WLD 4h:
  - LOCAL_PIVOT_WINDOW_10 captures more full Elliott-like context, including preceding ABC-like structure.
  - LOCAL_PIVOT_WINDOW_20 filters harder and captures a coarser 1-2-3-4-like structure.
  - ZigZag percent detectors compress the structure too much for primary Elliott/Fibo context, but may still be useful for coarse comparison.

Rule:
Detector choice is not global.
Detector choice must be evaluated per symbol, interval, and research purpose.
