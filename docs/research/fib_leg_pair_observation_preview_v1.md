# Fib Leg Pair Observation Preview V1

## Purpose

`fib_leg_pair_observation_preview_v1` is the first v2 measurement-first fib
research runner.

It reads only public market candles from `obs_market_candle` plus asset
metadata from `asset`, detects sequential leg pairs, and emits raw leg-pair
observations for later research.

It does not choose fib targets up front.
It does not calculate `target_t1`, `target_t2`, or `target_extension`.
It does not test predefined fib levels.

## Relation To `fib_leg_pair_multiplier_research_v1`

This runner is the first implementation step of
`docs/research/fib_leg_pair_multiplier_research_v1.md`.

That document defines the research direction:

- measure leg pairs first
- derive realized multipliers from raw leg points
- inspect distributions before making any fib claim

This runner applies that direction directly.

## Why This Is Measurement-First

The runner does not ask which fib target should be used.

It asks a simpler question:

```text
What leg pairs occurred in the observed public candle history?
```

From those leg pairs, preview outputs include derived multiplier fields for
inspection. Those derived fields are convenience output only. They are not the
source truth.

The source truth is the raw leg-pair geometry:

- pivot A to pivot B
- pivot B to pivot C

## What A Leg Is

A leg is a directional move defined from two sequential pivots:

- start timestamp
- start price
- finish timestamp
- finish price

V1 detects pivots from local highs and lows using a configurable
`swing_window`.

## What A Leg Pair Is

A leg pair is two consecutive legs from an ordered pivot sequence:

- leg1 = pivot A -> pivot B
- leg2 = pivot B -> pivot C

The preview runner emits every valid leg pair found inside the lookback window.

It does not:

- choose only the latest pair
- choose the best pair
- label fib targets
- create target names

## Detection Model

Preview detection flow:

1. load the latest N candles for each asset
2. detect local pivot highs and lows using `swing_window`
3. build an ordered pivot sequence
4. compress same-side pivot runs into a cleaner alternating sequence
5. convert consecutive pivot pairs into legs
6. convert consecutive legs into leg pairs
7. emit all valid leg pairs found in the lookback window

This stays inside the public candle measurement layer.

## Raw Fields Versus Derived Preview Fields

Raw output fields are the important part of the preview:

- venue
- symbol
- interval_code
- asof_ts_utc
- source_table
- detector_name
- detector_version
- lookback_candles
- swing_window
- input_first_ts_utc
- input_last_ts_utc
- leg1_start_ts_utc
- leg1_start_price
- leg1_finish_ts_utc
- leg1_finish_price
- leg2_start_ts_utc
- leg2_start_price
- leg2_finish_ts_utc
- leg2_finish_price

Optional provenance fields:

- pivot_count
- leg_pair_index
- generated_at_utc

Preview-derived fields are included only for convenience and are clearly
prefixed with `derived_`:

- derived_leg1_move_abs
- derived_leg2_move_abs
- derived_realized_multiplier
- derived_leg1_direction
- derived_leg2_direction
- derived_same_direction
- derived_opposite_direction
- derived_leg1_duration_candles
- derived_leg2_duration_candles

Important rule:

Future DB source tables should store raw leg points first. Derived values should
be calculated on the fly or cached later only if repeated analysis becomes
expensive.

## Why Fixed Fib Targets Are Excluded

Fixed fib targets are excluded because they would bias the measurement step.

If the runner starts by testing preferred levels, then the observation model is
already contaminated by the target hypothesis.

The correct order is:

1. collect leg pairs
2. inspect realized multiplier distributions
3. compare observed clusters later

Not the reverse.

## Why `canonical_fib_zone_map_v1` Is Not Used Here

`canonical_fib_zone_map_v1` is not part of this preview because that lane is
about fixed zone and target mapping.

This preview is narrower:

- no target maps
- no fib ladders
- no target hierarchy
- no zone labels

It measures pivot-to-pivot leg pairs only.

## Why `paper_advice_observation` Is Excluded

`paper_advice_observation` is excluded because it is not a market-only source
table for this task.

This preview must remain:

- public-market only
- account-agnostic
- strategy-agnostic
- execution-agnostic

Leg-pair measurement should start from observed candle structure, not from
later interpretation layers.

## Output Files

When `--write-files` is used, the runner writes:

- `fib_leg_pair_observation_preview_rows_v1.csv`
- `fib_leg_pair_observation_preview_rows_v1.jsonl`
- `summary.json`

## Safety Boundary

This preview is research-only.

It does not:

- write to the database
- create migrations
- modify dashboards
- change `canonical_fib_zone_map_v1`
- call broker APIs
- create orders
- use account-aware logic
- touch `selection_engine`
- touch `decision_gate`
- touch `execution_planner`
- touch `executor`

## Future Path

1. inspect the leg-pair preview output
2. plot `derived_realized_multiplier` distributions
3. group later by symbol, interval, regime, and context
4. only afterward compare observed clusters with fibo values, natural
   constants, prime values, and other numeric families

That keeps the lane aligned with the v2 rule:

```text
measure first
interpret later
compare hypotheses afterward
```
