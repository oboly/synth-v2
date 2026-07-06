# TODO — Native SHORT Runtime Owner And Scope Status V1

## Status

queued / PR A may proceed in parallel; PR B blocked on P0-A

## Sequencing / P0-A dependency

- PR A — native-map status semantics may proceed in parallel with P0-A because it has no wrapper, timer, service, systemd, broker, or production deployment action.
- PR B — runtime-owner deployment is blocked until P0-A / PR #54 is merged and its bounded logging plus disk/log health containment is accepted.
- Do not deploy any recurring native SHORT runtime, wrapper, service, or timer before PR B is unblocked.
- PR C remains dependent on PR A.

## Sources

- Source: agreed runtime-owner plan from recent chat, canonicalized here.
- `docs/ops/native_short_map_materializer_canary_v1.md`
- `docs/ops/native_short_map_ledger_health_report_v1.md`
- `docs/research/native_short_map_ledger_population_audit_v1.md`
- `src/market_data/native_short_map_materializer_v1.py`
- `src/market_data/run_native_short_map_materializer_v1.py`
- `src/market_data/native_short_map_lifecycle_v1.py`
- `db/migrations/20260626_native_short_map_lifecycle_v1.sql`

## Purpose

Define the durable market-only runtime lane that evaluates native SHORT maps from
persisted public candles, observes lifecycle transitions, and exposes one
rebuildable current scope-status projection for reporting/UI.

## Current state / facts

- The existing native SHORT materializer runner is market-only and reusable.
- The current ledger contract has no explicit runtime wrapper or scheduler owner.
- Immutable native map rows must never have source timestamps mutated to simulate
  freshness.
- Unchanged geometry must not publish duplicate maps.
- Generation and lifecycle ledgers must not be overloaded with hourly heartbeat
  rows.
- Current reporting and health semantics currently risk conflating immutable map
  geometry vintage with current evaluation freshness.
- A map may remain structurally active while its real lifecycle has not been
  recently observed; that is a user-facing correctness risk.

## Required architecture

Distinct layers must remain separate:

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

Mutable/rebuildable market projection
- native_short_scope_status_v1
- one canonical current row per SUPPORTED scope
```

The UI and reporting layer must consume `native_short_scope_status_v1`. It must
not independently join map/event ledgers or invent its own freshness rules.

## Required semantics

The canonical scope-status projection must separate:

```text
map geometry vintage
latest materializer evaluation
current source freshness
map lifecycle state
actionability state
```

A normal unchanged-geometry evaluation must:

```text
evaluate current persisted 4h/1h candles
record operational observation evidence
retain existing immutable map unchanged
update/rebuild scope status
not emit a duplicate map
not mutate map timestamps
not emit a generation-event heartbeat
```

A normal evaluation must also observe the current active map for terminal
lifecycle transitions. If target completion, invalidation, or expiry occurs, the
runtime appends exactly one lifecycle event even when geometry remains unchanged.

## Persistent cadence contract

Expected evaluation cadence and grace must be persisted in a market-data
scope/configuration contract. They must not be inferred only from systemd.

The contract must distinguish:

```text
CURRENT_EVALUATION
OBSERVATION_OVERDUE
SOURCE_STALE
SOURCE_UNAVAILABLE
SCOPE_RECENTLY_ADDED
SCOPE_NOT_APPLICABLE
MAP_INVALIDATED
MAP_COMPLETED
```

Current source rules:

```text
primary interval: 4h
primary freshness bound: 12h
supporting interval: 1h
supporting freshness bound: 3h
```

Target cadence: once after each expected closed 1h candle persistence window,
with explicit grace.

## Open tasks by priority

### P0 — Canonical status semantics

- Add persistent native SHORT materializer run records.
- Add persistent per-scope materializer observation records.
- Add a persistent cadence/grace contract at market-data scope level.
- Add lifecycle observation logic that emits only real transition events.
- Add rebuildable `native_short_scope_status_v1` with one canonical current row
  per `SUPPORTED` scope.
- Correct health reporting to consume `native_short_scope_status_v1` instead of
  inferring freshness from immutable map timestamps.
- Add tests for unchanged-geometry evaluations, lifecycle transition capture,
  stale/overdue/source-unavailable separation, and projection rebuild behavior.

### P1 — Runtime owner deployment

- Add one Odroid wrapper for the native SHORT runtime owner.
- Add one service/timer pair for the wrapper.
- Use a host singleton lock plus the existing per-scope DB lock.
- Evaluate all existing `SUPPORTED` scopes only.
- Keep logs bounded and operationally readable.
- Support non-blocking, read-only health observation.
- Roll back by disabling or removing the runtime owner only; never mutate ledger
  history.

### P2 — Profit Plan read-only consumption

- Make Profit Plan consume `native_short_scope_status_v1`.
- Resolve the active native-map reference from the projection.
- Use deterministic ladder IDs derived from the resolved current reference.

## PR decomposition

### PR A — Native-map status semantics

- persistent run and per-scope observation model
- persistent cadence contract
- lifecycle observer
- rebuildable `native_short_scope_status_v1`
- health-report correction to consume projection
- tests
- no systemd or wrapper deployment

### PR B — Runtime owner deployment

- one Odroid wrapper
- one service/timer pair
- host singleton lock plus existing per-scope DB lock
- evaluates all existing `SUPPORTED` scopes only
- bounded logs
- non-blocking read-only health observation
- rollback by disabling/removing owner, never mutating ledger history

### PR C — Profit Plan read-only consumption

- Profit Plan consumes scope-status projection
- resolved native-map reference
- deterministic ladder IDs
- no UI mutation, server preview, sizing, decision gate, planner, executor, or
  broker writes

## Current BTC evidence

Historical evidence to preserve:

```text
Root cause: MATERIALIZER_NOT_RUNNING
BTC map_id=2 was published by one authorized market-only canary.
map_id=1 was SUPERSEDED.
BTC map_id=2 became MAP_ACTIVE and ledger health was HEALTHY immediately after publication.
```

Additional historical evidence:

- A later health check exposed the current report's timestamp-conflation problem.
- A newer 1h candle by itself must not make an unchanged immutable map stale
  when no source-SLA breach exists.

## Blockers / dependencies

- PR A depends on agreeing the canonical scope/config cadence contract and
  projection shape before any runtime owner is deployed.
- PR B depends on PR A landing first; runtime ownership must not ship before the
  projection semantics exist.
- PR C depends on PR A; Profit Plan must read the projection instead of joining
  ledgers directly.

## Boundary

- market-only
- account-agnostic
- public persisted candle inputs only
- no broker/private account calls
- no broker writes
- no wallet/dashboard/UI changes in PR A or PR B
- no decision_gate changes
- no execution_planner changes
- no executor changes
- no live trading enablement

Safety markers for this lane:

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
- No broker/private account calls.
- No wallet/dashboard/UI changes in PR A or PR B.
- No automatic scope seeding.
- No duplicate map publication for unchanged geometry.
- No manual BTC rematerialization.
- No A+, Breathline, Elliott Wave, replay, or execution work.
