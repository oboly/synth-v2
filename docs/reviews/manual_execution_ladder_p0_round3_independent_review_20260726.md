# Manual Execution Ladder P0 Round 3 — Independent Enforcement Review

## Reviewed state

```text
HOST: devlap
MODEL: GPT-5 Codex
EFFORT: high
ROLE: reviewer
THREAD: CLEAR
REPOSITORY: /home/gurk/projects/synth-v2
BRANCH: agent/canonical-agent-orchestration-contract-v1
BASE SHA: d15cb5f99768bed570a26e9e2f91d434a72d6684
HEAD SHA: d15cb5f99768bed570a26e9e2f91d434a72d6684
WORKING TREE: uncommitted
DEPLOYMENT PERMISSION: not granted
RUNTIME MUTATION PERMISSION: not granted
DB WRITE PERMISSION: not granted
BROKER / PRIVATE API PERMISSION: not granted
```

Review date: 2026-07-26.

The supplied original review,
`docs/reviews/manual_execution_ladder_p0_implementation_review_20260725.md`,
is absent from the working tree, base commit, and previously inspected
reachable history. The Round 2 independent review and Round 3 implementation
evidence were available. The missing evidence does not soften this verdict:
the active callable code independently proves the blockers below.

Implementation files reviewed: all 31 changed/untracked working-tree files,
including every changed source, script, migration, and test file, plus the
pre-existing generic planner, planner repository, exit policy, PAPER cycle,
and executor dependencies reached by the independent call graph.

## Final verdict

```text
BLOCK_REJECT
```

Round 3 blocks several named legacy aliases, but it does not make the manual
service or persisted decision-gate approval the only authority accepted by
planner logic.

Decisive failures:

1. `build_manual_sell_execution_plan_preview()` accepts caller-injected
   request, approval, and planning-input repository protocols. A caller can
   publicly construct `ManualExecutionApprovalRecord`, return it from a fake
   repository, and receive a SELL plan. An independent probe produced
   `PASSIVE_EXIT`, `side=SELL`, `quantity_base=999`.
2. The planner does not verify that the resolved record's `approval_id`
   equals the supplied `approval_id`, or that the resolved request's
   `request_id` equals the supplied `request_id`. Those identity guarantees
   are delegated entirely to the injected repositories.
3. Approval freshness is caller-controlled. Both `process()` and the
   canonical planner accept `now`; an independent probe supplied a backdated
   time and successfully planned with an approval already expired at the real
   review time.
4. No production producer calls `manual_execution_service_v1.process()`.
   The canonical planner itself remains directly callable without the
   service.
5. Separate production planner paths accept caller decision state, side, and
   quantity/notional and build SELL plans without a manual request or
   persisted approval. `execution_planner_v1.build_execution_plan()` was
   independently invoked with caller `requested_side=SELL` and
   `max_notional_eur=777`; it returned a SELL plan. Its CLI and the full PAPER
   cycle can persist such plans, while `exit_policy_v1` creates a PAPER exit
   plan explicitly without a reservation.
6. The claimed 18-entry inventory is assertion data, not discovery, and
   omits the paths above, the production-importable test helper that forges
   authority, and additional callable compatibility/executor surfaces.

Each failure independently prevents all four required primary targets from
being `ENFORCED_END_TO_END`.

## Independent SELL entrypoint inventory

The inventory below was built from production imports, function signatures,
call sites, plan constructors, persistence calls, and executor consumers. It
does not rely on `SELL_ENTRYPOINT_CLASSIFICATION` in the Round 3 test.

