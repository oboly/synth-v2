# TODO — Native SHORT Runtime Owner And Scope Status V1

## Status

```text
PR A0–A3: completed and merged
PR B: runtime-owner deployment remains blocked on P0-A / PR #54 acceptance
PR C: Short Swing read-only consumption is scoped by
      docs/architecture/native_short_scope_status_profit_plan_consumer_contract_v1.md
```

## Sequencing / P0-A dependency

- PR A0–A3 may remain fully operational without systemd, timer, service, wrapper,
  or host deployment work.
- PR B is blocked until P0-A / PR #54 is merged and its bounded logging plus
  disk/log health containment is accepted.
- Do not deploy any recurring native SHORT runtime, wrapper, service, or timer
  before PR B is unblocked.
- PR C depends on the completed A0–A3 scope-status contract. Full ladder coverage
  semantics additionally depend on a future native per-map-level lifecycle read
  model; see the consumer contract.

## Sources

- `docs/architecture/native_short_scope_status_contract_v1.md`
- `docs/architecture/native_short_scope_status_profit_plan_consumer_contract_v1.md`
- `docs/ops/native_short_map_ledger_health_report_v1.md`
- `src/market_data/native_short_scope_status_projection_v1.py`
- `src/market_data/native_short_scope_status_materializer_v1.py`
- `src/reporting/native_short_map_ledger_health_report_v1.py`
- `db/migrations/20260626_native_short_map_lifecycle_v1.sql`
- `db/migrations/20260706_native_short_scope_status_persistence_v1.sql`

## Purpose

Define the durable market-only native SHORT lane that evaluates native maps from
persisted public candles, records lifecycle/runtime evidence, and exposes one
rebuildable current scope-status projection for reporting/UI consumers.

## Current state / facts

- Native SHORT materialization, lifecycle observation, and the persisted
  `native_short_scope_status_v1` projection are implemented.
- Health reporting consumes the projection instead of independently joining map,
  generation, lifecycle, and candle ledgers.
- The projection keeps immutable map geometry vintage separate from current
  evaluation, source freshness, observation freshness, lifecycle, and actionability.
- `CONFIGURATION_UNAVAILABLE` is represented distinctly from source unavailability,
  source staleness, and observation overdue.
- Immutable native map rows are never mutated to simulate current freshness.
- Unchanged geometry does not publish duplicate maps or generation-heartbeat rows.
- Runtime ownership/deployment remains intentionally absent.
- Profit Plan currently requires a read-only consumer migration. Its future current
  map/freshness authority is the scope-status projection, not legacy context files
  or reporting-side candle reconstruction.

## Required architecture

Distinct layers remain separate:

```text
Immutable facts
- native_short_map_v1

Decision provenance
- native_short_map_generation_event_v1
- only real publication/rejection/decision events

Lifecycle provenance
- native_short_map_lifecycle_event_v1
- append only on actual transitions:
  ACTIVATED / COMPLETED / INVALIDATED / EXPIRED / SUPERSEDED

Operational runtime evidence
- native_short materializer run records
- per-scope materializer observations

Mutable/rebuildable current market projection
- native_short_scope_status_v1
- exactly one canonical current row per SUPPORTED scope
```

Reporting/UI consumes `native_short_scope_status_v1` for current-map resolution and
freshness/status facts. It must not independently join map/event ledgers or use
candles to create a second current-state authority.

## Required semantics

The canonical scope-status projection separates:

```text
map geometry vintage
latest materializer evaluation
current source freshness
map lifecycle state
market-only actionability state
```

A normal unchanged-geometry evaluation:

```text
evaluates persisted 4h/1h candles
records operational observation evidence
retains the immutable map unchanged
rebuilds scope status
emits no duplicate map
mutates no map timestamp
emits no generation-event heartbeat
```

A normal evaluation can append one real terminal lifecycle event when canonical
market evidence proves completion or invalidation.

## Persistent cadence contract

Expected evaluation cadence and grace are persisted in the market-data scope/config
contract, never inferred from systemd alone.

The contract distinguishes:

```text
CONFIGURATION_UNAVAILABLE
CURRENT_EVALUATION
OBSERVATION_OVERDUE
SOURCE_STALE
SOURCE_UNAVAILABLE
SCOPE_RECENTLY_ADDED
MAP_INVALIDATED
MAP_COMPLETED
```

