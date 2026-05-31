# Canonical Fib Zone Map V1

## Purpose

`canonical_fib_zone_map_v1` is the planned DB-backed canonical source for the
Breath/Fibo strategy dashboard layer.

It exists because the source audit showed:

- `canonical_ready_fields=0`
- current fib-map CSV coverage is too sparse
- Entry Zone and Invalidation Level are still legacy-only
- `paper_advice_observation` must not act as a strategy-map source

The table is intended to provide one canonical market-only map per:

- venue
- symbol
- interval
- asof timestamp
- map version

## Relationship To The Dashboard

This table is the intended primary map source for:

- `breath_fibo_strategy_static_dashboard_v1`

It should provide the dashboard with explicit, provenance-safe values for:

- Current Leg
- Entry Zone
- Target levels
- Invalidation Level
- Support / Reaction Zone
- Anchor / Swing context
- source freshness / provenance

The dashboard should read this table later, but this task does not wire that
integration yet.

## Why Paper Advice Is Excluded

`paper_advice_observation` is legacy blackbox advice context.

It may still exist elsewhere in the repo for legacy review/debug, but it is not
a valid primary source for:

- Entry Zone
- Target
- Invalidation Level
- Current Leg

This canonical table exists specifically to replace that dependency for
strategy-map display work.

## Why Regime Stays Separate

`active_regime_observation` remains a separate visible market-context table.

It is allowed for:

- visible regime context
- visible framing
- research display

It is not merged into this table because regime is context, not a fib/zone map.
It must not become:

- hidden veto logic
- final advice
- execution permission

## Table Grain

One row represents one market-only fib/zone map snapshot for:

```text
(venue, symbol, interval_code, asof_ts_utc, map_version)
```

This allows:

- latest-row dashboard reads
- historical point-in-time replay
- deterministic backtests later
- source-version separation

## Required Fields

### Identity / status

- `venue`
- `symbol`
- `interval_code`
- `asof_ts_utc`
- `map_version`
- `map_status`
- `map_quality`
- `source_family`
- `source_ref`
- `source_created_at_utc`

### Current Leg

- `current_leg`
- `leg_method`
- `leg_confidence`

Interpretation:

- `UP`, `DOWN`, `RANGE`, `UNKNOWN`
- descriptive market structure only
- not a permission or action label

### Anchor / Swing context

- `anchor_low_ts_utc`
- `anchor_low_price`
- `anchor_high_ts_utc`
- `anchor_high_price`
- `swing_range_abs`
- `swing_range_pct`
- `anchor_method`
- `anchor_quality`

Interpretation:

- identifies the anchor pair used to derive the map
- makes the map inspectable instead of blackbox

### Entry Zone

- `entry_zone_low`
- `entry_zone_high`
- `entry_zone_mid`
- `entry_zone_method`
- `entry_zone_source_field`

Interpretation:

Entry Zone is the price zone where a long / re-entry / add-back hypothesis is
investigated.

It may represent:

- support reaction
- fib pullback
- retest
- reload-after-TP
- reclaim

It is not a buy command.

### Support / Reaction Zone

- `support_reaction_zone_low`
- `support_reaction_zone_high`
- `support_reaction_method`

Interpretation:

This is the nearest mapped support/reaction band visible to the strategy map.
It may overlap with Entry Zone, but does not have to.

### Targets

- `target_t1`
- `target_t2`
- `target_extension`
- `target_method`
- `target_source_field`

Interpretation:

Targets are market-only map levels such as:

- local reaction target
- next extension target
- larger continuation target

They are not TP orders.

### Invalidation Level

- `invalidation_level`
- `invalidation_method`
- `invalidation_source_field`

Interpretation:

Invalidation Level is the price level below or above which the current
market-only map is considered invalid.

It must always carry explicit provenance so the dashboard can explain where it
came from.

### Optional derived distances

- `distance_entry_to_target_pct`
- `distance_entry_to_invalidation_pct`
- `reward_risk_hint`

These are convenience fields only.
They are not strategy permission, allocation, or execution logic.

### Freshness / provenance

- `input_latest_candle_ts_utc`
- `source_freshness_state`
- `provenance_payload`
- `created_at_utc`
- `updated_at_utc`

These fields make the map auditable and freshness-aware.

## Provenance Requirements

Every row should answer:

- what market inputs were used
- what family produced the map
- what method produced leg/zone/target/invalidation
- when the input market candle context was last fresh
- when the row itself was created

Without this provenance, the strategy dashboard would become another hidden
blackbox.

## Null / Missing-Data Policy

This table allows nullable fields because map quality and source completeness
vary.

Rules:

- missing fields must remain explicit
- nulls must not be silently backfilled from legacy advice context
- incomplete rows should use `map_status` such as:
  - `INCOMPLETE`
  - `STALE`
  - `RESEARCH_ONLY`
  - `INVALIDATED`
- dashboard/reporting layers should degrade honestly when required fields are
  missing

## Latest-Row Access

This migration includes:

- `canonical_fib_zone_map_latest_v1`

The view returns the latest row per:

```text
(venue, symbol, interval_code, map_version)
```

This is intended as a convenience surface for dashboard/reporting reads.

## Research-Only Boundary

This schema is market-only and research/display oriented.

It must not include:

- account fields
- position fields
- sizing fields
- order fields
- broker fields
- decision permission fields
- final advice labels such as `BUY_READY`, `SELL_NOW`, `AVOID`, `WATCH_ONLY`

It must not change:

- `selection_engine`
- `decision_gate`
- `execution_planner`
- `executor`

## Future Writer Requirements

The future writer is out of scope for this task, but it must be:

- deterministic
- market-only
- explicit-source
- explicit-provenance
- no legacy paper blackbox fallback
- point-in-time safe for historical replay use

## Future Relationship To Backtests And Sweeps

Later research lanes can reuse this table for:

- point-in-time dashboard history
- fib/zone outcome validation
- parameter sweep alignment
- chart overlays
- source quality comparisons

But the table itself is not:

- a strategy
- a signal
- a permission layer
- an execution plan

## Expected Next Step

The likely next implementation step after this schema is:

1. build a deterministic market-only writer that promotes validated fib-map
   research into `canonical_fib_zone_map_v1`
2. validate coverage and freshness
3. only then attach the latest-view read into
   `breath_fibo_strategy_static_dashboard_v1`