| # | Callable path | Classification | Enforcement finding |
|---:|---|---|---|
| 1 | `manual_execution_service_v1.process` | ROUTED_CANONICALLY | Calls request persistence, gate, approval lookup, and canonical planner, but has no producer and accepts injected repositories and caller time. |
| 2 | Generic contract builder: `EXIT_PASSIVE_LIMIT` | HARD_BLOCKED | Rejects the alias before full plan construction. |
| 3 | Generic contract builder: `EXIT_LADDER` | HARD_BLOCKED | Rejects the alias before full plan construction. |
| 4 | Generic contract builder: `PLACE_PASSIVE_LIMIT + SELL` | HARD_BLOCKED | Rejects every generic `side=SELL`. |
| 5 | `_build_buy_execution_plan_preview(...SELL...)` | HARD_BLOCKED | Private full-plan helper has an explicit BUY-only check. |
| 6 | Generic contract-preview CLI with SELL/EXIT | HARD_BLOCKED | Returns 2 before constructing an intent. |
| 7 | Legacy sell-only decision runner | HARD_BLOCKED | Returns 2 before environment/DB access. |
| 8 | Legacy `insert_intent` helper | HARD_BLOCKED | Unconditional `PermissionError` precedes SQL. |
| 9 | Legacy sell-only plan runner | HARD_BLOCKED | Returns 2 before environment/DB access. |
| 10 | Legacy `insert_plan` helper | HARD_BLOCKED | Unconditional `PermissionError` precedes SQL. |
| 11 | Legacy sell-only PAPER executor runner | HARD_BLOCKED | Returns 2 before environment/DB access. |
| 12 | Legacy `update_plan_state` helper | HARD_BLOCKED | Unconditional `PermissionError` precedes SQL. |
| 13 | Legacy executor `insert_event` helper | HARD_BLOCKED | Unconditional `PermissionError` precedes SQL; omitted from the claimed inventory. |
| 14 | `resolve_ladder_preview()` with SELL profile | HARD_BLOCKED | Raises before ladder construction. |
| 15 | Ladder-profile preview runner | HARD_BLOCKED | Returns 2 before profile/DB reads. |
| 16 | `build_limit_sell_ladder_orders()` | HARD_BLOCKED | Raises before order-request construction. |
| 17 | `place_limit_sell_ladder_orders()` | HARD_BLOCKED | Always raises; no broker call. |
| 18 | CSV limit-SELL ladder script | HARD_BLOCKED | Transitively raises in the blocked builder. |
| 19 | `build_manual_sell_execution_plan_preview()` direct call | STILL_BYPASSABLE | Direct public planner; injected fake repositories can supply caller request, approval, quantity, IDs, reservation/snapshot fields, venue inputs, and time. |
| 20 | `tests.test_manual_execution_service_v1._canonical()` | STILL_BYPASSABLE | Production-importable support helper constructs fake repositories and successfully feeds a public caller-built approval record to production planner code. |
| 21 | `execution_planner_v1.build_execution_plan()` with SELL config | STILL_BYPASSABLE | Accepts caller `DecisionResult`, `decision_state`, `requested_side`, `max_notional_eur`, and reference price; returns `PlannedExecution(side=SELL)` without manual approval. |
| 22 | `execution_planner_v1.build_exit_plan_from_position()` | STILL_BYPASSABLE | Accepts caller position quantity/config and returns a PAPER SELL close plan without manual request/approval/reservation. |
| 23 | `run_execution_planner_v1.main --requested-side SELL` | STILL_BYPASSABLE | Active CLI reaches the generic planner and can persist the SELL plan with `--write-db`; no manual approval ID. |
| 24 | `run_paper_cycle_v1.main --requested-side SELL` | STILL_BYPASSABLE | Active PAPER CLI builds and persists a generic SELL plan and then invokes the PAPER executor. |
| 25 | `exit_policy_v1.run_exit_policy_v1()` | STILL_BYPASSABLE | Builds a SELL exit plan and calls `create_exit_plan_without_reservation()`. |
| 26 | `ExecutionPlannerRepository.create_exit_plan_without_reservation()` | STILL_BYPASSABLE | Public persistence compatibility path accepts a caller-provided plan and deliberately writes it without the manual reservation/approval. |
| 27 | Legacy `decide_position()` | NON_AUTHORITATIVE_BUT_CALLABLE | Produces decision data only; its legacy persistence consumer is blocked. |
| 28 | `round_ladder_preview()` | NON_AUTHORITATIVE_BUT_CALLABLE | Rounds a caller-provided preview object; does not create/persist a canonical plan. |
| 29 | `preview_limit_sell_ladder_orders()` | NON_AUTHORITATIVE_BUT_CALLABLE | Serializes caller-provided order-request objects; builder/placement are blocked. |
| 30 | `executor_v1.execute_plan_paper()` | NON_AUTHORITATIVE_BUT_CALLABLE | Executor, not planner, but it consumes separate persisted SELL/close plans and mutates PAPER lifecycle state. |
| 31 | `run_executor_v1.main()` | NON_AUTHORITATIVE_BUT_CALLABLE | PAPER executor wrapper; does not create approval or plan. |
| 32 | `run_paper_execution_runner_v1` | NON_AUTHORITATIVE_BUT_CALLABLE | PAPER executor wrapper; does not create approval or plan. |