`CONFIGURATION_UNAVAILABLE` is the highest-precedence state for a supported scope
without an eligible exact full-key cadence configuration at `as_of_utc`. It is never
reported as `SOURCE_UNAVAILABLE`, `SOURCE_STALE`, or `OBSERVATION_OVERDUE`.

Current source rules:

```text
primary interval: 4h
primary freshness bound: 12h
supporting interval: 1h
supporting freshness bound: 3h
```

Target cadence: after each expected persisted closed 1h candle window, with explicit
grace.

## Open tasks by priority

### P0 — Canonical status semantics

Completed:

- persistent native SHORT materializer-run records
- persistent per-scope materializer observations
- market-data cadence/grace contract
- lifecycle observation that emits real transition events only
- rebuildable `native_short_scope_status_v1` per supported scope
- health-report consumption of the projection
- tests for unchanged geometry, lifecycle transition capture, source/observation
  separation, configuration unavailable, and projection rebuild behavior

### P1 — Runtime owner deployment

Blocked on P0-A / PR #54 acceptance:

- one Odroid wrapper
- one service/timer pair
- host singleton lock plus existing per-scope DB lock
- all existing supported scopes only
- bounded and operationally readable logs
- non-blocking read-only health observation
- rollback by disabling/removing runtime owner only; never mutate ledger history

### P2 — Short Swing / Profit Plan read-only consumption

Lane B sequence:

1. Resolve current native map only from `native_short_scope_status_v1`.
2. Read immutable geometry only by projection `current_map_id` plus full scope key.
3. Use projection `current_map_cycle_id` as the canonical market-only cycle identity.
4. Replace render UUID row authority with deterministic map-level row identity.
5. Render explicit blocked/review states for missing, invalid, stale, terminal, or
   configuration-unavailable projection state.
6. Do not make level-coverage claims until a native per-map-level lifecycle read
   model supplies current `ACTIVE` / `REACHED_OR_PASSED` / `COMPLETED` / `HISTORICAL`
   state under the native evaluation clock.

The P2 consumer boundary and row-identity rules are canonicalized in:

```text
docs/architecture/native_short_scope_status_profit_plan_consumer_contract_v1.md
```

## PR decomposition

### PR A0 — Scope-status persistence contract

Completed.

### PR A1 / A1b — Persistence and configuration-unavailable representation

Completed.

### PR A2 — Materializer integration and projection

Completed.

### PR A3 — Health-report projection consumption

Completed.

### PR B — Runtime-owner deployment

Blocked. Scope:

- one Odroid wrapper
- one service/timer pair
- host singleton lock plus existing per-scope DB lock
- evaluates supported scopes only
- bounded logs
- non-blocking read-only health observation
- rollback only removes runtime ownership; it never mutates history

### PR C — Profit Plan read-only consumption

Not yet implemented. Scope:

- Profit Plan consumes scope-status projection
- projection-selected immutable native-map reference
- canonical map-cycle identity
- deterministic read-only ladder row identity
- no UI mutation, server preview, sizing, decision gate, planner, executor, or broker
  writes

Full `MISSING` / `ARMED` / `STALE` per-level coverage semantics are blocked until
native current per-level lifecycle status exists. Reporting must not approximate that
state from its own candle history.

## Historical BTC evidence

```text
Root cause: MATERIALIZER_NOT_RUNNING
BTC map_id=2 was published by one authorized market-only canary.
map_id=1 was SUPERSEDED.
BTC map_id=2 became MAP_ACTIVE and ledger health was HEALTHY immediately after publication.
```

A later health check exposed timestamp conflation. A newer 1h candle alone must not
make an unchanged immutable map stale when the configured source SLA is still met.

## Boundary

```text
market-only
account-agnostic
public persisted candle inputs only
no broker/private account calls
no broker writes
no decision_gate changes
no execution_planner changes
no executor changes
no live trading enablement
```

Safety markers:

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
```

## Non-goals

- No P0-A / PR #54 changes.
- No systemd, timer, service, wrapper, or Odroid deployment work.
- No broker/private-account calls.
- No account-snapshot/freshness orchestration changes owned by Lane A.
- No wallet/dashboard mutation path.
- No selection_engine changes.
- No decision_gate, execution_planner, or executor changes.
- No duplicate map publication for unchanged geometry.
- No manual BTC rematerialization.
- No A+, Breathline, Elliott Wave, replay, or execution work.
