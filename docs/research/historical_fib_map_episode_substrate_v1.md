# Historical Fib/Map Episode Substrate V1

## Purpose

`historical_fib_map_episode_substrate_v1` is the first bounded implementation
slice for issue #555. It builds a deterministic, immutable, market-only
historical PIT episode dataset for the canonical ShortTF Fib/map producer,
covering independent `1h` and `4h` timeframe configurations.

It owns the historical episode dataset only. It does not perform #664 Fib
Reach calibration, #723 promotion qualification, or #657 promotion
mechanics. Those issues consume this substrate later; they are not
implemented here.

## Read-Only / Research-Only Boundary

This substrate is:

- research-only
- read-only (SELECT only against `obs_market_candle` / `asset`)
- market-only
- account-agnostic

It must not:

- write to the DB
- call broker private APIs
- submit orders
- change `selection_engine`, `decision_gate`, `execution_planner`, or
  `executor`

Safety markers:

```text
research_only=1
market_only=1
account_awareness=0
decision_permission=0
execution_intent=0
broker_calls=0
broker_writes=0
orders=0
db_writes=0
production_profile_writes=0
runtime_activation=0
```

## Files

```text
src/research/historical_fib_map_episode_substrate_v1.py   pure contract + deterministic builder (no DB)
src/research/run_historical_fib_map_episode_substrate_v1.py  read-only DB runner, immutable JSON output
tests/test_historical_fib_map_episode_substrate_v1.py     synthetic unit tests (no DB)
```

## Canonical Projection Reuse

The substrate reuses the exact same production projection function used by
the canonical 4h Fib map producer, unchanged:

```text
src.market_data.canonical_fib_zone_map_v1.build_row
```

`build_row` owns map eligibility, direction/map projection, anchor
timestamps, entry zone, targets, invalidation, and map status/quality/
provenance. It in turn calls the canonical geometry engine
(`src.market_data.fib_navigation_map_v1.build_fib_navigation_map`) and the
canonical trend classifier (`src.structure.trend_state_v1.compute_trend_state`).
None of that projection glue is reimplemented in this substrate: anchor
timestamps, entry-zone/target/invalidation field selection, and the
direction decision all come straight through from `build_row`'s returned
row (see `build_episode_feature` in
`historical_fib_map_episode_substrate_v1.py`). The same function is called
for both the `1h` and `4h` timeframe configurations
(`TIMEFRAME_CONFIGS["1h"]` / `TIMEFRAME_CONFIGS["4h"]`); only the interval
code and stale-after multiple differ.

`build_row` requires a trend-feature input (`price_vs_ema20`,
`price_vs_ema50`, `ema_spread_pct`) aligned exactly to the as-of candle. In
production this is read from the persisted `feat_candle` table, which may
not have full historical coverage for arbitrary replay windows. This
substrate reconstructs the identical input directly from raw historical
candles using the canonical `src.features.indicators.ema` primitive and the
exact formula `src/features/etl_candle_feat.py` persists into
`feat_candle` (`_reconstruct_trend_row`). This is feature-input
reconstruction, not a second trend classifier — the actual classification
decision is made exactly once, inside `build_row`'s own call to
`compute_trend_state`.

ATR-unit distance normalization (`target_t1_distance_atr` /
`target_t2_distance_atr` / `invalidation_distance_atr`) is computed by this
substrate using the shared `src.features.indicators.atr` helper, since
`build_row`'s own `distance_entry_to_target_pct` /
`distance_entry_to_invalidation_pct` fields are always `None` in production
(not computed there).

## Critical PIT Separation

Every episode carries two structurally distinct payloads:

- `EpisodeFeaturePayload`: everything knowable at `map_creation_ts_utc`
  (anchor selection, geometry, targets, invalidation, ATR normalization).
  Built only from candles at or before as-of.
- `EpisodeOutcomeLabels`: lifecycle/outcome labels derived strictly from
  candles *after* as-of (time to entry, time to target 1/2, time to
  invalidation, map lifetime, terminal reason).

This split is enforced at runtime, not just by convention:

- `build_episode_feature` raises `PitViolationError` if any candle in its
  input window is timestamped after the window's own as-of candle.
- `build_episode_labels` raises `PitViolationError` if any forward candle is
  timestamped at or before `map_creation_ts_utc`.

Labels never feed back into anchor selection, map eligibility, geometry,
target generation, invalidation generation, or episode admission.

