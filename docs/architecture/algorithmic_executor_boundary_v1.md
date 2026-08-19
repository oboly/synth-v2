# Algorithmic executor boundary v1

The SELL lane in #392 and BUY lane in #399 converge only at the shared
`src/executor/` substrate. Both must provide a frozen `ApprovedExecutionPlanV1`
after their own decision-gate permission and execution-planner work. The
executor performs no selection, strategy, sizing, allocation, or account
permission decision.

Callers never select `executor_mode` freely. Normal `executor_mode` is derived
exclusively from the canonical account_mode that produced the approved plan
(`paper` -> `PAPER`, `live` -> `LIVE`); the only permitted explicit override is
`DRY_RUN`, a non-production acceptance/testing override only, never a
production execution mode.

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

## #392 -> #206 automatic-exit handoff adapter boundary

`src/execution_planner/automatic_exit_execution_handoff_adapter_v1.py` is
the sole deliberate import boundary between Issue #392's automatic-exit
planner output (`AutomaticExitPlanV1`) and this document's shared handoff
contract (`ApprovedExecutionPlanV1` / `ExecutionHandoffRepositoryV1`). It is
a pure function: no re-evaluation of exit policy, no re-run of
`decision_gate`, no quantity/price recompute or re-rounding, no broker,
credential, LIVE-authority, or kill-switch inspection, and no order
submission. `src/executor` core modules stay unaware of `AutomaticExitPlanV1`.

`plan_reference_id` is derived deterministically from the plan's full
logical identity (account/position/venue/asset/market/side, REDUCE vs EXIT
action, evidence id, exit profile id/version, gate approval provenance,
planner version, and every leg's exact index/side/price/quantity), excluding
only the wall-clock planning timestamp. This is deliberate: `ApprovedExecutionPlanV1.content_hash`
is side-neutral order-mechanics identity only and does not by itself
distinguish REDUCE from EXIT or carry #392 evidence provenance, so
`plan_reference_id` — which the content hash also covers — must carry that
distinction, or two logically different approved plans that happen to
produce numerically identical legs could otherwise collide under #206's
`(plan_source, plan_reference_id)` handoff idempotency.

`automatic_exit_execution_handoff_application_v1.py` composes the adapter
with `ExecutionHandoffRepositoryV1`: DRY_RUN/PAPER route through `.intake`,
LIVE routes through `.intake_live_authorized`. It never pre-checks or
duplicates credential-scope, LIVE-authority, or kill-switch decisions —
those remain exclusively owned by `ExecutionHandoffRepositoryV1` as
described above. Reaching a `decision_gate`-`APPROVED` LIVE candidate is not,
by itself, executor operational LIVE authority.

The runner's normal executor mode is derived exclusively from the account's
own `account_mode` (`paper` -> `PAPER`, `live` -> `LIVE`) via
`resolve_automatic_exit_executor_mode_v1`. The **only** permitted explicit
override is `DRY_RUN` — a deliberate non-production acceptance/testing mode
— enforced both by the CLI's restricted `--executor-mode` choices and,
defensively, inside `run_cycle_with_handoff` itself for any direct Python
caller. `PAPER` and `LIVE` are never valid override values: allowing either
would let executor mode contradict the account_mode/decision_gate path that
actually produced the approved plan (for example, a paper account's plan
reaching `intake_live_authorized`, or a live account's plan reaching
ordinary `PAPER` intake). No override, including `DRY_RUN`, bypasses gate
evaluation itself — a plan only reaches the handoff seam at all once
`decision_gate` has already approved it under the account's real
`account_mode`.

`src/exit_policy/run_automatic_exit_policy_with_handoff_once_v1.py` is the
composition-root runner that wires the real #392 candidate ->
account-protection -> gate -> planner path to this seam. It consumes only
the in-memory `AutomaticExitPlanV1` (`RuntimeItemOutcomeV1.plan`) produced in
the same evaluation cycle. The append-only `automatic_exit_evaluation_audit_v1`
audit table is never read as executor input by this runner or by any other
module — it remains audit/replay evidence only. The pre-existing,
audit-only `run_automatic_exit_policy_once_v1.py` runner is unchanged and
remains architecturally guarded against importing `src.executor`
(`tests/test_automatic_exit_runtime_architecture_guards_v1.py`).

This adapter does not activate LIVE trading, provision credentials, grant
executor operational LIVE authority, or submit broker orders by itself.
