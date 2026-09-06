# Fib-Map-Bound Exit Decision V1 (Issue #753 Phase B2)

## Purpose

`src/decision_gate/fib_map_bound_exit_decision_v1.py` is a pure, typed
decision seam that turns an immutable Fib-map trade binding (#766,
`fib_map_bound_trade_v1.py`) plus exact strategy-owned remaining quantity
(#752, `strategy_owned_inventory_v1.py`) plus current market price evidence
into a single deterministic exit decision.

It is decision_gate-owned domain logic, not execution or order logic.

## Scope (what B2 is)

- Pure function: `evaluate_fib_map_bound_exit_decision_v1(...)`.
- No DB access, no broker calls, no LIVE authority, no runtime activation.
- No `execution_planner` or `executor` coupling of any kind.
- Caller-owned inputs only: the bound trade, the owned position snapshot,
  which target-ladder rungs were already consumed, and market price
  evidence with an observation timestamp.

## Decision semantics

- Invalidation (`current_price <= invalidation_price`) always overrides any
  unconsumed/future profit target, regardless of ladder progression.
- Targets are evaluated in the bound, validated ascending order from
  `FibMapBoundTradeV1.target_levels`; only the next unconsumed rung is ever
  actionable in one call.
- Target-ladder progression (which rungs were already realized) is supplied
  by the caller, exactly like `account_protection_evaluation` in
  `automatic_exit_gate_v1` -- this module never infers fill history itself.
- Quantity per rung is `bought_base_quantity / len(target_levels)`, capped by
  the current exact `owned_base_quantity`, so partial progression and a
  final smaller remainder both resolve to the exact owned amount.
- Zero remaining owned quantity always yields `NO_ACTION` /
  `NO_REMAINING_STRATEGY_OWNED_QUANTITY`.
- A newer or different canonical Fib map never mutates a prior decision:
  the module never fetches or resolves a binding itself, it only evaluates
  the exact `FibMapBoundTradeV1` instance supplied by the caller for that
  lineage.

## Fail-closed behavior

The module returns `STATE_FAIL_CLOSED` with a typed reason instead of
raising or guessing whenever it is given:

- a missing or non-instance binding (`MISSING_FIB_MAP_BOUND_TRADE`)
- a structurally invalid binding, e.g. bad geometry/targets
  (`INVALID_FIB_MAP_BOUND_TRADE`)
- an unrecognized target-ladder semantics version
  (`UNSUPPORTED_TARGET_LADDER_SEMANTICS_VERSION`)
- a non-monotonic target ladder (`NON_MONOTONIC_TARGET_LADDER`)
- an out-of-range or malformed progression record
  (`INVALID_TARGET_PROGRESSION_STATE`)
- a naive/missing evaluation timestamp
  (`INVALID_EVALUATION_TIMESTAMP`)
- invalid or stale market price evidence
  (`INVALID_MARKET_PRICE_EVIDENCE`, `MARKET_PRICE_EVIDENCE_STALE`)
- an owned-position snapshot whose identity does not exactly match the
  bound trade lineage (`STRATEGY_OWNERSHIP_LINEAGE_MISMATCH`) -- this is
  the no-cross-selling-across-lineages guard
- an impossible inventory state, e.g. owned exceeding bought
  (`IMPOSSIBLE_STRATEGY_INVENTORY_STATE`)

## Layer boundaries respected

```text
fib_map_bound_trade_v1        -> immutable map/trade truth (#766)
strategy_owned_inventory_v1   -> exact owned quantity (#752)
fib_map_bound_exit_decision_v1 -> typed exit decision (this module, B2)
decision_gate (account layer) -> owns account permission / ownership validation
execution_planner             -> owns execution intent (not wired in B2)
executor                      -> owns order handling (not wired in B2)
```

`decision_gate` account-permission/ownership validation, `execution_planner`
execution intent, and `executor` order handling are untouched by this
module. It does not fabricate `automatic_exit_profile_v1` and does not reuse
the #707/#723 promotion policy; it is a new, narrowly scoped decision
contract.

## Safety markers

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
live_authority_changes=0
production_runtime_activation=0
```

## Next slice (B3, not in this PR)

Wiring this decision output into `execution_planner` as execution intent
(passive/urgent/ladder plan construction) is out of scope for B2 and is
left as Phase B3. B2 intentionally stops at the pure decision seam so the
planner integration can be reviewed as its own bounded change.
