# TODO — Native SHORT Current Map-Level Status V1

## Status

B0 contract accepted and merged via PR #68.

Current slice:

```text
feat: add native short map level status persistence or projection
```

This slice adds only:

```text
- rebuildable current table definition
- pure validation/type contract
- persistence/import-boundary tests
```

It intentionally does not add a materializer, candle evaluator, runner hook, UI
consumer, or order-related behavior.

Canonical contract:

```text
docs/architecture/native_short_map_level_status_contract_v1.md
```

## Goal

Provide a rebuildable, market-only current level-status read model for the
projection-selected native SHORT map:

```text
native_short_scope_status_v1
-> current_map_id / current_map_cycle_id
-> native_short_map_level_status_v1
-> later Short Swing read-only consumption
```

## Approved V1 Boundary

V1 covers only named immutable extension SELL levels:

```text
SELL_EXT_1_272
SELL_EXT_1_618
SELL_EXT_2_000
```

V1 uses explicit, closed 4h candle semantics:

```text
ACTIVE  = no high reaches the level
REACHED = high reaches level; no closed 4h candle closes above it
PASSED  = at least one closed 4h candle closes above it
```

`COMPLETED` remains a canonical map-terminal fact, not a synonym for touch.
`HISTORICAL` is used for selected invalidated/expired map context.

## Blocked / Out Of Scope

No contract currently exists for lifecycle semantics of:

```text
BUY_RELOAD_R382
BUY_RELOAD_R500
BUY_RELOAD_R618
BUY_RELOAD_R786
BREAKOUT_GATE
INVALIDATION
```

Do not introduce their current-state semantics in reporting or under an
implementation convenience heuristic. A separate native contract is required.

## Implementation PR Sequence

1. `docs: define native short current map level status contract`
   - status: merged as PR #68

2. `feat: add native short map level status persistence or projection`
   - status: current slice
   - migration/model types only
   - one rebuildable status collection
   - no runner integration

3. `feat: materialize current native short map level status`
   - pure lifecycle evaluator
   - MariaDB reader/writer
   - use existing explicit scope-status `projection_as_of_utc`
   - no scheduler/deployment change

4. `test: cover native short map level lifecycle read model`
   - deterministic identities
   - active/reached/passed/completed/historical
   - projection fail-closed and configuration distinction
   - import boundaries and immutable-ledger non-mutation

## Non-Goals

```text
no Profit Plan resolver migration
no reporting/UI work
no account/order snapshot work
no broker calls or writes
no order submission
no decision_gate/execution_planner/executor changes
no systemd/timer/service/wrapper/Odroid deployment
no selection_engine change
```
