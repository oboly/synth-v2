# Manual Execution Ladder P0 Round 2 — Independent Enforcement Review

## Review identity

```text
HOST: devlap
MODEL: GPT-5 Codex
EFFORT: high
ROLE: reviewer
THREAD: CLEAR
REPOSITORY / WORKTREE: /home/gurk/projects/synth-v2
BRANCH: agent/canonical-agent-orchestration-contract-v1
BASE SHA: d15cb5f99768bed570a26e9e2f91d434a72d6684
HEAD SHA: d15cb5f99768bed570a26e9e2f91d434a72d6684
DEPLOYMENT PERMISSION: not granted
RUNTIME MUTATION PERMISSION: not granted
DB WRITE PERMISSION: not granted
BROKER / PRIVATE API PERMISSION: not granted
```

Review date: 2026-07-26.

Working-tree state reviewed: uncommitted. `HEAD` equals the supplied base SHA;
all implementation under review is in the working tree.

## Verdict

```text
BLOCK_REJECT
```

Round 1 and Round 2 are not enforced end to end.

Decisive P0 failures:

1. A caller can construct `ManualExecutionApproval` with the exported canonical
   token and call the planner with the exported caller-token string. The tests
   themselves construct the accepted approval this way.
2. `build_execution_plan_preview()` and its CLI still accept
   `intent_type=PLACE_PASSIVE_LIMIT`, `side=SELL`, caller quantity, caller
   decision state, caller tick size, and no canonical approval. An independent
   CLI probe produced a `PASSIVE_EXIT` plan for caller quantity `999`.
3. The legacy sell-only PAPER chain remains callable and can write an approved
   sell intent, a sell plan, and executor-preview lifecycle transitions without
   the canonical request, service, gate approval, or reservation.
4. The production transaction does not establish the claimed MariaDB
   concurrency guarantee. A plain idempotency `SELECT` occurs before the row
   lock. Under MariaDB/InnoDB's default REPEATABLE READ behavior, that can
   establish a snapshot which later plain reservation-total reads continue to
   use after waiting for the lock. A competing committed reservation can
   therefore be invisible to the waiter.
5. No approval is persisted. Only the reservation is inserted. Retry creates a
   new approval timestamp/expiry, discards the original snapshot identity, and
   accepts any existing reservation state.
6. The intended canonical service has no producer and cannot produce a ladder:
   `QUANTITY_POLICY_LADDER_LEVELS` is the only path selecting `EXIT_LADDER`, but
   decision_gate rejects that policy before planning.
7. Pair, snapshot, reservation, venue-constraint version, and provenance
   bindings are incomplete or absent.
8. Planner rejection after reservation leaves an active reservation with no
   wired release path. The existing reconciliation method requires exactly one
   broker match even for an approved-but-never-submitted cancellation/expiry.

These failures violate the supplied merge rule independently. Passing fake-DB
and fake-lock tests cannot substitute for the missing runtime enforcement.

## Required input status

Read:

- `AGENTS.md`
- `docs/ops/agent_orchestration_contract_v1.md`
- `docs/ops/agent_search_hygiene_v1.md`
- `docs/reviews/manual_execution_ladder_p0_remediation_implementation_20260726.md`
- every changed source, script, migration, and test file listed below
- relevant pre-existing P0, planner, executor, ladder, rounding, venue, and
  reservation tests and runtime dependencies

Evidence gap:

- `docs/reviews/manual_execution_ladder_p0_implementation_review_20260725.md`
  is absent from the working tree, the supplied base commit, and reachable Git
  history. It could not be reviewed. The remediation document and multiple
  source comments cite a file that is not present.
- This gap does not soften the verdict because the review mission supplied the
  complete enforcement criteria, and the active code paths independently
  demonstrate P0 failures.

## Changed-file inventory reviewed

### Documentation

- `docs/architecture/manual_execution_ladder_future_readiness_audit_v1.md`
- `docs/todo/README.md`
- `docs/todo/manual_execution_ladder_future_readiness_backlog_v1.md`
- `docs/reviews/manual_execution_ladder_p0_remediation_implementation_20260726.md`

### Migrations

- `db/migrations/20260726_manual_execution_request_v1.sql`
- `db/migrations/20260726_manual_execution_atomic_approval_v1.sql`

### Source and scripts

