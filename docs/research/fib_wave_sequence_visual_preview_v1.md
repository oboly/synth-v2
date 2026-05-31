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

The runner can highlight a selected sequence of pivots rather than always
forcing the latest complete nine-pivot block.

This matters because visual review showed that the latest complete `P0-P8`
window is not always the most useful one.

Examples from review:

- BTC `1w` `zigzag_percent=20` likely starts the relevant macro sequence at
  current pivot index `2`, while earlier pivots belong to prior downtrend or
  `ABC` context
- WLD `1w` `zigzag_percent=20` has a useful latest complete sequence, but also
  an earlier complete candidate worth reviewing
- BTC `1w` `zigzag_percent=15` appears more sensitive and inserts extra pivots

Because of that, sequence selection is now a visual-review tool.

Future batch research should evaluate rolling candidates automatically rather
than assuming the latest block is always the correct one.

When `sequence_length=9`, the labels are:

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

If fewer pivots are selected than the requested `sequence_length`, the sequence
is treated as active or incomplete.

## Sequence Selection Modes

The runner supports:

### `sequence-mode latest`

Default behavior.

- use the latest available sequence of `sequence_length` pivots
- if fewer pivots exist, use all available pivots
- mark `has_complete_sequence=0` when the requested length is not available

### `sequence-mode start-index`

Visual review helper.

- use `pivots[sequence_start_index : sequence_start_index + sequence_length]`
- if fewer pivots exist after the chosen start index, use the available trailing
  pivots
- mark `has_complete_sequence=0` when the requested length is not available

This is useful when the reviewer wants to skip earlier context and inspect a
later macro sequence candidate directly.

### `sequence-mode all`

Rolling candidate review mode.

- render the latest selected sequence on the chart
- also render a table of all rolling sequence candidates for the chosen
  `sequence_length`
- each row includes start/end index, timestamps, completeness, basis direction,
  and available ratios

This is still visual review only.

## Sequence Length

`sequence_length` is configurable.

Default:

- `sequence_length=9`

Shorter lengths are allowed when the reviewer wants to inspect partial or
active structures instead of forcing a full `P0-P8` candidate.

## Candidate 1-2-3-4-5-A-B-C Interpretation

For visual review, the segment labels are shown only when the required points
exist:

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

Only available ratios are computed:

- `wave2_vs_wave1` if `P0-P2` exists
- `wave3_vs_wave1` if `P0-P3` exists
- `wave4_vs_wave3` if `P0-P4` exists
- `wave5_vs_wave1` if `P0-P5` exists
- `wave5_vs_wave3` if `P0-P5` exists
- `waveB_vs_waveA` if `P5-P7` exists
- `waveC_vs_waveA` if `P5-P8` exists

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

## Weekly Aggregation Support

When `--interval` is `1w`, the runner does not require native weekly candles in
`obs_market_candle`.

Instead it:

1. reads `1d` candles from `obs_market_candle`
2. aggregates them into deterministic UTC weekly candles in memory
3. runs the selected detector on that aggregated weekly series
4. renders the chart normally

No aggregated candles are written to the database.

This keeps the lane read-only while still supporting macro visual review.

### Deterministic UTC Weekly Aggregation

Weekly grouping uses UTC calendar weeks.

For each weekly group:

- `open = first daily open in the week`
- `high = max daily high in the week`
- `low = min daily low in the week`
- `close = last daily close in the week`
- `volume = sum daily volume in the week`
- `close_ts_utc = last daily close_ts_utc in the week`

Ordering stays by `close_ts_utc`.

If a weekly group has fewer than 3 daily candles, it is skipped by default to
avoid tiny partial-week artifacts.

### Why Weekly Exists Here

Weekly candles are intended for macro Elliott/Fibo visual review.

Daily and `4h` remain useful for:

- substructure inspection
- internal wave cleanup
- nearer-term timing context

## Major Pivot Filtering

V1 now supports an optional major-pivot filtering step after raw detector pivots
are built.

Flow:

1. detect raw pivots
2. preserve the raw pivot sequence
3. optionally derive a major pivot sequence from the raw pivots
4. use the major pivot sequence for `P0-P8` labels when a major filter is
   enabled

The filter is deterministic and uses only the already-available pivot sequence.

Supported modes:

- `none`
- `relative_move`
- `duration`
- `relative_move_and_duration`

### `none`

No extra filtering.

The major pivot sequence is the raw pivot sequence.

### `relative_move`

The filter walks the raw pivots from left to right.

For each candidate leg from the latest accepted major pivot:

- compute the candidate leg absolute move
- compare it against the previous accepted major leg absolute move
- accept the candidate if there is no previous major leg yet, or if:

```text
candidate_leg_abs >= previous_major_leg_abs * min_leg_vs_previous_ratio
```

If a candidate is rejected as too small, scanning continues.

If same-type major pivots appear after skipped pivots:

- `HIGH` keeps the higher high
- `LOW` keeps the lower low

### `duration`

Accept a candidate leg only if:

```text
duration_from_previous_accepted_major_pivot >= min_leg_duration_candles
```

### `relative_move_and_duration`

Apply both rules at the same time.

The candidate leg must pass the relative-move rule and the duration rule.

## Raw Versus Major Pivots In The Chart

The chart now renders both pivot layers:

- raw pivots as small markers
- major pivots as larger markers

This makes it possible to inspect what the filter removed without hiding the
underlying detector output.

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

The same rule applies after major-pivot filtering.

The filter is a research convenience for visual structure cleanup.
It is not a claim that the resulting count is the correct Elliott count.

## Why This Remains Measurement-First

The preview remains measurement-first because it only does the following:

- reads public candles
- selects pivots with one chosen detector
- selects a review sequence from the already-built pivot stream
- measures move sizes and ratios from those pivots
- renders a static visual review page

It does not:

- choose targets
- test fib hits
- create trade logic
- create execution logic
- use symbol-specific exceptions
- use manual skip lists

The major-pivot filter is still measurement-first because it is derived only
from the pivot geometry already observed in the selected detector output.

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
