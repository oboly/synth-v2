# TODO — Native SHORT Current Map-Level Status V1

## Status

```text
done / parked
```

The V1 contract and implementation sequence are complete.

## Canonical contract

```text
docs/architecture/native_short_map_level_status_contract_v1.md
```

## Completed scope

The rebuildable market-only current collection is implemented for the projection-selected native SHORT map:

```text
native_short_scope_status_v1
-> current_map_id / current_map_cycle_id
-> native_short_map_level_status_v1
```

V1 roles remain deliberately closed:

```text
SELL_EXT_1_272
SELL_EXT_1_618
SELL_EXT_2_000
```

Lifecycle semantics remain:

```text
ACTIVE  = no authoritative high reaches the level
REACHED = authoritative high reaches the level without the required closed-4h continuation
PASSED  = at least one authoritative closed 4h candle closes above the level
```

`COMPLETED` is a map-terminal fact. `HISTORICAL` is audit context for terminal/previous maps.

## Completion evidence

```text
PR #68 contract
PR #71 persistence and validation
PR #76 materializer
PR #77 runner
PR #81 interruption and observability follow-up
PR #79 scope-status-chain integration
PR #87 canonical runtime-owner wiring and acceptance
```

The persistence, evaluator, MariaDB adapter, runner, deterministic identities, exact-scope replacement, failure handling, tests, and runtime integration are no longer open tasks.

## Out of scope by design

No lifecycle contract was introduced for:

```text
BUY_RELOAD_R382
BUY_RELOAD_R500
BUY_RELOAD_R618
BUY_RELOAD_R786
BREAKOUT_GATE
INVALIDATION
```

A future extension requires a separate explicit native contract. Reporting must not invent those states.

## Downstream ownership

Profit Plan read-only consumption and deterministic actionable ladder identity are tracked only in:

```text
docs/todo/profit_plan_live_ladder.md
```

Target crossing/history correctness is tracked only in:

```text
docs/todo/profit_plan_target_lifecycle_history_truth_v1.md
```

## Boundary

```text
market-only
account-agnostic
no reporting/UI mutation
no broker calls or writes
no order submission
no decision_gate changes
no execution_planner changes
no executor changes
no selection_engine changes
```

## Reopen criteria

Reopen only for a demonstrated defect in persistence identity, lifecycle evaluation, exact-scope rebuild, idempotency, projection linkage, or runtime invocation.