## Lifecycle Transition Reasons

```text
TARGET1_REACHED                                target_t1 crossed before target_t2/invalidation
TARGET2_REACHED                                 target_t2 crossed before invalidation
INVALIDATION_BREACHED                           invalidation_level crossed
AMBIGUOUS_TARGET_INVALIDATION_SAME_CANDLE       see below
FORWARD_WINDOW_EXHAUSTED                        replay's bounded forward-candle budget ran out
                                                 with no terminal event (research-only concept;
                                                 production runs forward live and never needs
                                                 this)
SOURCE_DATA_EXHAUSTED                           ran out of historical candles before any
                                                 terminal event or before the forward budget
```

`TARGET1_REACHED` / `TARGET2_REACHED` / `INVALIDATION_BREACHED` carry the
same semantic meaning as the canonical `fib_navigation_map_v1` rebuild
triggers `TRIGGER_ALL_TARGETS_PASSED` / `TRIGGER_PRICE_BELOW_INVALIDATION`.

### Same-Candle Target/Invalidation Ambiguity

A single `obs_market_candle` row only records the high and low reached
during that bar, not the order in which they were touched. When a
candle's OHLC range crosses **both** a target level and the invalidation
level, there is no way to determine from the source data whether the
target or the invalidation happened first.

This substrate does not infer an order. When this collision occurs, the
label builder:

- sets `lifecycle_transition_reason = AMBIGUOUS_TARGET_INVALIDATION_SAME_CANDLE`
- records the candle's timestamp in `ambiguous_ts_utc`
- leaves `target1_ts_utc`, `target2_ts_utc`, and `invalidation_ts_utc` (and
  their `time_to_*` fields) as `None` for that episode

Downstream research (#664/#723) must not count an episode with this reason
as a target success or an invalidation success unless a later frozen
protocol explicitly decides how to resolve the ambiguity (e.g. an
intra-candle tie-breaking convention, or a switch to finer-grained source
data). `NON_ATTRIBUTABLE_LIFECYCLE_REASONS` in
`historical_fib_map_episode_substrate_v1.py` names the reason(s) that must
be excluded from success/failure attribution by default.

Target1-vs-target2 same-candle collisions are not ambiguous in this sense:
extension levels are monotonically nested on the same side of price (e.g.
`ext_1618` is farther than `ext_1272` in the same direction), so a single
high/low crossing the farther level necessarily also crossed the nearer
one — there is no competing interpretation, so `TARGET2_REACHED` governs
and `target1_ts_utc` is backfilled to the same candle.

## Historical Data Source

`obs_market_candle`, SELECT only, explicit `open_ts_utc` bounds,
`ORDER BY open_ts_utc ASC`. No current-state snapshot table is used as
historical backfill authority. `validate_candle_sequence` rejects duplicate
or non-monotonic candle timestamps before any geometry is built.

## Determinism and Immutability

- No wall-clock dependence: all "now" values used by the geometry engine
  come from the historical candle's own timestamp, never `datetime.now()`.
- `episode_id` is a SHA-256 of `(symbol, venue, interval_code,
  contract_version, map_creation_ts_utc, direction, anchor_low, anchor_high)`.
- The runner (`run_historical_fib_map_episode_substrate_v1.py`) writes
  `episodes_v1.json` and `manifest_v1.json` under
  `data/research/historical_fib_map_episode_substrate_v1/<venue>/<symbol>/<interval_code>/`
  via atomic hardlink-create. A repeat run with identical content is
  idempotent; a repeat run with different content is refused
  (`write_immutable_json` raises `ValueError`).

## Scope Boundary

Implemented in this slice:

1. contract/schema (`EpisodeFeaturePayload`, `EpisodeOutcomeLabels`,
   `EpisodeRecord`)
2. deterministic builder (`build_episode_feature`, `build_episode_labels`,
   `build_episodes`)
3. synthetic/unit tests (21 tests, no DB)
4. one-symbol/one-window smoke capability
   (`run_historical_fib_map_episode_substrate_v1.py`)
5. immutable manifest/provenance (`manifest_v1.json` with source bounds,
   candle/episode counts, and a SHA-256 of the episode payload)

Not implemented in this slice (explicitly out of scope for #555):

- #664 Fib Reach Strength calibration
- #723 promotion-grade evidence qualification
- #657 promotion mechanics / `automatic_exit_profile_v1` writes
- broad full-universe historical dataset generation
