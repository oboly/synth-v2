# Issue #392 Phase 6 SELL LIVE-readiness audit

Date: 2026-08-17
Status: audit only; no LIVE activation performed or authorized by this document.

**Update (2026-08-17, same date, follow-on change):** blocker C (real #318
account-protection producer/configuration wiring) is now RESOLVED — see
"Account protection (#318) wiring (Phase C finding)" below, which is
rewritten in place to describe the real wiring rather than the gap. Blockers
A and B are unchanged and still block `GO_LIVE_READY`. No LIVE activation,
executor change, or broker authority was introduced by that follow-on
change; see its own safety markers where noted below.

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

**Exactly one explicit adapter/intake boundary is still required, and it must
be a typed, in-process application/runtime seam, not a persistence-mediated
one.** The canonical future topology is:

```text
canonical persisted evidence
-> #392 runtime evaluation
-> exit_policy candidate
-> decision_gate
-> execution_planner AutomaticExitPlanV1
-> explicit #392 execution-handoff adapter
-> #206 ExecutionHandoffRepositoryV1
-> authority / kill switch / credential
-> executor
```

The adapter (not created by this audit) must consume the already-produced
in-memory typed `AutomaticExitPlanV1` object at the deliberate runtime
boundary — i.e. it is called directly, in the same evaluation cycle, by
whatever orchestrates candidate -> gate -> planner -> handoff — and map it
field-for-field into `ApprovedExecutionPlanV1` (`plan_source`,
`plan_reference_id`, `trading_account_id`, `venue`, `market`, `side`, `legs`)
before calling the existing `ExecutionHandoffRepositoryV1.intake`
(DRY_RUN/PAPER) or `.intake_live_authorized` (LIVE). It must **not** obtain
its input by polling `automatic_exit_evaluation_audit_v1`, parsing
`immutable_plan_json` back out of that table, or otherwise reconstructing
planner intent from audit/reporting persistence — the append-only Phase 4B
audit table is runtime/audit evidence for replay and provenance only and must
never silently become an executor input queue. If crash/restart durability is
required between planner output and executor intake (e.g. the process dies
after planning but before handoff), that must be designed explicitly as part
of the future adapter/runtime task using canonical typed, idempotent handoff
semantics of its own — not by repurposing the Phase 4B audit table for it.
This is stated explicitly here so a future implementation does not casually
default to "read the STAGED audit row" as the path of least resistance.

`tests/test_automatic_exit_plan_shared_handoff_compatibility_v1.py` (added by
this audit) proves the field mapping is lossless and
side/price/quantity/leg-count preserving for both REDUCE and EXIT — i.e. the
two contracts are compatible — using the in-memory `AutomaticExitPlanV1`
object directly, without adding that production adapter and without touching
audit/reporting persistence. It also documents a real, minor contract note:
`ApprovedExecutionPlanV1`'s content hash intentionally carries no REDUCE/EXIT
or evidence provenance (only account/venue/market/side/legs), so the future
adapter must derive `plan_reference_id` from a canonical immutable #392
logical-evaluation identity that is (a) deterministic across retry/restart,
(b) different whenever the logical execution intent differs, and (c) traces
back to #392 evidence. This audit does not prescribe `evidence_id` or any
other field as that identity source, and does not invent a new ID scheme:
the exact identity source must be finalized by the adapter implementation
task itself, after auditing whether an existing #392 idempotency/evaluation
key (e.g. the Phase 4B audit table's own idempotency key derivation in
`automatic_exit_runtime_contract_v1.py`) already satisfies these three
properties or needs its own dedicated key.

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

**RESOLVED (2026-08-17 follow-on change).** `src/decision_gate/account_protection_evaluation_v1.py`
is now the single composition seam:
`src/exit_policy/automatic_exit_runtime_orchestrator_v1.py::evaluate_automatic_exit_runtime_item_v1`
calls `evaluate_account_protection_for_automatic_exit_v1(conn, ...)` for
every candidate before constructing `AutomaticExitGateContextV1`, and always
passes the typed `AccountProtectionEvaluationV1` result into
`AutomaticExitGateContextV1.account_protection_evaluation` — the field no
longer stays `None` on the real path. `requested_action` maps directly from
`candidate.candidate_action`; `sleeve_code` is always `None`; account-state
freshness is derived explicitly from the same aligned
`item.account_state_observed_ts_utc` the runtime already loaded (no second
snapshot query, no implicit `fresh=True`).

