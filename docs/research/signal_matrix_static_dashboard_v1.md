# Signal Matrix Static Dashboard V1

## Purpose

`signal_matrix_static_dashboard_v1` is the first transparent Synth v2.14
dashboard layer for market-only signal inventory.

It is upstream of:

```text
manual_ladder_dashboard_v1
```

It exists to show:

- primitive signals per asset
- primitive signals per timeframe
- explicit conflicts across timeframes
- separate HTF and LTF truth surfaces
- separate regime / catalyst / validation-readiness context

It does not exist to:

- output final advice labels
- merge hidden veto logic
- create execution intent
- hide disagreement

Core sentence:

```text
Elke timeframe mag zijn eigen waarheid hebben; het dashboard toont conflicten, het lost ze niet verborgen op.
```

## Scope

This is:

- reporting-only
- research-only
- market-only
- account-agnostic
- static dashboard design

This is not:

- `selection_engine`
- `decision_gate`
- `execution_planner`
- `executor`
- broker integration
- order logic

## Hard Boundaries

```text
No BUY_READY / AVOID / WATCH_ONLY final advice labels
No hidden HTF/LTF veto logic
No hand-made signal combinations
No selection_engine changes
No decision_gate changes
No execution_planner changes
No executor changes
No broker calls
No broker writes
No orders
No account-aware logic
```

## Design Role In The Dashboard Stack

Correct stack:

```text
signal_matrix_static_dashboard_v1
-> manual_ladder_dashboard_v1
-> later research/validation consumers
```

Not:

```text
manual ladder dashboard invents hidden signal composition first
```

Interpretation:

- the signal matrix is the transparent inventory
- the manual ladder dashboard is the downstream human-reading surface
- the manual ladder dashboard may consume matrix rows later
- the matrix itself must not pre-collapse truth into a final conclusion

## Source Tables / Files To Inspect

V1 should inspect existing market-only and reporting-safe sources only.

Primary DB sources to inspect:

- `selection_state`
  - only as one visible signal source, not as the final dashboard truth
- `trade_setup_filter_observation`
  - only as visible setup-state context, not as final advice
- `paper_advice_observation`
  - legacy/debug only, not the primary matrix truth
- `execution_zone_context`
  - zone, reclaim, retest, target, invalidation, confidence
- `obs_market_candle`
  - current price, candle timestamps, primitive price-position facts
- `active_regime_observation`
  - canonical regime context only

Primary research/output files to inspect when present:

- `data/research/fibo_target_map_v1/fibo_target_map_rows_v1.csv`
  - fib target ladder, support/reentry ladder, anchor quality, target status
- reload scalp selected-event or other research files only as debug/readiness
  overlays
- external catalyst flags only if they already exist in a canonical research
  file or normalized table

Supporting docs / priors:

- `docs/todo/signal_matrix_dashboard.md`
- `docs/todo/manual_ladder_dashboard.md`
- `docs/legacy_synth_v1_regime_strategy_priors.md`

## Primitive Signal Inventory

The matrix should inventory primitive signals explicitly, not a composed
opinion.

### 1. Breath / Fibo Frame

Asset-level frame, shown above timeframe rows or as a separate top band:

- A+ posture if available:
  - `aplus_phase`
  - `aplus_coherence`
  - `aplus_field`
  - `aplus_role`
  - `aplus_bias`
- harmonic phase if available:
  - `harmonic_phase`
  - `phase_state`
  - `offset_band`
  - `drift_direction`
  - `quality`
  - `extension_risk`
- fib target map if available:
  - `leg_direction`
  - `anchor_interval`
  - `anchor_quality`
  - `current_target_band`
  - `target_status`
  - `next_extension_target_level`
  - `next_extension_target_price`
  - `next_fibo_support_level`
  - `next_fibo_support_price`
  - `reentry_zone_label`

These are frame/map inputs only.
They are not combined into final advice here.

### 2. Primitive Signals Per Timeframe

Per timeframe row, visible independently:

- price relation to entry/reaction zone
- price relation to target/extension zone
- price relation to invalidation
- reclaim state
- retest state
- compression/expansion state
- direction / bias
- target proximity
- support proximity
- invalidation proximity
- freshness of signal source
- source module/table

