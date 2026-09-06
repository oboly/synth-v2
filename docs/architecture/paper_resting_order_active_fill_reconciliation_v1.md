# PAPER Resting-Order ACTIVE -> FILLED Reconciliation V1 (Issue #753 Phase B7.5)

## Purpose

Closes the gap `docs/architecture/automatic_buy_paper_order_placement_adapter_v1.md`
(B5.5) explicitly deferred and
`docs/status/issue_753_paper_acceptance_blocker_v1.md` names as the remaining
B8 blocker: B5.5's `PaperOrderPlacementAdapterV1` is submission-time-only and
never itself returns `FILLED` for a non-crossing post-only order -- there was
no later reconciliation path for a resting `ACTIVE` PAPER leg anywhere in the
shared executor. This phase adds exactly that one missing transition and
nothing else.

This phase does **not**:

- change B5.5's placement-time contract (a crossed post-only order is still
  `REJECTED`, never fabricated as filled);
- build B8's exact-path PAPER acceptance harness (that remains the next,
  separate phase, now technically runnable -- see "Status" below);
- write to or mutate `executor_paper_order_placement`, which remains
  immutable placement-ack history;
- simulate partial fills, queue position, or any broker/network/live path;
- change `decision_gate`, `execution_planner`, or LIVE composition.

## What changed

- `src/executor/paper_resting_order_reconciliation_v1.py` (new) --
  `reconcile_paper_resting_leg_v1(leg, *, quote_provider, max_quote_age_seconds,
  now_fn, leg_repository)`: given one caller-supplied, already-persisted
  `ExecutionLegV1` and the existing `PaperMarketQuoteProviderV1` evidence
  seam (reused verbatim from B5.5), deterministically decides full-fill-on-
  touch:
  - BUY fills when `best_ask <= price`.
  - SELL fills when `best_bid >= price`.
  - A non-touching quote returns the leg unchanged (still `ACTIVE`); no write.
  - An already-`FILLED` leg is returned unchanged without ever consulting the
    quote provider -- idempotent replay never re-validates evidence for a
    leg that is already resolved.
  - Any leg not in `ACTIVE`/`FILLED` raises
    `PaperRestingLegNotReconcilableError`.
  - Missing, malformed, market-mismatched, future-dated, or stale evidence
    raises the existing `PaperMarketEvidenceUnavailableError` -- this module
    imports and reuses B5.5's own quote-validation helpers so the two paths
    can never silently diverge on what counts as valid evidence.
- `src/executor/execution_leg_v1.py` -- one new guarded repository method,
  `ExecutionLegRepositoryV1.mark_active_filled_on_touch(leg_id, *,
  broker_raw_status)`. Guarded CAS: `UPDATE ... WHERE state='ACTIVE'`,
  writing `state='FILLED'`, the new `broker_raw_status`, and
  `last_reconciled_ts_utc`; `broker_order_id` and `restatement_reason` are
  never written by this statement, so they are preserved verbatim. Replaying
  an already-`FILLED` leg is idempotent; any other current state raises
  `ExecutionLegConflictError`. No schema or trigger change was needed: the
  existing `trg_eel_immutable` trigger (from
  `db/migrations/20260815_executor_reconciliation_evidence_v1.sql`) already
  permits `ACTIVE -> FILLED`.
- `src/entry_policy/automatic_buy_paper_fill_execution_v1.py` -- before its
  existing FILLED-leg -> #752 bridge loop, an `ACTIVE` leg found for the
  current handoff is first passed through
  `reconcile_paper_resting_leg_v1` using the same `quote_provider`/
  `max_quote_age_seconds`/`now_fn` this function already receives. This makes
  a *second* invocation of `submit_and_reconcile_automatic_buy_paper_plan_v1`
  for the same plan/handoff the place a resting automatic-BUY PAPER order
  actually reaches `FILLED` and gets bridged into #752 ownership, with no new
  public entry point.
- `tests/test_paper_resting_order_reconciliation_v1.py` (new) -- BUY/SELL
  touch and no-touch (including exact-threshold equality), replay
  idempotency without a quote-provider call, non-`ACTIVE`/`FILLED` leg
  rejection, all six B5.5-shaped fail-closed evidence cases, and a
  no-broker/network import guard.
- `tests/test_automatic_buy_paper_fill_execution_v1.py` -- added
  `MemoryLegRepository.mark_active_filled_on_touch` and one new wiring test:
  first invocation rests `ACTIVE`, second invocation (fresh touching quote)
  reconciles to `FILLED` and bridges exactly one ownership event, third
  invocation replays idempotently with no duplicate placement or ownership
  delta.

No existing test's assertions changed; `PaperOrderPlacementAdapterV1`,
`PaperOrderPlacementRepositoryV1`, the shared submission orchestrator, and
B5.5's crossed-post-only-is-`REJECTED` behavior are all unchanged and still
covered by their existing tests.

## Why this composes in `executor`, not `entry_policy` or `decision_gate`

`ExecutionLegV1` state and its guarded transitions are executor-owned; B7.5
adds one more guarded transition (`ACTIVE -> FILLED`) to the same repository
that already owns every other transition, exactly like B5.5's adapter and
the shared submission orchestrator do. `entry_policy`
(`automatic_buy_paper_fill_execution_v1.py`) only *composes* this new
executor-owned function -- it does not implement fill semantics itself,
matching the same division B5.5 already established (executor decides
market-truth outcomes; entry_policy decides which plan/handoff/legs to run
that decision against and bridges the result to #752).

## Layer boundaries respected

```text
executor           -> extended: one new guarded state transition + one new
                       reconciliation function; no strategy/ownership logic
decision_gate       -> unchanged; only its existing public B5 bridge is called
execution_planner   -> unchanged
entry_policy        -> extended composition only (which legs to reconcile,
                        when); no new fill semantics of its own
```

## Status

B7.5 makes B8's exact-path PAPER acceptance harness **technically runnable**:
a real automatic-BUY PAPER order can now reach `FILLED` end-to-end (rest on
first submission, reconcile to `FILLED` on a later invocation with a
touching quote), which is the exact real fill B7
(`fib_map_bound_trade_first_fill_binding_adapter_v1.py`) needs to exercise on
B8. **B8 is not accepted by this phase.** Whether the harness's exact
end-to-end path actually passes -- real handoff -> real placement -> real
resting -> real reconciliation -> real #752 event -> real B7 binding, wired
together as one exercised path rather than as independently-tested units --
remains to be built and run as B8 itself. See
`docs/status/issue_753_paper_acceptance_blocker_v1.md` for the updated
status.

## Safety markers

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=unchanged
execution_planner=unchanged
executor=extended (new guarded ACTIVE->FILLED transition + new resting-order
reconciliation function only; executor_paper_order_placement unchanged/
immutable; existing schema trigger already permitted this transition)
production_runtime_activation=0
paper_adapter_not_configured_guard=unchanged (shared_execution_runtime_v1.py)
```