This closes two previously-open sub-gaps:

- **Configuration ownership.** No durable, versioned, account-scoped
  protection-configuration persistence existed before this change. It now
  does: `src/decision_gate/account_protection_policy_contract_v1.py` (pure
  resolver) + `src/decision_gate/account_protection_policy_repository_v1.py`
  (DB reads) + the append-only `account_protection_policy_config_v1` table
  (migration artifact only, not applied:
  `db/migrations/20260817_account_protection_policy_config_v1.sql`). No
  effective row, an ambiguous overlap, or an unsupported `config_version` all
  resolve to a typed `BLOCKED` evaluation
  (`PROTECTION_CONFIGURATION_UNRESOLVED`) rather than raising or silently
  permitting. **Operational consequence:** an account with no provisioned
  policy config row can no longer reach an `APPROVED` automatic-exit gate
  decision at all — provisioning at least a permissive (all-thresholds-`None`)
  config row per account is now a prerequisite for automatic-exit candidates
  to stage a plan, in addition to the existing automatic-exit planning
  permission row.
- **Persisted lock facts.** `account_protection_repository_v1.load_protection_lock_facts_for_account_v1`
  is called for exactly the candidate's `trading_account_id`; manual locks and
  cooldowns already flow correctly end-to-end.

**Still open, deliberately not addressed by this change:** no canonical
metric-fact producer exists for `MAX_ACCOUNT_DRAWDOWN`, `DAILY_REALIZED_LOSS`,
or `REPEATED_STOPLOSS_STREAK`. The composition seam always supplies an empty
`metric_facts` tuple; if a future config row enables one of those thresholds
without a producer, the existing P2 evaluator fails closed on its own
(`REQUIRED_PROTECTION_METRIC_MISSING`) rather than this seam fabricating a
value. Building that producer (and, if desired, deriving metric-based locks)
remains separate implementation work and a real remaining item, tracked here
rather than silently worked around.

Audit provenance: the append-only `automatic_exit_evaluation_audit_v1` table
gained two nullable columns, `protection_code` and `protection_reason_code`
(migration artifact only, not applied, same file as above), populated on
every audit write from the gate decision's own protection fields — review
evidence only, never an executor input, never protection configuration truth,
and never a mutation of the table's append-only/idempotency semantics
(`gate_state`/`gate_reason_code` already carried the decisive outcome; these
two columns close the smallest deterministic provenance gap: which protection,
if any, evaluated and permitted an otherwise-approved decision).

Tests added: `tests/test_account_protection_policy_contract_v1.py`,
`tests/test_account_protection_policy_repository_v1.py`,
`tests/test_account_protection_evaluation_v1.py`, plus real-wiring cases
appended to `tests/test_automatic_exit_runtime_orchestrator_v1.py` (REDUCE/EXIT
with no active protection, drawdown-lock permits REDUCE/EXIT, manual lock
denies REDUCE/EXIT, unresolved config fails closed, missing metric producer
fails closed, cross-account isolation, real gate context populated, no
executor/broker imports) and a binding-mismatch case appended to
`tests/test_automatic_exit_gate_v1.py`.