- `scripts/trade_place_limit_sell_order_ladders_from_csv.py`
- `src/decision_gate/free_base_quantity_v1.py`
- `src/decision_gate/manual_execution_gate_v1.py`
- `src/decision_gate/run_sell_only_decision_gate_preview_v1.py`
- `src/decision_gate/sell_reservation_v1.py`
- `src/execution/limit_sell_ladder_v1.py`
- `src/execution_ladder/resolver.py`
- `src/execution_ladder/run_ladder_profile_preview_v1.py`
- `src/execution_planner/contract_preview_v1.py`
- `src/execution_planner/run_execution_planner_contract_preview_v1.py`
- `src/execution_planner/run_sell_only_execution_plan_preview_v1.py`
- `src/executor/run_sell_only_paper_executor_preview_v1.py`
- `src/manual_execution/__init__.py`
- `src/manual_execution/manual_execution_request_v1.py`
- `src/manual_execution/manual_execution_service_v1.py`

### Tests

- `tests/test_manual_execution_atomic_approval_v1.py`
- `tests/test_manual_execution_gate_v1.py`
- `tests/test_manual_execution_request_v1.py`
- `tests/test_manual_execution_service_v1.py`

Working-tree files under review: 25. This review document is not counted as
implementation under review.

## Runtime call graph

### Intended canonical graph

```text
producer
  -> build_manual_execution_request()
  -> manual_execution_service_v1.process()
     -> ManualExecutionRequestRepository.create_request_idempotent()
     -> caller-supplied VenueExecutionConstraints.status check
     -> ManualExecutionGateRepository.approve_and_reserve()
        -> plain idempotency SELECT
        -> INSERT IGNORE lock row
        -> SELECT lock row FOR UPDATE
        -> plain account/snapshot/reservation reads
        -> evaluate_manual_execution_request()
        -> execution_sell_reservation INSERT
        -> in-memory ManualExecutionApproval
     -> request_id comparison
     -> contract_preview_v1.build_execution_plan_preview()
     -> separate request-state UPDATE
  -> ManualExecutionOutcome
```

No production producer imports or calls `manual_execution_service_v1.process()`.
The graph is callable in isolation but not wired to an operator CLI, UI, or
runtime.

The canonical ladder subgraph is unreachable:

```text
request.quantity_policy == LADDER_LEVELS
  -> service chooses EXIT_LADDER
  -> gate rejects LADDER_LEVELS as QUANTITY_POLICY_NOT_YET_SUPPORTED
  -> planner never runs
```

### Active competing graph: contract preview alias

```text
operator CLI or direct caller
  -> ExecutionIntentPreview(
       intent_type=PLACE_PASSIVE_LIMIT,
       side=SELL,
       quantity_base=<caller>,
       decision_state=<caller>)
  -> build_execution_plan_preview()
     -> manual approval guard is skipped
     -> PASSIVE_EXIT / PREVIEW_ONLY plan
```

Independent command result: exit `0`, plan type `PASSIVE_EXIT`, source decision
state `EXECUTION_ALLOWED`, source reason `CALLER_SUPPLIED`, and plan quantity
`999`.

### Active competing graph: sell-only PAPER chain

```text
run_sell_only_decision_gate_preview_v1
  --approve-paper-preview --write-db
  -> latest account_position_snapshot.available_quantity_base
  -> caller request_fraction
  -> execution_sell_intent(intent_state=APPROVED)

run_sell_only_execution_plan_preview_v1 --write-db
  -> reads approved execution_sell_intent
  -> execution_sell_plan(plan_state=PLANNED)

run_sell_only_paper_executor_preview_v1 --write-db
  -> PLANNED -> READY_TO_SUBMIT -> SUBMITTED -> FILLED
```

This chain performs operational PAPER DB writes without the new request,
approval, reservation, freshness rule, or canonical planner. Comments calling
it non-authoritative do not block execution.

### Other callable SELL/PAPER graphs

```text
run_ladder_profile_preview_v1
  -> raw resolve_ladder_preview()
  -> display-only raw ladder

build_limit_sell_ladder_orders(available_qty=<caller>)
  -> BitvavoOrderRequest objects
  -> preview
  -> place_limit_sell_ladder_orders() hard-fails

exit_policy_v1
  -> build_exit_plan_from_position()
  -> PAPER execution plan without the new manual reservation
  -> execute_plan_paper()
  -> PAPER position close
```

The last graph is strategy/policy-driven rather than a manual ladder producer,
but it confirms the repository still has separate callable PAPER SELL planner
and executor contracts. It must remain explicitly segregated from manual
producers.

## Enforcement matrix

