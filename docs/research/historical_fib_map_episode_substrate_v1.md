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

T1 is **not terminal**. Reaching `target_t1` records `target1_ts_utc` /
`time_to_target1_seconds` and the forward scan keeps going, so one episode
can carry time-to-T1 **and** time-to-T2 (issue #555 explicitly requires
both, plus time-to-first-entry and time-to-invalidation). Only T2,
invalidation, same-candle ambiguity, or exhaustion of the forward/source
data terminate the scan and set `lifecycle_transition_reason`:

```text
TARGET2_REACHED                                 target_t2 crossed (target1_ts_utc is backfilled
                                                 to this candle if T1 was not already recorded
                                                 earlier)
INVALIDATION_BREACHED                           invalidation_level crossed on a candle with no
                                                 target hit
AMBIGUOUS_TARGET_INVALIDATION_SAME_CANDLE       see below
FORWARD_WINDOW_EXHAUSTED                        replay's bounded forward-candle budget ran out
                                                 with no terminal event (research-only concept;
                                                 production runs forward live and never needs
                                                 this)
SOURCE_DATA_EXHAUSTED                           ran out of historical candles before any
                                                 terminal event or before the forward budget
```

`target1_ts_utc` / `time_to_target1_seconds` can therefore be populated
under any of the above terminal reasons (or with no terminal target/
invalidation event at all, e.g. `SOURCE_DATA_EXHAUSTED`) -- it records
"when T1 was reached", independent of how/whether the episode later
terminated. `TARGET2_REACHED` / `INVALIDATION_BREACHED` carry the same
semantic meaning as the canonical `fib_navigation_map_v1` rebuild triggers
`TRIGGER_ALL_TARGETS_PASSED` / `TRIGGER_PRICE_BELOW_INVALIDATION`.

### Same-Candle Target/Invalidation Ambiguity

A single `obs_market_candle` row only records the high and low reached
during that bar, not the order in which they were touched. When a
candle's OHLC range crosses **both** a target level (T1 and/or T2) and the
invalidation level, there is no way to determine from the source data
whether the target or the invalidation happened first.

This substrate does not infer an order. When this collision occurs, the
label builder:

- sets `lifecycle_transition_reason = AMBIGUOUS_TARGET_INVALIDATION_SAME_CANDLE`
- records the candle's timestamp in `ambiguous_ts_utc`
- terminates the scan
- leaves `target2_ts_utc` and `invalidation_ts_utc` (and their `time_to_*`
  fields) as `None` for **this** candle
- preserves `target1_ts_utc` if it was already recorded from an earlier,
  unambiguous candle -- an earlier T1 hit is a separate, already-resolved
  observation and is not retroactively invalidated by a later ambiguous
  candle

