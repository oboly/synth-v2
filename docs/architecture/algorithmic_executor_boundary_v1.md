# Algorithmic executor boundary v1

The SELL lane in #392 and BUY lane in #399 converge only at the shared
`src/executor/` substrate. Both must provide a frozen `ApprovedExecutionPlanV1`
after their own decision-gate permission and execution-planner work. The
executor performs no selection, strategy, sizing, allocation, or account
permission decision.

Intake permits `DRY_RUN` and `PAPER` only. `LIVE` is represented in schema
vocabulary for future compatibility but is denied by application intake. A
credential binding is resolved for the exact account, venue, executor identity
and runtime owner; it must be ACTIVE, TRADE_EXECUTION, order-write enabled and
withdrawal disabled. No secret material is read or stored.

Before a placement adapter call, the executor persists `SUBMISSION_UNCERTAIN`.
Each persisted leg binds immutable handoff, leg, account, venue, market, side,
client-order, operator, price, and quantity identity.
An ambiguous result remains uncertain; a definitive no-order lookup becomes
`RECONCILIATION_REQUIRED`, a PR1 dead end. There is no rearm, no automatic
second POST, and no delete path. Adapters normalize only to the neutral ack
vocabulary; the stub is non-live.

If a concurrent authoritative absence lookup reaches
`RECONCILIATION_REQUIRED` while the original placement call is still in
flight, the dead-end state wins over any later acknowledgement. This can
require manual reconciliation, but it cannot create a second POST.

Rescue commit `10eba297` is a historical donor only and is not part of this
branch, its ancestry, or its architecture authority.
