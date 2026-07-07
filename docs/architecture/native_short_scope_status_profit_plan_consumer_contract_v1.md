# Native SHORT Scope-Status Profit Plan Consumer Contract V1

## Status

Consumer-boundary contract for Synth v2.22 Lane B.

Native SHORT scope-status PR A0 through A3 are complete:

```text
A0: persistence contract
A1/A1b: persistence schema and configuration-unavailable representation
A2: materializer, lifecycle observation, and scope-status projection
A3: health report consumes the projection
```

This document defines the read-only boundary for Short Swing / Profit Plan. It does
not authorize runtime deployment, private-account reads, order planning, execution,
or broker writes.

## Ownership

```text
native_short_scope_status_v1
= sole current market-status authority for a supported native SHORT scope

native_short_map_v1
= immutable geometry/provenance for the map explicitly referenced by that projection

Short Swing / Profit Plan
= read-only consumer; display and untrusted future selection only

Lane A
= runtime, disk, systemd, account snapshot, and account-snapshot freshness ownership
```

Reporting must not re-select a current map, recompute source freshness, or infer
map lifecycle from immutable map timestamps, generation ledgers, lifecycle ledgers,
or candles.

## Canonical Resolution Chain

For exactly one full native SHORT scope key:

```text
venue
symbol
quote_currency
fib_trading_horizon
primary_interval
supporting_interval
```

the consumer resolves state in this exact order:

```text
native_short_scope_status_v1
-> validate one projection row for the full scope key
-> read projection status/lifecycle/freshness/actionability/current_map_id/current_map_cycle_id
-> fetch immutable geometry only by projection.current_map_id plus the same full scope key
-> render read-only map and ladder context
```

The consumer must not use map publication time, map source-candle time, generation
event time, lifecycle event time, or a candle query as an alternative current-map
selector or freshness clock.

### Projection failure handling

A supported scope is blocked for active-map consumption when any of the following is
true:

```text
PROJECTION_MISSING
PROJECTION_INVALID
CONFIGURATION_UNAVAILABLE
SOURCE_UNAVAILABLE
SOURCE_STALE
OBSERVATION_OVERDUE
SCOPE_RECENTLY_ADDED
NO_CURRENT_MAP
TERMINAL_MAP
```

The rendered state must explain the actual projection fact. In particular:

```text
CONFIGURATION_UNAVAILABLE
!= SOURCE_UNAVAILABLE
!= SOURCE_STALE
!= OBSERVATION_OVERDUE
```

No fallback may fabricate an active, current, or fresh map.

### Geometry vintage versus current evaluation

The consumer may display both values, with distinct labels:

```text
geometry_vintage_utc = current_map_published_at_utc
current_evaluation_utc = projection_as_of_utc
latest_scope_observation_utc = latest_observed_at_utc
```

`geometry_vintage_utc` is immutable publication provenance. It is never a freshness
claim. Current source and observation state are the projection fields
`source_freshness_state`, `observation_freshness_state`, `scope_status_code`, and
`actionability_state`.

## Canonical Map Cycle

`current_map_cycle_id` is the canonical market-only map-cycle identity for the
projection-selected map.

Its owner is the native SHORT map/context contract. The native context constructs it
from the selected symbol, native horizon, primary interval, anchor start timestamp,
and anchor end timestamp; the map materializer persists it on `native_short_map_v1`;
the scope-status projection forwards it from the selected current map.

Rules:

```text
same canonical map cycle -> same non-empty map_cycle_id
new canonical map cycle  -> different map_cycle_id
reporting render UUID    -> never a map_cycle_id input
map publication time     -> never a substitute map_cycle_id
```

A row cannot be actionable when `current_map_id` or `current_map_cycle_id` is absent.
The consumer must render review/data-unavailable state instead.

## Immutable Geometry Access

The projection is the only current-map authority. Once it resolves a non-terminal,
actionable current map, the consumer may read that map's immutable geometry by
`current_map_id` and full scope key.

The immutable map record currently preserves named Fib geometry in `fib_ratios_json`
and target snapshots in `target_levels_json`. It does not make `local_reaction_price`
a mandatory ladder target. `local_reaction_price` is not a canonical active SELL
level unless a future native map-level contract explicitly assigns it a canonical
level role.

The consumer must preserve map geometry as provenance and must not rebuild a Fib map
or navigation map from current candles.

## Deterministic Read-Only Ladder Identity

The eventual Lane B identity implementation must expose two different identifiers.

### 1. Map-level row identity

`ladder_row_id` is stable across renders for the same canonical level:

