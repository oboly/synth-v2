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

That issue also appears inside one pivot stream.

Visual review showed that fibo-like ratios can appear even when `P0` starts in
the wrong context.

If `P0` starts too early or too late:

- the measured ratios can still look superficially fibo-like
- the shape can still resemble a wave candidate
- but the sequence can describe the wrong structure

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

## Wave Start Candidate Scan

V1 now supports a research-only candidate scan:

- `candidate_scan=none`
- `candidate_scan=all-starts`

### `candidate_scan=all-starts`

This mode keeps the selected chart sequence unchanged, but evaluates every
possible start index on the final pivot stream after:

1. detector selection
2. structural filtering
3. major filtering
4. anchor refinement for each scanned candidate

Rules:

- scan every possible `start_index`
- use up to `candidate_scan_length` pivots from each start
- allow incomplete or active candidates when at least 4 pivots exist
- compute only available ratios
- do not auto-select the highest-ranked candidate for the chart

The HTML adds a `Wave start candidate scan` table ranked by
`combined_candidate_score`.

This is visual and research-only.
It does not claim Elliott truth and does not create a trading signal.

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

## Candidate Scores

The candidate scan adds two simple research-only scores plus a combined rank.

### `fibo_magnet_score`

Reference set:

- `0.236`
- `0.382`
- `0.500`
- `0.618`
- `0.786`
- `1.000`
- `1.272`
- `1.414`
- `1.618`
- `2.000`
- `2.618`
- `3.618`
- `4.236`

For each available ratio:

- find the nearest fibo reference
- measure the absolute delta to that reference

Then:

- `fibo_magnet_score = average delta across available ratios`
- lower is better

The scan also reports:

- `fibo_magnet_hit_count`
- `fibo_magnet_ratio_count`

### `elliott_shape_score`

This is a research-only heuristic score.

Start at `0` and subtract penalties:

- missing `W2/W1`: `-1`
- missing `W3/W1`: `-1`
- `W2/W1 < 0.236` or `W2/W1 > 0.90`: `-1`
- `W3/W1 < 1.0`: `-1`
- `W4/W3 > 0.786` when available: `-1`
- full `W1-W5` exists and `W3` is shortest of `W1/W3/W5`: `-2`
- fewer than 4 pivots: `-2`

Higher is better because fewer penalties were triggered.

### `combined_candidate_score`

`combined_candidate_score = elliott_shape_score - fibo_magnet_score`

Higher is better.

This score is only a research ranking aid.
It must not be treated as automatic best-candidate truth or trading logic.

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

## Raw Pivots Versus Refined Anchors

Raw pivots remain the detector output.

Refined anchors are a later visual-review layer applied only after:

1. raw pivots are detected
2. major pivots are optionally filtered
3. the selected review sequence is chosen

This separation matters because a local pivot can be technically valid while
still not being the best candle extreme for use as a wave anchor.

## Pivot Diagnostics

V1 now exposes a pivot diagnostics table for visual inspection before any
structural filtering changes are made.

The diagnostics table includes:

- `pivot_index`
- `source_layer`
- `ts_utc`
- `type`
- `price`
- `previous_pivot_index`
- `previous_type`
- `previous_price`
- `move_from_previous_abs`
- `move_from_previous_pct`
- `direction_from_previous`
- `structural_note`

`source_layer` is one of:

- `RAW`
- `STRUCTURAL`
- `MAJOR`
- `SELECTED`

This is diagnostics only.
It does not change detector behavior, major filtering, or anchor refinement.

## Structural Pivot Filtering

V1 now supports an optional structural filter between raw pivot detection and
major filtering.

Modes:

- `structural_filter=none`
- `structural_filter=strict_progression`

### `structural_filter=none`

No structural filtering.

The major filter receives the raw pivot sequence.

### `structural_filter=strict_progression`

The structural filter keeps raw pivots visible for audit, but removes pivots
from the downstream structural/major/selected layers when they are
structurally invalid as progression anchors.

After the WLD `15m` visual review, this mode is intentionally conservative.

It removes pivots only when their note is:

- `SAME_TYPE_AS_PREVIOUS`
- `ZERO_OR_INVALID_MOVE`

It does not automatically remove:

- `LOW_ABOVE_PREVIOUS_HIGH`
- `HIGH_BELOW_PREVIOUS_LOW`

Those two notes remain warnings, not automatic invalidation.

This filter is applied:

1. after raw pivot detection
2. before major filtering
3. before sequence selection

That creates the layer flow:

- `RAW`
- `STRUCTURAL`
- `MAJOR`
- `SELECTED`

The raw layer remains unchanged and visible in the chart and diagnostics table.

WLD `15m` visual review showed that harsher removal skipped a useful small
Elliott-like internal structure inside the `A` area.

Because of that, warning-style progression anomalies remain visible in
`STRUCTURAL`, `MAJOR`, and `SELECTED` unless a later explicit harsher filter is
added.

### Structural Notes

The diagnostics table uses simple descriptive notes:

- `FIRST_PIVOT`
- `OK`
- `LOW_ABOVE_PREVIOUS_HIGH`
- `HIGH_BELOW_PREVIOUS_LOW`
- `SAME_TYPE_AS_PREVIOUS`
- `ZERO_OR_INVALID_MOVE`

These notes are intended to explain why a pivot may be structurally
questionable without introducing new strategy or filtering logic yet.

`LOW_ABOVE_PREVIOUS_HIGH` and `HIGH_BELOW_PREVIOUS_LOW` should be read as
warnings.
They can still represent bullish or bearish stair-step continuation or
gap-like structure, especially on `15m`.

### CSV Export

If `--write-pivot-diagnostics PATH` is provided, the same diagnostics table is
also written to CSV.

## Anchor Refinement

V1 supports:

- `anchor_refinement=none`
- `anchor_refinement=segment_extreme`

### `anchor_refinement=none`

Keep the selected sequence anchors unchanged.

### `anchor_refinement=segment_extreme`

For each selected anchor `B` after `P0`:

- let `A` be the previous selected anchor
- search candles between `A.ts` and `B.ts`, inclusive
- if `B` is `HIGH`, refine `B` to the candle with the highest high in that
  segment
- if `B` is `LOW`, refine `B` to the candle with the lowest low in that segment

The raw detector pivots stay unchanged.
The major pivot filtering logic stays unchanged.
Only the selected review sequence anchors are refined.

### P0 Limitation

`P0` is intentionally not refined in v1.

Reason:

- refining `P0` cleanly requires explicit previous-context handling
- that is outside the current narrow visual-review scope

## Why Refinement Exists

Visual review of WLD `15m` showed that:

- `local_pivot_window=10`
- `major_filter=relative_move`
- `min_leg_vs_previous_ratio=0.382`

follows the micro-curve well, but still benefits from anchor refinement to
capture better segment extremes.

That is exactly the role of `segment_extreme` in v1.

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
- can scan start-index candidates without mutating the selected chart sequence
- optionally refines selected anchors from candle segment extremes
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
