# Fib-map-bound PAPER SELL fill ownership bridge v1

Issue #753 B7.6 closes the missing production composition between a truthfully
FILLED PAPER SELL execution leg and #752 strategy-owned inventory reduction.

## Ownership boundaries

- `execution_planner` owns the immutable SELL intent only.
- `executor` owns placement, resting-order reconciliation, and `ACTIVE -> FILLED`.
- `decision_gate` owns exact-lineage reduction authorization and #752 fill reconciliation.
- `orchestration` sequences those reviewed seams and adds no policy.

Canonical path:

```text
FibMapBoundExitPlanV1
-> existing PAPER handoff
-> shared PAPER placement ACTIVE
-> later strict price-through FILLED
-> executor FILLED-leg cumulative evidence
-> decision_gate exact-lineage SELL authorization
-> #752 reconciliation fact + optional SELL inventory event
```

The bridge never uses wallet balance as strategy ownership, never mutates an
execution leg directly, and never enables LIVE/private-broker authority.

## Replay and safety

A newly placed ACTIVE leg cannot fill in the same invocation. Only a leg that
was already ACTIVE before the submission call may be reconciled. Exact snapshot
replay returns the prior reconciliation fact and emits no duplicate inventory
event. Before a non-zero SELL delta is returned, decision_gate authorizes that
exact delta against the current persisted #752 lineage quantity, so the bridge
cannot over-reduce or cross-sell another strategy bucket.

Safety markers: `broker_private_calls=0`, `broker_writes=0`, `live_orders=0`,
`wallet_balance_sell_authority=0`, `production_runtime_activation=0`.
