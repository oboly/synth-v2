# Issue #753 — exact-path PAPER acceptance: blocked on missing identity bridge

## Status

BLOCKED. Documenting the precise gap instead of inventing a shortcut, per task
contract and `AGENTS.md` (do not fabricate ownership from wallet balance, do
not invent parallel logic, do not revive #707/#723).

## What already composes safely (reviewed, unit-tested, no changes needed)

- B1 `src/decision_gate/fib_map_bound_trade_v1.py` — `FibMapBoundTradeV1`
  (frozen dataclass) + `validate_fib_map_bound_trade_v1` +
  `assert_fib_map_binding_set_immutable_v1`. Pure in-memory structural
  validation over caller-supplied identity/geometry.
- B2 `src/decision_gate/fib_map_bound_exit_decision_v1.py` —
  `evaluate_fib_map_bound_exit_decision_v1(binding, owned_position,
  progression, market_evidence, evaluation_ts_utc, max_price_age_seconds)`.
  Pure function; invalidation-wins-over-target and next-unconsumed-target
  semantics are already correct and tested.
- B3 `src/execution_planner/fib_map_bound_exit_planner_v1.py` +
  `fib_map_bound_exit_execution_handoff_adapter_v1.py` +
  `..._application_v1.py` — builds a single-leg SELL plan from a B2 decision,
  adapts it to the shared `ApprovedExecutionPlanV1`, and submits it through
  the same `ExecutionHandoffRepositoryV1` (`src/executor/execution_handoff_v1.py`)
  used by the BUY side. Deterministic `plan_reference_id` prevents duplicate
  handoff on replay.

The B1→B2→B3 chain, given a `FibMapBoundTradeV1` and a
`StrategyOwnedInventoryPositionV1`, already produces a correct, idempotent,
layer-respecting exit path. This part does not need new code.

## The missing bridge

There is no reviewed path from a real automatic_buy (#399) PAPER fill to the
identity that B1/B2 require. Four concrete gaps, each its own architectural
decision:

1. **`AutomaticBuyPlanV1` carries no `trade_id`.**
   `src/execution_planner/automatic_buy_planner_v1.py:126-142` — fields are
   `strategy_id`, `strategy_version`, `setup_id`, but no `trade_id`. B1's
   lineage key and B2's ownership match both require `trade_id`.

2. **`strategy_bucket_id` is computed at gate time and dropped before the
   plan.** `src/decision_gate/automatic_buy_gate_v1.py:101,198,272` —
   `strategy_bucket_id` lives on the gate's context/decision object but is
   never copied onto `AutomaticBuyPlanV1` or into
   `automatic_buy_execution_handoff_adapter_v1.py`'s payload. #752's own
   reconciliation lineage (`StrategyOwnedFillLineageV1`,
   `src/decision_gate/strategy_owned_fill_reconciliation_v1.py:23-34`)
   requires exactly this field plus `trade_id` — confirming the gap is real,
   not incidental.

3. **No code creates a `StrategyOwnedInventoryEventV1` from a BUY fill.**
   `grep -rn "StrategyOwnedInventoryEventV1("` across `src/` matches only
   inside `strategy_owned_fill_reconciliation_v1.py:165` (the #752
   reconciliation module itself, which requires the lineage from gap 1/2 as
   input) and `strategy_owned_inventory_repository_v1.py:21` (row decoding).
   Nothing under `src/execution_planner/automatic_buy_*` or
   `src/decision_gate/automatic_buy_*` calls into #752's reconciliation to
   turn a PAPER fill into an ownership event.

4. **`fib_map_bound_trade_v1` has a DB schema
   (`db/migrations/20260906_fib_map_bound_trade_v1.sql`) but zero Python
   repository.** No module reads or writes that table; the binding is
   in-memory-dataclass-only today. A restart/replay acceptance test needs a
   repository that does not yet exist.

`tests/test_fib_map_bound_trade_v1.py`'s `_binding()` helper builds
`FibMapBoundTradeV1` from hardcoded literals (`"trade-1"`, `"fill-1"`,
`"plan-1"`) — synthetic identity, not identity produced by any real
automatic_buy fill. No test file imports both `automatic_buy_*` and
`fib_map_bound_*` together (`grep` confirms zero matches either direction).

## Why this is not safe to bridge inside this bounded slice

Each gap is a production-code decision on already-merged, reviewed contracts:

- adding `trade_id` (and deciding its generation rule — new value at first
  fill vs. reuse of `setup_id`/`candidate_evidence_id`) to `AutomaticBuyPlanV1`
  and its handoff payload;
- propagating `strategy_bucket_id` through the same path;
- wiring automatic_buy's PAPER fill handling to call #752's reconciliation
  and persist a `StrategyOwnedInventoryEventV1`;
- writing a new `fib_map_bound_trade_v1` repository and deciding the
  "bind at first fill" transaction boundary against the existing unique keys
  (`uq_fib_map_bound_trade_lineage`, `uq_fib_map_bound_trade_source_fill`).

None of these choices are settled by the existing #399/#752/#753 threads.
Fabricating them here — e.g. inventing a `trade_id` convention or writing a
new adapter that silently derives ownership from a BUY plan without a
reviewed contract — would be exactly the kind of parallel/shortcut logic the
task contract prohibits, and would risk masking real ownership-attribution
bugs behind a harness that only proves synthetic identities compose (which
the existing B1/B2/B3 unit tests already prove).

## Recommended next bounded slices (for separate review/PRs)

1. `#753 B4` — add `trade_id` + `strategy_bucket_id` to `AutomaticBuyPlanV1`
   and the automatic_buy execution handoff payload; document the `trade_id`
   generation rule.
2. `#753 B5` — wire automatic_buy PAPER fill handling to #752 reconciliation
   so a real fill produces a `StrategyOwnedInventoryEventV1`.
3. `#753 B6` — add a `fib_map_bound_trade_v1` repository
   (insert-at-first-fill, load-by-lineage) matching the existing migration's
   unique keys.
4. `#753 B7` — adapter that constructs a `FibMapBoundTradeV1` from a
   strategy-owned inventory position + canonical Fib map evidence at first
   fill, using B4-B6.
5. `#753 B8` — the exact-path PAPER acceptance harness this task was asked to
   build, once B4-B7 give it a real (not fabricated) identity bridge to
   exercise.

## Safety markers

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=unchanged
execution_planner=unchanged
executor=unchanged
production_code_changed=0
```
