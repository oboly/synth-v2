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

`SOURCE_DATA_EXHAUSTED` means the market itself had no more candles to
scan -- not that the requested `--to-ts` output bound was reached. The
runner's forward-label tail (see "Forward-Label Tail" below) is what keeps
these two cases distinct: without it, an episode near `--to-ts` would be
mislabeled `SOURCE_DATA_EXHAUSTED` purely because retrieval stopped at the
requested bound.

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

## Forward-Label Tail: To-Ts Invariance for Outcome Labels

`[--from-ts, --to-ts)` is the **episode emission window**. Historically the
runner also stopped *source retrieval* at `--to-ts`, which meant an episode
emitted near the end of that window -- whose T2 or invalidation only
resolves on a candle *after* `--to-ts` -- had no forward candles left to
scan and was mislabeled `SOURCE_DATA_EXHAUSTED`. That reason is supposed to
mean "the market itself ran out of history", not "the caller's requested
output window ended"; before this fix the label silently depended on the
requested output bound rather than on the market.

The runner fixes this the same way it fixes the warmup case, but forward:
after fetching pre-bound warmup and the requested `[from_ts, to_ts)`
candles, it fetches up to `cfg.forward_max_candles` additional historical
`obs_market_candle` rows starting at `open_ts_utc >= to_ts`
(`fetch_forward_tail_candles`, a single bounded `LIMIT`-ed query, `ORDER BY
open_ts_utc ASC`). The build input becomes `warmup_candles +
requested_candles + forward_tail_candles`; `build_episodes`' existing
forward-only indexing (`forward_candles = candles[i + 1:]`) and
`emit_from_ts_utc`/`emit_to_ts_utc` gate need no change to honor this
correctly:

- forward-tail candles can only ever be reached from an as-of index
  *before* them, so they can only extend outcome-label scanning for
  episodes already emitted from the requested window -- never contribute to
  feature/geometry construction for an earlier as-of candle (feature
  construction only ever looks backward from its own as-of index)
- forward-tail candles can themselves become an as-of position during the
  build loop (the loop runs over the full candle array), but any episode
  candidate there has `map_creation_ts_utc >= to_ts`, which fails the
  `emit_to_ts_utc` gate exactly like a warmup-region as-of candle fails
  `emit_from_ts_utc` -- so a forward-tail candle can never itself produce a
  newly emitted episode
- the tail is derived only from the caller's `--to-ts` argument, never from
  `datetime.now()`/wall-clock time, and reads the same historical
  `obs_market_candle` table as every other fetch in this runner -- no
  current-state/snapshot source
- the fetch is bounded by construction (`LIMIT cfg.forward_max_candles`),
  matching the same bound `build_episode_labels` already applies when
  scanning forward from any individual episode's own as-of point, so the
  tail is always sufficient for the worst case (an episode emitted on the
  very last candle before `--to-ts`) without being unbounded