Each required item has exactly one classification from the supplied set.

| Item | Classification | Enforcement finding |
|---|---|---|
| canonical request parent | PARTIALLY_WIRED | Frozen type and builder exist, but the public dataclass constructor bypasses all builder validation; DB constraints do not enforce payload consistency; no producer uses it. |
| single canonical service entrypoint | IMPLEMENTED_NOT_WIRED | `process()` exists and calls the intended layers, but no producer calls it and competing active paths remain. |
| caller quantity rejection | PARTIALLY_WIRED | `EXIT_*` rejects intent quantity, but `PLACE_PASSIVE_LIMIT+SELL`, legacy PAPER planning, and the limit-sell builder accept caller quantity. |
| decision_gate-only approval | NOT_IMPLEMENTED | Exported token plus publicly constructible dataclass is forgeable; no signature, private capability, persistence lookup, or DB identity proves issuance. |
| approval binding/freshness | PARTIALLY_WIRED | Some fields are compared, but pair/request/snapshot/reservation/approved timestamp are not planner-enforced; retry renews freshness and loses snapshot identity. |
| account-derived free quantity | PARTIALLY_WIRED | Canonical repository derives it from a scoped snapshot minus reservations, but competing paths bypass it and source/symbol identity are not verified. |
| atomic SELL reservation | PARTIALLY_WIRED | A transaction and lock table exist, but approval is not persisted, MVCC visibility is unsafe, and the public reservation repository does not require the same lock. |
| idempotent retry | PARTIALLY_WIRED | Unique keys prevent a simple duplicate row, but concurrent request creation can fail, payload conflicts are not checked, service terminal-state retry fails, and approval is reissued from any reservation state. |
| planner approval enforcement | PARTIALLY_WIRED | `EXIT_*` has checks, but they are forgeable and the SELL alias plus separate planner APIs bypass them. |
| legacy bypass blocking | NOT_IMPLEMENTED | One CLI branch is blocked; the sell-only PAPER chain and multiple callable builders/planners remain behaviorally unchanged. |
| MariaDB concurrency guarantee | TEST_ONLY | Only a Python `threading.Lock` fake was exercised; no MariaDB test exists and the real SQL has a REPEATABLE READ snapshot hazard. |
| migration readiness | BLOCKED | Static syntax is plausible, but approval persistence/FKs/constraints are missing and no clean/repeat/concurrency MariaDB validation was run. |
| reconciliation ownership | IMPLEMENTED_NOT_WIRED | A state-transition method exists, but no caller owns the lifecycle and unused reservations cannot be released through the current exactly-one-broker-row precondition. |
| venue enforcement | PARTIALLY_WIRED | Only caller-supplied `status` and `tick_size` are used; venue/market identity, quantity step, minimums, order type, TIF, provenance, and version are not enforced. |
| provenance binding | NOT_IMPLEMENTED | `provenance_id` is an unchecked nullable scalar with no FK and no runtime validation/consumption. |

No required item qualifies as `ENFORCED_END_TO_END`.

## Canonical request parent analysis

Positive evidence:

- `ManualExecutionRequest` is `frozen=True`.
- The builder omits free quantity, approval, venue constraint, and executable
  order fields.
- The builder validates supported modes, sides, and quantity-policy payloads.
- Repository writes separate content creation from request-state updates.

Enforcement failures:

- `ManualExecutionRequest` itself is a public dataclass with no `__post_init__`.
  A caller can directly instantiate it with arbitrary `request_id`,
  `schema_version`, negative IDs, unsupported state, rejection fields, or an
  internally contradictory quantity payload. The tests exercise only the
  builder.
- A caller can use `dataclasses.replace()` to construct a persisted-looking
  request; the new atomic tests do exactly this to set `request_id`.
- The service does not require `request_state == DRAFT`.
- `create_request_idempotent()` returns an existing row solely by key without
  comparing immutable content or a payload digest. Same-key/different-payload
  conflicts do not fail closed.
- The repository uses SELECT-then-INSERT without handling a concurrent unique
  conflict by re-reading and validating the winner.
- `update_request_state()` does not guard on the expected old state and does
  not verify affected-row count.
- The DB schema has enum-like checks but no checks tying quantity policy to its
  required/null payload, positive requested values, valid ladder JSON, DRAFT
  creation state, or rejection/state consistency.
- Account code, venue, asset ID, base asset, and quote asset are not resolved
  as one DB-backed identity. A request can name one `asset_id` but a different
  `base_asset`; the gate reads quantity by ID while the planner emits the
  caller's symbol.