Independent totals:

```text
SELL_ENTRYPOINTS_FOUND=32
ROUTED_CANONICALLY=1
HARD_BLOCKED=17
STILL_BYPASSABLE=8
NON_AUTHORITATIVE_BUT_CALLABLE=6
```

The implementation's claimed total of 18 is incomplete. More importantly,
it incorrectly classifies the direct canonical planner as routed through the
service even though it is a public downstream function and performs no such
routing.

## Runtime call graphs

### Intended production-persistence graph

```text
ManualExecutionRequest
  -> manual_execution_service_v1.process(now=<caller>)
     -> request_repository.create_request_idempotent()
     -> caller venue_constraints.status check
     -> gate_repository.approve_and_reserve(now=<caller>)
        -> existing-reservation SELECT
        -> lock-row INSERT IGNORE
        -> lock-row SELECT FOR UPDATE
        -> wallet/account/reservation reads
        -> reservation INSERT
        -> approval INSERT
     -> build_manual_sell_execution_plan_preview(
          request_id,
          approval_id,
          request_repository=<injected>,
          approval_repository=<injected gate repository>,
          planning_input_repository=<caller inputs wrapped by service>,
          now=<caller>)
     -> request-state UPDATE
  -> PAPER ExecutionPlanPreview
```

This graph is implemented and exercised by fakes. No CLI, UI, app, script, or
runtime producer imports/calls `process()`.

### Direct caller-forged canonical-planner graph

```text
caller constructs ManualExecutionRequest(request_id=1, ...)
caller constructs ManualExecutionApprovalRecord(
  approval_id=501,
  approved_quantity_base=999,
  internally self-consistent copied reservation/snapshot fields)
caller implements RequestReader.find_by_id() -> caller request
caller implements ApprovalReader.find_approval_by_id() -> caller approval
caller implements PlanningInputReader.resolve_for_request() -> caller context/constraints
caller selects now
  -> build_manual_sell_execution_plan_preview(...)
  -> PASSIVE_EXIT / SELL / quantity_base=999
```

No decision-gate call, database lookup, reservation insert, or service call
occurs. The planner checks the contents returned by the caller's protocols,
not their persistence provenance.

Independent DB-free probe:

```text
plan_type=PASSIVE_EXIT
side=SELL
quantity_base=999
approval_source=caller_constructed_record_via_fake_repository
```

### Caller-controlled freshness graph

```text
approval.expires_ts_utc < real review time
caller passes now < approval.expires_ts_utc
  -> planner compares expiry to caller now
  -> PASSIVE_EXIT accepted
```

Independent DB-free probe:

```text
expired_at_real_now=true
caller_backdated_now_accepted=true
plan=PASSIVE_EXIT
```

### Separate generic SELL planner graph

