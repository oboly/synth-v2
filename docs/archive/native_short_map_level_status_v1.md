# Native SHORT Current Map-Level Status V1 — Historical Record

Archived from `docs/todo/native_short_map_level_status_v1.md` in Batch 6F
(`docs/development/docs_todo_archive_remove_batch_6f_v1.md`). Canonical
contract lives at
`docs/architecture/native_short_map_level_status_contract_v1.md`; this file
is historical record only, not current operational authority.

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
docs/archive/profit_plan_target_lifecycle_history_truth_v1.md
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

## Addendum (2026-07-31): Companion append-only target-event ledger

The V1 current-projection contract and status above are unchanged and remain
`done / parked`; this is not a reopening. A separate, additive companion
ledger, `native_short_map_level_target_event_v1`, now records append-only
REACHED/PASSED transitions for the same V1 SELL roles, prospectively only,
under a distinct authorization (Synth Outcome & Reliability Program). See
`docs/architecture/native_short_map_level_status_contract_v1.md` addendum and
`docs/archive/profit_plan_target_lifecycle_history_truth_v1.md` addendum for the
full contract and the explicit statement that no canonical BTC/IOST
regression evidence exists or is implied by this work.

The existing `native_short_map_level_status_v1` read model, its materializer,
and its runner are unchanged when the new optional
`--target-event-coverage-watermark-utc` flag is omitted (the default).

### Correction (2026-07-31, same day)

Independent cross-provider review found the first pass's per-run watermark
check insufficient (a candle predating publication or the watermark could
still evidence a transition) and found the terminal (`COMPLETED`) transition
path could lose the final target event to a race with the scope-status
writer. Both are fixed: coverage is now durable, persisted, per-map state
with an immutable causal cutoff
(`native_short_map_level_target_event_coverage_v1`), and
`native_short_scope_status_materializer_v1.evaluate_scope` now appends any
final target events for a map before recording its terminal lifecycle event,
in the same transaction. See the architecture doc addendum for the full
corrected contract. This V1 current-projection contract's own status and
reopen criteria above remain unaffected.
