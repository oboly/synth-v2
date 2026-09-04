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

## Canonical Geometry Reuse

The substrate reuses the exact same production Fib geometry engine used by
the canonical 4h Fib map producer:

```text
src.market_data.fib_navigation_map_v1.build_fib_navigation_map
```

The same function is called for both the `1h` and `4h` timeframe
configurations (`TIMEFRAME_CONFIGS["1h"]` / `TIMEFRAME_CONFIGS["4h"]` in
`historical_fib_map_episode_substrate_v1.py`); only the interval, ATR
period, EMA spans, and stale-after multiple differ. There is no second Fib
implementation anywhere in this substrate — level lookups
(`_find_level`) only read labels already computed by the canonical engine's
`retracement_levels` / `extension_levels` tuples; they do not recompute Fib
math.

Direction (bullish/bearish) is classified with the same canonical trend
function used by the production 4h writer,
`src.structure.trend_state_v1.compute_trend_state`, fed by EMA20/EMA50
features computed from the PIT candle window using the shared
`src.features.indicators.ema` helper. This avoids depending on a persisted
production trend-feature table (which may not have full historical
coverage for arbitrary replay windows) while still reusing the identical
classification function and thresholds production uses.

Entry zone / target / invalidation field selection mirrors
`canonical_fib_zone_map_v1.build_row`'s convention exactly:

```text
entry_zone   = retracement levels r_0382 / r_0618 (mid = r_0500)
target_t1    = extension level ext_1272
target_t2    = extension level ext_1618
invalidation = retracement level r_1000
```

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
TARGET1_REACHED             target_t1 crossed before target_t2/invalidation
TARGET2_REACHED             target_t2 crossed before invalidation
INVALIDATION_BREACHED       invalidation_level crossed
FORWARD_WINDOW_EXHAUSTED    replay's bounded forward-candle budget ran out
                            with no terminal event (research-only concept;
                            production runs forward live and never needs
                            this)
SOURCE_DATA_EXHAUSTED       ran out of historical candles before any
                            terminal event or before the forward budget
```

`TARGET1_REACHED` / `TARGET2_REACHED` / `INVALIDATION_BREACHED` carry the
same semantic meaning as the canonical `fib_navigation_map_v1` rebuild
triggers `TRIGGER_ALL_TARGETS_PASSED` / `TRIGGER_PRICE_BELOW_INVALIDATION`.

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
