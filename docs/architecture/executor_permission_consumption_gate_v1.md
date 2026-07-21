# Executor Permission Consumption Gate V1

Status: repaired draft pending independent review

## Ownership

Credentials authenticate broker requests. They never authorize execution.

The canonical flow is:

```text
decision_gate audit/result
-> decision_gate_permission_evidence
-> execution_plan permission foreign key
-> execution_attempt atomic claim
-> executor broker handling
```

`selection_engine` remains market-only and account-agnostic. `decision_gate` owns account-aware permission. `execution_planner` owns explicit intent and binds one plan to one permission record. `executor` validates and consumes those exact records; it does not infer intent, side, permission, or strategy policy.

## Permission Producer

The canonical producer is `src/decision_gate/permission_evidence_v1.py::DecisionGatePermissionRepository`. `create_permission` writes an explicitly allowed LIVE `decision_gate_audit_log` row and its immutable `decision_gate_permission_evidence` row in one transaction.

The producer signs the complete permission scope with an Ed25519 private key supplied only as `SYNTH_DECISION_GATE_EVIDENCE_PRIVATE_KEY_B64`. The executor verifies with `SYNTH_DECISION_GATE_EVIDENCE_PUBLIC_KEY_B64`; the public verifier cannot mint evidence. A row inserted manually without a valid canonical signature fails closed even if its relational fields look valid.

Every accepted permission has a non-null, unique audit foreign key and exact audit/evidence agreement for trading account, venue, asset, market, intent, action, side, permission state, decision state, and LIVE mode.

## Planner Binding

LIVE `execution_plan` rows persist all of:

- `trading_account_id`
- `decision_gate_permission_evidence_id`
- `execution_intent`
- `action_type`
- `requested_side`
- `market`
- `execution_mode=LIVE`
- a finite `valid_until_ts_utc`

The planner validates the exact permission ID and scope before insert or promotion. `execution_plan.account_id` remains the legacy portfolio account identity and is never interpreted as `trading_account_id`. Missing explicit fields, blank intent or side, lowercase values, and legacy unbound plans fail closed for LIVE execution.

## Paper And Live

Persisted plan mode owns routing. A `PAPER` plan always follows paper handling even when the worker is globally armed for live operation. It does not query permission evidence, construct trade credentials or a private broker client, place or cancel orders, or poll authenticated orders. Paper monitoring uses the public-only client in `src/market_data/bitvavo_public_client_v1.py`.

A `LIVE` plan requires the global worker arm plus every relational authorization gate. Neither worker mode nor permission evidence can convert `PAPER` to `LIVE`. Lowercase legacy plan modes are not accepted as LIVE; the migration only normalizes historical lowercase `paper` to `PAPER`.

## Atomic Claim

`ExecutionPermissionRepository.claim_live_action` starts a database transaction and locks the exact execution plan, bound evidence, audit row, trading account, and prior attempt. Inside that transaction it revalidates:

- plan mode, actionable state, and expiry
- exact plan/evidence/account identity and scope
- canonical BUY or SELL side and action type
- signed decision-gate provenance and allowed audit outcome
- active, current, non-revoked, non-superseded evidence
- enabled account and `live_trading_enabled=true`
- exact live-execution and broker-write environment grants
- absence of any earlier attempt for the plan/action

The transaction inserts `execution_attempt` in `CLAIMED`, records the authorization snapshot, and conditionally moves the plan to `SUBMISSION_CLAIMED`. That commit is the authorization-consumption boundary. No database transaction remains open during the exchange call. Revocation after commit cannot authorize another claim and does not erase the committed snapshot.

The database unique key on `(execution_plan_id, action_type)` prevents concurrent or later duplicate attempts. The attempt stores a deterministic idempotency key and stable Bitvavo `clientOrderId` before the network call. A confirmed call moves to `CONFIRMED`. An indeterminate network result moves to `UNCERTAIN` and is never automatically submitted again; broker reconciliation is required. Pre-call client construction failure moves to `FAILED` without a broker call.

Only initial claimed `PLACE_ORDER` is implemented. LIVE cancellation, reprice, escalation, and authenticated monitoring are deliberately fail-closed in this version. Direct ladder placement remains disabled; ladder construction and preview remain available.

## Side And Action

Planner side and permission side must be exactly `BUY` or `SELL`. The executor passes that validated planner value unchanged to `BitvavoOrderRequest`; only the Bitvavo adapter maps the canonical enum to the exchange's lowercase wire value. There is no BUY default and no derivation from `execution_intent` or `desired_action`.

`PLACE_ORDER`, `CANCEL_ORDER`, and `MONITOR_ORDER` are distinct stored action scopes. This version exposes a broker mutation only for claimed `PLACE_ORDER`; the other actions cannot reuse the placement path.

## Revocation And Supersession

The decision-gate repository owns create, revoke, and supersede operations. The database enforces lifecycle combinations. MariaDB does not permit its `AUTO_INCREMENT` evidence ID in a `CHECK`, so the repository rejects self-supersession before SQL and the executor repeats that defensive rejection. The repository locks both evidence rows, requires an ACTIVE source and a different ACTIVE successor with identical scope, and performs the transition.

## Enforcement Layers

Database enforcement covers non-null provenance, foreign keys, canonical stored values, permission windows, lifecycle combinations, one evidence per audit, one plan per evidence, and one attempt per plan/action. Self-supersession is repository-enforced and executor-validated because MariaDB forbids `AUTO_INCREMENT` columns in checks.

Repository enforcement covers the decision-gate-only producer transaction, signed immutable scope, ACTIVE-only revoke/supersede transitions, exact planner binding, row locking, conditional claim transition, and attempt completion transitions.

Executor defensive validation repeats exact audit/evidence/plan/account scope, mode, state, time, signature, environment grants, and canonical action/side checks at claim time.

## Migration Upgrade

`20260721_executor_permission_evidence_v1.sql` creates the canonical v2 evidence and attempt tables, adds explicit plan binding columns, and is idempotent after success. It repairs compatible missing indexes, constraints, foreign keys, and an empty nullable audit-provenance column. It validates critical column types, FK targets, and claim uniqueness. Incompatible partial tables or provenance-null rows fail with an `EPE_MIGRATION_*` error and require manual repair; the migration does not drop data.

The earlier draft `execution_permission_evidence` table and its historical rows are preserved for audit but are never queried by the executor. They cannot authorize execution.

## Non-Goals

Account-to-trade-credential resolution remains PR B2. This PR does not apply the migration, enable live trading, deploy services, or call an exchange.
