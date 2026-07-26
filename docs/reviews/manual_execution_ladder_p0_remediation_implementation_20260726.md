# Manual Execution Ladder P0 Remediation — Implementation Evidence (2026-07-26)

This document now covers two remediation rounds against the same BLOCK/REJECT
review, both landed 2026-07-26. Round 1 (§1-8 below) implemented the
canonical request contract and service entrypoint. Round 2 (§9 onward)
implements DecisionGate authority over account-derived quantity/approval and
atomic SELL reservation creation. Round 2 supersedes round 1's "Remaining P0
blockers" list where noted; see §12 for the current one.

## Round 1: canonical request contract + service entrypoint

### Scope of this change

This change implements exactly one remediation item against the BLOCK/REJECT
independent review at
`docs/reviews/manual_execution_ladder_p0_implementation_review_20260725.md`
(commit `d15cb5f`, reviewed by an OpenAI Codex thread, high effort):

> Implement the canonical immutable `manual_execution_request` parent and the
> single canonical manual execution service entrypoint.

Explicitly out of scope for this change (unchanged by this diff):

- atomic SELL reservation creation (review §13 items 4/9) — the gate reads
  existing reservation totals but does not create one;
- reconciliation state-machine changes (review §13 item 11);
- live executor wiring / broker submission (review §13 "before live
  authorization");
- applying the new migration (schema created, not run against any database);
- branch rename/rebase (review §1, "Branch name");
- A+ ladder anchor-based quantity calculation
  (`src/execution_ladder/resolver.py`, `docs/todo/manual_execution_ladder_profiles_v1.md`'s
  ladder-profile fields);
- unrelated cleanup outside the files listed below.

A pre-existing git stash on this branch, `stash@{0}` ("QUARANTINE accidental
manual-execution remediation from stale PR147 branch"), was found untouched
at the start of this work and was **not** applied, read further than a
`--stat`, or used as a basis for anything in this diff — it is unrelated
prior work quarantined by someone else, left exactly as found.

## 1. `manual_execution_request` — canonical immutable request contract

File: `src/manual_execution/manual_execution_request_v1.py`.

`ManualExecutionRequest` (frozen dataclass) fields: `request_id`,
`schema_version`, `idempotency_key`, `created_ts_utc`, `source`,
`requested_by`, `mode` (PAPER|LIVE), `trading_account_id`, `account_code`,
`venue`, `asset_id`, `base_asset`, `quote_asset`, `side` (BUY|SELL),
`quantity_policy`, `requested_base_quantity`, `requested_quote_notional`,
`ladder_levels`, `provenance_id`, `request_state`, `rejection_code`,
`rejection_detail`, `processed_ts_utc`.

By construction there is no field for free/available base quantity, approval
or decision state, tick size, quantity/amount step, minimum quantity or
notional, or an executable broker order intent — those names do not exist on
this type, so `build_manual_execution_request(**kwargs)` raises `TypeError`
immediately if a caller passes any of them (proven in
`tests/test_manual_execution_request_v1.py::TestUntrustedFieldsCannotBeSupplied`,
7 tests). `build_manual_execution_request()` fails closed on every
incomplete/unsupported/contradictory field (unknown source/mode/side/
quantity_policy, mismatched quantity-policy payload, empty
idempotency_key/venue/account_code, non-positive account/asset ids).

Immutability: content fields never change after construction.
`advance_manual_execution_request_state()` is the only permitted
state-transition path (single hop `DRAFT -> {GATE_BLOCKED, PLANNED,
PLAN_REJECTED, FAILED}`, matching `sell_reservation_v1`'s transition-table
discipline); anything else raises
`InvalidManualExecutionRequestTransitionError`.

`ManualExecutionRequestRepository` persists/identifies requests
idempotently on `idempotency_key` (SELECT-then-INSERT, same pattern as
`SellReservationRepository.create_reservation_idempotent`).

Trading-account identity: the request keys on `trading_account_id` (the
model `account_position_snapshot`/`execution_sell_reservation` already use),
not the legacy `account_id`/`sleeve_code` portfolio-sleeve model — manual
SELL requests act on an existing position, not a sleeve allocation. This
avoids reintroducing the identity-bridge gap the review flagged
(`docs/reviews/manual_execution_ladder_p0_implementation_review_20260725.md`
§3, "`trading_account_id` resolves sleeve dependency ... PARTIALLY_WIRED").
`sleeve_code` is still accepted by `manual_execution_service_v1.process()`
as a separate, explicit parameter — it only selects an execution-style
profile in `contract_preview_v1` (post-only/reprice/urgency), not a
capital-allocation or permission input.

## 2. `decision_gate` public contract for a manual request

File: `src/decision_gate/manual_execution_gate_v1.py`.

`evaluate_manual_execution_request(request, gate_input)` is pure (no DB) and
is the trusted producer `free_base_quantity_v1` was missing (review finding
B2). It fails closed, in order, on: `mode != PAPER`, `side != SELL` (BUY
manual requests are not yet implemented — honest boundary, not a silent
approval), an unsupported `quantity_policy` (only `FULL_AVAILABLE_BASE` and
`FIXED_BASE_QUANTITY` resolve to a base quantity here; `FIXED_QUOTE_NOTIONAL`
and `LADDER_LEVELS`' notional variant would require a market price to
convert to base quantity, which is not decision_gate's account-aware
concern — both fail closed with `QUANTITY_POLICY_NOT_YET_SUPPORTED`),
account disabled/live-trading-enabled/not-paper-mode, a missing wallet
snapshot, and every `free_base_quantity_v1` blocking reason (stale/
incomplete/contradictory snapshot, reconciliation-pending reservations,
mismatch). On success, `approved_quantity_base` is `min(requested,
free_base_quantity)` — the request's own `requested_base_quantity` is never
trusted directly into the planner.

`ManualExecutionGateRepository.load_gate_input()` is the trusted producer:
reads `trading_account` (enabled/live_trading_enabled/account_mode) and the
latest `account_position_snapshot` row into a typed `WalletAvailableSnapshot`,
and reuses the existing `SellReservationRepository.sum_approved_not_submitted`
/ `count_reconciliation_pending` (no new reservation-repository code). It
does **not** create a reservation — that remains the explicitly-excluded
next remediation item.

## 3. Canonical service entrypoint

File: `src/manual_execution/manual_execution_service_v1.py`.

`process(request, *, request_repository, gate_repository, market_context,
venue_constraints, sleeve_code, now=None) -> ManualExecutionOutcome` is the
one call graph:

```text
ManualExecutionRequest
  -> mode != PAPER? -> FAILED (decision_gate/execution_planner never called)
  -> request_repository.create_request_idempotent()
  -> gate_repository.load_gate_input()
  -> evaluate_manual_execution_request()
     -> BLOCKED? -> GATE_BLOCKED (execution_planner never called)
  -> venue_constraints.status != FRESH? -> GATE_BLOCKED (execution_planner never called)
  -> contract_preview_v1.build_execution_plan_preview(
         intent(quantity_base=gate_result.approved_quantity_base,   # gate-approved only
                decision_state="EXECUTION_ALLOWED",                  # service-fixed, not caller
                tick_size=venue_constraints.tick_size),               # resolved constraints, not caller
         authorized_caller="manual_execution_service_v1")
     -> ValueError? -> PLAN_REJECTED
     -> else -> PLANNED, plan_preview returned
```

`process()` does not itself compute permission, free quantity, venue
rounding, or plan legs — those calls are delegated exactly as listed above.
It never absorbs broker submission or reconciliation (neither is called
anywhere in this module).

market_context (reference/bid/ask price, spread, regime) is accepted as
public market data from the caller — that is account-agnostic and outside
decision_gate's scope, unlike quantity/decision_state/tick_size.

## 4. Removing the `contract_preview_v1` bypass

File: `src/execution_planner/contract_preview_v1.py`.

`build_execution_plan_preview()` gained a keyword-only `authorized_caller`
parameter. For `intent_type in {EXIT_PASSIVE_LIMIT, EXIT_LADDER}` (the
manual SELL exit intents — review bypass-list items 1-2), it now raises
`UnauthorizedManualExecutionCallError` unless `authorized_caller ==
"manual_execution_service_v1"`. `PREPARE_PLAN`/`PLACE_PASSIVE_LIMIT`/
`PLACE_LADDER` (the unrelated selection-driven BUY lane) are unaffected —
confirmed by
`tests/test_manual_execution_service_v1.py::TestLegacyDirectCallBypassIsBlocked::test_prepare_plan_still_works_without_authorized_caller`
and a manual `--help`/CLI run (below).

`src/execution_planner/run_execution_planner_contract_preview_v1.py` (the
CLI previously documented as the "designated authoritative" manual path) now
prints `[BLOCKED]` and exits 2 for `--intent-type EXIT_PASSIVE_LIMIT|EXIT_LADDER`,
pointing at the canonical service, before ever constructing an intent.
Manually verified:

```text
$ python -m src.execution_planner.run_execution_planner_contract_preview_v1 --intent-type EXIT_LADDER ...
[BLOCKED] intent_type=EXIT_LADDER is a manual SELL exit intent. ...
exit=2

$ python -m src.execution_planner.run_execution_planner_contract_preview_v1 --intent-type PREPARE_PLAN ...
(prints a normal PREVIEW_ONLY table; exit=0 — BUY lane unaffected)
```

## 5. Audit of other manual/PAPER preview entrypoints

Per review bypass-list items 3-7, none of these place a broker order or have
an executor consumer today (`place_limit_sell_ladder_orders()` still always
raises `PermissionError`; the sell-only PAPER chain writes only
`execution_sell_intent`/`execution_sell_plan` preview state). They are
**not** hard-blocked in this change — doing so would touch A+ ladder
quantity calculation (`execution_ladder/resolver.py`) or the unrelated
BUY-side generic PAPER worker, both explicitly out of scope. Each now carries
an explicit non-authoritative docstring/comment pointing at the canonical
service, with no behavior change:

- `src/execution_ladder/resolver.py`, `src/execution_ladder/run_ladder_profile_preview_v1.py`
- `src/execution/limit_sell_ladder_v1.py`, `scripts/trade_place_limit_sell_order_ladders_from_csv.py`
- `src/decision_gate/run_sell_only_decision_gate_preview_v1.py`,
  `src/execution_planner/run_sell_only_execution_plan_preview_v1.py`,
  `src/executor/run_sell_only_paper_executor_preview_v1.py`

The generic PAPER planner/worker (`run_execution_planner_v1`,
`execution_planner_v1.py`, `worker.py`) is a different, BUY-oriented,
selection-driven feature, not a manual-execution entrypoint — left untouched
and undocumented here as out of scope.

## 6. Persistence

File: `db/migrations/20260726_manual_execution_request_v1.sql` — **created,
not applied.** No `ALTER`/migration command was run against any database
this session (`database_writes=0`, confirmed by `git status` showing the
file as untracked/new only).

Compatibility notes:

- FK to `trading_account`/`asset`, `CHECK` constraints on `mode`/`side`/
  `quantity_policy`/`request_state` (mirrors `execution_sell_reservation`'s
  and `execution_research_provenance`'s existing CHECK-constraint pattern).
- No FK yet from `execution_sell_reservation.manual_execution_request_id` to
  this table (atomic reservation creation is the next, separate item) and no
  FK from a `provenance_id` column here to `execution_research_provenance`
  (provenance binding is also a separate, not-yet-implemented item — review
  §13 item 12). Both are called out as non-goals in the migration header,
  following the same forward-compat-without-FK convention the 2026-07-25
  migration already used for `manual_execution_request_id`.
- `CREATE TABLE IF NOT EXISTS` carries the same partial-apply/no-transaction
  caveat the 2026-07-25 migration has (MariaDB DDL implicitly commits); this
  migration adds exactly one new table and no seed DML, so there is no
  seed-overwrite-on-rerun risk like the 2026-07-25 migration's fixed seeds.

## 7. Tests

```text
tests/test_manual_execution_request_v1.py   28 tests
tests/test_manual_execution_gate_v1.py      16 tests
tests/test_manual_execution_service_v1.py    7 tests
```

Coverage against this item's required list:

| Requirement | Test |
|---|---|
| Valid manual requests accepted | `TestConstructionGuardsIntent` (3 cases: full-available, fixed-quantity, ladder) |
| Incomplete requests fail closed | `TestConstructionGuardsIntent` (9 rejection cases) |
| Caller-supplied free quantity rejected | `TestUntrustedFieldsCannotBeSupplied::test_free_base_quantity_kwarg_rejected` (TypeError — no such field) |
| Caller-supplied approval rejected | `test_decision_state_kwarg_rejected`, `test_approved_kwarg_rejected` |
| Caller-supplied venue execution metadata rejected | `test_tick_size_kwarg_rejected`, `test_amount_step_kwarg_rejected`, `test_min_notional_kwarg_rejected` |
| Direct executable intents rejected | `test_broker_order_id_kwarg_rejected`; plus `TestLegacyDirectCallBypassIsBlocked` (EXIT_LADDER/EXIT_PASSIVE_LIMIT without `authorized_caller` raise `UnauthorizedManualExecutionCallError`) |
| Planner unreachable without a decision_gate result | `TestProcessGateBlocked::test_blocked_gate_never_reaches_planner` (`plan_preview is None`) |
| Legacy authoritative-preview bypass blocked or routed | `TestLegacyDirectCallBypassIsBlocked` (2 cases) + CLI `[BLOCKED]` exit 2 (manual run, §4) |
| PAPER and future LIVE requests use the same contract | `TestPaperAndLiveShareOneContract` (construction) + `TestProcessLiveModeFailsClosed` (service fails closed pre-gate for `mode=LIVE`, proven via a repository stub that raises `AssertionError` if touched) |

Full focused run (includes the pre-existing P0 suite for regression):

```text
python -m pytest tests/test_bitvavo_venue_adapter_v1.py tests/test_canonical_rounding_v1.py \
  tests/test_free_base_quantity_v1.py tests/test_limit_sell_ladder_v1.py \
  tests/test_manual_execution_p0_architecture_boundaries_v1.py tests/test_manual_execution_p0_integration_v1.py \
  tests/test_research_provenance_v1.py tests/test_sell_reservation_v1.py \
  tests/test_venue_execution_constraints_v1.py tests/test_manual_execution_request_v1.py \
  tests/test_manual_execution_gate_v1.py tests/test_manual_execution_service_v1.py -q
131 passed in 0.97s
```

`python -m py_compile` clean on all 16 changed/added Python files.
`git diff --check` clean.

## 8. Remaining P0 blockers (round 1 snapshot — superseded, see §12)

Everything in
`docs/reviews/manual_execution_ladder_p0_implementation_review_20260725.md`
§13 "Before merge" not listed as done above remains open, in particular:

- atomic SELL reservation creation under an account/asset lock (item 4/9) —
  `manual_execution_gate_v1` reads reservation totals but does not write one;
- full venue-constraint leg validation (step/minimum quantity/notional,
  order type/TIF) inside the planner call (item 6/7) — the service supplies
  a fresh `VenueExecutionConstraints.tick_size`, but `contract_preview_v1`
  still only calls `round_price_for_side`, not `round_leg_for_side`;
- reconciliation ownership (item 11);
- provenance binding to the request (item 12);
- disposable-MariaDB migration tests and concurrency tests (item 14);
- branch rename/rebase (item 1) — untouched, out of scope for this item.

## Safety markers (round 1)

```text
host=devlap
code_modifications=16 files (see git diff --stat)
migrations_applied=0
database_writes=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=extended (manual_execution_gate_v1, read-only against
  trading_account/account_position_snapshot/execution_sell_reservation)
execution_planner=extended (authorized_caller guard on contract_preview_v1;
  no new broker/DB calls)
executor=none
merge_or_push=0
```

## 15. Round 4 — non-substitutable authority, trusted time, and SELL closure

Round 4 implements only the enforcement blockers identified by the
authoritative Round 3 independent review. It does not implement or authorize
MariaDB validation/deployment, reconciliation ownership, venue expansion,
Odroid PAPER execution, live execution, or BUY-side manual execution.

### Trusted approval authority composition

The public canonical planner signature is now:

```text
build_manual_sell_execution_plan_preview(
    *,
    request_id: int,
    approval_id: int,
    planning_inputs: ManualSellPlanningInputs,
) -> ExecutionPlanPreview
```

Neither the planner nor `manual_execution_service_v1.process()` accepts a
request repository, approval repository, gate repository, clock, timestamp,
approval object, raw quantity, or decision state. Production composition is
explicit:

```text
manual_execution_service_v1.process()
  -> ManualExecutionRequestRepository()
  -> ManualExecutionGateRepository()
       -> INSERT reservation
       -> INSERT approval
       -> returned approval_id
       -> SELECT approval JOIN reservation JOIN snapshot BY returned ID
       -> verify every immutable binding
  -> build_manual_sell_execution_plan_preview(request_id, approval_id, inputs)
       -> decision_gate.manual_execution_approval_v1
          .resolve_persisted_manual_execution_authority(request_id, approval_id)
          -> production ManualExecutionRequestRepository()
          -> private production approval reader
       -> explicit returned request_id/approval_id equality checks
       -> binding/state/freshness validation
       -> preview intent construction
```

An ordinary production caller has no API parameter, factory argument,
environment selector, setter, registry, token, or caller string with which to
replace approval persistence. `ManualExecutionApprovalRecord` remains a
read-model shape, but no planner/service parameter accepts it. Unit tests
substitute the private resolver only with process-local test monkeypatching;
production code neither imports nor selects test infrastructure.

The create result is never trusted directly. A missing/non-positive returned
ID, a missing row on re-read, a different approval ID, or any changed
idempotency/request/account/venue/asset/pair/side/quantity/snapshot/
reservation/time/mode/provenance/state/reason binding raises and rolls back
the transaction.

### Trusted clock composition

`src/manual_execution/_trusted_clock_v1.py` owns the wall-clock read. Public
manual service, gate, approval authority, free-quantity resolver, and planner
APIs expose no `now`, `current_time`, `clock`, or equivalent freshness
parameter.

- approval creation and expiry use a gate-owned clock read;
- wallet freshness uses its own subsystem clock read;
- planner expiry uses an independent subsystem clock read;
- the planner rejects expired approvals and TTLs longer than the canonical
  five-minute boundary;
- caller payload timestamps remain data and cannot replace the authority
  clock.

Tests patch the private clock module only inside the test process. There is no
production runtime selection path for a test clock.

### Generic planner caller proof and BUY preservation

All production calls of `execution_planner_v1.build_execution_plan()` were
traced before finalizing the SELL guards:

- `run_execution_planner_v1`: CLI parser accepts BUY only; `main()` also
  rejects a monkeypatched SELL namespace before repository construction.
- `run_paper_cycle_v1`: CLI parser accepts BUY only; `main()` has the same
  pre-repository SELL guard.
- `run_live_paper_cycle_v1` and `run_live_paper_loop_v1`: configuration is
  fixed to `requested_side="BUY"`.
- `run_paper_candidate_execution_planner_preview_v1`: fixed to BUY.
- `build_exit_plan_from_position()`: its only production caller is
  `exit_policy_v1`, which now hard-fails before connection construction.

BUY planner, repository-contract, CLI-help, and PAPER-worker regression tests
remain green. The unrelated side-less skeleton planner was inspected and left
unchanged.

### Discovery-based SELL entrypoint inventory

`tests/manual_sell_entrypoint_discovery_v1.py` parses production ASTs under
the bounded manual/planner/execution roots. It discovers entrypoint-shaped
functions by SELL/EXIT literals, names, and calls to planner/persistence/
executor sinks. `tests/test_manual_execution_round4_enforcement_v1.py`
requires exact equality between the discovered set and the reviewed
classification map; it has no fixed-count assertion. A mutation test writes a
new temporary `build_new_sell_alias()` containing `SELL`/`EXIT_LADDER` and
proves it is returned as unclassified.

Discovery is intentionally bounded. It excludes research-only/config seed
code and the unrelated side-less skeleton planner, and it does not claim to
prove arbitrary dynamic dispatch, generated code, or monkeypatching of a
running Python process. Runtime tests independently exercise the authoritative
and hard-blocked boundaries.

Current discovered/classified set equality:

```text
discovered=44
classified=44
set_equality=true
routed_canonically=6
hard_blocked=38
still_bypassable=0
```

| Discovered production surface | Round 4 disposition |
|---|---|
| `scripts.run_live_paper_trader.main` | HARD_BLOCKED |
| `scripts.trade_place_limit_sell_order_ladders_from_csv.<module>` | HARD_BLOCKED |
| `decision_gate.manual_execution_gate_v1.evaluate_manual_execution_request` | ROUTED_CANONICALLY |
| legacy sell decision `insert_event` | HARD_BLOCKED |
| legacy sell decision `insert_intent` | HARD_BLOCKED |
| legacy sell decision runner | HARD_BLOCKED |
| limit SELL order builder | HARD_BLOCKED |
| limit SELL broker placer | HARD_BLOCKED |
| limit SELL order preview | HARD_BLOCKED |
| canonical PAPER execution runner | HARD_BLOCKED for SELL |
| generic execution worker plan validation | HARD_BLOCKED for SELL |
| generic execution worker processing | HARD_BLOCKED for SELL |
| raw SELL ladder resolver | HARD_BLOCKED |
| rounded SELL ladder preview | HARD_BLOCKED |
| ladder profile runner | HARD_BLOCKED |
| canonical side-aware rounding primitive | ROUTED_CANONICALLY |
| generic private BUY plan builder receiving SELL | HARD_BLOCKED |
| canonical manual ladder-leg builder | ROUTED_CANONICALLY |
| canonical manual single-leg builder | ROUTED_CANONICALLY |
| generic contract-preview planner | HARD_BLOCKED for SELL/EXIT |
| canonical manual SELL planner | ROUTED_CANONICALLY |
| generic `execution_planner_v1.build_execution_plan` | HARD_BLOCKED for SELL |
| generic `build_exit_plan_from_position` | HARD_BLOCKED |
| generic repository `_insert_execution_plan` | HARD_BLOCKED for SELL |
| generic repository exit-without-reservation writer | HARD_BLOCKED |
| generic repository plan-with-reservation writer | HARD_BLOCKED for SELL |
| generic repository plan-without-reservation writer | HARD_BLOCKED for SELL |
| generic repository plan updater | HARD_BLOCKED for SELL |
| contract-preview CLI main | HARD_BLOCKED for SELL/EXIT |
| contract-preview CLI argument surface | HARD_BLOCKED for SELL/EXIT |
| generic execution-planner CLI | HARD_BLOCKED for SELL |
| legacy sell planner `insert_event` | HARD_BLOCKED |
| legacy sell planner `insert_plan` | HARD_BLOCKED |
| legacy sell planner runner | HARD_BLOCKED |
| generic PAPER executor | HARD_BLOCKED for SELL |
| generic PAPER executor CLI | HARD_BLOCKED for SELL |
| legacy sell executor `insert_event` | HARD_BLOCKED |
| legacy sell executor runner | HARD_BLOCKED |
| legacy sell executor state updater | HARD_BLOCKED |
| `manual_execution_service_v1.process` | ROUTED_CANONICALLY |
| live PAPER single-cycle planner caller | HARD_BLOCKED for SELL; fixed BUY |
| live PAPER loop planner caller | HARD_BLOCKED for SELL; fixed BUY |
| generic PAPER cycle | HARD_BLOCKED for SELL |
| exit policy | HARD_BLOCKED before planning/persistence |

### Disposition of every Round 3 bypass

| Round 3 bypass | Final disposition |
|---|---|
| Direct canonical planner with injected repositories | ROUTED_CANONICALLY: repository parameters removed; persisted authority is internally resolved |
| Production-importable `_canonical()` test forgery helper | HARD_BLOCKED: helper removed; no public planner injection argument exists |
| Generic `execution_planner_v1.build_execution_plan(...SELL...)` | HARD_BLOCKED before planner logic |
| `build_exit_plan_from_position()` | HARD_BLOCKED before planner logic |
| `run_execution_planner_v1 --requested-side SELL` | HARD_BLOCKED before repository construction |
| `run_paper_cycle_v1 --requested-side SELL` | HARD_BLOCKED before repository construction |
| `exit_policy_v1.run_exit_policy_v1()` | HARD_BLOCKED before connection/planner construction |
| `create_exit_plan_without_reservation()` | HARD_BLOCKED before connection/write |

The six Round 3 `NON_AUTHORITATIVE_BUT_CALLABLE` surfaces were also closed:
legacy `decide_position`, SELL ladder rounding, limit-SELL order preview, the
generic PAPER executor, its CLI, and the PAPER execution runner all reject
SELL directly or transitively before SELL execution mutation.

### Round 4 negative evidence

Focused tests prove:

- caller/service/planner APIs cannot accept an approval repository;
- fake approval readers and caller-created approval records cannot enter the
  planner call;
- the returned approval ID is mandatory and re-read;
- missing, changed, replaced, or mismatched re-read rows roll back;
- request and approval IDs are explicitly compared after resolution;
- expired approvals cannot be revived with a caller timestamp;
- all public manual authority APIs expose no authoritative time parameter;
- PAPER manual SELL uses the same persisted authority path;
- every generic SELL planner and persistence writer rejects before its
  connection boundary;
- every Round 3 bypass is canonical or hard-blocked;
- discovery and classification sets are exactly equal;
- a newly added unclassified SELL alias is discovered.

### Migration and remaining blockers

No Round 4 migration change was required: the existing unapplied migration
already supplies approval identity, unique request/reservation/idempotency
keys, restrictive foreign keys, expiry/state checks, and immutable approval
triggers needed by this scope. It was not applied.

Migration readiness remains `BLOCKED` pending separately authorized
disposable-MariaDB clean/repeat/partial/concurrency validation. Remaining
out-of-scope blockers are reconciliation lifecycle ownership, complete venue
step/minimum/order-type/TIF enforcement, Odroid PAPER authorization, live
authorization, BUY-side manual execution, A+ ladder calculation, and branch
rename/rebase.

## 14. Round 3 — SELL bypass removal and persisted approval authority

This section supersedes the Round 2 approval-object, caller-token, retry,
planner-signature, and legacy-bypass descriptions above. Reconciliation,
full venue step/minimum/order-type/TIF enforcement, BUY-side manual
execution, live submission, and A+ ladder calculation remain out of scope.

### Final SELL call graph

```text
producer
  -> ManualExecutionRequestRepository.create_request_idempotent()
  -> manual_execution_service_v1.process()
  -> ManualExecutionGateRepository.approve_and_reserve()
       BEGIN
       lock (account, venue, asset)
       re-read wallet + active SELL reservations
       insert execution_sell_reservation
       insert manual_execution_approval
       COMMIT
       -> approval_id
  -> build_manual_sell_execution_plan_preview(
       request_id,
       approval_id,
       request_repository,
       approval_repository,
       planning_input_repository,
     )
       -> resolve persisted request
       -> resolve persisted approval joined to reservation + wallet snapshot
       -> validate every binding/freshness/state field
       -> private plan construction
  -> PAPER ExecutionPlanPreview
```

There is no caller identity string or token in this graph. The generic
`build_execution_plan_preview()` rejects every `side=SELL` call and every
`EXIT_PASSIVE_LIMIT`/`EXIT_LADDER` spelling before private plan
construction. This also closes the former
`PLACE_PASSIVE_LIMIT + side=SELL` alias.

### Removed and hard-blocked aliases

Removed authority surfaces:

- `MANUAL_EXECUTION_APPROVAL_TOKEN`
- public `ManualExecutionApproval` object acceptance
- `authorized_caller`
- generic-planner `approval` and `now` parameters
- service construction of caller-shaped `ExecutionIntentPreview`

No legacy function was deleted because several modules still contain
read-compatibility code for existing PAPER rows. Their callable write/build
surfaces now fail before DB access or plan/order construction:

- generic planner: all SELL plus both `EXIT_*` aliases
- generic planner CLI: all SELL plus both `EXIT_*` aliases
- sell-only decision runner and `insert_intent`
- sell-only plan runner and `insert_plan`
- sell-only PAPER executor runner and `update_plan_state`
- SELL `execution_ladder.resolver.resolve_ladder_preview`
- ladder-profile preview runner
- `build_limit_sell_ladder_orders` and direct placement
- the CSV ladder script, transitively blocked by its builder

`tests/test_manual_execution_round3_enforcement_v1.py` is the executable
inventory. It classifies 18 known entrypoints as only
`ROUTED_CANONICALLY` or `HARD_BLOCKED`; there is no bypassable or
convention-only classification.

The independent review's separate strategy lane
(`execution_planner_v1.build_execution_plan` /
`build_exit_plan_from_position` through `exit_policy_v1`) remains outside
this manual-execution inventory: it does not accept
`ManualExecutionRequest`, these manual `EXIT_*` aliases, or a manual
approval ID. Read-only sell-intent/permission reports likewise do not
construct a plan. Neither group was relabeled as canonical manual
execution.

### Canonical planner signature

```text
build_manual_sell_execution_plan_preview(
    *,
    request_id: int,
    approval_id: int,
    request_repository: ManualExecutionRequestReader,
    approval_repository: ManualExecutionApprovalReader,
    planning_input_repository: ManualSellPlanningInputReader,
    now: datetime | None = None,
) -> ExecutionPlanPreview
```

The signature has no raw quantity, caller decision state, approved boolean,
approval object, caller token, tick size, reservation state, or executable
intent fields. A caller-created `ManualExecutionApprovalRecord` cannot be
passed to it. Unknown/guessed IDs fail on persistence lookup.

### Persisted approval schema and resolution

`db/migrations/20260726_manual_execution_atomic_approval_v1.sql` now creates
`manual_execution_approval` after the request, reservation, snapshot, and
provenance parents exist. One immutable row binds:

- approval ID and idempotency key
- request ID
- account ID/code, venue, asset ID, base/quote pair, SELL side
- approved base quantity
- wallet snapshot ID and snapshot timestamp version
- reservation ID
- approval timestamp and exclusive expiry boundary
- PAPER mode
- provenance ID
- `APPROVED` state and decision reason

Unique constraints enforce one approval per request and reservation.
Foreign keys bind request, account, asset, wallet snapshot, reservation, and
provenance. A new FK binds non-NULL
`execution_sell_reservation.manual_execution_request_id` to its request.
Database triggers reject approval UPDATE and DELETE. The gate inserts the
reservation and approval in the same transaction; retry resolves the
existing persisted approval and refuses to reconstruct one if it is absent.

The planner joins approval to the actual reservation and wallet snapshot
and rejects unknown IDs, non-approved/expired rows, future or invalid
timestamps, and request/account/account-code/venue/asset/pair/side/mode/
quantity/snapshot/reservation/provenance mismatches. The approved quantity
is accepted only when it equals the joined reservation quantity and the
reservation remains `APPROVED_NOT_SUBMITTED`.

Migration ordering, the NULL-only legacy compatibility window, and MariaDB
DDL rollback limitations are documented at the top of the migration.
Migration application and shared-database validation were not performed.

### Remaining blockers after Round 3

- Reconciliation lifecycle ownership is not implemented.
- Full venue quantity-step, minimum quantity/notional, order-type, and TIF
  enforcement is not implemented.
- The migration still requires disposable real-MariaDB syntax, FK, trigger,
  atomicity, idempotency, and concurrency validation before deployment.
- Odroid PAPER preview remains unauthorized until migration validation and
  an independent re-review pass.
- Live broker submission and live authorization remain unavailable.
- BUY-side manual execution, A+ ladder calculation, and branch
  rename/rebase remain untouched.

Round 3 validation on devlap:

```text
py_compile changed Python files: PASS
focused P0/manual/planner/reservation/venue/ladder tests: 238 passed
git diff --check (tracked changes): PASS
git diff --no-index --check (all untracked files): PASS
migrations_applied=0
database_writes=0
private_broker_calls=0
broker_writes=0
orders=0
```

## Round 2: DecisionGate authority + atomic SELL reservation creation

### Scope of this round

> DecisionGate must become the single authoritative source of
> account-derived quantity and approval, together with atomic SELL
> reservation creation.

Explicitly out of scope for this round (unchanged by this diff): reconciliation
ownership, broker submission changes, live execution, provenance expansion,
venue enhancements beyond what §11's tick-size sourcing already used,
branch rename/rebase, migration application, A+ ladder calculations.

## 9. The canonical approval contract

File: `src/decision_gate/manual_execution_gate_v1.py`.

`ManualExecutionApproval` (frozen dataclass) is the one object
`execution_planner` accepts as authority for a manual SELL exit. It binds:
`approval_token`, `request_id`, `trading_account_id`, `venue`, `asset_id`,
`side`, `approved_quantity_base`, `reservation_id` (the SELL reservation
created atomically with this approval — see §10), `wallet_snapshot_identity`
(`"account_position_snapshot:{account_position_snapshot_id}"` — the exact
snapshot row/version the approval was resolved against; `WalletAvailableSnapshot`
gained a new optional `snapshot_id` field to carry this), `approved_ts_utc`,
and `expires_ts_utc` (`approved_ts_utc + APPROVAL_TTL_SECONDS`, 5 minutes).
It is constructed only inside `approve_and_reserve()` (§10) or its
idempotent-retry path — nowhere else in the codebase sets
`approval_token = MANUAL_EXECUTION_APPROVAL_TOKEN`.

`execution_planner.contract_preview_v1.build_execution_plan_preview()` now
requires this object for `EXIT_PASSIVE_LIMIT`/`EXIT_LADDER` and rejects, via
the new `MissingOrInvalidApprovalError`:

- **caller quantity** — `intent.quantity_base`/`intent.max_notional_eur` must
  both be `None`; supplying either raises immediately, before the approval
  is even inspected;
- **caller approval** — `approval=None` raises;
- **fabricated approval** — `approval.approval_token != MANUAL_EXECUTION_APPROVAL_TOKEN`
  raises (same code-discipline boundary as round 1's `authorized_caller`
  token — not cryptographic, but combined with the checks below it makes a
  hand-built approval object rejectable on sight);
- **stale approval** — `now > approval.expires_ts_utc` raises;
- **mismatched approval** — `trading_account_id`/`venue`/`asset_id`/`side` on
  the approval must equal the intent's; any mismatch raises;
- **incomplete approval** — `approved_quantity_base` must be `> 0`.

Only after every check passes does the function derive the plan's quantity
and `source_decision_state` — exclusively from `approval.approved_quantity_base`
and a fixed `"EXECUTION_ALLOWED"` — via `dataclasses.replace(intent, ...)`
before falling into the existing per-intent-type leg-building logic
unchanged. `intent.decision_state`/`decision_reason` the caller supplied are
never read for these two intent types.

`manual_execution_service_v1.process()` adds one further check the planner
cannot make itself, because `ExecutionIntentPreview` carries no `request_id`
field: **mismatched request** — if `approval.request_id != persisted_request.request_id`,
`process()` rejects (`PLAN_REJECTED`, code `APPROVAL_REQUEST_ID_MISMATCH`)
before ever calling the planner. In the one real call graph this can never
fire (`approve_and_reserve` always binds an approval to the exact request it
derived it from) — it exists as defense in depth and is exercised directly
in tests via a stub gate repository that returns a deliberately mismatched
approval.

## 10. Atomic reservation creation

File: `src/decision_gate/manual_execution_gate_v1.py`,
`ManualExecutionGateRepository.approve_and_reserve()`.

This is now decision_gate's single authoritative entrypoint — the only
function anywhere that produces a `ManualExecutionApproval`, and it creates
the account's SELL reservation in the same transaction as the approval
decision, under one lock:

```text
approve_and_reserve(request, now):
  BEGIN (one connection/transaction — src.common.db_core_v1.db_cursor)
    idempotent-retry check: SELECT execution_sell_reservation
      WHERE idempotency_key = "manual_execution_request:{request.idempotency_key}"
      -> found? return the approval bound to that existing reservation,
         WITHOUT re-deriving the decision (see below)
    INSERT IGNORE INTO manual_execution_sell_lock (trading_account_id, venue, asset_id)
    SELECT ... FROM manual_execution_sell_lock WHERE (same key) FOR UPDATE
      -> blocks until any other transaction holding this key's lock commits/rolls back
    fresh reads (same transaction, after the lock is held):
      trading_account (enabled/live_trading_enabled/account_mode)
      account_position_snapshot (latest wallet row -> WalletAvailableSnapshot)
      execution_sell_reservation SUM(APPROVED_NOT_SUBMITTED), COUNT(SUBMITTED_AWAITING_RECONCILIATION)
    evaluate_manual_execution_request(request, gate_input)  # pure, unchanged from round 1
      -> BLOCKED? return (gate_result, approval=None) — no reservation written
      -> ALLOWED? INSERT execution_sell_reservation(quantity_base=approved_quantity_base,
                    manual_execution_request_id=request.request_id, idempotency_key=...)
                  build ManualExecutionApproval bound to the new reservation_id
  COMMIT (releases the FOR UPDATE lock) / ROLLBACK on any exception (releases it too)
```

Why this closes the "no execution path where request A and request B can
both approve against the same free quantity" requirement: the lock is
per-`(trading_account_id, venue, asset_id)`, acquired via `SELECT ... FOR
UPDATE` against a guaranteed-existent row (`INSERT IGNORE` first), and every
read that feeds the decision happens only after the lock is held, inside the
same transaction that will (if approved) write the reservation. A second
transaction requesting the same key cannot proceed past its own `FOR UPDATE`
until the first commits, at which point its reservation-sum read already
includes the first's insert.

`manual_execution_sell_lock` is a new table added by
`db/migrations/20260726_manual_execution_atomic_approval_v1.sql`
(**created, not applied** — same evidence discipline as round 1's
migration: `git status` shows it untracked/new only, no `ALTER`/DDL command
was run against any database this session). No other schema change was
needed — `execution_sell_reservation.manual_execution_request_id` already
existed (round 1's migration) and is now actually populated.

`SellReservationRepository` (`src/decision_gate/sell_reservation_v1.py`)
gained an optional `cursor` parameter on `find_by_idempotency_key` (new),
`create_reservation_idempotent`, `sum_approved_not_submitted`, and
`count_reconciliation_pending` — when supplied, each reuses the caller's
open cursor/transaction instead of opening its own, which is what lets
`approve_and_reserve` compose all of the reads and the write inside one
lock/transaction. Every method's no-`cursor` (default) behavior is
unchanged, so all of round 1's `sell_reservation_v1` tests still pass
unmodified.

**Idempotent retries**: a retry with the same `request.idempotency_key`
short-circuits on the existing-reservation check *before* taking the lock
or re-reading account/wallet state, and returns an approval reconstructed
from that reservation directly. This matters beyond simple retry-safety of
the reservation row (which `create_reservation_idempotent`'s own
SELECT-then-INSERT already gave it in round 1): without the short-circuit, a
retry after the wallet balance had legitimately moved could re-derive a
*different* gate decision than the first call produced, which would not be
a true retry. Proven in
`tests/test_manual_execution_atomic_approval_v1.py::TestApproveAndReserveIdempotentRetry`
by zeroing the fake wallet balance between the first and second call and
asserting the second still returns the first's `EXECUTION_ALLOWED` result.

**Rollback**: the entire lock+read+decide+write sequence is one
`db_cursor(commit=True)` context; `src/common/db_core_v1.py`'s
implementation rolls back and closes the connection on any exception raised
inside it, which also releases the `FOR UPDATE` lock at the DB level.
Proven in
`tests/test_manual_execution_atomic_approval_v1.py::TestApproveAndReserveRollback`
using a fake session that raises during the reservation `INSERT`: the
reservation table is empty afterward, and an immediately following call for
the same key succeeds (proving the lock was not left stuck).

**Ordering fix in the service**: `manual_execution_service_v1.process()` now
checks `venue_constraints.status == FRESH` *before* calling
`approve_and_reserve`, not after (round 1 checked it after the — then
reservation-less — gate call). This avoids creating a real reservation for
a request that cannot reach the planner anyway due to a venue-metadata
precondition. A plan-construction failure *after* a successful approval can
still leave an approved-but-unused reservation (ladder-shape/leg validation
inside `contract_preview_v1` runs after the reservation already exists) —
releasing that reservation is a reconciliation-layer concern and remains
explicitly out of scope; see §12.

## 11. Reservation lifecycle (unchanged state machine, now actually reached)

`src/decision_gate/sell_reservation_v1.py`'s state machine
(`APPROVED_NOT_SUBMITTED -> SUBMITTED_AWAITING_RECONCILIATION -> OPEN ->
PARTIALLY_FILLED -> {FILLED, CANCELLED, REJECTED, EXPIRED}`) is unchanged by
this round — no new states, no change to `reconcile_reservation_state`'s
`matching_broker_rows == 1` requirement (still the only permitted
transition path, still owned exclusively by reconciliation, still not
implemented/callable from anywhere in this round's code). What changed is
that a reservation now actually gets created, in state
`APPROVED_NOT_SUBMITTED`, bound to a real `manual_execution_request_id`,
through exactly one path (`approve_and_reserve`) instead of never being
created at all.

## 12. Remaining P0 blockers (current, supersedes §8)

- **Reconciliation ownership** (review §13 item 11) — no runner or module
  calls `reconcile_reservation_state`; an approved-but-plan-rejected
  reservation (§10's ordering-fix note) has no release path yet.
- **Full venue-constraint leg validation** (review §13 item 6/7) — the
  service supplies a fresh, `FRESH`-status `VenueExecutionConstraints.tick_size`
  to the planner, but `contract_preview_v1` still calls only
  `round_price_for_side`, not `round_leg_for_side` (no step/minimum
  quantity/notional/order-type/TIF enforcement in the planner call).
- **Provenance binding to the request** (review §13 item 12) — unchanged
  from round 1; `manual_execution_request.provenance_id` still has no FK and
  no runtime path validates/consumes a provenance record against a request.
- **BUY-side manual gate** — `evaluate_manual_execution_request` still fails
  closed on `side != SELL` rather than resolving a free-quote-balance
  equivalent; unchanged from round 1, not part of this round's scope.
- **Disposable-MariaDB migration tests** (review §13 item 14) — the new
  `manual_execution_sell_lock` table has not been tested against real
  MariaDB (no DB available in this environment); the concurrency proof in
  §10 uses a real-thread fake-lock backend, not a real database.
- **Branch rename/rebase** (review §1) — untouched, out of scope.
- **Live execution / broker submission** — untouched, out of scope; no
  executor consumes any preview this round produces.

## 13. Tests (round 2)

```text
tests/test_manual_execution_atomic_approval_v1.py   4 tests (new)
tests/test_manual_execution_service_v1.py           19 tests (was 7; +12 for
  the approval contract: caller-quantity/max-notional rejection, missing/
  fabricated/stale/mismatched-account/venue/asset/side/incomplete approval
  rejection, valid-approval acceptance, venue-constraints-before-gate
  reordering, approval-request-id mismatch)
```

Coverage against this round's required list:

| Requirement | Test |
|---|---|
| Caller quantity ignored/rejected | `test_caller_supplied_quantity_base_is_rejected_even_with_valid_approval`, `test_caller_supplied_max_notional_eur_is_rejected` |
| Caller approval rejected | `test_authorized_caller_but_no_approval_is_rejected` |
| Stale approval rejected | `test_stale_approval_is_rejected` |
| Mismatched account rejected | `test_mismatched_account_is_rejected` (+ venue/asset/side variants) |
| Mismatched request rejected | `TestProcessRejectsMismatchedApproval::test_approval_for_a_different_request_id_is_rejected` |
| Concurrent requests cannot reserve identical quantity | `TestApproveAndReserveConcurrency::test_two_concurrent_full_available_requests_cannot_both_reserve_it` (real `threading.Thread`s, real lock contention) |
| Retry remains idempotent | `TestApproveAndReserveIdempotentRetry::test_retry_returns_same_approval_without_rederiving_decision` |
| Rollback leaves no orphan reservation | `TestApproveAndReserveRollback::test_failed_insert_leaves_no_orphan_reservation_or_stuck_lock` |
| Planner cannot execute without canonical approval | `test_authorized_caller_but_no_approval_is_rejected`, `test_fabricated_approval_token_is_rejected`, plus all round-1 `UnauthorizedManualExecutionCallError` cases |

Full focused run (round 1 + round 2, regression-checked together):

```text
python -m pytest tests/test_bitvavo_venue_adapter_v1.py tests/test_canonical_rounding_v1.py \
  tests/test_free_base_quantity_v1.py tests/test_limit_sell_ladder_v1.py \
  tests/test_manual_execution_p0_architecture_boundaries_v1.py tests/test_manual_execution_p0_integration_v1.py \
  tests/test_research_provenance_v1.py tests/test_sell_reservation_v1.py \
  tests/test_venue_execution_constraints_v1.py tests/test_manual_execution_request_v1.py \
  tests/test_manual_execution_gate_v1.py tests/test_manual_execution_service_v1.py \
  tests/test_manual_execution_atomic_approval_v1.py -q
147 passed in 1.03s
```

The concurrency test was additionally re-run 5x in isolation to check for
flakiness (`TestApproveAndReserveConcurrency` only) — passed all 5 times.

`python -m py_compile` clean on every changed/added Python file, including
the new `src/manual_execution/*.py` package files (confirmed via a separate
`find src/manual_execution -name "*.py"` pass, since `git status --short`
shows that directory as a single untracked `??` line rather than per-file).
`git diff --check` clean.

Manually re-verified the round-1 CLI guard still behaves identically after
this round's `contract_preview_v1` changes:
`run_execution_planner_contract_preview_v1 --intent-type EXIT_LADDER ...`
still prints `[BLOCKED]` and exits 2; `--intent-type PREPARE_PLAN ...` still
produces a normal `PREVIEW_ONLY` table (BUY selection-driven lane
unaffected).

## Safety markers (round 2, final)

```text
host=devlap
code_modifications=20 files total across both rounds (see git status --short)
migrations_applied=0
database_writes=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=extended (manual_execution_gate_v1.approve_and_reserve: reads
  trading_account/account_position_snapshot/execution_sell_reservation and
  writes execution_sell_reservation + manual_execution_sell_lock, all PAPER-
  preview-scoped, no broker calls)
execution_planner=extended (approval-contract validation on contract_preview_v1;
  no new broker/DB calls — still fully read-only itself)
executor=none
reconciliation=none (unchanged; explicitly out of scope this round)
merge_or_push=0
```
