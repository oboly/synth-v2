# Canonical Fib Zone Map V1

## Purpose

`canonical_fib_zone_map_v1` is the DB-backed canonical source for the
Breath/Fibo strategy dashboard layer. The production repository slice is
implemented by `src.market_data.canonical_fib_zone_map_v1` and
`src.market_data.run_canonical_fib_zone_map_v1`.

Production activation is not part of this repository change. The migration,
dedicated writer grant, merged checkout, controlled first publication, and
dashboard render must be applied and verified after merge.

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

The production dashboard reads the latest complete publication cohort directly.
It does not calculate or repair Fibonacci geometry.

## Direction Authority

Direction is owned by the adopted `structure_state_engine` v1.2 classifier,
whose pure implementation is in `src/structure/trend_state_v1.py`. It consumes
the latest persisted 4h `feat_candle` EMA measurements:

- `UPTREND_STRONG` / `UPTREND_WEAK` -> bullish `FibNavigationMap`, `UP`
- `DOWNTREND_STRONG` / `DOWNTREND_WEAK` -> bearish `FibNavigationMap`, `DOWN`
- `RANGE` -> unavailable directional map with descriptive leg `RANGE`
- missing or timestamp-misaligned feature input -> unavailable map with
  descriptive leg `UNKNOWN`

The feature timestamp must exactly match the latest input candle timestamp.
The writer never substitutes the research pivot preview as direction truth.
`provenance_payload.map_direction` must agree with `current_leg` for every
available map.

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
- `anchor_move_pct`
- `anchor_method`
- `anchor_quality`

Interpretation:

- identifies the anchor pair used to derive the map
- `anchor_move_pct` means the exact percentage move between
  `anchor_low_price` and `anchor_high_price`
- makes the map inspectable instead of blackbox

Current note:

- the initial migration draft may still show `swing_range_pct`
- prefer `anchor_move_pct` as the canonical field name before DB application
- treat `swing_range_pct` as legacy/deprecated wording before application

### Entry Zone

- `entry_zone_low`
- `entry_zone_high`
- `entry_zone_mid`
- `entry_zone_method`
- `entry_zone_source_field`

Interpretation:

Entry Zone is the directional retracement band where reaction or continuation
structure may be inspected.

It may represent:

- support reaction for an `UP` map
- resistance reaction for a `DOWN` map
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

This is the nearest mapped reaction band visible to the strategy map: support
for `UP`, resistance for `DOWN`.
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

## Production writer contract

The writer is:

- deterministic
- market-only
- explicit-source
- explicit-provenance
- no legacy paper blackbox fallback
- point-in-time safe for historical replay use

It uses only:

```text
venue_market + asset tracked-universe flags
-> persisted obs_market_candle 4h rows
-> FibNavigationMap
-> one transactional canonical_fib_zone_map publication cohort
```

The tracked universe is the existing enabled/tradeable Bitvavo EUR
`is_portfolio OR is_core_sensor` universe used to seed the global dashboard.
It is not derived from balances, positions, orders, profiles, selection,
Native SHORT scope permission, or sector rotation.

`canonical_fib_zone_map_publication_v1` is the cohort commit record.
`canonical_fib_zone_map_latest_v1` exposes only the newest committed complete
cohort. A failed build or transaction leaves the prior cohort intact.
Dashboard reads reclassify source timestamps against current time, so the
prior cohort becomes visibly stale rather than silently remaining current.

The active `native_short_4h_chain` on `devlap` is the sole recurring producer.
The existing Odroid MVP cockpit render chain is the read-only consumer. DB
authority is necessary because the canonical writer and dashboard consumer
are on different hosts and the existing native SHORT filesystem snapshot has
no cross-host transport contract.

## Activation and rollback

After merge, on the DB host:

```text
apply db/migrations/20260531_canonical_fib_zone_map_v1.sql if absent
apply db/migrations/20260730_canonical_fib_zone_map_production_v1.sql
apply db/dba/synth_chain_4h_writer_v1.sql with the existing secret transport
grant the existing Odroid dashboard read identity SELECT on canonical_fib_zone_map_latest_v1
```

Then deploy the same merged commit to devlap and Odroid. Keep both timers
stopped during preflight. Run the writer once on devlap through the authorized
4h service, validate one complete cohort, then run the existing MVP dashboard
render once on Odroid and verify `/var/www/html/synth/fibo-map.html`.

Acceptance:

```text
tracked row_count equals deterministic tracked-universe count
available_count > 0
all available rows source_freshness_state=FRESH
latest input age <= 8 hours
dashboard canonical_fib_map_rows equals publication row_count (subject to display limit)
paper_advice reads=0
broker_private_calls=0 broker_writes=0 order_submission=0
decision_gate=none execution_planner=none executor=none
```

Rollback disables only the new chain step by returning to the prior merged
commit on devlap and Odroid. Do not delete the last valid publication. It
remains auditable and becomes visibly stale. The migration tables may remain;
no destructive DB rollback is required.

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

## Next step

Merge, apply the repository-owned migration and least-privilege grants, deploy
the exact merge commit, run one controlled writer/render cycle, then observe
the existing 4h and cockpit timers. No new scheduler or design is required.
