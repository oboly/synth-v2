# Fib-Map-Bound Exit Execution Handoff V1 (Issue #753 Phase B3)

## Purpose

Phase B3 connects the typed map-bound exit decision (#753 Phase B2,
`src/decision_gate/fib_map_bound_exit_decision_v1.py`) to execution intent
and order transport, without collapsing any layer boundary. It reuses the
existing `automatic_exit_planner_v1` (#392) pattern and the shared #206
executor handoff contract instead of introducing a parallel SELL stack.

## New modules

```text
src/execution_planner/fib_map_bound_exit_planner_v1.py
    decision + binding + venue context -> immutable FibMapBoundExitPlanV1

src/execution_planner/fib_map_bound_exit_execution_handoff_adapter_v1.py
    FibMapBoundExitPlanV1 -> shared ApprovedExecutionPlanV1 (#206)
    + deterministic plan_reference_id derivation

src/execution_planner/fib_map_bound_exit_execution_handoff_application_v1.py
    composes the adapter with the shared ExecutionHandoffRepositoryV1.intake
    / .intake_live_authorized methods (#206); re-exports the existing
    side-neutral resolve_automatic_exit_executor_mode_v1 mapping instead of
    duplicating it
```

## Flow

```text
FibMapBoundExitDecisionV1 (B2, decision_gate)
  + FibMapBoundTradeV1 (immutable binding, #766)
  + VenueExecutionConstraints
-> build_fib_map_bound_exit_plan_v1()          (execution_planner, this module)
-> adapt_fib_map_bound_exit_plan_to_approved_execution_plan_v1()
-> submit_fib_map_bound_exit_plan_to_execution_handoff_v1()
-> ExecutionHandoffRepositoryV1.intake / intake_live_authorized (#206, executor)
```

`execution_planner` never re-evaluates exit policy, never re-derives target
price or decision quantity, and never infers ownership from broker wallet
balance -- `decision.decision_quantity_base` and `decision.target_price` are
taken exactly as decided by B2. It performs venue-aware rounding and
structural validation only, exactly like `automatic_exit_planner_v1` (#392).

`executor` (via the shared #206 `ExecutionHandoffRepositoryV1`) remains the
sole owner of order handling, LIVE authority checks, credential scope, and
kill-switch enforcement. Nothing in this slice pre-checks or duplicates
those substrate responsibilities.

## Quantity and lineage guarantees

- A `PARTIAL_PROFIT_TARGET` decision plans exactly the decided bounded rung
  quantity (`decision.decision_quantity_base`), never the full remaining
  owned quantity.
- A `PROTECTIVE_EXIT` decision plans exactly the full remaining owned
  quantity the decision already computed.
- `trading_account_id`, `venue`, `market`, `strategy_bucket_id`,
  `strategy_id`, `strategy_version`, and `trade_id` propagate unchanged from
  the binding into the plan and then into the handoff identity payload, so
  exact strategy/trade lineage survives end to end.
- Rounding can only ever reduce planned quantity toward venue step size,
  never push it above `decision.decision_quantity_base`
  (`PLANNED_QUANTITY_EXCEEDS_DECISION_QUANTITY` fails closed otherwise).

## Determinism / replay safety

`derive_fib_map_bound_exit_plan_reference_id_v1` hashes a canonical payload
that includes `binding_id`, `decision_id`, `decision_state`, full lineage
identity, and exact leg price/quantity, but excludes wall-clock
`planning_ts_utc`. Duplicate evaluation of the exact same decision (retry,
process restart) always derives the same `plan_reference_id`, so it resolves
to the same handoff row via the shared #206 repository's existing
identity-conflict/dedup path instead of creating a duplicate executable
handoff. Any change to lineage, binding, decision identity/state, or leg
price/quantity changes the id, so two logically distinct decisions -- even
with numerically identical SELL legs -- never collide.

## Fail-closed behavior

The planner (`FibMapBoundExitPlanningError`) and adapter
(`FibMapBoundExitPlanAdapterError`) reject with a stable machine
`reason_code` instead of guessing on:

- non-actionable decision states (`NO_ACTION`, `FAIL_CLOSED`) or a
  non-`OK` `reason_code` (`DECISION_NOT_ACTIONABLE`,
  `DECISION_REASON_NOT_OK`)
- a structurally invalid binding (`BINDING_INVALID`)
- decision/binding identity mismatch (`DECISION_BINDING_IDENTITY_MISMATCH`)
- invalid decision quantity/target price
  (`DECISION_QUANTITY_INVALID`, `DECISION_TARGET_PRICE_INVALID`)
- stale, missing, or mismatched venue execution constraints
  (`VENUE_CONSTRAINTS_TIMESTAMP_STALE_OR_FUTURE`,
  `VENUE_CONSTRAINTS_IDENTITY_MISMATCH`, `VENUE_CONSTRAINTS_INVALID`)
- venue capability gaps (`VENUE_LIMIT_ORDER_UNSUPPORTED`,
  `VENUE_GTC_UNSUPPORTED`)
- a malformed or ambiguous plan reaching the adapter (`PLAN_SIDE_NOT_SELL`,
  `PLAN_LEGS_EMPTY`, `PLAN_LEGS_NOT_SINGLE_LEG`,
  `PLAN_LEG_QUANTITY_SUM_MISMATCH`, `PLAN_IDENTITY_FIELD_EMPTY`, etc.)
- an unsupported executor mode at the application seam
  (`UNSUPPORTED_EXECUTOR_MODE`)

## Layer boundaries respected

```text
fib_map_bound_exit_decision_v1  -> typed exit decision only (#753 B2, decision_gate)
fib_map_bound_exit_planner_v1   -> execution intent (this module, execution_planner)
...adapter/...application_v1    -> translation + shared handoff selection (execution_planner)
ExecutionHandoffRepositoryV1    -> order transport, LIVE authority, kill switch (#206, executor)
```

No fabrication of `automatic_exit_profile_v1`, no reuse of the #707/#723
promotion policy, no `selection_engine` changes. `decision_gate` is not
bypassed: only an already-produced `FibMapBoundExitDecisionV1` is consumed,
never re-derived.

## Safety markers

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
live_authority_changes=0
production_runtime_activation=0
```

Repository/PAPER only. LIVE handoff still requires the shared #206
`intake_live_authorized` path to independently pass credential binding,
LIVE authority, and kill-switch checks; nothing in this slice grants or
short-circuits that.
