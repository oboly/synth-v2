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
- `FIB_3618_BULL_TARGET`
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
- `FIB_3618_BULL_TARGET`
  - high-extension bull / mania-style objective
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
- `local_reaction_price`
- `distance_to_local_reaction_pct`
- `next_extension_target_level`
- `next_extension_target_price`
- `distance_to_next_extension_pct`
- `main_extension_target_level`
- `main_extension_target_price`
- `stretch_target_level`
- `stretch_target_price`
- `bull_target_level`
- `bull_target_price`
- `moonbag_target_level`
- `moonbag_target_price`
- `next_fibo_support_level`
- `next_fibo_support_price`
- `distance_to_next_fibo_support_pct`
- `secondary_fibo_support_level`
- `secondary_fibo_support_price`
- `distance_to_secondary_fibo_support_pct`
- `reentry_zone_label`
- `reentry_distance_pct`
- `tp_reentry_risk_label`
- `target_status`

Initial `target_status` values:

- `BELOW_LOCAL_REACTION`
- `APPROACHING_1272`
- `BETWEEN_1272_1618`
- `BETWEEN_1618_2618`
- `BETWEEN_2618_3618`
- `BETWEEN_3618_4236`
- `TARGETS_EXCEEDED`
- `INSUFFICIENT_SWING`
- `NOT_IMPLEMENTED`

Notes:

- `LOCAL_REACTION_TP` is not the main bull TP
- local reaction target and next fib extension target must always be shown
  separately
- `FIB_1618_MAIN_TP` is the main bull TP
- `FIB_2618_STRETCH_TP` is the stretch target
- `FIB_3618_BULL_TARGET` is the bull / mania target
- `FIB_4236_MOONBAG_TP` is the moonbag / blow-off map
- `current_target_band` should describe where price currently sits in the ladder
- `next_extension_target_level` should expose the next higher unresolved fib
  extension target in the active leg direction
- support/reentry ladder fields should expose likely reload bands below current
  price
- support/reentry ladder helps decide TP sizing by comparing upside target vs
  expected re-entry zone
- V1 also emits `anchor_quality`,
  `bars_since_anchor_end`, and `anchor_reason` for research/debug review

## V1 Runner Scope

Initial implementation target:

- `src/research/run_fibo_target_map_v1.py`

V1 runner behavior:

- reads `obs_market_candle` and `asset`
- defaults to `1d`
- supports `1w` as the same anchor-style lane
- detects a recent confirmed `swing_low -> later swing_high` for `UP` legs
- calculates fib ladder prices from the anchored swing range only
- marks `DOWN` leg mapping as `NOT_IMPLEMENTED` when that is the latest
  confirmed structure
- emits separate local-reaction, extension, and support/reentry ladder fields
- when `--symbols` is provided, emits one row per requested symbol
- requested symbols are not silently dropped; missing inputs resolve to explicit
  skip rows

Hard implementation rule:

- no `current_price * fib` shortcut
- all extension prices must come from anchored swing range

## Swing Detection Notes

V1 uses a conservative pivot-window approach:

- detect pivot lows
- detect later pivot highs
- choose a recent meaningful `UP` swing pair
- score recency and move size conservatively

If no reliable `UP` swing exists:

- emit `INSUFFICIENT_SWING`

If requested market data is missing:

- emit `MISSING_MARKET_DATA`
- set `anchor_reason` to a concrete skip reason such as
  `no_market_candles_found_for_symbol`
  or `symbol_not_found_in_asset_universe`

If the latest confirmed structure is a `DOWN` leg:

- emit `NOT_IMPLEMENTED`

This is intentional.
V1 does not fake down-leg ladder logic before that path is designed properly.

## UP Leg Ladder Semantics

For `UP` legs:

- `local_reaction_price = swing_high_price`
- local reaction remains useful, but it is not the same as the next fib
  extension target
- extension ladder determines the larger bull map
- support ladder determines likely fibo re-entry / reload bands below current
  price

V1 status intent:

- `BELOW_LOCAL_REACTION`
  - current price is still below the local reaction high
  - next fib extension target is still `FIB_1272_TP`
- `APPROACHING_1272`
  - current price is above local reaction but below `1.272`
- `BETWEEN_1272_1618`
  - next extension target is `FIB_1618_MAIN_TP`
- `BETWEEN_1618_2618`
  - next extension target is `FIB_2618_STRETCH_TP`
- `BETWEEN_2618_3618`
  - next extension target is `FIB_3618_BULL_TARGET`
- `BETWEEN_3618_4236`
  - next extension target is `FIB_4236_MOONBAG_TP`
- `TARGETS_EXCEEDED`
  - current price is already above the documented ladder

Support/reentry mapping:

- below local reaction:
  - next support = `SWING_LOW_SUPPORT`
- above local reaction but below `1.272`:
  - next support = `LOCAL_REACTION_SUPPORT`
- above `1.272`:
  - next support steps down one fib ladder level at a time

Reload labels:

- `EASY_RELOAD`
- `NORMAL_RELOAD`
- `DEEP_RELOAD`
- `HARD_RELOAD`
- `UNKNOWN_RELOAD`

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

Global validation rule:

- every future strategy/backtest must compare strategy profit against
  `HOLD` / buy-and-hold baseline
- profit alone is not enough
- excess return versus `HOLD` must be reported
- drawdown improvement versus `HOLD` must be reported

## Chart Integration

Primary first integration target:

- `synth_chart_app_v1`

Expected chart behavior:

- overlay fib ladder levels on the chart
- label local TP separately from fib targets
- highlight `1.618` as the main larger target
- show `2.618`, `3.618`, and `4.236` as stretch / bull / moonbag ladder levels
- show support/reentry ladder separately from upside ladder
- support visual user review

Chart UI should make the distinction visible:

- local reaction target
- main fib continuation target
- stretch targets above the main objective

This lane is intended to support visual review before any promotion into a
stronger validation or runtime context.

## CLI

Planned / implemented V1 CLI:

```bash
python -m src.research.run_fibo_target_map_v1 --help
```

Primary args:

- `--venue bitvavo`
- `--interval 1d`
- `--quote EUR`
- `--symbols`
- `--lookback-candles 180`
- `--swing-window 5`
- `--max-symbols 0`
- `--write-files`
- `--output summary|json`
- `--output-dir data/research/fibo_target_map_v1`

Smoke example:

```bash
python -m src.research.run_fibo_target_map_v1 \
  --venue bitvavo \
  --interval 1d \
  --symbols NEAR,RENDER \
  --lookback-candles 180 \
  --swing-window 5 \
  --output summary
```

## Output Files

V1 runner output files:

- `fibo_target_map_rows_v1.csv`
- `fibo_target_map_rows_v1.jsonl`
- `summary_by_target_status_v1.csv`
- `summary_by_anchor_quality_v1.csv`
- `manifest_v1.json`

Default output root:

- `data/research/fibo_target_map_v1`

Scoped write behavior:

- full-universe runs replace the canonical output set
- scoped runs using `--symbols` or `--max-symbols` merge the updated symbol rows
  into the existing canonical CSV/JSONL so a narrow smoke does not erase
  unrelated symbols from `fibo_target_map_rows_v1.csv`

## Safety

Manifest markers:

- `db_writes=0`
- `broker_calls=0`
- `broker_writes=0`
- `order_submission=0`
- `account_tables_used=false`
- `executor=none`
- `research_only=true`

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