Downstream research (#664/#723) must not count an episode with this reason
as a target2/invalidation success unless a later frozen protocol explicitly
decides how to resolve the ambiguity (e.g. an intra-candle tie-breaking
convention, or a switch to finer-grained source data).
`NON_ATTRIBUTABLE_LIFECYCLE_REASONS` in
`historical_fib_map_episode_substrate_v1.py` names the reason(s) that must
be excluded from success/failure attribution by default.

Target1-vs-target2 same-candle collisions (no invalidation involved) are
not ambiguous in this sense: extension levels are monotonically nested on
the same side of price (e.g. `ext_1618` is farther than `ext_1272` in the
same direction), so a single high/low crossing the farther level
necessarily also crossed the nearer one -- there is no competing
interpretation, so `TARGET2_REACHED` governs and `target1_ts_utc` is
backfilled to the same candle if not already set.

### Same-Candle Entry/Outcome Ambiguity

The same OHLC ordering limitation applies to `first_entry_ts_utc`. A
candle's range only records that the entry zone and a terminal-outcome
level (invalidation and/or a target) were *both* touched during that bar,
not which happened first. `build_episode_labels` therefore never attributes
`first_entry_ts_utc` / `time_to_first_entry_seconds` from a candle that also
hits invalidation and/or a target in the same bar:

- an earlier, unambiguous entry candle (if any) is left untouched --
  attribution is only withheld for the colliding candle itself
- if entry has not yet been recorded, a later, unambiguous candle (one that
  touches the entry zone without also hitting a terminal-outcome level) can
  still set `first_entry_ts_utc`
- this uses the same non-attributable-ambiguity posture as the
  target/invalidation collision above; it does not invent a trade-execution
  ordering convention

## Historical Data Source

`obs_market_candle`, SELECT only, explicit `open_ts_utc` bounds,
`ORDER BY open_ts_utc ASC`. No current-state snapshot table is used as
historical backfill authority. `validate_candle_sequence` rejects duplicate
or non-monotonic candle timestamps before any geometry is built.

`fetch_candles` normalizes every `open_ts_utc` / `close_ts_utc` value read
from the DB through `normalize_db_datetime_to_utc` before constructing
`HistoricalCandle`: a naive datetime (the MariaDB storage convention) is
treated as UTC, and an aware datetime is converted to UTC. `HistoricalCandle`
instances -- and therefore `episode_id`, which serializes
`map_creation_ts_utc` via `isoformat()` -- are always built from UTC-aware
timestamps, independent of connector/session/host timezone.

## Warmup: As-Of Feature Invariance to the Requested Window

`--from-ts`/`--to-ts` is a **research output** bound, not a feature-input
bound. Reconstructing the canonical PIT trend/EMA input and Fib-anchor
window for an as-of candle near `--from-ts` needs the same
`cfg.lookback_candles` (180 for both `1h` and `4h`) candles of history a run
with an earlier `--from-ts` would have used for that identical as-of
candle -- otherwise the same as-of candle could silently produce a
different trend/anchor outcome depending only on what the caller asked for.

The runner fixes this by fetching `cfg.lookback_candles - 1` extra candles
strictly before `--from-ts` as **pre-bound warmup**
(`fetch_warmup_candles`, a single bounded `LIMIT`-ed query, `ORDER BY
open_ts_utc DESC` then reversed to ascending). Warmup candles are feature
input only:

- `build_episodes` still scans them to reconstruct window/EMA/ATR state
  exactly as production would, via `emit_from_ts_utc` / `emit_to_ts_utc`
- an episode is only ever **emitted** (appended to the result) when
  `feature.map_creation_ts_utc` falls inside `[emit_from_ts_utc,
  emit_to_ts_utc)` -- the requested `[--from-ts, --to-ts)` window
- warmup never reads a candle at/after `--to-ts` (no future data) and never
  reads from a current-state snapshot table (historical `obs_market_candle`
  rows only)

`max_episodes` is checked before building each candidate episode (not
after appending), so `--max-episodes 0` deterministically yields zero
episodes rather than one.

## Bounded/Chunked Retrieval and Interruption

`fetch_candles` retrieves the requested `[from_ts, to_ts)` range in bounded
pages (`--chunk-size-candles`, default 5000) using deterministic
`ORDER BY open_ts_utc ASC` keyset pagination: the first page uses
`open_ts_utc >= from_ts`, every following page uses `open_ts_utc >
<last row's open_ts_utc>` (strict), so no page can duplicate or skip a row
at a page boundary and no single query is unbounded. `fetch_warmup_candles`
is inherently bounded by its `LIMIT` and needs no pagination.

The runner is single-process, single-worker (no worker pool) and prints an
observable phase per stage: `STARTED`, `FETCHING` (warmup, then per-chunk
progress on the requested window), `BUILDING`, `WRITING`, and exactly one
terminal `FINISHED` or `INTERRUPTED` line. SIGINT/SIGTERM are caught by
`_SignalState` (a single flag, no threads); the flag is polled between DB
chunks and at each phase boundary (after asset/warmup/requested fetch and
after build, before write). On interruption the runner prints `INTERRUPTED`
with the signal and a non-zero exit code (130 for SIGINT, 143 for SIGTERM)
and never calls `write_immutable_json` -- so a killed run never produces a
partial `episodes_v1.json`/`manifest_v1.json`; the immutable files are only
written after a fully successful build.

## CLI Validation

`validate_args` runs before any DB connection or query (before
`fetch_asset_id`) and rejects:

- `--episode-stride-candles <= 0`
- `--max-episodes` present and `< 0`
- `--chunk-size-candles <= 0`
- `--from-ts` not strictly earlier than `--to-ts`

An invalid CLI invocation prints a `FAILED reason=invalid_arguments` line
and returns exit code 2 without ever calling `get_connection`.

## Determinism and Immutability

- No wall-clock dependence: all "now" values used by the geometry engine
  come from the historical candle's own timestamp, never `datetime.now()`.
- `episode_id` is a SHA-256 of `(symbol, venue, interval_code,
  contract_version, map_creation_ts_utc, direction, anchor_low, anchor_high)`.
- The runner (`run_historical_fib_map_episode_substrate_v1.py`) writes
  `episodes_v1.json` and `manifest_v1.json` under
  `data/research/historical_fib_map_episode_substrate_v1/<venue>/<symbol>/<interval_code>/<run_id>/`
  via atomic hardlink-create. `<run_id>` is a SHA-256 of the canonical
  (sorted-key) JSON of every dataset-defining parameter --
  `builder_version`, `contract_version`, `venue`, `symbol`, `timeframe`,
  `from_ts`, `to_ts`, `episode_stride_candles`, `max_episodes` -- computed by
  `compute_run_id()`. Keying the immutable path on venue/symbol/timeframe
  alone was unsafe: different `from_ts`/`to_ts`/`episode_stride_candles`/
  `max_episodes` produce different datasets, so a bounded smoke run and a
  later canonical/full run (or any two differently-bounded runs) could
  otherwise collide at the same immutable path. Folding the full parameter
  set into the path makes that structurally impossible: two runs with any
  differing dataset-defining input always resolve to different `<run_id>`
  directories, while a repeat run with identical inputs always resolves to
  the same path (idempotent; a repeat run with different *content* at that
  same path is still refused by `write_immutable_json`, which raises
  `ValueError`). The manifest also carries `run_id`, `episode_stride_candles`,
  and `max_episodes` directly, so a run's full identity is recoverable from
  the manifest alone.
- `compute_run_id()` deliberately does **not** include warmup candle count
  or `--chunk-size-candles`: for fixed dataset-defining parameters, the
  emitted episode set is identical regardless of how the data was fetched.
  The manifest still records `warmup_candle_count`,
  `source_fetch_from_ts_utc` (the earliest candle timestamp actually
  fetched, including warmup), and `chunk_size_candles` -- as provenance,
  not identity.

## Scope Boundary

Implemented in this slice:

1. contract/schema (`EpisodeFeaturePayload`, `EpisodeOutcomeLabels`,
   `EpisodeRecord`)
2. deterministic builder (`build_episode_feature`, `build_episode_labels`,
   `build_episodes`)
3. synthetic/unit tests (75 tests, no DB)
4. one-symbol/one-window smoke capability
   (`run_historical_fib_map_episode_substrate_v1.py`)
5. immutable manifest/provenance (`manifest_v1.json` with source bounds,
   candle/episode counts, and a SHA-256 of the episode payload)

Not implemented in this slice (explicitly out of scope for #555):

- #664 Fib Reach Strength calibration
- #723 promotion-grade evidence qualification
- #657 promotion mechanics / `automatic_exit_profile_v1` writes
- broad full-universe historical dataset generation