Safety markers for this follow-on change:

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
production_db_mutation=0
production_migration_apply=0
executor_adapter=0
executor_calls=0
credential_provisioning=0
live_authority_provisioning=0
service_activation=0
timer_activation=0
```

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
  `gurkdb` runs the #392 policy runtime on its planned cadence. Each
  evaluation cycle still writes its append-only Phase 4B audit row for
  replay/provenance, exactly as today, and separately — in the same
  in-process cycle, not via a second process reading that table back — calls
  the future typed #392 execution-handoff adapter directly with the
  in-memory `AutomaticExitPlanV1` it just produced, which then calls
  `ExecutionHandoffRepositoryV1`. There is exactly one runtime process per
  cycle, not a producer/consumer pair connected through the audit table.
  Owner of that combined runtime is TBD (likely `gurkdb` for symmetry with
  its DB-local read model, but not yet decided); only that runtime would ever
  hold TRADE_EXECUTION credentials or call Bitvavo. A future design may still
  split candidate/gate/planner evaluation from handoff/execution into two
  processes, but if so the hand-off between them must be its own explicit,
  typed, idempotent contract designed for that purpose (see the adapter note
  above) — not the Phase 4B audit table repurposed as a queue.

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
| 7 | Account protection producer/configuration state resolved | **PARTIAL** — the real #392 path now wires `account_protection_runtime_v1` via `account_protection_evaluation_v1.py` and a durable config contract exists (see Phase C finding, RESOLVED 2026-08-17), but no policy config row is provisioned on any production account yet (NOT VERIFIED — runtime-dependent) and no metric-fact producer exists for `MAX_ACCOUNT_DRAWDOWN`/`DAILY_REALIZED_LOSS`/`REPEATED_STOPLOSS_STREAK`; a missing config row now fails closed rather than silently permitting |
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

`GO_LIVE_READY = NO`.

Three actual Phase 6 blockers were identified. Blocker C is now RESOLVED (see
Phase C finding above); blockers A and B remain open, each its own explicitly
authorized, reviewed implementation task — neither resolvable by a
documentation or test-only change:

- **A. #392 -> #206 typed adapter / runtime seam.** No adapter/intake
  boundary exists between #392's in-memory planner output and #206's shared
  executor handoff (Phase B). It must be the typed, in-process seam described
  above — not a persistence-mediated one built on top of the Phase 4B audit
  table.
- **B. Reviewed LIVE-capable extension of the automatic-exit `decision_gate`.**
  `automatic_exit_gate_v1` is a DRY_RUN/PAPER-only contract by construction
  today (`REASON_LIVE_EXECUTION_NOT_GRANTED` on any non-paper mode); it
  cannot approve a LIVE candidate until deliberately extended.
- ~~**C. Real #318 account-protection producer/configuration wiring into the
  #392 runtime.**~~ **RESOLVED 2026-08-17.** The real #392 runtime
  orchestrator now calls the P2 evaluator through
  `account_protection_evaluation_v1.py` and supplies its result to the gate
  context on every evaluation; a durable, versioned, account-scoped
  configuration contract now exists and fails closed when unresolved. No
  metric-fact producer exists yet for `MAX_ACCOUNT_DRAWDOWN`/
  `DAILY_REALIZED_LOSS`/`REPEATED_STOPLOSS_STREAK` — tracked as a real
  remaining item (see Phase C finding), but it does not block manual-lock/
  cooldown protection from being enforced today, and it fails closed rather
  than silently permitting if a future config ever enables it without a
  producer.

Required dependency ordering — each step depends on the previous one being
merged and reviewed, and no step authorizes skipping ahead:

1. ~~Account-protection producer/wiring (blocker C)~~ — DONE. Establishes the
   real permission signal the gate needs before it can be trusted to approve
   anything at all, LIVE or otherwise. Provisioning a policy config row per
   production account (and, if wanted, a metric-fact producer) remains a
   prerequisite operational/implementation step before automatic-exit
   candidates on those accounts can reach `APPROVED` again.
2. LIVE-capable gate contract (blocker B) — only once account-protection
   composition is real should the gate's paper-only restriction be
   deliberately extended for LIVE.
3. Typed planner -> shared-handoff adapter/runtime seam (blocker A) — only
   once the gate can correctly produce a LIVE-eligible `APPROVED` decision
   does connecting the planner's output to #206 become meaningful; building
   the adapter first, against a gate that can never approve LIVE, would
   invite exactly the kind of premature/implicit coupling this audit warns
   against.
4. Final repository-level integrated non-broker acceptance — an end-to-end
   DRY_RUN/PAPER exercise of candidate -> gate (with real protections) ->
   planner -> adapter -> handoff, still with zero broker calls, zero
   authority rows, zero credentials.
5. Only then: work through the Phase J production activation checklist and a
   separately authorized LIVE activation decision. No step in this ordering
   authorizes LIVE by itself, including this one.

Additionally, and independent of that ordering: no #392 SELL LIVE authority
row exists (correctly — none was created by this audit), no
executor-invocation runtime owner is registered, and no LIVE service/timer
exists for either lane. Those remain Phase J/K activation-time concerns, not
implementation blockers in themselves.
