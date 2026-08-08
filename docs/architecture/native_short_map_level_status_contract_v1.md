# Native SHORT Current Map-Level Status Contract V1

## Status

Contract freeze for Synth v2.22 Lane B0.

This contract defines a market-only, rebuildable level-status read model. It does
not add a scheduler, runtime owner, account snapshot, broker call, order coverage,
reporting/UI consumer, decision gate, execution planner, executor, or order write.

Implementation PRs must not start until this contract is accepted.

## Purpose

`native_short_scope_status_v1` is the sole current authority for a native SHORT
scope. It resolves the current map, map-cycle identity, map lifecycle, source
freshness, observation freshness, actionability, and explicit semantic clock.

It does not expose current lifecycle state for individual immutable map levels.

This contract adds the missing market-data read model:

```text
native_short_scope_status_v1
-> projection-selected current_map_id / current_map_cycle_id
-> native_short_map_level_status_v1
-> future read-only consumer
```

No reporting surface may reconstruct these states from candles.

## Phase 0 Evidence Inventory

### Current scope authority and semantic clock

`native_short_scope_status_v1` is rebuildable and has exactly one row per
SUPPORTED scope. `projection_as_of_utc` is its only semantic clock; it is explicit
and must not be replaced with `datetime.now()` or database `NOW()`.

The projection already exposes:

```text
current_map_id
current_map_cycle_id
map_lifecycle_state
scope_status_code
source_freshness_state
observation_freshness_state
actionability_state
projection_as_of_utc
```

The projection selects a current map by excluding authoritative superseded maps,
then choosing the latest eligible map by `(published_at_utc, map_id)`. A consumer
must never repeat that selection logic.

### Immutable geometry

`native_short_map_v1` is immutable map geometry/provenance. Its named Fib geometry
is preserved in `fib_ratios_json`:

```text
breakout_gate
ext_1_272
ext_1_618
ext_2_000
reload_r382
reload_r500
reload_r618
reload_r786
```

It separately preserves:

```text
target_levels_json      # immutable active/previous snapshot, without canonical role labels
invalidation_price
anchor_low/high data
map_payload_json
```

`target_levels_json` is not the role authority because its `active` and `previous`
arrays contain prices only. V1 canonical roles must therefore be extracted from the
named immutable `fib_ratios_json` keys, never inferred by price ordering or display
labels.

### Existing lifecycle predicates

The current native 4h context classifies extension targets by using the maximum
primary-candle high since the anchor:

```text
previous_target_levels = target levels where max_high_since_anchor >= level
active_target_levels   = target levels where max_high_since_anchor < level
```

At map level it emits `TARGET_REACHED_OR_PASSED`; the existing code intentionally
does not distinguish a touch from a closed pass-through. Map completion is reached
when no active extension target remains. Map invalidation uses the configured
invalidation buffer. The status materializer may append only map-level
`COMPLETED` or `INVALIDATED` lifecycle events from those existing predicates.

No existing native contract defines per-level lifecycle rows. No existing
native predicate defines a distinct `REACHED` versus `PASSED` state.

### Reload, breakout, and invalidation levels

The reentry builder exposes named retracement levels and a `recently_touched` flag
from the latest low. It does not define durable per-level lifecycle, pass-through,
completion, or historical semantics. Breakout and invalidation levels are map
context/risk boundaries, not canonical ladder sides in the existing native contract.

Therefore they are intentionally excluded from V1 materialized level rows. A later
contract may add BUY-reload or context-boundary level state only after it defines
explicit lifecycle predicates and side ownership.

### Tick-rounding ownership

`src.market_rules/price_tick_normalization_v1.py` is the canonical public,
account-agnostic owner of market tick rules. It resolves DB rules first, static
public fallback second, and exposes deterministic Decimal-only normalization:

```text
TARGET_SELL -> round up
REENTRY_BUY -> round down
INVALIDATION -> round down
DISPLAY_ONLY -> nearest tick
```

Tick rounding is not map geometry and must not affect the lifecycle predicate. V1
stores both the immutable analytical price and an optional tick-normalized price.

## V1 Scope

V1 materializes only canonical native SHORT extension target levels:

| Canonical map-level role | Immutable geometry key | Side |
|---|---|---|
| `SELL_EXT_1_272` | `ext_1_272` | `SELL` |
| `SELL_EXT_1_618` | `ext_1_618` | `SELL` |
| `SELL_EXT_2_000` | `ext_2_000` | `SELL` |

