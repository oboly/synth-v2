# Issue #392 Phase 6 SELL LIVE-readiness audit

Date: 2026-08-17
Status: audit only; no LIVE activation performed or authorized by this document.

This document is the repository-level readiness record for Issue #392 Phase 6
("LIVE activation: separately authorized decision and issue only after Phase 5
acceptance"). It audits current `main` (base SHA `d4fae21d1cf38be1a11025f0e0fa5dd220e33a9e`)
against the canonical intended path:

```text
persisted market/account evidence
-> exit_policy candidate
-> decision_gate (incl. account protections)
-> execution_planner immutable SELL plan
-> shared executor handoff
-> LIVE authority + kill switch
-> scoped TRADE_EXECUTION credential
-> executor
-> Bitvavo
-> reconciliation
```

## Canonical components (verified on main)

| Stage | Module / entrypoint |
| --- | --- |
| Automatic exit candidate | `src/exit_policy/automatic_exit_candidate_v1.py::evaluate_automatic_exit_candidate_v1` |
| Automatic exit gate (decision_gate) | `src/decision_gate/automatic_exit_gate_v1.py::evaluate_automatic_exit_candidate_permission_v1` |
| Account protection contract (#227/#318) | `src/decision_gate/account_protection_contract_v1.py` (`resolve_account_protection_state_for_action_v1`), runtime evaluator `src/decision_gate/account_protection_runtime_v1.py::evaluate_account_protection_runtime_v1` |
| Automatic exit planner | `src/execution_planner/automatic_exit_planner_v1.py::build_automatic_exit_plan_v1` -> `AutomaticExitPlanV1` |
| Runtime orchestration (Phase 4B) | `src/exit_policy/automatic_exit_runtime_orchestrator_v1.py::evaluate_automatic_exit_runtime_item_v1` |
| Runtime entrypoint | `src/exit_policy/run_automatic_exit_policy_once_v1.py` (owner `gurkdb`, one-cycle + flock, `deploy/ownership/account_runtime_capability_ownership_v1.json` capability `AUTOMATIC_EXIT_POLICY_RUNTIME`, `activation_status: PLANNED`) |
| Shared side-neutral plan identity (#206) | `src/executor/execution_plan_reference_v1.py::ApprovedExecutionPlanV1` (content-hash immutable identity) |
| Shared executor handoff (#206) | `src/executor/execution_handoff_v1.py::ExecutionHandoffRepositoryV1.intake` / `.intake_live_authorized` |
| TRADE_EXECUTION credential binding (#206) | `src/executor/execution_credential_scope_v1.py::ExecutorCredentialScopeRepository.resolve` |
| LIVE authority (#413) | `src/executor/execution_live_authority_v1.py::require_execution_live_authority_v1` / `ExecutionLiveAuthorityRepositoryV1` |
| Kill switch (#413) | `src/executor/execution_kill_switch_v1.py::ExecutionKillSwitchRepositoryV1` |
| Submission orchestrator (#206) | `src/executor/execution_submission_orchestrator_v1.py::submit_execution_plan` |
| Bitvavo adapter (#206) | `src/executor/bitvavo_order_adapter_v1.py` |
| Reconciliation (#206) | `src/executor/execution_order_reconciliation_v1.py::reconcile_execution_leg` |

Canonical boundary narrative for the shared substrate is already documented in
`docs/architecture/algorithmic_executor_boundary_v1.md`; this document does
not duplicate it and instead records the #392-specific gap and readiness
state on top of it.

## Missing live link (Phase B finding)

There is currently **no adapter/intake boundary at all** between #392's
immutable `AutomaticExitPlanV1` and #206's shared executor substrate:

- `src/exit_policy/automatic_exit_runtime_orchestrator_v1.py` calls the
  planner, then writes the plan only as `immutable_plan_json` into the
  append-only runtime audit table
  (`src/exit_policy/automatic_exit_runtime_audit_writer_v1.py`). It never
  imports `src/executor`, never constructs an `ApprovedExecutionPlanV1`, and
  never calls `ExecutionHandoffRepositoryV1`.
- `grep -rn "AutomaticExitPlanV1\|automatic_exit_planner_v1" src/executor/`
  returns no matches; `src/executor` has no awareness #392 exists.
- This absence is enforced, not accidental:
  `tests/test_automatic_exit_runtime_architecture_guards_v1.py` asserts the
  Phase 4B runtime modules import none of `src.executor`, `src.manual_execution`,
  or `src.account_provisioning`. That guard is correct today and must stay
  correct until a real adapter module is deliberately introduced and its own
  guard test updated to permit exactly one crossing point.

**Exactly one explicit adapter/intake boundary is still required**: a new
module (not created by this audit) that reads an already-approved
`AutomaticExitPlanV1`, maps it field-for-field into `ApprovedExecutionPlanV1`
(`plan_source`, `plan_reference_id`, `trading_account_id`, `venue`, `market`,
`side`, `legs`), and calls the existing `ExecutionHandoffRepositoryV1.intake`
(DRY_RUN/PAPER) or `.intake_live_authorized` (LIVE). `tests/
test_automatic_exit_plan_shared_handoff_compatibility_v1.py` (added by this
audit) proves the field mapping is lossless and side/price/quantity/leg-count
preserving for both REDUCE and EXIT — i.e. the two contracts are compatible —
without adding that production adapter. It also documents a real, minor
contract note: `ApprovedExecutionPlanV1`'s content hash intentionally carries
no REDUCE/EXIT or evidence provenance (only account/venue/market/side/legs),
so a real adapter must derive `plan_reference_id` from evidence that is
already unique per evaluation cycle (e.g. `evidence_id`) to preserve
idempotency/audit traceability; it must not rely on the shared content hash
for that purpose.

**A second, independently blocking finding**: even with that adapter built,
`src/decision_gate/automatic_exit_gate_v1.py`
(`_evaluate_automatic_exit_candidate_permission_base_v1`, line ~189) contains:

```python
if context.live_trading_enabled or context.account_mode != "paper":
    return _decision(STATE_DENIED, REASON_LIVE_EXECUTION_NOT_GRANTED, candidate)
```

This is deliberate, tested Phase 2 behavior
(`tests/test_automatic_exit_gate_v1.py::test_account_disabled_live_enabled_and_non_paper_modes_are_denied`)
and is not a bug: the automatic-exit gate contract itself is DRY_RUN/PAPER-only
by construction today. A LIVE automatic-exit candidate cannot reach
`STATE_APPROVED` through this gate at all until this contract is deliberately
extended for a LIVE mode, under its own explicit, reviewed change — not as a
side effect of building the executor adapter.

## Account protection (#318) wiring (Phase C finding)

The pure contract composition is correct and already tested at the gate-unit
level:

- `PROTECTION_BLOCKED_ACTIONS` in `account_protection_contract_v1.py` blocks
  only `ACTION_BUY` for the five automated risk protections
  (`MAX_ACCOUNT_DRAWDOWN_BLOCK`, `DAILY_REALIZED_LOSS_BLOCK`,
  `REPEATED_STOPLOSS_BLOCK`, `LOW_PROFIT_ASSET_COOLDOWN`,
  `POST_CLOSE_REENTRY_COOLDOWN`); `MANUAL_ACCOUNT_LOCK` blocks
  `BUY`, `REDUCE`, and `EXIT`.
- `automatic_exit_gate_v1.evaluate_automatic_exit_candidate_permission_v1`
  composes an optional `AccountProtectionEvaluationV1` and can only turn an
  otherwise-approved decision into `DENIED`; it never inspects protection
  internals (`REASON_MANUAL_ACCOUNT_LOCK_ACTIVE`, etc. stay inside the
  protection module).
- `tests/test_automatic_exit_gate_v1.py::test_risk_increase_protection_does_not_deny_reduce_or_exit`
  and `::test_manual_lock_denies_reduce_and_exit_without_exit_policy_awareness`
  prove exactly REDUCE->REDUCE, EXIT->EXIT mapping with no protection logic
  inside `exit_policy` or `execution_planner`.

However, **the real runtime path never populates this evaluation**:
`AutomaticExitGateContextV1.account_protection_evaluation` defaults to `None`,
and `src/exit_policy/automatic_exit_runtime_orchestrator_v1.py` constructs
`AutomaticExitGateContextV1` without ever setting that field.
`grep -rn "account_protection" src/exit_policy/` returns no matches, and
`grep -rln "evaluate_account_protection_runtime_v1"` matches only
`src/decision_gate/account_protection_runtime_v1.py` itself and its own test
file. `RuntimeItemV1` (`automatic_exit_runtime_repository_v1.py`) has no
protection-fact fields at all. **#318 protections are therefore not enforced
on the real #392 path today** even though the contract and the pure runtime
evaluator both exist and are independently tested. Wiring a metric-fact/lock-fact
producer into the Phase 4B runtime is separate implementation work, not
performed by this audit.

## LIVE authority / kill switch (Phase D/E) — verified sufficient

`execution_live_authority_v1.py` binds trading_account_id, venue, side,
optional market (exact-match or `NULL` wildcard), executor_identity, and
runtime_owner, over a finite effective window (max 7 days), with append-only
grants and append-only revocations (immediate effect; future-dated revoke
rejected — `test_execution_live_authority_datetime_v1.py`). Absence of a
grant row denies (`EXECUTION_LIVE_AUTHORITY_NOT_GRANTED`); any repository,
validation, ambiguity, or read exception collapses to deny
(`require_execution_live_authority_v1`'s catch-all). The kill switch
(`execution_kill_switch_v1.py`) is an append-only event stream; `is_engaged()`
returns `False` only when the latest event's `state == DISENGAGED` or no event
exists (clear-by-default is correct only because authority itself remains
deny-by-default); a malformed row raises and is caught by the same catch-all
deny path. `execution_handoff_v1.intake_live_authorized` checks kill switch +
authority after credential resolution and before persisting the LIVE handoff
row; no #392-specific bypass exists because no #392 caller reaches this path
at all yet (see missing-link finding above).

## Credential binding (Phase F) — verified sufficient

`execution_credential_scope_v1.ExecutorCredentialScopeRepository.resolve`
requires an exact `(trading_account_id, venue, executor_identity,
runtime_owner)` match with `binding_status=ACTIVE`, `permission_scope=
TRADE_EXECUTION`, `credential_status=ACTIVE`, `allowed_order_write=True`,
`allowed_withdrawal=False`; any non-exact match (0 or >1 rows) denies. No
fallback and no cross-account row can satisfy the join. This audit
provisioned no credential.

## Plan immutability (Phase G) — verified sufficient, mechanism reused

`execution_submission_orchestrator_v1._validated_persisted_handoff`
recomputes `ApprovedExecutionPlanV1.content_hash` from the plan passed to
submission and compares it against the DB-persisted handoff's stored
`plan_content_hash`, `plan_source`, `plan_reference_id`, account, venue,
market, and side. The submission orchestrator never recomputes quantity,
price, spacing, side, market, or leg count from the plan; it only reads
`plan.legs` as given. `tests/
test_automatic_exit_plan_shared_handoff_compatibility_v1.py` adds the #392-side
half of this proof (planner output -> shared reference is lossless and
hash-stable); the #206-side half (`ApprovedExecutionPlanV1` self-hash
stability/tamper-detection) is already covered by
`tests/test_execution_plan_reference_v1.py`.

## Reconciliation / crash safety (Phase H) — verified, no SELL-specific fork needed

`execution_order_reconciliation_v1.py` and `execution_submission_orchestrator_v1.py`
are side-neutral (parametrized `side in {"BUY","SELL"}` throughout
`tests/test_execution_live_authority_v1.py`, `tests/test_execution_handoff_v1.py`).
`SUBMISSION_UNCERTAIN` -> reconciliation lookup -> `RECONCILIATION_REQUIRED` on
confirmed absence; a concurrent `RECONCILIATION_REQUIRED` wins over a late
placement acknowledgement; there is no rearm path back to `PREPARED` and no
automatic second POST (`execution_submission_orchestrator_v1._resolve_leg`,
`execution_order_reconciliation_v1.reconcile_execution_leg`). No SELL-specific
fork exists or is needed for #392; the deterministic `clientOrderId` and
duplicate-claim (`claim_submission`) protections are already shared.

## Runtime owner / deployment topology (Phase I)

- `AUTOMATIC_EXIT_POLICY_RUNTIME` capability: owner `gurkdb`, entrypoint
  `python -m src.exit_policy.run_automatic_exit_policy_once_v1`, host-local
  flock at `~/.local/state/synth/runtime/locks/automatic-exit-policy-runtime.lock`,
  `activation_status: PLANNED` (`deploy/ownership/account_runtime_capability_ownership_v1.json`).
  Per Issue #392 comment history, a 5-minute cadence is the accepted planned
  direction; no systemd timer exists yet.
- No shared-executor runtime capability entry exists in the ownership registry
  at all (deliberately `UNASSIGNED` per the #206 PR3 issue comment). There is
  therefore no competing owner and no duplicate scheduler today, but also no
  registered LIVE executor runtime owner to activate against.
- Intended activation topology (documentation only, nothing enabled):
  `gurkdb` runs the #392 policy runtime on its planned cadence, writing only
  to the append-only Phase 4B audit table. A future, separately owned
  executor-invocation runtime (owner TBD, likely `gurkdb` for symmetry with
  its DB-local read model, but not yet decided) would poll `STAGED` audit
  rows, run them through the new adapter into `ExecutionHandoffRepositoryV1`,
  and only that runtime would ever hold TRADE_EXECUTION credentials or call
  Bitvavo.

## Production prerequisite checklist (Phase J)

Every row must be independently verified true immediately before activation;
any missing row is NO-GO. This audit performed no DB reads/writes and
verifies repository-level state only.

| # | Prerequisite | State at base SHA |
| --- | --- | --- |
| 1 | Required migrations present in repo | YES — `db/migrations/20260817_executor_live_authority_v1.sql` plus prior #206 migrations exist |
| 2 | Required migrations applied on the production host | NOT VERIFIED — no DB connection made by this audit; must be confirmed on `gurkdb` before activation |
| 3 | Canonical account exists | NOT VERIFIED — requires DB read on `gurkdb` |
| 4 | Automatic-exit planning permission exists (fresh) | NOT VERIFIED — runtime-dependent, not a static repo fact |
| 5 | Fresh automatic-exit profile exists | NOT VERIFIED — runtime-dependent |
| 6 | Fresh aligned account evidence exists | NOT VERIFIED — runtime-dependent |
| 7 | Account protection producer/configuration state resolved | **NO** — no producer wires `account_protection_runtime_v1` into the #392 runtime path (see Phase C finding); this alone is a hard blocker |
| 8 | TRADE_EXECUTION credential exists and exact binding verified | NOT PROVISIONED (by design/prohibition of this audit); contract verified sufficient |
| 9 | #392 SELL LIVE authority row exists and is effective | **NO** — zero authority rows exist or are authorized by this audit; also blocked by missing adapter and gate's paper-only contract |
| 10 | Kill switch state authoritative and clear | NOT VERIFIED — runtime-dependent; mechanism verified fail-closed |
| 11 | Executor/runtime ownership unique | PARTIAL — #392 policy runtime owner is registered (`gurkdb`, PLANNED); no executor-invocation runtime owner is registered yet |
| 12 | Reconciliation state clean | NOT VERIFIED — runtime-dependent |
| 13 | No `SUBMISSION_UNCERTAIN` unresolved | NOT VERIFIED — runtime-dependent |
| 14 | Broker/open-order evidence reconciled | NOT VERIFIED — runtime-dependent |
| 15 | LIVE service/timer explicitly enabled | **NO** — no timer exists for either the policy runtime or a future executor-invocation runtime |
| 16 | Rollback/revoke procedure verified | Documented below (Phase K); not yet exercised end-to-end |

## Rollback / emergency stop (Phase K)

1. Engage the global kill switch immediately:
   `ExecutionKillSwitchRepositoryV1.append_event(state="ENGAGED", actor=..., reason=...)`.
   This alone force-denies every future LIVE submission across every account/venue/side,
   independent of any authority grant.
2. Revoke the specific #392 SELL authority grant:
   `ExecutionLiveAuthorityRepositoryV1.revoke(grant_id=..., revoked_by=..., revocation_reason=...)`.
   Revocation is immediately effective (no future-dated revoke is possible) and append-only.
3. New submissions stop at `require_execution_live_authority_v1` (kill switch
   and/or authority now denies); already-`PREPARED`/`SUBMITTING` legs in
   flight are unaffected by the kill switch/authority check itself, since that
   check runs before placement, not after.
4. **Already-open broker orders are not automatically cancelled.** Nothing in
   #206's canonical path (`docs/architecture/algorithmic_executor_boundary_v1.md`)
   owns automatic cancellation; this audit does not invent one. They must be
   reconciled (`reconcile_execution_leg` / Get Order) and, if still open,
   cancelled manually through an explicitly authorized, separate action.
5. Reconcile authoritative broker state for every `SUBMISSION_UNCERTAIN` /
   `RECONCILIATION_REQUIRED` leg before declaring the account clean.
6. Disable the runtime/service only after authority is revoked and the kill
   switch is engaged, never before — disabling the runner first only stops
   new cycles, it does not deny an in-flight or already-authorized submission
   path the way the kill switch does.
7. Never delete `executor_execution_handoff`, `executor_leg`,
   `executor_live_authority_grant/revocation`, `executor_kill_switch_event`,
   or the Phase 4B audit rows; they are the append-only audit trail.

## First-live bound recommendation (Phase L)

Smallest safe first activation, once every Phase J row is independently
verified and the missing adapter + gate LIVE-mode work (Phase B) has been
built and reviewed separately:

- One `trading_account_id`, `venue="bitvavo"`, `side="SELL"` only.
- The LIVE authority model **can** scope to one asset via the grant's
  `market` field (exact match beats the `NULL` wildcard row
  deterministically), so the first grant should use an exact `market`
  (e.g. one already-held position's market), not the wildcard. It **cannot**
  scope below market to one specific `position_reference`/lot — if a single
  account holds multiple distinct position lots in the same market, the
  authority grants both automatically. If narrower position-level scoping is
  required for the first activation, that is a real limitation of the current
  #413 authority model and would require widening the grant schema, which is
  out of scope for this audit and must not be done as a side effect of
  writing the runbook.
- Bounded authority window: shortest practical duration, well under the 7-day
  maximum, so the grant expires on its own even if revocation is missed.
- Minimal position/quantity/risk ceiling is already enforced upstream: the
  `automatic_exit_gate_v1` ceiling (`min(fraction * held, free_quantity,
  optional max_automatic_exit_quantity_base)`) and the venue's
  `min_base_quantity`/`qty_step_size` constraints in the planner. No new gate
  is required; use the existing `max_automatic_exit_quantity_base` context
  field for an explicit first-activation ceiling if an even tighter cap than
  the fraction/free-quantity ceiling is wanted.
- Monitor and reconcile immediately after: verify the audit trail, the
  handoff row, leg terminal states, and Bitvavo open-order state before any
  second cycle is allowed to run live.

## Test evidence (Phase M)

Added: `tests/test_automatic_exit_plan_shared_handoff_compatibility_v1.py`
(5 tests, explicitly test-scope-only, does not import into or from production
code) — proves REDUCE and EXIT planner output map losslessly onto the shared
`ApprovedExecutionPlanV1` reference (account/venue/market/side/leg
count/price/quantity all preserved), proves the mapped reference's content
hash is stable for identical input and changes for any leg-affecting field,
and documents that REDUCE/EXIT provenance is carried by `plan_reference_id`,
not the shared content hash.

The rest of the Phase M matrix (wrong account/venue/runtime-owner denied,
missing/expired/revoked authority denied, kill switch active/missing denied,
missing/mismatched credential denied, valid repository-only eligibility
without a broker call, duplicate invocation safe, `SUBMISSION_UNCERTAIN` no
second POST, shared reconciliation) is already covered by the existing,
side-neutral (`BUY`/`SELL`-parametrized) #206/#413 test suites — principally
`tests/test_execution_live_authority_v1.py`,
`tests/test_execution_live_authority_datetime_v1.py`,
`tests/test_execution_handoff_v1.py`,
`tests/test_execution_credential_scope_v1.py`,
`tests/test_execution_submission_orchestrator_v1.py`,
`tests/test_bitvavo_order_adapter_v1.py` — and REDUCE/EXIT compatibility at
the candidate/gate/planner level is already covered by
`tests/test_automatic_exit_candidate_v1.py`,
`tests/test_automatic_exit_gate_v1.py`, and
`tests/test_automatic_exit_planner_v1.py`. No SELL-specific fork of any #206
test was required or added, matching the side-neutral architecture.

Commands run for this audit:

```bash
python -m pytest tests/test_automatic_exit_candidate_v1.py tests/test_automatic_exit_gate_v1.py \
  tests/test_automatic_exit_planner_v1.py tests/test_automatic_exit_runtime_orchestrator_v1.py \
  tests/test_automatic_exit_runtime_architecture_guards_v1.py tests/test_execution_plan_reference_v1.py \
  tests/test_execution_handoff_v1.py tests/test_execution_live_authority_v1.py \
  tests/test_execution_credential_scope_v1.py tests/test_account_protection_contract_v1.py \
  tests/test_account_protection_runtime_v1.py tests/test_execution_submission_orchestrator_v1.py \
  tests/test_automatic_exit_plan_shared_handoff_compatibility_v1.py -q
# 193 passed
python -m py_compile tests/test_automatic_exit_plan_shared_handoff_compatibility_v1.py
git diff --check
```

Safety markers for this audit's own work (no repository code changed, tests
and docs only):

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
production_db_mutation=0
production_migration_apply=0
credential_provisioning=0
live_authority_provisioning=0
service_activation=0
timer_activation=0
```

## Go-live determination

`GO_LIVE_READY = NO`. Blocking, in priority order:

1. No adapter/intake boundary exists between #392's planner output and
   #206's shared executor handoff (Phase B).
2. `automatic_exit_gate_v1` is a DRY_RUN/PAPER-only contract by construction
   today (`REASON_LIVE_EXECUTION_NOT_GRANTED` on any non-paper mode); it
   cannot approve a LIVE candidate until deliberately extended.
3. #318 account protections are not wired into the real #392 runtime path
   (contract and pure evaluator both exist and are tested in isolation, but
   nothing calls the evaluator or supplies it to the gate context today).
4. No #392 SELL LIVE authority row exists (correctly — none was created by
   this audit) and no executor-invocation runtime owner is registered.
5. No LIVE service/timer exists for either lane.

None of items 1-3 can be resolved by a documentation or test-only change;
each requires its own explicitly authorized, reviewed implementation task.
