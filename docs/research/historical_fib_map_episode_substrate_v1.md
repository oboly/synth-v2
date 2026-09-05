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

### CLI Bound Normalization: `--from-ts`/`--to-ts` Offset Safety

`--from-ts`/`--to-ts` accept any ISO-8601 timestamp, including one with an
explicit UTC offset (e.g. `2026-01-01T00:00:00+02:00`). `main()` parses
both into UTC-aware datetimes once (`from_ts_dt`/`to_ts_dt`, via
`parse_ts_arg`) and uses THOSE -- never the raw CLI strings -- for every
downstream purpose that must agree on the exact instant being requested:
`build_episodes`' `emit_from_ts_utc`/`emit_to_ts_utc` emission gate, AND
every DB query bound (`fetch_ema_state_prehistory_candles`' `from_ts`,
`fetch_candles`' `from_ts`/`to_ts`, `fetch_forward_tail_candles`' `to_ts`),
via `format_ts_for_query(from_ts_dt)` / `format_ts_for_query(to_ts_dt)`.

`format_ts_for_query` renders a UTC-aware datetime as the canonical naive
`'YYYY-MM-DD HH:MM:SS'` string `obs_market_candle`'s naive, UTC-convention
timestamp columns expect. Without it, passing the raw CLI string straight
into a parameterized query would filter on the literal wall-clock digits
the caller typed (with any offset silently dropped/misinterpreted by the
DB layer) rather than the UTC instant those digits actually name --
fetching a different window than the one the emission boundary uses, and
silently changing which episodes/labels are produced for the same declared
UTC contract. `compute_run_id`/`build_manifest` deliberately continue to
use the raw CLI strings for `from_ts`/`to_ts` (they identify the REQUESTED
contract as the caller typed it, not the DB fetch bound); this fix only
changes what is sent to `obs_market_candle` queries.

## EMA-State Prehistory: Production-Equivalent Trend Reconstruction

`--from-ts`/`--to-ts` is a **research output** bound, not a feature-input
bound, and the Fib/map GEOMETRY window (`cfg.lookback_candles`, 180 for
both `1h` and `4h`) is a SEPARATE, deliberately unchanged concern from the
EMA/trend feature input:

- Production `src.features.etl_candle_feat.compute_features` computes
  `price_vs_ema20`/`price_vs_ema50`/`ema_spread_pct` via
  `close.ewm(span=20/50, adjust=False, min_periods=20/50).mean()`. With
  `adjust=False`, this is a RECURSIVE state (`y_t = alpha*x_t +
  (1-alpha)*y_{t-1}`, seeded at `y_0 = x_0`) that depends on EVERY
  preceding row of whatever candle series it was given -- not a fixed
  trailing window.
- Earlier historical replay reconstructed this same formula
  (`_reconstruct_trend_row`) from only the capped `cfg.lookback_candles`
  Fib-geometry window. That is production-INEQUIVALENT: identical as-of
  candles could silently classify to a different trend state -- and
  therefore a different canonical `build_row` admission/direction -- than
  production would, purely because replay looked at less history than
  production's own EWM recursion would have accumulated.