The following immutable geometry is explicitly out of scope for V1 level-status
materialization:

```text
breakout_gate
reload_r382
reload_r500
reload_r618
reload_r786
invalidation_price
```

This is a deliberate narrow boundary, not an assertion that those levels have no
market meaning. They lack an accepted native per-level lifecycle definition.

## Entity: native_short_map_level_status_v1

### Purpose and authority

`native_short_map_level_status_v1` is a rebuildable, current, market-only
collection for canonical V1 levels of the map selected by
`native_short_scope_status_v1`.

It is not authoritative history, map geometry, a decision gate, account/order
coverage, or execution intent.

The collection has no independent map selector and no independent wall clock.
Every row is derived from one validated scope-status projection row and its
`projection_as_of_utc`.

### Scope key and uniqueness

Every row carries the complete native SHORT scope key:

```text
venue
symbol
quote_currency
fib_trading_horizon
primary_interval
supporting_interval
```

The row uniqueness key is:

```text
venue,
symbol,
quote_currency,
fib_trading_horizon,
primary_interval,
supporting_interval,
current_map_id,
canonical_map_level_role,
side,
canonical_unrounded_price
```

`current_map_id + canonical_map_level_role + side + canonical_unrounded_price`
is the canonical map-level identity. It is market-only and does not contain an
account reference, browser UUID, render UUID, display label, or render timestamp.

### Required fields

| Field | Required | Meaning |
|---|---:|---|
| `map_level_status_id` | yes | Surrogate rebuildable-row id |
| full native SHORT scope key | yes | Canonical scope identity |
| `current_map_id` | yes | Must equal the selected projection `current_map_id` |
| `map_cycle_id` | yes | Must equal the selected projection `current_map_cycle_id` |
| `canonical_map_level_role` | yes | Closed V1 role enum |
| `side` | yes | Closed V1 enum; `SELL` only in V1 |
| `canonical_unrounded_price` | yes | Immutable analytical map geometry price |
| `canonical_tick_rounded_price` | no | Optional public tick-normalized price; null only when tick rule is missing |
| `tick_rule_status` | yes | Tick normalization evidence; distinct missing-rule state |
| `tick_rule_source` | yes | DB, static public fallback, or missing |
| `level_lifecycle_state` | yes | Closed level lifecycle enum below |
| `level_status_as_of_utc` | yes | Equal to source projection `projection_as_of_utc` |
| `evaluation_reference` | yes | Closed evaluation-reference enum below |
| `reason_code` | yes | Stable reason for the state |
| `projection_scope_status_code` | yes | Source projection top-level status, forwarded verbatim |
| `projection_map_lifecycle_state` | yes | Source projection map lifecycle, forwarded verbatim |
| `projection_actionability_state` | yes | Source projection actionability, forwarded verbatim |
| `rebuilt_at_utc` | yes | Operational metadata only; never semantic input |

### Closed enums

`canonical_map_level_role`:

```text
SELL_EXT_1_272
SELL_EXT_1_618
SELL_EXT_2_000
```

`side`:

```text
SELL
```

`level_lifecycle_state`:

```text
ACTIVE
REACHED
PASSED
COMPLETED
HISTORICAL
```

`evaluation_reference`:

```text
PRIMARY_4H_CLOSED_CANDLES
MAP_LIFECYCLE_EVENT
```

No other level state may be invented through reporting labels or database contents.

## Selection and Rebuild Gate

### Sole current-map selector

The level-status materializer reads one scope-status projection row by the full
scope key. It must validate all of the following before reading immutable geometry:

```text
scope_support_state = SUPPORTED
current_map_id is not null
current_map_cycle_id is non-empty
projection map identity matches immutable map id, full scope key, and map_cycle_id
```

It then reads immutable geometry by exactly:

```text
projection.current_map_id + full scope key
```

It must not select a map by map timestamp, generation event, lifecycle ledger, or
candle history.

### Active-evaluation gate

Dynamic `ACTIVE`, `REACHED`, and `PASSED` rows may be materialized only when the
source projection states all hold:

