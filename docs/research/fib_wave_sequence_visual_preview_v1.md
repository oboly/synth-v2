# Fib Wave Sequence Visual Preview V1

## Purpose

`fib_wave_sequence_visual_preview_v1` renders a static HTML preview for the
latest candidate `P0` through `P8` pivot sequence on one symbol and timeframe.

The purpose is visual inspection before building any database tables, caches, or
backtests for larger wave-style fib research.

This is a chart-review tool only.

## Relation To `fib_leg_pair_multiplier_research_v1`

`fib_leg_pair_multiplier_research_v1` sets the base rule for v2 fib research:

- measure first
- interpret later
- compare hypotheses afterward

This wave-sequence preview stays inside that rule.

It does not choose targets or test fib levels. It only visualizes a candidate
pivot sequence and measures move sizes and ratios from that sequence.

## Relation To `fib_detector_visual_compare_v1`

`fib_detector_visual_compare_v1` helps compare detector families before choosing
one for a symbol and timeframe.

This runner comes after that step.

It uses one chosen detector and asks a narrower question:

```text
What does the latest candidate P0-P8 sequence look like under this detector?
```

## P0-P8 Candidate Model

The runner highlights the latest complete sequence of nine pivots if at least
nine pivots exist:

- `P0`
- `P1`
- `P2`
- `P3`
- `P4`
- `P5`
- `P6`
- `P7`
- `P8`

These are candidate labels only.

The runner does not claim they are the correct count.

## Candidate 1-2-3-4-5-A-B-C Interpretation

For visual review, the segment labels are:

- `P0 -> P1 = W1`
- `P1 -> P2 = W2`
- `P2 -> P3 = W3`
- `P3 -> P4 = W4`
- `P4 -> P5 = W5`
- `P5 -> P6 = A`
- `P6 -> P7 = B`
- `P7 -> P8 = C`

This is only a candidate interpretive overlay for inspection.

It is not a claim that the market is actually in a confirmed Elliott count.

## Ratio Definitions

Move sizes:

- `wave1_move_abs = abs(P1 - P0)`
- `wave2_move_abs = abs(P2 - P1)`
- `wave3_move_abs = abs(P3 - P2)`
- `wave4_move_abs = abs(P4 - P3)`
- `wave5_move_abs = abs(P5 - P4)`
- `waveA_move_abs = abs(P6 - P5)`
- `waveB_move_abs = abs(P7 - P6)`
- `waveC_move_abs = abs(P8 - P7)`

Ratios:

- `wave2_vs_wave1 = wave2_move_abs / wave1_move_abs`
- `wave3_vs_wave1 = wave3_move_abs / wave1_move_abs`
- `wave4_vs_wave3 = wave4_move_abs / wave3_move_abs`
- `wave5_vs_wave1 = wave5_move_abs / wave1_move_abs`
- `wave5_vs_wave3 = wave5_move_abs / wave3_move_abs`
- `waveB_vs_waveA = waveB_move_abs / waveA_move_abs`
- `waveC_vs_waveA = waveC_move_abs / waveA_move_abs`

These are descriptive measurements only.

## Detector Support

V1 supports:

1. `local_pivot_window`
2. `zigzag_percent`

`local_pivot_window`:

- uses `--swing-window`
- pivot high if `high[i]` is strictly greater than the left/right window
- pivot low if `low[i]` is strictly lower than the left/right window
- consecutive same-type pivots are cleaned by keeping the stronger extreme

`zigzag_percent`:

- uses `--zigzag-percent`
- uses close prices consistently for candidate tracking and reversal confirmation
- emits alternating pivots after deterministic percent reversals

## Why Labels Are Candidate-Only

Wave labeling is highly detector-sensitive.

If the detector changes:

- pivot placement changes
- segment lengths change
- the candidate `P0-P8` sequence can change

Because of that, v1 keeps the language strict:

- candidate labels only
- visual review only
- no claim of correctness

## Why This Remains Measurement-First

The preview remains measurement-first because it only does the following:

- reads public candles
- selects pivots with one chosen detector
- measures move sizes and ratios from those pivots
- renders a static visual review page

It does not:

- choose targets
- test fib hits
- create trade logic
- create execution logic

## Boundaries

This runner has no strategy role.

It does not:

- write to the database
- create migrations
- create dashboard changes
- use target labels
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

That keeps the lane aligned with v2 measurement-first research.
