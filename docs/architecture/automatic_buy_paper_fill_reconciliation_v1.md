# Automatic BUY PAPER Fill Reconciliation Bridge V1 (Issue #753 Phase B5)

## Purpose

Closes gap 3 of `docs/status/issue_753_paper_acceptance_blocker_v1.md` --
"No code creates a `StrategyOwnedInventoryEventV1` from a BUY fill" -- and
resolves the RE_ENTER lineage-continuity decision Phase B4 explicitly
deferred (`docs/architecture/automatic_buy_trade_lineage_identity_v1.md`,
"Explicitly deferred: RE_ENTER lineage continuity").

This phase does **not** add a `fib_map_bound_trade_v1` repository (B6), does
not build the exact-path PAPER acceptance harness (B8), and -- see "What
remains blocked" below -- does not build a PAPER order-placement adapter.

## What changed

- `src/decision_gate/automatic_buy_fill_reconciliation_v1.py` (new, pure) --
  `AutomaticBuyFillPlanIdentityV1` (the exact lineage #770 bridged onto
  `AutomaticBuyPlanV1`: trading_account_id, venue, market,
  strategy_bucket_id, strategy_id, strategy_version, genesis trade_id, plus
  the execution-plan/broker-order identity), `resolve_automatic_buy_fill_lineage_v1`
  (RE_ENTER continuity resolution, below), and
  `reconcile_automatic_buy_paper_fill_v1` (resolves lineage, then calls
  #752's unchanged `reconcile_cumulative_fill_v1`).
- `src/decision_gate/automatic_buy_fill_reconciliation_persistence_v1.py`
  (new) -- thin DB wiring: `reconcile_and_persist_automatic_buy_paper_fill_v1`
  loads prior facts/events through the existing, unchanged #752 repositories
  (`strategy_owned_fill_reconciliation_repository_v1`,
  `strategy_owned_inventory_repository_v1`), calls the pure reconciliation
  above, and persists the resulting fact (always) and inventory event (only
  when the fill produced a positive delta). No new tables, no new
  reconciliation rule.
- `tests/automatic_buy_account_allocation_evidence_fixtures_v1.py` -- added
  the `strategy_owned_fill_reconciliation_fact_v1` sqlite table (mirrors
  `db/migrations/20260906_strategy_owned_fill_reconciliation_v1.sql`) to the
  shared fixture; that table had no test coverage before this phase.

## RE_ENTER lineage-continuity contract (V1)

`resolve_automatic_buy_fill_lineage_v1` decides, at the one point in the
system that actually has DB-backed inventory state, whether an accepted
automatic-BUY decision's fresh genesis `trade_id` (bound by the planner per
B4, DB-free) should instead continue an already-open strategy-owned
position:

- Project prior `StrategyOwnedInventoryEventV1` rows via #752's own
  `project_strategy_owned_inventory_v1`.
- Filter to positions matching the exact (trading_account_id, venue, market,
  strategy_bucket_id, strategy_id, strategy_version) lineage with
  `owned_base_quantity > 0`.
- Zero matches -> use the planner's genesis `trade_id` (first ENTER, or a
  RE_ENTER after a full prior exit -- a genuinely new lineage).
- Exactly one match -> reuse that position's `trade_id` (a RE_ENTER adding to
  an still-open position -- the same conceptual trade continues).
- More than one match -> fail closed
  (`AMBIGUOUS_OPEN_STRATEGY_OWNED_POSITION`). Correct accounting should never
  produce two simultaneously open positions under one exact lineage; this is
  not assumed safe by construction.

This never merges two lineages that do not share the full
(strategy_bucket_id, strategy_id, strategy_version) key -- a manual fill or a
different strategy's fill can never absorb or be absorbed by an automatic-BUY
position, even in the same account/venue/market (see the unrelated-fill test
in `tests/test_automatic_buy_fill_reconciliation_v1.py`).

## What remains blocked

Wiring this bridge to a real trigger requires a real
`BrokerCumulativeFillEvidenceV1` for an automatic-BUY PAPER order. That
evidence does not exist anywhere in reviewed code today:

- The shared executor handoff path automatic-BUY plans flow through
  (`src/executor/execution_handoff_v1.py`,
  `src/executor/shared_execution_consumer_v1.py`,
  `src/executor/execution_submission_orchestrator_v1.py`) only produces an
  order-placement acknowledgement (`OrderAckV1`: ACTIVE/PARTIALLY_FILLED/
  FILLED/etc.) via an injected `OrderPlacementAdapter`. `ExecutionLegV1`
  itself carries no fill-quantity field.
- `src/executor/shared_execution_runtime_v1.py` explicitly and intentionally
  raises `SharedExecutorModeAdapterUnavailableError("PAPER_ADAPTER_NOT_CONFIGURED")`
  for `executor_mode == PAPER` -- a reviewed, tested guard
  (`tests/test_shared_execution_runtime_v1.py`), not an oversight: "PAPER and
  LIVE remain valid persisted handoff modes, but each requires a separately
  authorized, truthful adapter; they never fall back to a synthetic or test
  adapter."
- The canonical fill-quantity read authority for the shared handoff path,
  `account_open_order_snapshot`, is populated only by the real
  wallet-refresh job against a real broker
  (`src/executor/manual_execution_submission_leg_reconciliation_v1.py`
  documents this explicitly for the analogous SELL reconciliation seam). No
  broker exists for a PAPER account, so this table never gains rows for a
  PAPER automatic-BUY order.
- The legacy per-plan PAPER simulator (`src/executor/repository.py`'s
  `fill_passive_plan_paper`, used by the old `execution_plan_id`-based
  `executor_v1.execute_plan_paper`) is a different, unrelated execution path;
  no automatic-BUY code creates a legacy `execution_plan` row, and wiring
  automatic-BUY onto that older path instead of the shared handoff path B3/B4
  already use would itself be an undocumented architecture change.

Deciding what a "truthful" PAPER order-placement adapter does (fill
instantly at the plan's limit price on ack? read latest market price the way
the legacy simulator does? simulate partial fills over time based on
book-crossing?) is a genuine, consequential, unresolved architectural
decision -- not settled by any existing merged contract for this path.
Fabricating an answer here, or quietly reviving the legacy per-plan PAPER
path for automatic-BUY specifically, would be exactly the invented shortcut
the task contract prohibits. This phase stops at the reconciliation bridge
and documents the gap instead.

## Layer boundaries respected

```text
execution_planner / executor -> unchanged; still no strategy/ownership logic
decision_gate                -> owns this reconciliation bridge (new files),
                                 exactly like #752's own reconciliation module
```

## Safety markers

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=extended (new pure reconciliation bridge + DB wiring)
execution_planner=unchanged
executor=unchanged
production_runtime_activation=0
```

## Next slice

A PAPER order-placement adapter for the shared executor handoff path is a
prerequisite for any real invocation of this bridge (and therefore for B8,
the exact-path PAPER acceptance harness). That decision is out of scope here
and should be its own reviewed slice. Independently, B6
(`fib_map_bound_trade_v1` repository) and B7 (binding adapter) remain next
per `docs/status/issue_753_paper_acceptance_blocker_v1.md`'s original
sequencing and do not depend on the PAPER adapter gap above.