```text
scope_status_code = CURRENT_EVALUATION
source_freshness_state = SOURCE_CURRENT
observation_freshness_state = OBSERVATION_CURRENT
actionability_state = ACTIONABLE_ACTIVE_MAP
map_lifecycle_state = MAP_ACTIVE
```

The materializer must use the exact source `projection_as_of_utc` as
`level_status_as_of_utc`.

### Fail-closed outcomes

No dynamic level state may be fabricated when the projection is missing, invalid,
or blocked. The materializer deletes/rebuilds the scope collection atomically and
emits no current level rows for:

```text
PROJECTION_MISSING
PROJECTION_INVALID
CONFIGURATION_UNAVAILABLE
SOURCE_UNAVAILABLE
SOURCE_STALE
SCOPE_RECENTLY_ADDED
OBSERVATION_OVERDUE
NO_CURRENT_MAP
```

The reason remains authoritative in `native_short_scope_status_v1`; absence of a
level row is not a substitute for, or conflation of, those scope states. A future
consumer must read scope status first and fail closed if the level collection is
absent.

`NO_CURRENT_MAP` is reported under two distinct gate branches, which differ only
in classification, never in persistence (both emit zero level rows and clear any
stale collection atomically, so the "no dynamic level state fabricated"
invariant holds identically for both):

```text
BLOCKED                          -- map rows exist for the exact scope key but
                                    none is currently selected (for example an
                                    established scope whose maps are all
                                    SUPERSEDED with no successor published).
                                    An unexpectedly missing current map;
                                    hard-stop, fail-closed.
EXPECTED_BOOTSTRAP_NO_CURRENT_MAP -- zero map rows have ever existed for the
                                    exact scope key: the expected, transient
                                    first-map bootstrap state of a newly
                                    promoted scope. Not an integrity defect.
```

The distinguishing predicate is ledger existence only (zero
`native_short_map_v1` rows for the exact canonical scope key, independent of
`as_of_utc` and of lifecycle state), supplied to `select_gate_decision` as the
required `never_published_any_map` keyword. It is deliberately not a timing,
ordering, or grace-window inference.

In particular:

```text
CONFIGURATION_UNAVAILABLE
!= SOURCE_UNAVAILABLE
!= SOURCE_STALE
!= OBSERVATION_OVERDUE
```

### Terminal projection-selected maps

The selected map can have a known terminal lifecycle even when no later map exists.
For that map only:

```text
MAP_COMPLETED   -> every V1 row is COMPLETED, evaluation_reference=MAP_LIFECYCLE_EVENT
MAP_INVALIDATED -> every V1 row is HISTORICAL, evaluation_reference=MAP_LIFECYCLE_EVENT
MAP_EXPIRED     -> every V1 row is HISTORICAL, evaluation_reference=MAP_LIFECYCLE_EVENT
```

Reason codes must preserve the terminal fact:

```text
MAP_COMPLETED
MAP_INVALIDATED
MAP_EXPIRED
```

A superseded map is never selected by `native_short_scope_status_v1`; its levels
are not copied into this current collection. Its immutable geometry remains audit
history in `native_short_map_v1`, not current level status.

## V1 SELL-Level Lifecycle Predicate

### Candle domain

For an active projection-selected map, the level evaluator receives only persisted
closed primary-interval candles satisfying:

```text
map.anchor_high_ts_utc <= candle.close_ts_utc <= projection_as_of_utc
```

The primary interval is the map's canonical `4h` scope interval. The evaluator uses
immutable `canonical_unrounded_price`, never tick-rounded price, for lifecycle
classification.

The interval, anchor boundary, map identity, and evaluation clock are explicit.
No wall-clock reads are permitted.

### Deterministic definitions

For each V1 SELL level at price `L`:

```text
PASSED
= at least one eligible closed 4h candle has close_price > L

REACHED
= at least one eligible closed 4h candle has high_price >= L
  AND no eligible closed 4h candle has close_price > L

ACTIVE
= no eligible closed 4h candle has high_price >= L
```

This creates a monotonic causal distinction:

```text
intrabar touch/rejection -> REACHED
closed 4h continuation above level -> PASSED
not reached -> ACTIVE
```

A current price below a previously passed level does not revert it to `REACHED` or
`ACTIVE`.

This V1 predicate is intentionally narrower than trade completion. A price touch is
not `COMPLETED`; only a canonical map terminal lifecycle event yields `COMPLETED`.

### Reason codes