```text
caller DecisionResult(decision_state=EXECUTION_ALLOWED,
                      execution_intent=PLACE_PASSIVE_LIMIT)
caller ExecutionPlannerConfig(requested_side=SELL,
                              max_notional_eur=777)
  -> execution_planner_v1.build_execution_plan()
  -> PlannedExecution(side=SELL, max_notional_eur=777)
```

Independent DB-free probe:

```text
planner=execution_planner_v1.build_execution_plan
side=SELL
max_notional_eur=777
manual_service_used=false
manual_approval_id_used=false
```

Its active CLI and PAPER cycle have repository writes behind explicit CLI
flags/normal PAPER execution. Those writes were not invoked during review.

## Enforcement matrix

Each item is assigned exactly one required classification.

| Item | Classification | Finding |
|---|---|---|
| canonical request parent | PARTIALLY_WIRED | Frozen builder contract and repository exist, but the dataclass is publicly constructible, repository identity is injectable, no producer uses it, and DB content immutability is not enforced. |
| canonical service entrypoint | IMPLEMENTED_NOT_WIRED | `process()` implements the intended sequence, but no producer calls it and multiple direct SELL planner paths survive. |
| caller quantity rejection | PARTIALLY_WIRED | Named contract-preview SELL aliases reject raw quantity, but caller-built approval repositories and generic planner/config/position paths control quantity/notional. |
| decision_gate-only approval | NOT_IMPLEMENTED | The planner accepts a caller-built public approval record returned by any object satisfying a public protocol; service tests demonstrate this composition. |
| approval binding/freshness | PARTIALLY_WIRED | Field comparisons are broad, but they validate caller-returned self-consistent objects; input IDs are not compared to resolved record IDs, time is caller-controlled, and maximum TTL is not enforced. |
| planner approval enforcement | PARTIALLY_WIRED | Real SQL repository lookup can work, but it is not mandatory by type/composition/capability and separate planner APIs accept no approval. |
| legacy bypass blocking | PARTIALLY_WIRED | Seventeen named legacy surfaces hard-fail, but the direct canonical planner and generic production SELL planners remain callable. |
| persisted approval authority | PARTIALLY_WIRED | Schema/repository/insert path exist, but planner authority is the injected reader's return value, not demonstrably persisted decision-gate state. |
| idempotent approval lookup | PARTIALLY_WIRED | Sequential fake retry returns one approval and unique keys prevent duplicate rows, but same-request concurrent retry is untested and the pre-lock read is not repeated under the lock. |
| migration readiness | BLOCKED | Migration is unapplied and lacks real MariaDB clean/repeat/partial/concurrency validation; `CREATE TABLE IF NOT EXISTS` does not validate an existing approval table's shape. |

None of the four primary decision targets is `ENFORCED_END_TO_END`.

## Approval authority and binding analysis

### Positive implementation evidence

- The production gate contains the only source-tree
  `INSERT INTO manual_execution_approval`.
- Reservation and approval inserts occur in the same
  `db_cursor(commit=True)` scope.
- The approval schema has unique request, reservation, and idempotency keys.
- Foreign keys bind approval to request, account, asset, wallet snapshot,
  reservation, and provenance.
- UPDATE and DELETE triggers make approval rows immutable if the migration is
  successfully applied.
- The concrete approval repository joins the reservation and wallet snapshot.
- The planner checks request/account-code/venue/asset/base/quote/side/mode/
  provenance/state/quantity/reservation/snapshot/timestamp/expiry fields.
- The planner rejects missing/non-positive IDs and unknown records returned
  by the supplied reader.

### Authority failures

- `ManualExecutionApprovalRecord` has a public constructor.
- `ManualExecutionApprovalReader`, `ManualExecutionRequestReader`, and
  `ManualSellPlanningInputReader` are public structural protocols.
- The canonical planner accepts any implementations of those protocols and
  does not require `ManualExecutionApprovalRepository` or a trusted
  composition root.
- Even the concrete approval repository accepts a caller-supplied
  `cursor_factory`.