### 3. Local Pattern Candidates Per Timeframe

Each timeframe row may carry explicit pattern flags only:

- `bullflag_candidate`
- `impulse_candidate`
- `compression_candidate`
- `failed_breakout`

These must remain primitive candidate flags.
They must not be silently combined into one verdict.

### 4. HTF Context

HTF context must be shown separately:

- HTF direction
- HTF reclaim/retest state
- HTF target band
- HTF fib target state
- HTF freshness

HTF is context only in this dashboard.

### 5. Regime Context

Canonical regime shown separately:

- `regime_source`
- `regime_asof`
- `regime_bucket`
- `regime_global`
- `regime_asset_class_state`
- `regime_validation_status`
- `regime_lookup_status`

Regime may help the user read the matrix.
It must not silently veto timeframes inside the dashboard.

### 6. External Catalyst / Dirty Squeeze Flags

Optional separate context band:

- catalyst present / absent
- dirty squeeze flag
- catalyst freshness
- source

These are display-only overlays.
They are not promotion logic.

### 7. Outcome Validation Readiness Fields

Per signal family / timeframe or per asset:

- replay-safe source available: yes/no
- enough sample size: yes/no
- symbol concentration risk: yes/no
- regime segmentation available: yes/no
- forward outcome coverage available: yes/no
- latest validation status

This is readiness metadata only.
It is not a trade state.

### 8. Debug / Source Details

Always keep an explicit source layer:

- source table/file name
- asof timestamp
- source candle timestamp
- freshness age
- missing fields
- replay-safe / latest-only marker

## Per-Timeframe Display Shape

Each asset should have one matrix card or panel with multiple timeframe rows.

Recommended timeframes:

- `15m`
- `1h`
- `4h`
- `1d`

Optional later:

- `5m`
- `30m`
- `1w`

Each timeframe row should contain:

```text
timeframe
direction/bias
zone relation
target relation
invalidation relation
reclaim/retest state
compression/expansion state
pattern candidate flags
freshness
source
missing fields
```

The row should remain readable as:

```text
what this timeframe currently says
```

Not:

```text
what the whole asset should do
```

## Asset x Timeframe Matrix Layout

Recommended structure per asset:

### Top Frame Band

Show:

- symbol
- current price
- price freshness
- breath/A+ frame
- fib target frame
- regime frame
- catalyst/dirty squeeze frame

### Timeframe Matrix

One row per timeframe.

Suggested columns:

```text
TF
direction
zone_state
target_state
invalidation_state
reclaim_retest
compression_expansion
pattern_flags
freshness
source
readiness
debug/missing
```

### Conflict Strip

Below or next to the timeframe rows:

- explicit summary of disagreements
- no resolution
- no final verdict

Example:

```text
1d trend constructive
4h reclaim pending
1h failed breakout
15m compression candidate
```

This is acceptable because it lists truth surfaces separately.

This is not acceptable:

```text
therefore wait
therefore avoid
therefore buy
```

## Conflict Display Rules

Conflicts must be surfaced explicitly.

### Allowed conflict behavior

- show disagreeing states side by side
- label conflict categories
- show which timeframe says what
- show freshness per timeframe
- show missing context explicitly

### Forbidden conflict behavior

- no hidden HTF veto
- no hidden LTF override
- no silent confidence weighting
- no silent “best timeframe wins”
- no final state collapse into one advice label

### Example conflict labels

Display-only conflict descriptors may be used, for example:

- `HTF_LTF_DIRECTION_CONFLICT`
- `HTF_CONSTRUCTIVE_LTF_FAILED_BREAKOUT`
- `TARGET_UPSIDE_PRESENT_ENTRY_UNCONFIRMED`
- `RECLAIM_PENDING_INTRABAR_WEAK`

These are debug/readability labels only.
They are not final advice outputs.

## Freshness / Source Fields

Each asset and timeframe row should expose freshness directly.

Required freshness fields:

- source asof timestamp
- source candle timestamp
- age in minutes/hours where practical
- source module/table/file
- latest-only vs replay-safe marker