- The fix keeps the Fib/map geometry window exactly as it was
  (`build_episodes`' `window = candles[max(0, i - lookback_candles + 1) :
  i + 1]`, unchanged, still `build_row`'s `candles` argument) and adds a
  SEPARATE `trend_history = candles[:i + 1]` -- the FULL preceding PIT
  candle stream up to the same as-of candle, with NO `lookback_candles`
  cap -- fed to `_reconstruct_trend_row` for EMA/trend reconstruction
  only. `build_episode_feature` accepts `trend_history` as an explicit
  parameter (falling back to `window` when omitted, for direct callers/
  tests that do not care about the distinction); `build_episodes` always
  supplies the full preceding stream explicitly.

To supply that full preceding stream, the runner fetches the FULL
available `obs_market_candle` history strictly before `--from-ts`
(`fetch_ema_state_prehistory_candles` -- no `LIMIT`, bounded/chunked per DB
round trip via the same keyset-pagination discipline as `fetch_candles`,
never a small fixed warmup count) as **EMA-state prehistory**. Prehistory
candles are feature input only:

- `build_episodes` still scans them to reconstruct EMA/trend and
  window/stride state exactly as production would, via `emit_from_ts_utc`
  / `emit_to_ts_utc`
- an episode is only ever **emitted** (appended to the result) when
  `feature.map_creation_ts_utc` falls inside `[emit_from_ts_utc,
  emit_to_ts_utc)` -- the requested `[--from-ts, --to-ts)` window
- prehistory never reads a candle at/after `--to-ts` (no future data) and
  never reads from a current-state snapshot table (historical
  `obs_market_candle` rows only)
- the trailing `cfg.lookback_candles - 1` prehistory candles additionally
  serve as the Fib/map GEOMETRY warmup -- a strict subset of the same
  fetch, not a separate query (see `fib_geometry_warmup_candle_count` in
  the manifest)

This is a deliberate performance/correctness tradeoff: EMA reconstruction
is recomputed over the full preceding stream for every attempted as-of
position (`_reconstruct_trend_row` re-runs `ewm(...)` over `trend_history`
each time), an `O(candles^2)` cost in the worst case over a very long
history, accepted for production-equivalent correctness. A streaming/
incremental EMA optimization is a future improvement if this becomes a
practical bottleneck; it is out of scope for this fix.

`max_episodes` is checked before building each candidate episode (not
after appending), so `--max-episodes 0` deterministically yields zero
episodes rather than one.

### Production Parity

`tests/test_historical_fib_map_episode_substrate_v1.py`'s
`TestProductionEmaParity` proves this reconstruction is byte-identical to
production, not merely "close": given the full preceding candle history
for a chosen as-of candle (420-candle synthetic series, as-of index 350 --
well beyond the 180-candle geometry window), `_reconstruct_trend_row`'s
`price_vs_ema20`/`price_vs_ema50`/`ema_spread_pct` exactly equal
`etl_candle_feat.compute_features`' own output on the identical candle
series. A paired negative control (`test_truncated_history_measurably_
diverges_from_production`) reconstructs the SAME as-of candle from only
the trailing 180 candles (the pre-fix behavior) and asserts the result
differs from production by more than `1e-6` for `price_vs_ema50`/
`ema_spread_pct` -- proving the parity test is not vacuous.

## Forward-Label Tail: To-Ts Invariance for Outcome Labels

`[--from-ts, --to-ts)` is the **episode emission window**. Historically the
runner also stopped *source retrieval* at `--to-ts`, which meant an episode
emitted near the end of that window -- whose T2 or invalidation only
resolves on a candle *after* `--to-ts` -- had no forward candles left to
scan and was mislabeled `SOURCE_DATA_EXHAUSTED`. That reason is supposed to
mean "the market itself ran out of history", not "the caller's requested
output window ended"; before this fix the label silently depended on the
requested output bound rather than on the market.

The runner fixes this the same way it fixes the prehistory case, but
forward: after fetching EMA-state prehistory and the requested
`[from_ts, to_ts)` candles, it fetches up to `cfg.forward_max_candles`
additional historical `obs_market_candle` rows starting at
`open_ts_utc >= to_ts` (`fetch_forward_tail_candles`, a single bounded
`LIMIT`-ed query, `ORDER BY open_ts_utc ASC`). The build input becomes
`prehistory_candles + requested_candles + forward_tail_candles`;
`build_episodes`' existing forward-only indexing (`forward_candles =
candles[i + 1:]`) and `emit_from_ts_utc`/`emit_to_ts_utc` gate need no
change to honor this correctly:

- forward-tail candles can only ever be reached from an as-of index
  *before* them, so they can only extend outcome-label scanning for
  episodes already emitted from the requested window -- never contribute to
  feature/geometry construction for an earlier as-of candle (feature
  construction only ever looks backward from its own as-of index)
- forward-tail candles can themselves become an as-of position during the
  build loop (the loop runs over the full candle array), but any episode
  candidate there has `map_creation_ts_utc >= to_ts`, which fails the
  `emit_to_ts_utc` gate exactly like a prehistory-region as-of candle fails
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
in the manifest as separate provenance, alongside
`ema_state_prehistory_candle_count`, `fib_geometry_warmup_candle_count`,
and `chunk_size_candles`.

To summarize the three retrieval regions explicitly:

```text
[from_ts, to_ts)      = episode emission window (build_episodes' emit gate)
EMA-state prehistory  = EMA/trend feature input only (full available
                        history below from_ts) -- never emits, never
                        labels. Its trailing cfg.lookback_candles - 1
                        candles ALSO serve as Fib/map geometry warmup
                        (a strict subset, not a separate fetch).
post-to_ts tail       = forward-label evidence only -- never emits, never
                        contributes to feature construction
```

## Bounded/Chunked Retrieval and Interruption

`fetch_candles` retrieves the requested `[from_ts, to_ts)` range in bounded
pages (`--chunk-size-candles`, default 5000) using deterministic
`ORDER BY open_ts_utc ASC` keyset pagination: the first page uses
`open_ts_utc >= from_ts`, every following page uses `open_ts_utc >
<last row's open_ts_utc>` (strict), so no page can duplicate or skip a row
at a page boundary and no single query is unbounded.
`fetch_ema_state_prehistory_candles` uses the identical pagination
discipline with no `LIMIT` at all (its first page has no lower bound
either -- there is no fixed warmup count to seed it with): each DB round
trip is still bounded to `chunk_size` rows, but the TOTAL row count
fetched is not capped, since production-equivalent EMA reconstruction
needs the full available history, not a fixed warmup window.

The runner is single-process, single-worker (no worker pool) and prints an
observable phase per stage: `STARTED`, `FETCHING` (`phase=ema_prehistory`,
then per-chunk progress on the requested window, then the forward-label
tail -- `FETCHING phase=forward_tail ...`), `BUILDING` (see below),
`WRITING`, and exactly one terminal `FINISHED`, `INTERRUPTED`, or `FAILED`
line. SIGINT/SIGTERM are caught by `_SignalState` (a single flag, no
threads); the flag is polled between DB chunks, during `BUILDING` (see
below), and at each phase boundary (after asset/prehistory/requested/
forward-tail fetch and after build, before write). On interruption the
runner prints `INTERRUPTED` with
the signal and
a non-zero exit code (130 for SIGINT, 143 for SIGTERM) and never calls
`publish_immutable_run` -- so a killed run never produces a run directory
at all, partial or otherwise; see "Atomic Publication" below for the
stronger guarantee that even a *reached* publish attempt can never leave a
partial directory behind.

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
output path, so `publish_immutable_run` is never reached.

## CLI Parsing and Validation

`main()` owns the FULL CLI terminal contract -- both argparse-level parse
failures and `validate_args()`-level semantic failures resolve to the same
`FAILED reason=invalid_arguments ...` line and exit code 2.

argparse's default `ArgumentParser.error()` prints a usage/error message
and raises `SystemExit(2)` directly from inside `parse_args()`, before
`main()` ever reaches `validate_args()`. Left as-is, a missing required
flag (e.g. no `--symbol`), an invalid `--timeframe` choice, or a malformed
numeric argument (e.g. `--max-episodes not-a-number`) would silently bypass
the `FAILED` terminal contract every other invalid-input path already
honors, and exit via a raw `SystemExit` with argparse's own usage text
instead. `_Parser` (a thin `argparse.ArgumentParser` subclass used by
`_build_parser()`) overrides only `error()` to raise `ArgParseError`
instead of calling `self.exit(2, ...)`; `main()` catches `ArgParseError`
the same way it catches `validate_args()`'s `ValueError` and produces
exactly one `FAILED reason=invalid_arguments detail=<message>` line, no
traceback, no separate argparse usage/error chatter, exit code 2, and
`get_connection` is never called.

`--help` is deliberately unaffected: `argparse`'s built-in help action
calls `parser.exit()` directly (never `error()`), so `_Parser`'s override
does not touch it -- `--help` keeps normal argparse help semantics (print
help to stdout, `SystemExit(0)`) and is never converted to `FAILED`.
`main()` does not catch `SystemExit` anywhere, so this propagates
naturally; no other stage of the pipeline catches `SystemExit` either.

Once parsing succeeds, `validate_args` runs before any DB connection or
query (before `fetch_asset_id`) and rejects, via the same
`FAILED reason=invalid_arguments` / exit-2 contract:

- `--episode-stride-candles <= 0`
- `--max-episodes` present and `< 0`
- `--chunk-size-candles <= 0`
- `--from-ts` not strictly earlier than `--to-ts`

## FAILED Terminal Summary

Every operational stage after argument validation is wrapped so an
expected failure produces exactly one `FAILED reason=<code> detail=<...>`
line and a non-zero exit, instead of an unhandled traceback. `detail` is
`str(exception)` only -- no traceback, no connection/environment payload --
so diagnostics do not leak secrets. Reason codes, in the order a run
encounters them:

```text
invalid_arguments          -- parse_args (argparse parse failure, before any DB call)
                              / validate_args (before any DB call); exit 2
asset_lookup_failed        -- fetch_asset_id
source_fetch_failed        -- fetch_ema_state_prehistory_candles / fetch_candles / fetch_forward_tail_candles
source_validation_failed   -- validate_candle_sequence (duplicate/non-monotonic candles)
build_failed                -- build_episodes (any failure other than BuildCancelled)
output_write_failed        -- build_manifest / publish_immutable_run (episodes+manifest)
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

Because `run_id`/output-path construction and `publish_immutable_run` run
only after a fully successful `BUILDING` phase, a failure in any earlier
stage (`asset_lookup_failed`, `source_fetch_failed`,
`source_validation_failed`, `build_failed`) creates zero files under
`--output-dir`. See "Atomic Publication" below for what happens once
publication is reached.

## Atomic Publication

**Invariant: a final `<run_id>` directory is either ABSENT or COMPLETE**
(both `episodes_v1.json` AND `manifest_v1.json` present and mutually
consistent) -- **never partial.**

The prior design wrote `episodes_v1.json` and `manifest_v1.json` as two
independent `write_immutable_json` calls, episodes first. If manifest
construction or its write failed in between, the run directory could be
left containing only `episodes_v1.json` -- a partial artifact masquerading
as content under an otherwise-immutable path.

`publish_immutable_run` replaces both calls with a single atomic
operation:

1. Both `episodes_text` and `manifest_text` are fully built in memory by
   `main()` *before* `publish_immutable_run` is ever called -- nothing
   about publication depends on any prior filesystem write.
2. If `output_dir` (the final `<run_id>` directory) already exists, it is
   checked immediately: both files must be present, and both must hash to
   the exact candidate content. All-present-and-identical is an
   **idempotent success** (nothing is written; the existing directory is
   returned as-is). Either file missing (a partial existing directory) or
   present-but-different content fails closed with `ValueError` -- a
   partial or conflicting existing directory is never "repaired" or
   silently overwritten.
3. Otherwise, both files are written into a private **staging directory**
   -- a sibling of `output_dir`, so guaranteed to be on the same filesystem
   -- and each is `fsync`'d individually; the staging directory's own
   entry is then `fsync`'d too.
4. The staging directory is published with a single `os.rename` directly
   onto `output_dir`. A directory rename either fully succeeds or does not
   happen at all -- there is no filesystem-visible intermediate state with
   only one file present, which is the structural property a
   write-episodes-then-write-manifest sequence cannot offer.
5. If the rename itself races with a concurrent identical/conflicting
   publish (`output_dir` now exists where it did not a moment ago), step 2
   is re-run rather than assuming success or failure.
6. The staging directory is *always* removed before this function returns
   or raises: a successful rename consumes it (nothing left at the old
   path), and a `finally` block removes it on every other path (idempotent
   match, conflict, or any other exception) -- so a failed or interrupted
   publish attempt can never leave an orphaned staging directory next to
   `output_dir`.

An `output_write_failed` result therefore always means `output_dir` itself
was left completely untouched: either it never existed at all, or a
pre-existing partial/conflicting directory was left exactly as found.

## Determinism and Immutability

- No wall-clock dependence: all "now" values used by the geometry engine
  come from the historical candle's own timestamp, never `datetime.now()`.
- `episode_id` is a SHA-256 of `(symbol, venue, interval_code,
  contract_version, map_creation_ts_utc, direction, anchor_low, anchor_high)`.
- The runner (`run_historical_fib_map_episode_substrate_v1.py`) writes
  `episodes_v1.json` and `manifest_v1.json` together under
  `data/research/historical_fib_map_episode_substrate_v1/<venue>/<symbol>/<interval_code>/<run_id>/`
  via `publish_immutable_run`'s stage-then-atomic-rename publication (see
  "Atomic Publication" above). `<run_id>` is a SHA-256 of the canonical
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
  (late-arriving backfill, a corrected OHLC value, less EMA-state
  prehistory/forward-tail history available at fetch time), which would
  otherwise produce different
  `episodes_v1.json` content at the same path. Folding both the full
  parameter set AND the source-content fingerprint into the path makes both
  structurally impossible: two runs collide at the same `<run_id>` only
  when BOTH the requested contract AND the actual source content used to
  satisfy it are identical (idempotent repeat), and a run whose CLI
  arguments match but whose fetched content differs resolves to a different
  `<run_id>` instead of hitting a spurious immutable-publish conflict.
  The manifest also carries `run_id`, `episode_stride_candles`,
  `max_episodes`, and `source_input_sha256` directly, so a run's full
  identity is recoverable from the manifest alone (`compute_run_id()` is
  mechanically re-derivable from the manifest's own fields).

### Source Input Fingerprint and Run Identity

`compute_run_id()` folds in `source_input_sha256`
(`compute_source_input_sha256`): a SHA-256 over a canonical (sorted-key,
compact-separator) JSON array of every candle in
`prehistory_candles + requested_candles + forward_tail_candles`, in that
exact fetch order -- the full PIT source snapshot a run's feature/label
output was actually computed from, not just the CLI parameters describing
what was requested.

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

**EMA-state-prehistory/forward-tail source content is NOT irrelevant to
identity.** Only purely operational retrieval parameters that never change
*which* candles are fetched -- `--chunk-size-candles` (DB round-trip
paging) and the `BUILDING` progress-heartbeat cadence -- are excluded from
`source_input_sha256`/`run_id`. Two runs produce the same `run_id` if and
only if both the requested contract (CLI/config parameters) and the actual
fetched source candle content are identical; any difference in either --
including a single changed OHLCV value in EMA-state prehistory, the
requested window, or the forward tail -- produces a different `run_id`.

## Scope Boundary

Implemented in this slice:

1. contract/schema (`EpisodeFeaturePayload`, `EpisodeOutcomeLabels`,
   `EpisodeRecord`)
2. deterministic builder (`build_episode_feature`, `build_episode_labels`,
   `build_episodes`)
3. synthetic/unit tests (131 tests, no DB)
4. one-symbol/one-window smoke capability
   (`run_historical_fib_map_episode_substrate_v1.py`)
5. immutable manifest/provenance (`manifest_v1.json` with source bounds,
   candle/episode counts, and a SHA-256 of the episode payload)

Not implemented in this slice (explicitly out of scope for #555):

- #664 Fib Reach Strength calibration
- #723 promotion-grade evidence qualification
- #657 promotion mechanics / `automatic_exit_profile_v1` writes
- broad full-universe historical dataset generation