Conclusion: immutable-by-convention, not an enforced immutable/fail-closed
parent.

## DecisionGate and approval authority analysis

Positive evidence:

- Account-aware permission and quantity calculation reside in decision_gate.
- Account flags and wallet snapshot are queried by `trading_account_id`,
  `venue`, and `asset_id`.
- Missing/stale/future/negative/contradictory wallet values and pending
  reconciliation are blocked in the pure resolver.
- Planner-side checks compare account ID, venue, asset ID, side, positive
  quantity, and expiry for `EXIT_*`.

Enforcement failures:

- `MANUAL_EXECUTION_APPROVAL_TOKEN` is exported plaintext.
- `ManualExecutionApproval` is publicly constructible. The accepted
  `test_valid_approval_is_accepted_and_drives_the_plan` approval is created by
  the test caller, not by decision_gate.
- `authorized_caller="manual_execution_service_v1"` is another caller-supplied
  plaintext string.
- Planner does not validate `request_id`, `reservation_id`,
  `wallet_snapshot_identity`, or `approved_ts_utc`.
- Approval has no pair fields. Planner accepts caller `symbol`; quote asset is
  absent from the intent.
- Approval does not bind the ladder levels, sleeve/profile, market context, or
  venue-constraint row/version used to build the plan.
- Service alone compares request ID. A direct gate call followed by a direct
  planner call bypasses that comparison.
- The retry path uses request fields for request ID/side while using reservation
  fields for account/venue/asset/quantity, without verifying that the existing
  reservation belongs to the same request or has matching symbol and state.
- Retry sets `wallet_snapshot_identity="RETRY_OF_EXISTING_RESERVATION"` and
  issues a new `approved_ts_utc` and expiry. This permits indefinite renewal
  without rechecking account flags, wallet freshness, or reservation state.
- A terminal, submitted, open, or stale existing reservation is sufficient to
  mint a new approval.

Conclusion: the approval is a data shape with a known label, not an enforceable
decision_gate capability.

## Authoritative quantity analysis

The intended calculation is correctly located:

```text
latest account_position_snapshot.available_quantity_base
- SUM(execution_sell_reservation.quantity_base
      WHERE reservation_state=APPROVED_NOT_SUBMITTED)
```

The canonical resolver also blocks while any reservation is
`SUBMITTED_AWAITING_RECONCILIATION`.

Remaining failures:

- The snapshot query selects the latest row across all `source_name` values and
  does not whitelist or otherwise authenticate the wallet source.
- The query does not select/verify the stored symbol. It constructs the
  snapshot symbol from the untrusted request.
- Equal timestamps have no deterministic ID tie-break.
- `account_code` and the requested base/quote pair are not checked against the
  account and asset rows.
- Legacy sell-only PAPER and direct planner/builder paths continue to use
  caller or separately derived quantities.
- Planner enforcement can be bypassed with `PLACE_PASSIVE_LIMIT+SELL` or a
  fabricated approval.

Conclusion: the arithmetic primitive is useful, but authoritative quantity is
not mandatory end to end.

## Transaction and locking analysis

### Actual production boundary

`db_cursor(commit=True)` opens one non-autocommit connection, executes the
idempotency read, lock-row write/lock, account/snapshot/reservation reads, and
reservation insert, then commits on context exit. Exceptions raised from the
context roll back that connection.

Request creation commits before this transaction. Request-state update occurs
in a later transaction. Plan construction occurs after the reservation
transaction has committed.

No approval row is inserted, so approval and reservation persistence are not
atomic.

### REPEATABLE READ visibility defect

The first statement is a plain `SELECT` on
`execution_sell_reservation.idempotency_key`, before acquiring the lock. The
later account, wallet, reservation `SUM`, and reconciliation `COUNT` reads are
also plain consistent reads.