- The planner does not compare `approval.approval_id` with its `approval_id`
  argument.
- The planner does not compare the returned `request.request_id` with its
  `request_id` argument.
- The direct-object negative test only proves that an unexpected `approval=`
  keyword raises `TypeError`; it does not prove that the same object cannot
  enter through the required repository interface.
- `process()` itself accepts a caller-supplied gate repository. Its happy-path
  test uses a fake gate that creates no persisted approval.
- No runtime composition root establishes which repository implementations
  are trusted.
- Database INSERT privilege is not scoped to a gate-owned stored procedure or
  distinct DB principal. Source-code ownership of the INSERT statement is not
  an unforgeability boundary.

### Binding/freshness gaps

- Binding checks prove self-consistency only when the reader is caller-owned.
- `now` is caller-controlled in service, gate, free-quantity freshness, and
  planner approval expiry.
- The migration enforces only `expires > approved`; it does not enforce the
  gate's five-minute maximum TTL.
- `account_code`, base asset, and quote asset are copied from the request and
  checked back against it, but are not constrained to the authoritative
  trading-account/asset/market parent rows.
- The planner checks current reservation state and quantity when using the
  concrete join, which is positive, but a structural reader can fabricate
  those joined fields.

## Persisted approval and migration analysis

Deployment ordering is coherent on paper:

```text
P0 safety parents
  -> manual_execution_request
  -> reservation/request and request/provenance FKs
  -> sell lock
  -> approval table
  -> immutability triggers
  -> runtime
```

Schema strengths:

- InnoDB tables and explicit parent FKs.
- One approval per request and per reservation.
- Positive quantity, PAPER/SELL/APPROVED, and expiry-order checks.
- Immutable approval UPDATE/DELETE triggers.
- Restrictive FK actions.

Readiness blockers:

- No migration was applied or parsed/executed by MariaDB.
- Static tests search for SQL fragments; they do not validate syntax,
  constraints, triggers, rerun behavior, or FK type compatibility.
- `CREATE TABLE IF NOT EXISTS manual_execution_approval` silently accepts an
  existing incompatible table; the procedure does not validate the approval
  table shape, indexes, FKs, engine, checks, or triggers.
- MariaDB DDL implicitly commits. The migration adds parent FKs before
  creating the approval table, so later failure can leave a partial schema.
- Existing invalid non-NULL request/provenance references can make an ALTER
  fail after an earlier DDL has committed; there is no data preflight.
- The same-request concurrent retry path is not re-read after acquiring the
  per-account lock. It can race from two pre-lock misses into a uniqueness
  error rather than returning the existing approval.
- The pre-lock consistent read/MariaDB REPEATABLE READ visibility concern from
  Round 2 remains unvalidated. The Python fake does not model InnoDB MVCC.

`MIGRATION_READINESS=BLOCKED`. This is separate from the explicitly
out-of-scope real MariaDB concurrency authorization gate.

## Test-evidence analysis

Review test command:

```text
python -m pytest -q \
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
  tests/test_manual_execution_round3_enforcement_v1.py \
  tests/test_manual_execution_round3_migration_v1.py \
  tests/test_execution_ladder_profiles_v1.py \
  tests/test_execution_planner_explicit_intent_v1.py
```

Result: `238 passed in 1.64s`.

Tests that prove runtime behavior:

- Generic contract-preview SELL/EXIT guards raise.
- Legacy runner entrypoints return 2 before DB access.
- Legacy direct mutation/build helpers raise.
- Concrete planner field-mismatch checks fail for the supplied records.
- Gate code attempts reservation and approval insertion in one context.
- Sequential fake retry returns the same approval ID.
- Fake rollback removes fake reservation and approval state.

Tests that mock away the critical boundary:

- The service happy path uses `GateRepository(_approval())`; no persisted
  decision-gate approval is created or read.
