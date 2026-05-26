# Fibo Target Map V1

## Purpose

`fibo_target_map_v1` defines a canonical research lane for building anchored
fib extension target ladders.

The purpose is to:

- build price target ladders from detected or selected swing anchors
- distinguish local take-profit reaction zones from larger fib extension targets
- support chart review first
- support later validation and replay work
- avoid premature execution interpretation

This lane is not execution.

It does not:

- submit orders
- create paper fills
- create live fills
- allocate capital
- create `decision_gate` permission
- create `execution_planner` intent
- enable `executor`

## Core Idea

Primary hierarchy:

- fib determines the target price ladder
- breath may later help decide whether higher targets are favored
- Elliott may later classify wave degree
- indicators remain secondary sensors, not the core price map

Interpretation:

- price levels come first
- timing can remain unknown
- market phase can later help rank which higher ladder targets are realistic
- the ladder must remain valid even before phase classification is mature

This means the first version is a price-map framework, not a timing model.

## Why This Lane Exists

Local TP zones are often useful for near-term reactions but can be too early for
larger trend curves.

Observed behavior in strong movers:

- price can move above the local reaction/TP zone
- local TP can catch sub-peaks rather than the larger curve
- extension targets can describe the broader path more faithfully

Therefore the system needs to separate:

- local reaction TP
- larger fib extension targets

The local target is still useful.
It just must not be confused with the full ladder.

## Target Hierarchy

Initial target ladder labels:

- `LOCAL_REACTION_TP`
- `FIB_1272_TP`
- `FIB_1618_MAIN_TP`
- `FIB_2618_STRETCH_TP`
- `FIB_3618_MANIA_TP`
- `FIB_4236_MOONBAG_TP`

Interpretation:

- `LOCAL_REACTION_TP`
  - nearest reaction / local resistance style objective
  - useful for trim/reaction review
  - not the same as the larger fib extension map
- `FIB_1272_TP`
  - first extension ladder target
  - useful as first extension confirmation
- `FIB_1618_MAIN_TP`
  - main extension target for broader continuation
  - default “larger curve” target in many cases
- `FIB_2618_STRETCH_TP`
  - strong continuation / stretch objective
- `FIB_3618_MANIA_TP`
  - high-extension / mania-style objective
- `FIB_4236_MOONBAG_TP`
  - extreme extension / moonbag ladder target

These are research target labels only.
They are not order instructions.

## Swing Anchoring

The ladder must always be anchored from an explicit swing range.

Required anchor concepts:

- `swing_low`
- `swing_high`
- `leg_direction`
- `anchor_interval`

Initial anchor priority:

- `1d`
- `1w`

Later expansion:

- smaller internal legs can use `4h`
- smaller internal legs can use `1h`

Hard rule:

- never calculate an extension as `current_price * fib`
- always calculate extension from the anchored swing range

Canonical principle:

- anchor first
- derive swing range second
- derive fib ladder from range third

This preserves structural meaning.

## Structural View

The larger curve can exist early in the day/week structure even if the exact
timing is not yet visible.

Desired read:

- long-term identity visible from early curve structure
- larger weekly/day ladder can coexist with smaller internal leg ladders
- each smaller leg can also have its own fib/extension structure

This implies a nested-map model:

- higher-interval anchor defines major ladder identity
- lower-interval anchors define internal leg ladders
- later wave-degree or breath context may help decide which ladder currently
  dominates

V1 does not need full multi-degree arbitration yet.
It only defines the target-map framework.

## Output Fields

Canonical output fields for a future runner/table:

- `symbol`
- `venue`
- `interval`
- `anchor_start_ts`
- `anchor_end_ts`
- `swing_low_price`
- `swing_high_price`
- `range_pct`
- `fib_1272_price`
- `fib_1618_price`
- `fib_2618_price`
- `fib_3618_price`
- `fib_4236_price`
- `current_price`
- `current_target_band`
- `next_target_level`
- `distance_to_next_target_pct`
- `target_status`

Initial `target_status` values:

- `LOCAL_ONLY`
- `APPROACHING_1272`
- `BETWEEN_1272_1618`
- `BETWEEN_1618_2618`
- `EXTENDED`
- `MOONBAG_ZONE`

Notes:

- `LOCAL_REACTION_TP` may exist alongside the fib ladder but is conceptually
  separate from the extension ladder fields
- `current_target_band` should describe where price currently sits in the ladder
- `next_target_level` should expose the next higher unresolved target in the
  active leg direction

## Validation Ideas

Validation should remain research-first and symbol-aware.

Initial ideas:

- hit rate by target level
- overshoot rate by target level
- rejection rate by target level
- time-to-target
- compare local TP vs fib extension TP
- symbol-level consistency
- interval-level consistency

Priority ordering:

- day/week anchors first
- lower intervals later
- timing metrics secondary

Interpretation notes:

- time-to-target matters, but price-map validity matters more first
- overshoot vs rejection helps distinguish “too early local TP” from valid
  continuation
- symbol-level consistency matters before treating a ladder target as generally
  useful

## Chart Integration

Primary first integration target:

- `synth_chart_app_v1`

Expected chart behavior:

- overlay fib ladder levels on the chart
- label local TP separately from fib targets
- highlight `1.618` as the main larger target
- show `2.618` and `4.236` as stretch / moonbag ladder levels
- support visual user review

Chart UI should make the distinction visible:

- local reaction target
- main fib continuation target
- stretch targets above the main objective

This lane is intended to support visual review before any promotion into a
stronger validation or runtime context.

## Relation To Later Lanes

Planned later context:

- breath as phase/timing context
- Elliott as wave-degree context
- lower-interval leg decomposition

But V1 deliberately keeps those separate.

V1 answer:

- where are the structurally anchored ladder prices?

Later lanes may answer:

- which ladder target is currently more likely?
- which phase is active?
- which wave degree dominates?

## Boundaries

This lane must remain:

- research-only
- market-only
- account-agnostic

Forbidden:

- orders
- paper fills
- live trading
- account-aware permission
- `decision_gate`
- `execution_planner`
- `executor`

No part of this document promotes fib ladder levels into direct trade
instructions.

## Canonical Summary

`fibo_target_map_v1` defines the first canonical Synth lane for anchored fib
target ladders:

- local TP is separate from extension TP
- `1d` / `1w` anchors come first
- extension targets must be derived from swing range, never from current price
- `1.618` is the main larger target
- `2.618` / `3.618` / `4.236` provide stretch and moonbag ladder context
- chart review is the first practical use
- validation comes before any stronger promotion