Non-terminal V1 reason codes:

```text
NO_PRIMARY_HIGH_REACHED_LEVEL
PRIMARY_HIGH_REACHED_WITHOUT_CLOSE_ABOVE
PRIMARY_CLOSE_PASSED_LEVEL
```

## Tick Normalization

The materializer derives the market as:

```text
{symbol}-{quote_currency}
```

For V1 SELL levels it calls the canonical tick owner with:

```text
price_role = TARGET_SELL
```

It persists:

```text
canonical_unrounded_price = immutable fib_ratios_json value
canonical_tick_rounded_price = canonical TARGET_SELL rounded value
```

If no tick rule is available:

```text
canonical_tick_rounded_price = NULL
tick_rule_status = MISSING_TICK_RULE
tick_rule_source = MISSING_TICK_RULE
```

The level lifecycle row remains valid market data because lifecycle uses immutable
unrounded geometry. A later account/order consumer must fail closed for any action
or identity that requires a tick-normalized price but receives missing tick evidence.

Tick normalization must not mutate `native_short_map_v1`, nor alter lifecycle
classification.

## Materialization Ownership

The implementation has two layers:

```text
pure layer
- validates projection-selected map identity
- extracts V1 named immutable SELL geometry
- evaluates eligible closed 4h candle facts at explicit projection_as_of_utc
- applies terminal-map and per-level lifecycle rules
- emits validated rebuildable rows or a fail-closed blocked outcome

MariaDB layer
- reads native_short_scope_status_v1
- reads immutable native_short_map_v1 by projection current_map_id and full scope key
- reads persisted public primary candles only when active evaluation is permitted
- resolves public tick metadata
- atomically replaces rows for the exact scope
```

The existing bounded native scope-status materializer may invoke this materializer
using the same explicit `as_of_utc` after rebuilding the scope projection. This is
not scheduler or deployment work. It must not append immutable maps, generation
events, lifecycle events, or heartbeat records.

## Integrity Rules

```text
- map_cycle_id is copied only from the projection-selected map and must match the map record.
- immutable map geometry is never updated for level status or freshness.
- level_status_as_of_utc equals projection_as_of_utc exactly.
- rebuilt_at_utc is operational metadata, never a lifecycle input.
- every active collection contains exactly the three V1 SELL roles once each.
- malformed, missing, duplicate, or non-positive immutable geometry fails closed for that scope.
- tick-normalized price is never used as a lifecycle threshold.
- reporting, account, broker, decision, planner, and executor packages are forbidden imports.
```

## Required Implementation Tests

The implementation PRs must prove:

```text
- same map/cycle/input/as-of produces identical level identities and rows
- changed selected map cycle produces rows with the new current_map_id/map_cycle_id
- immutable map geometry remains unchanged after rebuild
- level_status_as_of_utc equals the explicit projection_as_of_utc
- ACTIVE, REACHED, and PASSED distinguish high-touch from closed pass-through
- map completion emits COMPLETED without treating touch alone as completed
- invalidated/expired selected maps emit HISTORICAL with preserved terminal reason
- missing/invalid/blocked projection emits no false current rows
- CONFIGURATION_UNAVAILABLE remains distinguishable from source stale/unavailable through the source projection
- no map/generation/lifecycle heartbeat rows are written
- missing tick rule preserves unrounded lifecycle semantics and emits explicit missing-tick evidence
- no reporting/account/broker/decision/execution imports
```

## Explicit Non-Goals

```text
no Profit Plan resolver migration
no reporting or UI work
no account or order coverage
no ladder repair
no broker or private account calls
no broker writes
no order submission
no sizing
no decision_gate changes
no execution_planner changes
no executor changes
no selection_engine changes
no systemd, timer, service, wrapper, or Odroid deployment work
no reload-buy, breakout-gate, or invalidation level lifecycle in V1
```

## Addendum: Prospective Target-Event Lifecycle History (2026-07-31)

### Authorization boundary

This addendum implements append-only REACHED/PASSED target-event history for
V1 SELL levels. It is authorized under the Synth Outcome & Reliability
Program as a required foundation for reproducible *future* outcome
attribution -- **prospectively only**.

This authorization is explicitly **not**:

- evidence that the earlier IOST reporting-bridge case was a canonical
  lifecycle defect (the accepted forensic audit proved it was not: IOST never
  had a canonical map/scope);
