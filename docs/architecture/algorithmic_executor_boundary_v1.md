# Algorithmic executor boundary v1

The SELL lane in #392 and BUY lane in #399 converge only at the shared
`src/executor/` substrate. Both must provide a frozen `ApprovedExecutionPlanV1`
after their own decision-gate permission and execution-planner work. The
executor performs no selection, strategy, sizing, allocation, or account
permission decision.

Ordinary intake permits `DRY_RUN` and `PAPER` only; `LIVE` is denied. The same
canonical handoff repository has one explicit LIVE-authorized
intake method. It requires current operational LIVE authority before it may
persist `executor_mode=LIVE` into the existing `executor_execution_handoff`
table. Both intake forms preserve the same immutable identity, credential
binding, duplicate, and idempotency rules; there is no second handoff table or
executor path.

A credential binding is resolved for the exact account, venue, executor
identity and runtime owner; it must be ACTIVE, TRADE_EXECUTION, order-write
enabled and withdrawal disabled. The binding contains metadata, not LIVE
authority, and operational authority contains no credential. Both are required.

Before a placement adapter call, the executor persists `SUBMISSION_UNCERTAIN`.
Each persisted leg binds immutable handoff, leg, account, venue, market, side,
client-order, operator, price, and quantity identity.
An ambiguous result remains uncertain; an order not resolvable by the venue's
Get Order operation becomes `RECONCILIATION_REQUIRED`. The canonical shared reconciliation path may later
resolve either `SUBMISSION_UNCERTAIN` or `RECONCILIATION_REQUIRED` when an
authoritative lookup finds the original order. `RECONCILIATION_REQUIRED` to
`PREPARED` remains forbidden. There is no rearm, no automatic second POST, and
no delete path. Both BUY and SELL use the same submission orchestrator,
Bitvavo adapter, and reconciliation implementation.

If a concurrent not-resolvable Get Order result reaches
`RECONCILIATION_REQUIRED` while the original placement call is still in
flight, that state wins over the late placement acknowledgement. A later
authoritative lookup may still resolve the original order; it can never rearm
the leg or create a second POST.

## Bitvavo adapter boundary

The dormant adapter first verifies every supplied handoff identity field
against the canonical persisted `executor_execution_handoff` row. A non-null
handoff ID alone is not persistence proof. A missing or mismatched row fails
closed before credential loading, client construction, or a private operation.
This persisted-identity check is not LIVE authority.
The adapter then preserves the immutable executor market, side, price,
quantity, client order ID, and operator ID in a passive limit/post-only order.
It performs a fresh exact TRADE_EXECUTION credential-scope resolution for the
handoff account, venue, executor identity, runtime owner, and binding ID before
each private operation. It then performs the canonical composed LIVE-authority
check before credential decryption, private-client construction, or a broker
operation. The authority identity comes only from the canonical handoff; only
the authority grant's market field may use the defined wildcard semantics.

## Operational LIVE authority

The executor's LIVE authority answers only whether an exact account, venue,
side, optional market, executor identity, and runtime owner may submit LIVE at
the current time. It is deny-by-default, finite, and revocable. Grants are
immutable, last no longer than seven days, and are revoked by separate
append-only facts. Exact-market authority deterministically overrides wildcard
market authority; overlapping matches at the selected specificity fail closed.

The global kill switch is an append-only event stream. Its latest monotonic
event ID is authoritative, an engaged state overrides every grant, and a
disengaged state never grants authority. Read failures in either repository
fail closed.

This operational gate does not repeat or interpret strategy or account-risk
permission. The #410/#318 account protections remain solely owned by
`decision_gate`; the approved immutable plan is the upstream evidence that
those protections and planner responsibilities have already run.

The canonical private-operation order is:

```text
approved immutable plan
-> explicit LIVE-authorized canonical handoff
-> exact TRADE_EXECUTION credential binding metadata
-> fresh composed LIVE authority + global kill switch
-> credential decrypt / private-client construction
-> broker operation
-> shared reconciliation
```

Handoff creation does not guarantee later broker permission. Before every
private placement or client-order-ID lookup, the adapter re-verifies the exact
persisted LIVE handoff, freshly resolves its exact credential binding, and
freshly evaluates the composed authority gate. Expiry, revocation, ambiguity,
an engaged kill switch, or a read failure therefore denies the operation before
secret loading and the private boundary.

Repository acceptance remains non-live. This phase creates schema and dormant
code only: it creates no authority rows or credentials, applies no production
migration, activates no service or timer, and makes no broker call.

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
the deterministic `clientOrderId`; a found order is authoritative only when
market, client order ID, and side all match the handoff exactly.

Bitvavo error `404/240` means an order does not exist **or is no longer
active**. It is therefore `ORDER_NOT_RESOLVABLE_BY_GET_ORDER`, not proof that
the order was never created. From `SUBMISSION_UNCERTAIN` it leads to
`RECONCILIATION_REQUIRED`, never `PREPARED` or another POST.

The mapping follows Bitvavo's current official [Create Order][create-order],
[Get Order][get-order], and [order lifecycle][order-lifecycle] documentation.

[create-order]: https://docs.bitvavo.com/docs/rest-api/create-order/
[get-order]: https://docs.bitvavo.com/docs/rest-api/get-order/
[order-lifecycle]: https://docs.bitvavo.com/docs/order-lifecycle/

Rescue commit `10eba297` is a historical donor only and is not part of this
branch, its ancestry, or its architecture authority.