Examples:

- `selection_state.asof_ts_utc`
- `trade_setup_filter_observation.asof_ts_utc`
- `execution_zone_context.asof_ts_utc`
- `active_regime_observation.asof_ts_utc`
- latest candle `close_ts_utc`
- fib map `anchor_end_ts`

Freshness must be shown, not inferred silently.

## Missing-Data Handling

Missing data must be explicit and local to the missing field.

Rules:

- missing field != neutral field
- missing field != bearish field
- missing field != hidden fallback

Use explicit markers such as:

- `MISSING_ZONE_CONTEXT`
- `MISSING_REGIME_CONTEXT`
- `MISSING_FIB_MAP`
- `MISSING_PATTERN_INPUT`
- `MISSING_OUTCOME_READINESS`
- `SOURCE_UNAVAILABLE`

The matrix should stay renderable even when some sources are missing.

## Outcome Validation Readiness

Validation-before-promotion rule:

```text
Primitive signals may be displayed before they are validated.
Primitive signals may not be promoted into runtime strategy logic without validation.
```

Readiness fields should answer:

- is this signal family replay-safe?
- does this asset/timeframe have enough historical examples?
- is the signal family already outcome-validated?
- is regime segmentation available?
- is symbol concentration too high?
- is this source latest-only and therefore not safe for promotion?

Suggested readiness statuses:

- `REPLAY_SAFE_READY`
- `LATEST_ONLY_NOT_READY`
- `INSUFFICIENT_SAMPLE`
- `REGIME_SPLIT_MISSING`
- `VALIDATION_PENDING`
- `CONCENTRATION_RISK`

These are promotion-readiness fields only.
They are not market-direction signals.

## Relationship To Manual Ladder Dashboard V1

`manual_ladder_dashboard_v1` should be a downstream reader of the signal matrix.

Correct relationship:

```text
signal_matrix_static_dashboard_v1
  = transparent primitive truth inventory

manual_ladder_dashboard_v1
  = human reading/order-of-levels surface that consumes matrix/context
```

The ladder dashboard may later use:

- fib target frame
- regime frame
- per-timeframe pattern candidates
- explicit conflicts
- readiness/debug context

But the ladder dashboard should not be the first place where primitive truth is
merged.

## Legacy Synth v1 Priors

Legacy Synth v1 MTF/no-MTF/adaptive behavior may be shown only as research
priors.

Examples from the legacy prior doc:

- `LINK`, `XLM` leaned no-MTF
- `HBAR`, `HOT` leaned MTF/adaptive
- `HYPE` weak MTF/adaptive
- `SUI`, `XRP` caution/retest

Allowed usage:

- design discussion
- validation prioritization
- future regime/profile research

Forbidden usage:

- hardcoded runtime routing
- hidden dashboard veto
- direct selection behavior
- direct advice/action labels

## Source Inspection Plan For V1

Before code, inspect:

1. `selection_state`
   - available fields
   - timeframe coverage
   - freshness
2. `trade_setup_filter_observation`
   - visible setup primitives
3. `execution_zone_context`
   - reclaim/retest/target/invalidation fields
4. `active_regime_observation`
   - canonical regime fields only
5. `obs_market_candle`
   - current price / source timestamps / primitive proximity facts
6. `data/research/fibo_target_map_v1/*`
   - fib target/support ladder
7. any canonical catalyst/dirty squeeze source, if it already exists

If a source is missing:

- show it as missing
- do not invent substitutes

## Non-Goals For V1

- no order ladder
- no account-aware position logic
- no BUY/SELL instructions
- no final advice badge
- no hidden policy block logic
- no runtime strategy promotion
- no decision permission
- no execution path

## Summary

`signal_matrix_static_dashboard_v1` should be the transparent market-only truth
surface for Synth v2.14.

It must:

- show primitive signals
- show per-timeframe differences
- show context separately
- show conflicts explicitly
- show freshness and source
- show validation readiness

It must not:

- compose hidden conclusions
- solve timeframe conflicts silently
- act like a decision layer
- act like execution logic