- `_approval()` publicly constructs the supposedly authoritative record.
- `_canonical()` supplies caller-owned request, approval, and planning
  repositories to production planner code.
- Atomicity/concurrency uses `threading.Lock` and list snapshots, not MariaDB
  transactions, isolation, unique-key behavior, or FK enforcement.
- Migration tests assert substrings only.
- The entrypoint test asserts a hand-maintained 18-entry dictionary and
  cannot detect omitted paths.

Missing negative cases:

- Caller-built approval returned through the required repository interface.
- Approval reader returns record ID different from requested approval ID.
- Request reader returns request ID different from requested request ID.
- Caller-backdated `now` against an expired approval.
- Approval expiry beyond the gate's maximum TTL.
- Caller-controlled planning-input repository/venue constraints.
- Direct canonical planner invocation without the service.
- Generic `execution_planner_v1` SELL plan and its CLI/PAPER-cycle writers.
- Exit-policy plan-without-reservation path.
- Same-request concurrent approval retry.
- Real MariaDB clean apply, rerun, partial-state, trigger, FK, rollback, MVCC,
  and concurrency behavior.

One pre-existing test is direct counter-evidence:
`test_execution_planner_explicit_intent_v1.py` parametrizes
`build_execution_plan()` over `side in {BUY, SELL}` and explicitly verifies
that the repository persists a LIVE SELL contract without permission
evidence fields.

## Architecture findings

- `selection_engine` remains market-only in the reviewed Round 3 diff.
- The concrete manual gate correctly contains account-aware wallet,
  reservation, and permission logic.
- The manual service mostly orchestrates, but it accepts caller time and
  caller-resolved venue/planning inputs, so it is not a trust boundary.
- The canonical manual planner creates only a preview and performs no broker
  submission. Its persistence-reader injection nevertheless leaks approval
  authority into the caller.
- Executor/reconciliation code was not absorbed into the manual service.
- The separate exit policy violates the claimed single manual SELL safety
  boundary by creating a PAPER SELL plan without the manual reservation and
  feeding the generic persisted planner/executor lane.
- No broker/private API call or order placement was made during review.

## Required fixes before another enforcement review

1. Make the planner's production approval resolver non-substitutable by an
   ordinary caller. Establish a trusted composition root/capability that
   cannot be recreated by passing a structural fake repository. Tests may
   inject below that boundary, but the production callable API must not.
2. Remove caller-controlled `now` from production service/gate/planner
   authority and freshness decisions. Use an internal trusted clock; isolate
   clock injection to a non-production test seam.
3. Explicitly compare requested `request_id`/`approval_id` with the records
   returned by persistence.
4. Hard-block or structurally segregate every generic production SELL planner
   and writer path (`build_execution_plan`, `build_exit_plan_from_position`,
   their CLIs/PAPER cycle, exit policy, and plan-without-reservation
   repository) so a manual caller cannot use it as an equivalent SELL path.
5. Replace the hand-maintained inventory assertion with discovery over
   production planner constructors, wrappers, writers, and executor
   consumers.
6. Add negative tests for repository forgery, ID-return mismatch, backdated
   time, maximum TTL, planning-input forgery, generic SELL paths, and
   same-request concurrent retry.
7. Make the migration fail closed on incompatible pre-existing approval
   schema and validate it on disposable MariaDB, including clean/repeat/
   partial/concurrent cases. Do not treat this as authorization for shared
   DB migration or Odroid execution.

## Authorization gates

```text
ROUND3_ENFORCEMENT=BLOCK_REJECT
MARIADB_REAL_CONCURRENCY=NOT_EVALUATED_AS_READY
RECONCILIATION_OWNERSHIP=OUT_OF_SCOPE_NOT_READY
COMPLETE_VENUE_ENFORCEMENT=OUT_OF_SCOPE_NOT_READY
ODROID_PAPER_PREVIEW_AUTHORIZED=false
LIVE_AUTHORIZATION_ALLOWED=false
```