`cfg.forward_max_candles` is a per-timeframe constant already used to bound
the forward label scan (`build_episode_labels`'s `bounded =
forward_candles[:cfg.forward_max_candles]`); the tail fetch reuses the same
value as its `LIMIT`, so no new tunable parameter is introduced.
`fetch_forward_tail_candles` is evidence support for labels, not a new
CLI/config dataset-selection parameter -- but its actual fetched CONTENT is
not identity-irrelevant: how much forward-tail history is actually
available (and its exact OHLCV values) directly determines outcome labels
for episodes near `--to-ts`. That content is folded into `run_id` via
`source_input_sha256` -- see "Source Input Fingerprint and Run Identity"
below. Only the fetched *count* (`forward_tail_candle_count`) is recorded
in the manifest as separate provenance, alongside `warmup_candle_count` and
`chunk_size_candles`.

To summarize the three retrieval regions explicitly:

```text
[from_ts, to_ts)   = episode emission window (build_episodes' emit gate)
prehistory/warmup  = feature warmup only -- never emits, never labels
post-to_ts tail    = forward-label evidence only -- never emits, never
                     contributes to feature construction
```

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
progress on the requested window, then the forward-label tail --
`FETCHING phase=forward_tail ...`), `BUILDING` (see below), `WRITING`, and
exactly one terminal `FINISHED`, `INTERRUPTED`, or `FAILED` line.
SIGINT/SIGTERM are caught by `_SignalState` (a single flag, no threads); the
flag is polled between DB chunks, during `BUILDING` (see below), and at each
phase boundary (after asset/warmup/requested/forward-tail fetch and after
build, before write). On interruption the runner prints `INTERRUPTED` with
the signal and
a non-zero exit code (130 for SIGINT, 143 for SIGTERM) and never calls
`write_immutable_json` -- so a killed run never produces a partial
`episodes_v1.json`/`manifest_v1.json`; the immutable files are only written
after a fully successful build.

## BUILDING Heartbeat and Cancellation

`build_episodes` accepts three optional, purely deterministic hooks:
`on_progress(processed, total)`, `should_stop() -> bool`, and
`progress_interval_candles` (default `DEFAULT_PROGRESS_INTERVAL_CANDLES =
500`). Every `progress_interval_candles` *attempted as-of positions* (a
fixed count of loop iterations -- never wall-clock time), `on_progress` is
called if given, then `should_stop()` is polled if given. With both left
`None` -- the default for any direct caller of `build_episodes` -- nothing
is called and the builder's behavior/output is exactly what it was before
this hook existed: side-effect free and deterministic. This keeps the
research builder pure and reusable; only the runner supplies the hooks.

If `should_stop()` returns `True`, the loop stops at that same safe
boundary (no episode is left half-built) and raises `BuildCancelled`
(carrying whatever episodes were already built, for best-effort
diagnostics only -- the runner never uses or writes them). A caller can
therefore never mistake a cancelled build for a complete one: a normal
return is always the full result, a cancellation is always the exception.

The runner wires both hooks during `BUILDING`: `on_progress` prints
`BUILDING progress processed=<n> total=<n>`, and `should_stop` reads the
same `_SignalState.triggered` flag DB fetch already polls, using
`DEFAULT_BUILD_PROGRESS_INTERVAL_CANDLES = 500` as the cadence. This closes
the previous gap where a long `BUILDING` phase ran with no heartbeat and
observed SIGINT/SIGTERM only after every episode had already been built.
On cancellation the runner prints exactly one `INTERRUPTED` line (never
`FAILED`, never `FINISHED`) and returns before constructing `run_id` or the
output path, so `write_immutable_json` is never reached.

## CLI Validation

`validate_args` runs before any DB connection or query (before
`fetch_asset_id`) and rejects:

- `--episode-stride-candles <= 0`
- `--max-episodes` present and `< 0`
- `--chunk-size-candles <= 0`
- `--from-ts` not strictly earlier than `--to-ts`

An invalid CLI invocation prints a `FAILED reason=invalid_arguments` line
and returns exit code 2 without ever calling `get_connection`.

## FAILED Terminal Summary

Every operational stage after argument validation is wrapped so an
expected failure produces exactly one `FAILED reason=<code> detail=<...>`
line and a non-zero exit, instead of an unhandled traceback. `detail` is
`str(exception)` only -- no traceback, no connection/environment payload --
so diagnostics do not leak secrets. Reason codes, in the order a run
encounters them:

```text
invalid_arguments          -- validate_args (before any DB call); exit 2
asset_lookup_failed        -- fetch_asset_id
source_fetch_failed        -- fetch_warmup_candles / fetch_candles / fetch_forward_tail_candles
source_validation_failed   -- validate_candle_sequence (duplicate/non-monotonic candles)
build_failed                -- build_episodes (any failure other than BuildCancelled)
output_write_failed        -- write_immutable_json (episodes or manifest)
```

All non-`invalid_arguments` reasons return exit code 1 -- the reason code,
not the exit code, is the machine-readable contract. `BuildCancelled` is
caught *before* the generic `build_failed` handler and always resolves to
`INTERRUPTED`, never `FAILED` -- interruption and operational failure are
distinct outcomes. Each failure path `return`s immediately, so `FINISHED`
can never follow a `FAILED` line and no reason code can be printed twice in
one run. SIGINT/SIGTERM are handled by replacing the default signal
handler (`_SignalState.install`), not by catching `KeyboardInterrupt`, and
every `try/except` in `main()` catches `Exception` (never bare
`BaseException`), so `SystemExit`/`KeyboardInterrupt` semantics are not
accidentally swallowed by the FAILED-handling paths.

Because `run_id`/output-path construction and both `write_immutable_json`
calls happen only after a fully successful `BUILDING` phase, a failure in
any earlier stage (`asset_lookup_failed`, `source_fetch_failed`,
`source_validation_failed`, `build_failed`) creates zero files under
`--output-dir`. An `output_write_failed` conflict on the episodes file
(pre-existing content with a different hash) leaves that file untouched
and is detected before the manifest write is ever attempted, so no
manifest is written either.

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
  `from_ts`, `to_ts`, `episode_stride_candles`, `max_episodes` -- PLUS
  `source_input_sha256` (see "Source Input Fingerprint and Run Identity"
  below), computed by `compute_run_id()`. Keying the immutable path on CLI
  parameters alone was unsafe in two ways: different
  `from_ts`/`to_ts`/`episode_stride_candles`/`max_episodes` produce
  different datasets (a bounded smoke run and a later canonical/full run,
  or any two differently-bounded runs, could otherwise collide at the same
  immutable path); and, separately, two runs with byte-identical CLI
  arguments can still see different actual `obs_market_candle` content
  (late-arriving backfill, a corrected OHLC value, less warmup/forward-tail
  history available at fetch time), which would otherwise produce different
  `episodes_v1.json` content at the same path. Folding both the full
  parameter set AND the source-content fingerprint into the path makes both
  structurally impossible: two runs collide at the same `<run_id>` only
  when BOTH the requested contract AND the actual source content used to
  satisfy it are identical (idempotent repeat), and a run whose CLI
  arguments match but whose fetched content differs resolves to a different
  `<run_id>` instead of hitting a spurious `write_immutable_json` conflict.
  The manifest also carries `run_id`, `episode_stride_candles`,
  `max_episodes`, and `source_input_sha256` directly, so a run's full
  identity is recoverable from the manifest alone (`compute_run_id()` is
  mechanically re-derivable from the manifest's own fields).

### Source Input Fingerprint and Run Identity

`compute_run_id()` folds in `source_input_sha256`
(`compute_source_input_sha256`): a SHA-256 over a canonical (sorted-key,
compact-separator) JSON array of every candle in
`warmup_candles + requested_candles + forward_tail_candles`, in that exact
fetch order -- the full PIT source snapshot a run's feature/label output
was actually computed from, not just the CLI parameters describing what was
requested.

Each candle's fingerprint record (`_candle_fingerprint_fields`) covers every
field that can affect feature geometry or labels:

```text
symbol, venue, interval_code, open_ts_utc, close_ts_utc,
open_price, high_price, low_price, close_price, volume
```

Canonicalization rules, matching the discipline `compute_episode_id`
already uses:

- timestamps: UTC ISO-8601 (`astimezone(timezone.utc).isoformat()`) --
  candles reaching this point have already gone through
  `normalize_db_datetime_to_utc`, so this is never host-timezone dependent
- `Decimal` values: `format(value, "f")`, never `str()`/`repr()` (whose
  output can vary with a `Decimal`'s internal exponent for numerically
  equal values)
- candle order: preserved exactly as fetched (`validate_candle_sequence`
  separately enforces ascending, non-duplicate `close_ts_utc` before this
  fingerprint is computed)
- no dependence on Python's built-in `hash()`/`repr()` of any object

**Warmup/forward-tail source content is NOT irrelevant to identity.** Only
purely operational retrieval parameters that never change *which* candles
are fetched -- `--chunk-size-candles` (DB round-trip paging) and the
`BUILDING` progress-heartbeat cadence -- are excluded from
`source_input_sha256`/`run_id`. Two runs produce the same `run_id` if and
only if both the requested contract (CLI/config parameters) and the actual
fetched source candle content are identical; any difference in either --
including a single changed OHLCV value in warmup, the requested window, or
the forward tail -- produces a different `run_id`.

## Scope Boundary

Implemented in this slice:

1. contract/schema (`EpisodeFeaturePayload`, `EpisodeOutcomeLabels`,
   `EpisodeRecord`)
2. deterministic builder (`build_episode_feature`, `build_episode_labels`,
   `build_episodes`)
3. synthetic/unit tests (108 tests, no DB)
4. one-symbol/one-window smoke capability
   (`run_historical_fib_map_episode_substrate_v1.py`)
5. immutable manifest/provenance (`manifest_v1.json` with source bounds,
   candle/episode counts, and a SHA-256 of the episode payload)

Not implemented in this slice (explicitly out of scope for #555):

- #664 Fib Reach Strength calibration
- #723 promotion-grade evidence qualification
- #657 promotion mechanics / `automatic_exit_profile_v1` writes
- broad full-universe historical dataset generation