```text
SHA-256(canonical JSON object)
```

The canonical JSON object has this exact semantic input set:

```text
identity_version
trading_account_ref
venue
market
map_cycle_id
side
canonical_map_level_role
canonical_tick_rounded_price
```

Normalization requirements:

```text
trading_account_ref       = immutable account-reference value supplied by the read snapshot
venue                     = canonical lower/upper normalization fixed by contract
market                    = canonical base-quote market string
map_cycle_id              = projection.current_map_cycle_id verbatim
side                      = BUY or SELL
canonical_map_level_role  = native-map-owned role code, not a display label
canonical_tick_rounded_price = Decimal quantized under the canonical market tick rule,
                               serialized as a normalized decimal string
```

Display labels, browser UUIDs, render IDs, timestamps, distance-to-price, and card
ordering are forbidden identity inputs.

### 2. Existing-order cancellation reference

An open order reference is not part of `ladder_row_id`; otherwise the same map level
would receive a new primary identity whenever an order is replaced. When a read-only
row represents a specific existing order that a later execution lane could cancel,
it exposes:

```text
ladder_order_reference_id = SHA-256(canonical JSON object)
```

with:

```text
identity_version
ladder_row_id
current_order_reference
```

`current_order_reference` is required only for that existing-order reference. This
keeps map-level identity stable while preserving the exact order identity required by
a future cancellation path.

No browser-generated UUID is authoritative. Missing account or order snapshots must
not be replaced with invented account/order references.

## Read-Only Row Semantics

The intended semantics are:

```text
MISSING
= an active canonical map level has no covering open order in a fresh account-order snapshot

ARMED
= a fresh account-order snapshot contains an open order covering an active canonical map level

STALE
= a fresh account-order snapshot contains an open order that does not cover an active current-map level,
  or belongs to a previous/expired map

HISTORICAL
= audit-only map/level context; never actionable

DATA_UNAVAILABLE
= no safe coverage assertion is possible because required projection, geometry,
  map-level lifecycle, account/order snapshot, or freshness evidence is unavailable
```

Distance from current price is not a staleness predicate. A far active target remains
`ARMED` when a fresh snapshot proves coverage.

The following are never selectable/actionable:

```text
HISTORICAL
DATA_UNAVAILABLE
terminal-map rows
reached/passed rows
completed rows
projection-blocked rows
```

## Current Contract Gap: Per-Level Lifecycle

The current projection is sufficient for current scope status, selected map identity,
map-cycle identity, map-level lifecycle, source freshness, observation freshness,
and market-only actionability.

It does not currently expose canonical current lifecycle state for each immutable map
level. `target_levels_json` preserves an immutable `active` / `previous` snapshot at
map publication; it does not provide a current per-level state such as:

```text
ACTIVE
REACHED_OR_PASSED
COMPLETED
HISTORICAL
```

Therefore, Profit Plan must not use its own candle/history reconstruction to decide
whether an individual level was reached or passed. Doing so would recreate a second
current-evaluation authority in reporting.

Until a native map/read-model contract supplies deterministic current per-level
status, Lane B may:

```text
- resolve projection-selected map and render map-level blocked/review states
- render immutable geometry as provenance
- render active-level coverage only as DATA_UNAVAILABLE/non-selectable when per-level state is required
- render terminal or previous-map context as HISTORICAL/non-selectable
```

Lane B must not claim `MISSING`, `ARMED`, or `STALE` coverage for a level whose
current active/historical state is unknown.

## Required Upstream Contract Before Full Coverage Semantics

A subsequent native market-data/read-model slice must provide one deterministic,
projection-owned or projection-referenced level-status collection for the selected
current map. Minimum fields per level:

```text
current_map_id
map_cycle_id
canonical_map_level_role
side
canonical_unrounded_price
level_lifecycle_state
level_status_as_of_utc
```

`level_lifecycle_state` must distinguish at least:

```text
ACTIVE
REACHED_OR_PASSED
COMPLETED
HISTORICAL
```

Its semantic clock must be `projection_as_of_utc` or an explicitly linked native
market-data evaluation clock. Reporting consumes it verbatim and never derives it
from candles.

This upstream change belongs to the native-map/read-model contract lane. It is not a
Lane A runtime/systemd/account-snapshot change and not a live-ladder/execution change.

## Lane B Non-Goals

```text
no systemd
no timer/service/wrapper deployment
no Odroid runtime-owner work
no broker or private-account calls
no broker writes
no order submission
no sizing
no server preview
no decision_gate changes
no execution_planner changes
no executor changes
no live-ladder mutation path
no selection_engine changes
```