- evidence that BTC has exhibited a REACHED/PASSED-then-pullback regression
  (none has been found; BTC's canonical lifecycle has never regressed);
- a claim that existing historical target transitions on already-active maps
  can be reconstructed losslessly.

The prior evidence-gated conclusion in
`docs/todo/profit_plan_target_lifecycle_history_truth_v1.md` and the reopen
criteria in `docs/todo/native_short_map_level_status_v1.md` remain factually
correct and unmodified; this addendum sits alongside them, not in place of
them. See those files for the retained record.

```text
NO_CANONICAL_REGRESSION_EVIDENCE_FOUND=true
IMPLEMENTATION_JUSTIFICATION=PROSPECTIVE_OUTCOME_EVIDENCE
HISTORICAL_BACKFILL_AUTHORIZED=false
```

### Event authority and identity

`native_short_map_level_target_event_v1` (migration
`db/migrations/20260731_native_short_map_level_target_event_v1.sql`) is the
sole append-only persistence authority for V1 SELL target transitions. Only
`REACHED` and `PASSED` event types exist; there is no `ACTIVE` event -- ACTIVE
is defined as the absence of a terminal event for a covered level identity.

Canonical structured identity (no free-text/symbol matching is possible):

```text
map_id + canonical_map_level_role + side + canonical_unrounded_price + target_event_type
```

`map_id` is the exact immutable map (`native_short_map_v1.map_id`); rollover
to a successor map never carries target events forward, because a new map
has a new `map_id` and events are always looked up by the exact current
`map_id`.

### Causality and timestamps

`effective_at_utc` is sourced only from the causal closed 4h candle's
`close_ts_utc` (a database CHECK constraint enforces
`effective_at_utc = causal_candle_close_ts_utc`). `recorded_at_utc` is the
writer's wall-clock insert time and is never substituted for, or derived
from, `effective_at_utc`. Same-candle ambiguity (a single candle both touches
and closes above a level) is made explicit via `same_candle_reached_skipped`
on the `PASSED` row rather than silently fabricating an intermediate
`REACHED` row.

### Transition and idempotency rules

- Transitions are derived only from the same `classify_level_state` decision
  already used by `native_short_map_level_status_materializer_v1` over
  persisted closed primary candles -- there is no second, independently
  computed lifecycle authority.
- Events are insert-only; this module never issues an `UPDATE` against the
  event table. The database unique identity constraint is the sole
  duplicate-write fence: a duplicate insert attempt is rejected by the
  database and treated as an idempotent no-op, never as a mutation of the
  original row. Later runs therefore cannot rewrite an earlier event's causal
  candle or timestamp.
- Reprocessing identical candle input never appends a duplicate event.

### Immutable per-map coverage activation and causal cutoff (revised 2026-07-31)

Coverage is **durable, persisted, per-map state**, not a runtime-only
watermark check. `native_short_map_level_target_event_coverage_v1` holds at
most one immutable row per exact `map_id`:

```text
coverage_cutoff_utc = GREATEST(publication_boundary_utc, requested_watermark_utc_at_establishment)
```

`compute_target_event_coverage_cutoff` computes this once, at establishment
time only (`establish_or_fetch_target_event_coverage_for_map`). Only closed
candles whose causal `close_ts_utc` is **on or after** the persisted
`coverage_cutoff_utc` may create a REACHED/PASSED event
(`filter_candles_from_cutoff`) -- a candle before the cutoff can never create
an event, regardless of what the existing (unchanged) full-history
`classify_level_state` row-projection independently reports for the same map.

Coverage lifecycle:

- **No coverage row + no watermark supplied this run** -> `NO_WATERMARK_SUPPLIED`;
  no coverage row is created, no events are appended (byte-for-byte a no-op).
- **No coverage row + a watermark is supplied** -> coverage is established
  exactly once, with `coverage_cutoff_utc = GREATEST(map.published_at_utc, watermark)`.
- **Coverage row already exists** -> the persisted `coverage_cutoff_utc` is
  read and used; the current run's watermark parameter is *ignored* for
  cutoff purposes. A later run supplying an older watermark can never expand
  coverage backward, and a later run supplying a newer watermark can never
  rewrite the already-established cutoff.
- A map that goes terminal (COMPLETED/INVALIDATED/EXPIRED/SUPERSEDED) without
  ever having had coverage established remains **permanently uncovered** --
  `LEGACY_UNAVAILABLE` forever, never a silently-inferred `ACTIVE`, because
  coverage can only ever be established while a map is in `ACTIVE_EVALUATION`.

This supersedes the original, simpler "published-at-or-after-watermark"
per-run gate described in the first version of this addendum; that gate could
allow a causal candle from before either boundary to be used as evidence,
which this cutoff model closes.

### Projection / reducer ownership

`project_level_target_state_from_events` /
`project_level_target_state_from_event_types`
(`src/market_data/native_short_map_level_target_event_v1.py`) is the
deterministic reducer proving that, for a covered map-level identity, current
state is reproducible from immutable geometry plus persisted events alone
(`PASSED` if a `PASSED` event exists, else `REACHED` if a `REACHED` event
exists, else `ACTIVE`). For an uncovered identity this always resolves to
`LEGACY_UNAVAILABLE`, never a silent `ACTIVE` default -- ACTIVE vs
LEGACY_UNAVAILABLE is therefore always deterministically distinguishable from
the persisted coverage state alone, independent of whether any event exists.

### Writer ownership and terminal-transition atomicity

`append_native_short_map_level_target_events_for_map`
(`native_short_map_level_target_event_materializer_v1.py`) is the single
shared write authority for target events, called from exactly two sites:

1. The standalone per-symbol wrapper
   (`materialize_native_short_map_level_target_events_for_scope`), gated to
   `ACTIVE_EVALUATION` only, used by the manual
   `run_native_short_map_level_status_materializer_v1` runner behind its
   **optional** `--target-event-coverage-watermark-utc` flag; omitting it
   (the default, and every pre-existing call site's behavior) leaves the
   runner byte-for-byte unchanged.
2. The integrated scope-status materializer's terminal-transition hook
   (`native_short_scope_status_materializer_v1._append_terminal_target_events`),
   called from `evaluate_scope` **before** `_insert_lifecycle_event` whenever
   a map is about to be marked `COMPLETED`, using the same `conn` and
   therefore the same transaction the caller uses to record that terminal
   lifecycle event. This closes the gap where the same causal candle that
   completes a map could otherwise complete it without ever durably recording
   the final target-level transition that candle also caused, and removes any
   dependency on a later, separate manual runner seeing the map while it is
   still active. `evaluate_scope` never calls `conn.commit()`/`conn.rollback()`
   itself, so this atomicity is inherited entirely from whichever caller owns
   the transaction; a failure anywhere in the sequence leaves nothing
   partially committed. `run_native_short_scope_status_materializer` also
   gained the same optional `target_event_coverage_watermark_utc` parameter,
   defaulting to `None` (unchanged behavior).

There is no third, independently-computed target-event decision anywhere:
both call sites delegate to the one shared function above.

### Write-counter observability

`run_native_short_map_level_status_materializer_v1`'s `ScopeRunResult` now
reports writes explicitly and separately:

```text
status_rows_written        -- level-status projection rows (alias of the
                               pre-existing rows_written; that field's meaning
                               is unchanged)
target_event_rows_written  -- target events appended this cycle
rows_written_total         -- status_rows_written + target_event_rows_written
requested_target_event_watermark_utc        -- the watermark this run supplied
persisted_target_event_coverage_cutoff_utc  -- the durable, persisted cutoff
                                                actually in effect for the map
```

### Explicitly deferred

- `EXPIRED` target-level detection is not implemented.
- `PostTargetReentryProjection` is not implemented.
- Historical backfill of pre-coverage maps/targets remains unauthorized and
  is not performed.
- Production activation (choosing and applying the watermark, running one
  controlled BTC/PAPER cycle) is a separate, later, explicitly reviewed step.

## Follow-Up Contract Gap

A future native contract is required before adding these level roles:

```text
BUY_RELOAD_R382
BUY_RELOAD_R500
BUY_RELOAD_R618
BUY_RELOAD_R786
BREAKOUT_GATE
INVALIDATION
```

That contract must define, before implementation:

```text
side ownership
active/reached/passed predicates
terminal completion semantics
historical semantics
which closed candle interval is authoritative
whether and how state remains monotonic after a rebound
```

Reporting must not fill this gap with candle-history reconstruction.