MariaDB documents REPEATABLE READ as the default InnoDB isolation level and
states that all consistent reads in a transaction use the snapshot established
by the first read:
[MariaDB REPEATABLE READ](https://mariadb.com/docs/server/reference/sql-statements/transactions/transactions-repeatable-read).
`FOR UPDATE` locks the lock-table row, but it does not make unrelated later
plain reads current:
[MariaDB FOR UPDATE](https://mariadb.com/docs/server/reference/sql-statements/data-manipulation/selecting-data/for-update).

Unsafe schedule:

```text
T1: idempotency SELECT -> none
T1: acquire account/venue/asset lock
T1: read free=10
T1: insert reservation A=10

T2: idempotency SELECT -> none; establishes older read view
T2: waits for the same lock

T1: COMMIT
T2: acquires lock
T2: plain SUM uses its older consistent snapshot and can miss A
T2: reads free=10
T2: inserts reservation B=10 (different idempotency key)
T2: COMMIT
```

The Python fake always reads the current shared list after acquiring
`threading.Lock`; it cannot reproduce this database behavior.

### Lock scope and writer discipline

- Intended lock scope `(trading_account_id, venue, asset_id)` is appropriate
  for one-asset SELL availability.
- Only one such lock is acquired per request, so this function alone has no
  multi-key ordering cycle.
- `_SELL_LOCK_TIMEOUT_SECONDS` is unused. No bounded lock timeout, deadlock
  retry, or idempotent retry policy exists.
- `SellReservationRepository.create_reservation_idempotent()` remains public
  and can insert without the lock. The lock therefore serializes only callers
  that voluntarily use `approve_and_reserve()`.
- `INSERT IGNORE` can downgrade more than duplicate-key failures to warnings.
  MariaDB documents that ignored errors include foreign-key failures:
  [MariaDB IGNORE](https://mariadb.com/docs/server/reference/sql-statements/data-manipulation/inserting-loading-data/ignore).
  The code does not verify that the lock row was inserted/found before
  proceeding.
- Idempotency uniqueness prevents two committed rows with the same key, but
  it does not prevent different request keys from over-reserving one balance.
- A same-key concurrent race may surface as a unique-key exception rather than
  returning the winner because SELECT-then-INSERT is not retried.

### Rollback evidence

The production context manager does call rollback on exceptions. The new test
does not prove rollback of a partial write: its fake raises before appending the
reservation row, and the fake backend has no transaction staging/rollback
mechanism. There is no test that fails after reservation insertion and proves
the inserted row disappears.

### Planner failure window

Reservation commit precedes planner construction. Invalid ladder shape,
non-positive/fabricated fresh venue constraints, unsupported profile, rounding
failure, process crash, or request-state update failure can leave
`APPROVED_NOT_SUBMITTED` reserved indefinitely.

`reconcile_reservation_state()` requires `matching_broker_rows == 1` before any
transition, including `APPROVED_NOT_SUBMITTED -> CANCELLED|EXPIRED`. A never
submitted reservation normally has zero broker rows, so the current API cannot
release this failure case.

## Bypass inventory

| Callable path | Classification | Reason |
|---|---|---|
| `manual_execution_service_v1.process()` | ROUTED_CANONICALLY | Internally follows request -> gate -> planner, but has no production producer. |
| Contract-preview CLI with `EXIT_PASSIVE_LIMIT` or `EXIT_LADDER` | HARD_BLOCKED | Exits `2` before intent construction. |
| `build_execution_plan_preview(EXIT_*)` | STILL_BYPASSABLE | Public caller token and public approval token/dataclass can be reconstructed by any caller. |
| Contract-preview CLI/function with `PLACE_PASSIVE_LIMIT+SELL` | STILL_BYPASSABLE | Produces `PASSIVE_EXIT` from caller quantity/decision/tick with no approval; independently reproduced. |
| `ManualExecutionGateRepository.approve_and_reserve()` called directly, then planner | STILL_BYPASSABLE | Skips service request/venue checks; planner does not bind request ID. |
| `run_sell_only_decision_gate_preview_v1 -> run_sell_only_execution_plan_preview_v1 -> run_sell_only_paper_executor_preview_v1` | STILL_BYPASSABLE | Active PAPER DB-write chain uses a separate approval flag, quantity source, planner, and lifecycle. |
| `execution_ladder.resolver.resolve_ladder_preview()` | NON_AUTHORITATIVE_BUT_CALLABLE | Raw caller-quantity ladder builder; no planner/executor consumer in this path. |
| `run_ladder_profile_preview_v1` | NON_AUTHORITATIVE_BUT_CALLABLE | Read/display path, but not routed and not behaviorally blocked. |
| `build_limit_sell_ladder_orders()` | NON_AUTHORITATIVE_BUT_CALLABLE | Builds executable-shaped broker requests from caller `available_qty`; placement is separate. |
| `place_limit_sell_ladder_orders()` | HARD_BLOCKED | Always raises before broker call, including with confirmation true. |
| `trade_place_limit_sell_order_ladders_from_csv.py` | NON_AUTHORITATIVE_BUT_CALLABLE | Executes a caller-quantity order-builder preview; comments only. |
| `run_sell_intent_readonly_preview_v1` | NON_AUTHORITATIVE_BUT_CALLABLE | Read-only permission preview; accepts caller requested quantity but creates no plan/order. |
| `run_sell_permission_readonly_preview_v1` | NON_AUTHORITATIVE_BUT_CALLABLE | Read-only position permission display; creates no plan/order. |
| `execution_planner_v1.build_exit_plan_from_position()` policy PAPER exit | NON_AUTHORITATIVE_BUT_CALLABLE | Separate strategy/policy PAPER SELL path; callable and executor-consumed, not a manual ladder authority. |
| Generic `build_execution_plan()` / PAPER executor SELL mapping | NON_AUTHORITATIVE_BUT_CALLABLE | Separate decision-driven lane; must not be exposed as a manual producer. |

The inventory contains active `STILL_BYPASSABLE` paths. The merge condition is
therefore not met even without the transaction failures.

## Planner boundary analysis

For the two `EXIT_*` labels, the planner rejects missing approval, wrong token,
expired approval, account/venue/asset/side mismatch, non-positive quantity,
caller `quantity_base`, and caller `max_notional_eur`.

It does not enforce:

- gate-only construction of the approval;
- request ID;
- account code;
- base/quote pair or symbol-to-asset mapping;
- reservation existence, request ownership, quantity, or active state;
- wallet snapshot identity/version;
- approval timestamp chronology;
- original approval expiry on retry;
- venue-constraint venue/market/version/provenance;
- quantity step, minimum quantity, minimum notional, order type, or TIF;
- provenance;
- all SELL intent aliases and separate public planner APIs.

`PLACE_PASSIVE_LIMIT+SELL` is a direct alternate public API accepting
`decision_state`, raw quantity, and caller venue metadata. This is the old
authoritative shape under another accepted intent label.

## Migration review

### Static MariaDB review

The two new files use syntax compatible in shape with MariaDB 10.11:
`CREATE TABLE IF NOT EXISTS`, InnoDB, composite primary key, FKs, `CHECK`,
`DATETIME(6)`, and `ON UPDATE CURRENT_TIMESTAMP(6)`.

This was a static review only. The migrations were not parsed/applied against a
server. No schema or data was changed.

MariaDB DDL implicitly commits and is not a multi-file transaction:
[MariaDB implicit commits](https://mariadb.com/docs/server/reference/sql-statements/transactions/sql-statements-that-cause-an-implicit-commit).
Each `CREATE TABLE` is individually atomic on supported MariaDB versions, but
the two-file migration set and its dependencies are not one rollback unit.

### Request migration

Positive:

- Additive table.
- Unique idempotency key.
- FKs to account and asset.
- State/mode/side/policy checks.

Blocking gaps:

- No FK from `execution_sell_reservation.manual_execution_request_id` to the
  now-existing request parent.
- No uniqueness enforcing the claimed 1:1 request/reservation relationship.
- No approval table or persisted signed/capability record.
- No provenance FK.
- No DB constraint for quantity-policy payload consistency or positive
  requested values.
- No DB immutability trigger/guard; the comment is not enforcement.
- `CREATE TABLE IF NOT EXISTS` does not validate an existing table's shape.
- No clean-apply, repeat-apply, FK-order, or compatibility test.

### Atomic-approval migration

Positive:

- InnoDB composite primary key provides one lock row per account/venue/asset.
- FKs match the intended account/asset scope.

Blocking gaps:

- The migration creates only a lock table; it does not persist an approval.
- It does not add the missing reservation/request FK or request/reservation
  uniqueness.
- It does not force all reservation writers to participate in this lock.
- No transaction isolation contract is declared or verified.
- `INSERT IGNORE` warning behavior is not checked by runtime code.
- No disposable-MariaDB concurrency, rollback, or deadlock test exists.

Migration readiness classification: `BLOCKED`.

## Test-evidence analysis

### Tests run

```text
python -m pytest \
  tests/test_bitvavo_venue_adapter_v1.py \
  tests/test_canonical_rounding_v1.py \
  tests/test_free_base_quantity_v1.py \
  tests/test_limit_sell_ladder_v1.py \
  tests/test_manual_execution_p0_architecture_boundaries_v1.py \
  tests/test_manual_execution_p0_integration_v1.py \
  tests/test_research_provenance_v1.py \
  tests/test_sell_reservation_v1.py \
  tests/test_venue_execution_constraints_v1.py \
  tests/test_manual_execution_request_v1.py \
  tests/test_manual_execution_gate_v1.py \
  tests/test_manual_execution_service_v1.py \
  tests/test_manual_execution_atomic_approval_v1.py \
  tests/test_execution_planner_explicit_intent_v1.py \
  tests/test_executor_paper_contract_v1.py \
  tests/test_execution_ladder_profiles_v1.py \
  tests/test_execution_ladder_migration_v1.py -q

264 passed in 1.42s
```

Additional bounded checks:

- Five changed runner `--help` invocations: exit `0`.
- Contract-preview `EXIT_LADDER` CLI guard: exit `2`, blocked.
- Contract-preview `PLACE_PASSIVE_LIMIT+SELL` CLI exploit: exit `0`, caller
  quantity and decision accepted into a `PASSIVE_EXIT` plan.

### What the tests prove

- Builder validation works when callers voluntarily use the builder.
- Frozen request/state-transition value behavior works in pure Python.
- Free-quantity arithmetic and stale/contradictory input checks work.
- Account-scoped fake repository reads have the expected query shapes.
- `EXIT_*` rejects omitted/wrongly-labelled/mismatched approval data.
- The service does not call the planner on selected blocked outcomes.
- Canonical price rounding and isolated venue constraint utilities work.
- Direct broker placement in `limit_sell_ladder_v1` remains hard-blocked.
- Fake lock serialization produces one winner when the fake always exposes
  current committed list state.

### What the tests mock away

- MariaDB isolation/read-view behavior.
- Real row/gap/unique/FK locks.
- Real commit and rollback after a partial write.
- Concurrent request INSERT uniqueness handling.
- Approval persistence, because none exists.
- Trusted venue-constraint resolution; fixtures construct `status=FRESH`.
- Trusted approval issuance; tests construct approvals directly with the
  exported valid token.
- Request/pair/snapshot/reservation/provenance binding.
- A real service producer.
- Reconciliation cleanup after plan failure.

### Missing negative tests

- Direct `ManualExecutionRequest(...)` invalid construction.
- Same idempotency key with changed immutable payload.
- Two concurrent `create_request_idempotent()` calls.
- Reprocessing a persisted terminal request state.
- Valid public token used in a caller-fabricated approval as an attack case.
- `PLACE_PASSIVE_LIMIT+SELL` caller quantity/decision bypass.
- Approval request ID mismatch at the planner itself.
- Symbol/base/quote mismatch against asset ID.
- Venue-constraint venue/market mismatch and caller-fabricated fresh status.
- Snapshot identity missing/changed/untrusted source.
- Approval with future `approved_ts_utc`, inconsistent expiry, or renewed
  retry expiry.
- Existing reservation in terminal/submitted/open state used to mint approval.
- Existing reservation belonging to another request.
- Failure after reservation INSERT proving real rollback.
- Planner failure releasing the reservation.
- Canonical `LADDER_LEVELS` request reaching an `EXIT_LADDER` plan.
- Two-connection MariaDB race at the production isolation level.
- Lock timeout/deadlock retry.
- A noncanonical reservation writer racing the canonical lock.

The architecture test also checks only the older account-aware modules in the
selection import deny-list; it does not include the new manual gate/service.
Its reservation writer scan looks for `UPDATE`, not all unauthorized
`INSERT` paths or lock participation.

## Architecture findings

Positive:

- `selection_engine` remains market-only in the reviewed tree.
- Account quantity and permission logic were added under `decision_gate`.
- The new service does not submit broker orders.
- `contract_preview_v1` remains preview-only.
- Direct limit-sell broker placement remains hard-blocked.
- No live permission was added.

Violations/gaps:

- The active sell-only PAPER chain bypasses the new canonical layers and writes
  intent/plan/lifecycle state.
- Approval trust is implemented as caller-known labels rather than an
  enforceable gate capability.
- Planner accepts a separate raw-quantity SELL alias.
- Service trusts caller-created venue constraints and does not enforce the
  complete venue contract.
- Reconciliation has no wired owner, and executor-preview lifecycle writes are
  separate from reservation lifecycle truth.
- The service/gate/request repositories use the legacy `src.common.db` wrapper,
  whose own module contract says PAPER runtimes must use explicit
  `db_env_v1`/`db_core_v1` loading instead of implicit `.env` behavior.
- Documentation is internally stale: the changed architecture section says
  atomic reservation remains open, while Round 2 claims it implemented; the
  cited rejection document is absent.

No selection-to-account or research-to-execution leakage was found in the
changed source.

## Required fixes before merge

1. Make every manual SELL planner entry label fail closed unless it carries an
   enforceable gate capability. Include `PLACE_PASSIVE_LIMIT+SELL`, all
   compatibility wrappers, and all CLI paths; do not key authority only on the
   `EXIT_*` spelling.
2. Replace public string tokens and caller-constructible approval authority
   with a structurally or cryptographically verifiable gate-issued capability.
   Persist the approval or a verifiable approval record and validate it at the
   planner boundary.
3. Bind and validate request ID, trading account, account identity, venue,
   canonical market/pair, asset ID/symbol, side, approved quantity, reservation
   ID/state, snapshot ID/version, original approval timestamp/expiry, venue
   constraint identity/version, and provenance where supplied.
4. Add request validation that cannot be bypassed by direct dataclass
   construction or DB reload. Require DRAFT input at service entry. Reject
   same-key/different-payload retries and handle concurrent unique winners
   idempotently.
5. Wire the actual manual producer(s) only through
   `manual_execution_service_v1.process()`. Hard-block or remove the legacy
   sell-only PAPER write chain from manual use before merge.
6. Make a canonical `LADDER_LEVELS` request reach the gate and planner without
   accepting caller-authoritative quantity. Add an end-to-end positive ladder
   test.
7. Resolve venue constraints inside a trusted adapter/repository boundary or
   verify the supplied record against request venue/market and freshness
   provenance. Enforce step, minimum quantity/notional, order type, and TIF for
   every leg.
8. Acquire the account/venue/asset lock before any consistent read that can
   establish a stale view. Use locking/current reads or an explicit validated
   isolation contract for account, snapshot, and active reservations. Make all
   reservation writers use the same lock/capability.
9. Verify lock-row acquisition; do not let broad `INSERT IGNORE` warnings
   silently remove the lock. Implement bounded lock timeout, deadlock handling,
   deterministic lock ordering, and safe retry.
10. Persist approval and reservation in the same transaction. Add the
    reservation/request FK and the required uniqueness constraints.
11. Preserve original approval/snapshot/expiry on retry. Validate all existing
    reservation fields and active state. Never renew authority from terminal,
    submitted, open, mismatched, or expired state.
12. Provide reconciliation-owned cleanup for plan rejection/crash and make
    unused `APPROVED_NOT_SUBMITTED` reservations releasable with zero broker
    matches. Wire and test that owner.
13. Add clean/repeat migration validation and two-connection concurrency,
    rollback-after-insert, idempotency, lock-timeout, and deadlock tests against
    disposable MariaDB 10.11 using the production cursor path.
14. Bind provenance with an FK and runtime validation, or remove the field and
    claim until the binding is implemented.
15. Restore the original rejection document or remove/repair all broken
    canonical references, and reconcile the stale architecture/TODO status.

## Separate authorization gates

### MariaDB validation gate

```text
AUTHORIZED=false
STATUS=BLOCKED
```

No migration application or real-DB test was authorized or performed. This gate
requires the fixes above plus disposable-MariaDB clean/repeat migration,
two-connection concurrency, rollback, idempotency, lock timeout, and deadlock
evidence.

### Odroid PAPER preview gate

```text
AUTHORIZED=false
STATUS=BLOCKED
```

Do not deploy or activate this working tree on Odroid. Required first:
`MERGE_ACCEPT` review after P0 fixes, MariaDB gate success, exact runtime owner
verification, no duplicate writer, migration/change authorization, and bounded
PAPER-only preflight with safety markers.

### Live authorization gate

```text
LIVE_AUTHORIZATION_ALLOWED=false
STATUS=NOT_GRANTED
```

No live trading, broker private calls, broker writes, order submission,
executor activation, credential change, or permission change is authorized by
this review.

## Final verdict and safety record

```text
VERDICT=BLOCK_REJECT
WORKING_TREE_REVIEWED=true
CODE_MODIFIED=false
REVIEW_DOCUMENT_CREATED=true
MIGRATIONS_APPLIED=false
DB_WRITES=false
PRIVATE_BROKER_CALLS=false
BROKER_WRITES=false
ORDER_SUBMISSION=false
PUSHED=false
MERGED=false
ODROID_PAPER_PREVIEW_AUTHORIZED=false
LIVE_AUTHORIZATION_ALLOWED=false
```
