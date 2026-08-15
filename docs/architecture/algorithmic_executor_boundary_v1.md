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
`RECONCILIATION_REQUIRED`. The canonical shared reconciliation path may later
resolve either `SUBMISSION_UNCERTAIN` or `RECONCILIATION_REQUIRED` when an
authoritative lookup finds the original order. `RECONCILIATION_REQUIRED` to
`PREPARED` remains forbidden. There is no rearm, no automatic second POST, and
no delete path. Both BUY and SELL use the same submission orchestrator,
Bitvavo adapter, and reconciliation implementation.

If a concurrent authoritative absence lookup reaches
`RECONCILIATION_REQUIRED` while the original placement call is still in
flight, that state wins over the late placement acknowledgement. A later
authoritative lookup may still resolve the original order; it can never rearm
the leg or create a second POST.

## Bitvavo adapter boundary

The dormant adapter preserves the immutable executor market, side, price,
quantity, client order ID, and operator ID in a passive limit/post-only order.
It performs a fresh exact TRADE_EXECUTION credential-scope resolution for the
handoff account, venue, executor identity, runtime owner, and binding ID before
each private operation. The merged intake still denies LIVE, and this adapter
does not grant LIVE authority or activate a runtime.

The current Bitvavo REST order statuses map as follows:

- `new` and `awaitingTrigger` -> `ACTIVE`
- `partiallyFilled` -> `PARTIALLY_FILLED`
- `filled` -> `FILLED`
- `canceled` -> `CANCELED`
- `expired` -> `EXPIRED`

Missing or unknown status is `AMBIGUOUS` and fails closed. An `orderId` alone
never proves an active order. Bitvavo's `restatementReason`, including
`cancelPostOnly`, is audit provenance only: it does not create an executor
state or change `canceled` from `CANCELED`. Reconciliation uses Get Order with
the deterministic `clientOrderId`; authoritative absence never causes a POST.

The mapping follows Bitvavo's current official [Create Order][create-order],
[Get Order][get-order], and [order lifecycle][order-lifecycle] documentation.

[create-order]: https://docs.bitvavo.com/docs/rest-api/create-order/
[get-order]: https://docs.bitvavo.com/docs/rest-api/get-order/
[order-lifecycle]: https://docs.bitvavo.com/docs/order-lifecycle/

Rescue commit `10eba297` is a historical donor only and is not part of this
branch, its ancestry, or its architecture authority.
