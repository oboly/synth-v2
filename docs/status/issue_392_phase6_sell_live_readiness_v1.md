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

**Update (2026-08-18, blocker A implementation):** blocker A (the #392 ->
#206 typed adapter/runtime seam) is now RESOLVED in software — see
"Go-live determination" below. `src/execution_planner/
automatic_exit_execution_handoff_adapter_v1.py` provides a pure, lossless
`AutomaticExitPlanV1 -> ApprovedExecutionPlanV1` mapping with a deterministic,
retry-stable, evidence-traceable `plan_reference_id`;
`automatic_exit_execution_handoff_application_v1.py` selects
`ExecutionHandoffRepositoryV1.intake` (DRY_RUN/PAPER) or
`.intake_live_authorized` (LIVE) without duplicating #206's credential/LIVE-
authority/kill-switch checks; `src/exit_policy/
run_automatic_exit_policy_with_handoff_once_v1.py` is the new composition
root that wires the real candidate -> account-protection -> gate -> planner
runtime path to this seam, consuming only the in-memory
`RuntimeItemOutcomeV1.plan` from the same evaluation cycle -- never
`automatic_exit_evaluation_audit_v1.immutable_plan_json`. The existing
audit-only `run_automatic_exit_policy_once_v1.py` runner and its
architecture guard (forbidding `src.executor` imports) are unchanged. This
resolves `SOFTWARE_PHASE6_BLOCKERS=0`; `GO_LIVE_READY` remains `NO` — see
"Go-live determination" for the unchanged remaining prerequisites
(migration/provisioning/deployment/authorization). No LIVE activation,
credential provisioning, LIVE authority provisioning, kill-switch mutation,
service/timer activation, or broker call was performed or authorized by
this change.

**Update (2026-08-19, item 4 CLOSED — real repository-level acceptance PASS,
revision 3 — supersedes the revision-1/2 notes below):** with an explicit
disposable-only MariaDB grant now in place
(`GRANT ALL PRIVILEGES ON \`synth_acceptance_437\`.* TO
'synth'@'192.168.1.%'`), re-ran the same acceptance prepared in the
revision-1/2 notes and it **passed against the real repository and real
schema**. `CREATE DATABASE synth_acceptance_437` succeeded on the first
attempt with this grant (no broader privilege was needed or requested).
`SELECT DATABASE()` was verified equal to `synth_acceptance_437` before
every schema/seed/write step; every cursor factory used by the acceptance
script hard-fails if any call is ever routed at a database other than
`synth_acceptance_437`.

Read-only production `synth` snapshots taken before, during (after all
disposable writes, before `DROP DATABASE`), and after cleanup are byte-for-
byte identical: account mapping is exactly one row (`account_id=1 ->
trading_account_id=3`), `trading_account_id=3` still has
`live_trading_enabled=0`, and `executor_execution_handoff` still does not
exist as a table in production `synth` at all (its migration remains
`CREATED_NOT_APPLIED` there) — so production had, and still has, nothing to
mutate. Zero writes were issued against `synth`.

Applied the exact minimal migration dependency closure identified in the
prior revision into `synth_acceptance_437` only: (1) a minimal synthetic
`trading_account` PK-only stand-in (`trading_account_id=9900437`); (2)
`db/migrations/20260609_trading_account_credential_v1.sql`; (3)
`db/migrations/20260721_account_credential_binding_contract_v1.sql`; (4) only
the `uq_tac_credential_identity_v1` unique-key add and the
`executor_credential_binding` table from
`db/migrations/20260812_manual_execution_executor_handoff_v1.sql`; (5)
`db/migrations/20260815_shared_executor_substrate_v1.sql` in full. Seeded one
synthetic, non-secret `trading_account_credential` row (`permission_scope=
TRADE_EXECUTION`, `encrypted_envelope='{"synthetic":"acceptance-437-no-
secret"}'`, no real API key/secret material) and one matching
`executor_credential_binding` row for `executor_identity=
acceptance_437_executor` / `runtime_owner=acceptance_437_runtime`.

Built a real, canonical, typed `AutomaticExitPlanV1` through
`build_automatic_exit_plan_v1(decision=..., context=...)` — the same
constructor and fixture shape used by
`tests/test_automatic_exit_execution_handoff_adapter_v1.py` — for synthetic
`trading_account_id=9900437`, `venue=bitvavo`, `market=SOL-EUR`, `side=SELL`,
`candidate_action=REDUCE`, gate approval `state=APPROVED`. Never
deserialized from `automatic_exit_evaluation_audit_v1` or any audit/reporting
JSON. Passed it through the real, unmodified
`adapt_automatic_exit_plan_to_approved_execution_plan_v1` (#432) into a real
`ApprovedExecutionPlanV1`, then through the real, unmodified
`ExecutionHandoffRepositoryV1.intake(..., executor_mode="DRY_RUN", ...)` —
`intake_live_authorized()` was never called.

All four acceptance cases passed against the real `executor_execution_handoff`
table in `synth_acceptance_437`:

- **Case A (initial handoff):** `plan_reference_id=
  automatic_exit_v1:9900437:acc437-pos:acc437-ev1:d97f45c7...` persisted as
  `executor_execution_handoff_id=1`; row count went 0 -> 1; the persisted
  row's `trading_account_id`, `venue`, `market`, `side`, and `executor_mode`
  match the typed plan and `ApprovedExecutionPlanV1` exactly (venue, market,
  side, leg indices/prices/quantities all preserved losslessly — no
  replanning, re-rounding, or quantity recomputation anywhere in the path).
- **Case B (idempotent retry):** the exact same logical plan, rebuilt fresh
  from the planner (not reused in-memory), produced the identical
  `plan_reference_id` and resolved to the identical
  `executor_execution_handoff_id=1`; row count stayed at 1 — no duplicate
  handoff.
- **Case C (distinct logical intent):** changing only
  `candidate_evidence_id` (`acc437-ev1` -> `acc437-ev2`) produced a distinct
  `plan_reference_id` and a new row (`executor_execution_handoff_id=2`); row
  count went 1 -> 2.
- **Case D (identity conflict):** reusing Case A's exact `plan_reference_id`
  with conflicting content (a different `market`) raised
  `ExecutionHandoffIdentityConflictError` and failed closed; row count stayed
  at 2 — no corrupted or ambiguous row was written.

After evidence capture, `DROP DATABASE synth_acceptance_437` was executed
and `SHOW DATABASES LIKE 'synth_acceptance_437'` confirmed zero rows
afterward — zero acceptance residue. Zero broker calls, zero private-API
calls, zero order submission, zero LIVE intake at any point.

`REPOSITORY_LEVEL_ACCEPTANCE=PASS`. `SOFTWARE_PHASE6_BLOCKERS_REMAINING=0`.
`GO_LIVE_READY` remains `NO` — this is software/repository acceptance only,
not production LIVE authorization; production migration apply, executor
credential provisioning, LIVE authority provisioning, kill-switch
authoritative state, deployment, and an explicit user LIVE activation
decision all remain outstanding and unauthorized by this update. Item 4 in
the dependency ordering below is now closed; only item 5 (the Phase J
production activation checklist and a separately authorized LIVE activation
decision) remains.

**Update (2026-08-18, same branch, correctness fix, revision 1):** the
initial blocker-C migration made `account_protection_policy_config_v1`
fully immutable (`BEFORE UPDATE` unconditionally rejected), which made the
resolver's own supersession contract impossible to satisfy in practice — an
open-ended (`effective_until_ts_utc IS NULL`) config row could never be
closed, so any second row for the same account would overlap the first
forever and the account would be permanently stuck failing closed
(`AMBIGUOUS_PROTECTION_CONFIGURATION`) the moment a threshold needed to
change. A first fix permitted one narrow `UPDATE` transition (closing the
open window). Re-review found that still violated the required strictly
append-only architecture for this table.

**Update (2026-08-18, same branch, correctness fix, revision 2 — supersedes
revision 1):** config rows are now permanently immutable with no update
exception of any kind. Supersession/ending is instead expressed through a
new, separate, immutable, append-only
`account_protection_policy_config_revocation_v1` table (config id,
denormalized account id, `revocation_version`, `effective_ts_utc`, `actor`,
`reason`) — itself `UPDATE`/`DELETE`-rejecting. `resolve_account_protection_policy_v1`
now takes both config rows and revocation facts: a config row is revoked at
evaluation time `T` if *any* of its revocation facts has
`effective_ts_utc <= T`. Multiple revocation facts per config row are valid
by design so a future-scheduled revocation can never block a later,
immediate one. Malformed revocations (dangling config reference, effective
timestamp at/before the config's own start, empty `actor`/`reason`),
cross-account corruption, and an unsupported `revocation_version` all fail
closed. Superseding a config is now: insert a revocation fact for the old
row, then insert the new config row — never an `UPDATE`. This revision also
fixes a second, independent gap found in the same re-review:
`AccountProtectionPolicyConfigRowV1` was missing `source_provenance` even
though the DB row already persisted it; the repository now loads it and the
resolver validates it non-empty on the winning row (audit trail only, never
threshold semantics). See `docs/architecture/account_protection_contract_v1.md`'s
"Real #392 wiring" section and the rewritten
`tests/test_account_protection_policy_config_mariadb_ddl_v1.py` (registered
in `pr_mariadb_ddl_validation.yml`) for the corrected lifecycle proved
against a disposable MariaDB schema. Migration remains an artifact only (not
applied); no DB write, credential, authority, executor, or broker change.

**Update (2026-08-18, same branch, correctness fix, revision 3):** a further
re-review found the revocation table's cross-account binding was enforced
only by the resolver, not by MariaDB, because the two foreign keys (config
id, and a separately denormalized account id) could independently be valid
while still pairing one account's config with another account's id.
Revocation identity is now bound by `(account_protection_policy_config_id,
trading_account_id)`: `account_protection_policy_config_v1` gained a
`UNIQUE KEY` on that pair, and the revocation table's foreign key became the
matching composite `FOREIGN KEY` against it, replacing the two independent
single-column foreign keys. A structurally corrupt revocation is now
rejected by MariaDB itself at `INSERT` time; the resolver's own mismatch
check is retained as defense-in-depth, not the sole enforcement point. No
Python repository/resolver change was required. Same migration file edited
in place (still an artifact only, not applied); no DB write, credential,
authority, executor, or broker change.

**Update (2026-08-18, new branch, blocker B implementation):** blocker B
(reviewed LIVE-capable extension of the automatic-exit `decision_gate`) is
now RESOLVED — see "LIVE-capable decision-gate extension (Phase B finding,
RESOLVED)" below, which rewrites the former "Missing live link (Phase B
finding)" gate half of this document in place (the #392 -> #206 adapter half
of that finding, blocker A, is unchanged and still open — see that section's
new note). This change makes the `decision_gate` contract LIVE-*capable*
only: it introduces explicit, typed, account-scoped, fail-closed decision-gate
LIVE permission evidence. It does not activate LIVE trading, does not touch
the executor, and does not introduce or call any executor operational LIVE
authority, kill switch, credential, or broker module. See its own safety
markers where noted below.

**Update (2026-08-18, same branch, PR #426 review fix):** cross-provider
review of the blocker-B implementation found two real merge blockers, both
now fixed in place (see "LIVE-capable decision-gate extension (Phase B
finding, RESOLVED)" below for the corrected shape):

1. **Lifecycle gap.** The initial `automatic_exit_live_decision_gate_permission_v1`
   table was described as append-only but had no DB-enforced immutability
   and no revocation mechanism — an open-ended `TRUE` grant could not be
   safely revoked without either mutating the row or creating an
   indefinitely overlapping second row. Fixed by adopting the same corrected
   lifecycle already proven for `account_protection_policy_config_v1`
   (see the revision-2/3 updates above): the permission row is now
   permanently immutable (`UPDATE`/`DELETE` always rejected by DB trigger),
   and ending or superseding an open-ended row is expressed exclusively
   through an immutable, append-only fact in a new companion table,
   `automatic_exit_live_decision_gate_permission_revocation_v1`, bound to
   its permission row by a composite `(permission_id, trading_account_id)`
   foreign key so a cross-account revocation is rejected by MariaDB itself.
2. **Ownership leak.** `src/exit_policy/automatic_exit_runtime_repository_v1.py`
   (exit_policy) had started importing and resolving decision-gate LIVE
   permission directly, making exit_policy runtime infrastructure a second
   owner of permission semantics. Fixed by removing those imports/fields
   entirely from the exit_policy repository and introducing a new
   decision_gate-owned composition seam,
   `src/decision_gate/automatic_exit_live_permission_evaluation_v1.py`
   (mirroring `account_protection_evaluation_v1.py` exactly), which the
   orchestrator now calls directly and forwards unchanged into the gate
   context — exit_policy never resolves LIVE permission itself, matching
   its existing relationship to `account_protection_evaluation`.

**Update (2026-08-18, same branch, PR #426 second review fix):** a further
review found the gate trusted the typed
`AutomaticExitLivePermissionEvaluationV1` object's own claims too readily —
it checked only `trading_account_id` and `decision_state`, which is
insufficient for a safety-critical decision-gate permission artifact. A
malformed, stale, future-dated, unsupported-version, or structurally
incomplete `GRANTED` evaluation could reach the gate merely because its
account id and `decision_state` happened to match. Fixed by adding a
decision_gate-owned binding validator,
`automatic_exit_live_permission_evaluation_v1.validate_automatic_exit_live_permission_evaluation_binding_v1`,
mirroring `account_protection_contract_v1.validate_account_protection_evaluation_binding_v1`
exactly: it independently checks the evaluation's `evaluation_contract_version`,
that `trading_account_id` matches, that `decision_state` is a supported
value, that `evaluated_ts_utc` is timezone-aware and *exactly* equal to the
gate context's own `evaluation_ts_utc` (rejecting stale reuse and
future-dating alike — no tolerance window), and — for a `GRANTED`
evaluation specifically — that `permission_id` is present and positive,
`permission_version` is the supported contract version, and `reason_code`
is the canonical `OK` value. The gate calls this validator before accepting
a LIVE permission evaluation; any failure denies with the existing
`REASON_LIVE_PERMISSION_EVALUATION_BINDING_MISMATCH` reason code. The gate
still does not re-resolve DB permission and does not duplicate persistence
logic — it validates the shape and binding of the object it was handed, the
same division of responsibility the protection composition already uses.

No LIVE activation, executor change, or broker authority was introduced by
this fix; see its own safety markers where noted below.

**Update (2026-08-19, same branch, PR #432 review fix, mode-integrity):** a
further independent review found
`run_automatic_exit_policy_with_handoff_once_v1.py` exposed `--executor-mode
DRY_RUN|PAPER|LIVE` as caller-selectable overrides. Allowing `PAPER` or `LIVE`
as an explicit override would let a caller decouple executor mode from the
`account_mode`/`decision_gate` path that actually produced the approved plan
— e.g. a paper account's plan reaching `intake_live_authorized`, or a live
account's plan reaching ordinary PAPER intake, neither of which the gate or
planner ever authorized. **Canonical rule:** normal `executor_mode` is
derived exclusively from the account's own canonical `account_mode`
(`paper` -> `PAPER`, `live` -> `LIVE`) via
`resolve_automatic_exit_executor_mode_v1`; the only permitted explicit
override is `DRY_RUN`, a deliberate non-production acceptance/testing
override, never a production execution mode. Fixed by restricting the CLI
parser's `--executor-mode` `choices` to `DRY_RUN` only, and defensively
inside `run_cycle_with_handoff` itself (`executor_mode_override not in
(None, RUNTIME_MODE_DRY_RUN)` raises `AutomaticExitExecutorModeError`) so a
direct Python caller cannot bypass the CLI restriction. This does not change
executor operational LIVE authority, credential binding, or kill-switch
ownership, which remain independently owned by #206's `intake_live_authorized`
path. See the matching canonical statement in
`docs/architecture/algorithmic_executor_boundary_v1.md`. No LIVE activation,
production migration, credential/authority/kill-switch provisioning, service/
timer activation, or broker call was performed or authorized by this fix.

**Update (2026-08-29, Issue #588, canonical write path for
`automatic_exit_live_decision_gate_permission_v1`):** the module described in
the "LIVE-capable decision-gate extension" section below
(`automatic_exit_live_permission_repository_v1.py`) was read-only-only prior
to this change; there was no reviewed grant/insert path at all. This change
adds the canonical, narrowly-scoped, append-only grant path, still without
performing any production grant or LIVE activation:

- `automatic_exit_live_permission_repository_v1.py` gained exactly one write
  function, `insert_automatic_exit_live_decision_gate_permission_v1` (a bare
  single-row `INSERT`, no read-modify-write, no eligibility logic of its
  own — the DB triggers still reject every `UPDATE`/`DELETE` unconditionally
  as a second, independent enforcement layer), and one new read function,
  `load_trading_account_live_readiness_v1` (account existence/`account_mode`/
  `enabled`/`live_trading_enabled` only; optional `FOR UPDATE` row lock to
  serialize concurrent grant calls for the same account, mirroring
  `account_protection_policy_provisioning_v1._resolve_trading_account_id`).
- New service module `automatic_exit_live_permission_grant_v1.py` owns every
  eligibility, idempotency, and conflict decision: `trading_account` must
  exist, `enabled=1`, `account_mode='live'`, `live_trading_enabled=1`; the
  existing permission/revocation history is resolved through the unchanged
  pure contract resolver
  (`resolve_automatic_exit_live_decision_gate_permission_v1`) at the request
  timestamp. An already-effective `GRANTED` row returns `ALREADY_GRANTED`
  (idempotent, no new row); an active DENY fact or an ambiguous/overlapping
  (including future-dated) permission history fails closed
  (`CONFLICTING_LIVE_PERMISSION_STATE` / `OVERLAPPING_LIVE_PERMISSION_STATE`)
  rather than inserting. A new grant is always open-ended
  (`effective_until_ts_utc=NULL`, `live_execution_permitted=True`);
  revocation remains the wholly separate, pre-existing append-only
  revocation path and is not touched by this change.
- New ops CLI `run_grant_automatic_exit_live_permission_v1.py` with
  `--check` (read-only eligibility report) and `--apply` (performs the
  grant or reports `ALREADY_GRANTED`) modes; required input is
  `--trading-account-id` only — the CLI never accepts or prints an
  operator-supplied permission id, and holds no validation logic of its own
  (it only parses arguments, opens the DB connection, and prints the typed
  service result).
- No credential, account-binding, kill-switch, executor LIVE-authority, or
  broker/order code was touched; the grant module and CLI import none of
  `src.executor`, `src.credential`, or `src.kill_switch` (guarded by
  `tests/test_automatic_exit_live_permission_grant_v1.py::test_no_executor_credential_kill_switch_side_effects`).
  This remains decision-gate LIVE permission only, exactly as described
  above — it is not executor operational LIVE authority.
- `trading_account_id=5` is the canonical LIVE execution identity referenced
  by this task's context; **no grant was applied to any production account
  by this change** — the CLI was exercised only via `--help` and the full
  test suite below, never against a real database.

Tests added: `tests/test_automatic_exit_live_permission_grant_v1.py` (check
with no grant, first apply, idempotent already-granted, disabled account,
non-live account, `live_trading_enabled=0`, unknown account, conflicting
history, active-deny-blocks-grant, revocation-history interaction (grant
succeeds once the blocking deny fact is itself revoked), future-dated-row
overlap block, rollback-on-insert-failure leaves no row, accounts 2/3 never
touched, append-only — no `UPDATE`/`DELETE` ever issued across a grant plus
idempotent replay, no executor/credential/kill-switch import). The shared
sqlite test fixture `tests/automatic_exit_runtime_fixtures_v1.py` gained one
line stripping `FOR UPDATE` for sqlite compatibility (mirrors the existing
convention already used by
`tests/automatic_buy_account_allocation_evidence_fixtures_v1.py`); no other
fixture behavior changed.

Safety markers for this change:

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=automatic_exit_live_permission_grant_v1
execution_planner=none
executor=none
production_db_mutation=0
production_grant_applied=0
credential_mutation=0
kill_switch_mutation=0
executor_live_authority_grant=0
```

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

Building the adapter itself (blocker A) remains open and unchanged by this
document's blocker-B update; see "Go-live determination" below for current
ordering.

## LIVE-capable decision-gate extension (Phase B finding, RESOLVED)

**RESOLVED (2026-08-18).** Until this change,
`src/decision_gate/automatic_exit_gate_v1.py`
(`_evaluate_automatic_exit_candidate_permission_base_v1`) contained an
unconditional hard denial for any non-paper account:

```python
if context.live_trading_enabled or context.account_mode != "paper":
    return _decision(STATE_DENIED, REASON_LIVE_EXECUTION_NOT_GRANTED, candidate)
```

This was deliberate, tested Phase 2 behavior and not a bug: the gate
contract was DRY_RUN/PAPER-only by construction. The gate is now deliberately
LIVE-*capable* through explicit typed permission evidence rather than by
weakening or removing that check:

- `AutomaticExitGateContextV1.account_mode` must be exactly `"paper"` or
  `"live"` (`SUPPORTED_ACCOUNT_MODES`); any other value is `NON_ACTIONABLE`
  (`REASON_UNSUPPORTED_ACCOUNT_MODE`) — no lowercasing, guessing, or
  canonicalization of a malformed mode.
- `live_trading_enabled` (mirrored from `trading_account.live_trading_enabled`,
  the same column other account-scoped modules already trust as the
  authoritative live/non-live account fact) must always agree with
  `account_mode`. Disagreement in either direction is inconsistent evidence
  and fails closed to `NON_ACTIONABLE`
  (`REASON_ACCOUNT_MODE_EVIDENCE_INCONSISTENT`) rather than being trusted
  either way. Neither `account_mode == "live"` alone nor
  `live_trading_enabled == True` alone is ever sufficient permission.
- A new context field, `automatic_exit_live_permission_evaluation:
  AutomaticExitLivePermissionEvaluationV1 | None`, carries the typed
  decision-gate LIVE permission evaluation. It is required, in addition to
  a consistent `account_mode == "live"` / `live_trading_enabled == True`
  pair, before a LIVE candidate can reach `STATE_APPROVED`. `None` denies
  outright with `REASON_LIVE_EXECUTION_NOT_GRANTED`. Otherwise the gate does
  not trust the object's own claims — it calls
  `validate_automatic_exit_live_permission_evaluation_binding_v1` (added in
  the second PR #426 review fix; see the update above), which independently
  checks the evaluation's contract version, that `trading_account_id`
  matches the context's account (defense in depth against attaching the
  wrong account's evaluation), that `decision_state` is a supported value,
  and that `evaluated_ts_utc` is timezone-aware and *exactly* equal to the
  context's own `evaluation_ts_utc` — rejecting a stale reused evaluation, a
  future-dated one, or a forged/malformed one, with no tolerance window. A
  `GRANTED` evaluation is additionally required to carry a positive
  `permission_id`, the supported `permission_version`, and the canonical
  `OK` reason code — an incomplete or self-inconsistent `GRANTED` evaluation
  is not trustworthy evidence of permission merely because its account and
  timestamp line up. Any binding failure denies with
  `REASON_LIVE_PERMISSION_EVALUATION_BINDING_MISMATCH`; a validated
  non-`GRANTED` state denies with `REASON_LIVE_EXECUTION_NOT_GRANTED`. Not
  consulted at all for `account_mode == "paper"`.
- All existing freshness, identity, conflict, free-quantity, risk-ceiling,
  and #318 account-protection checks apply identically to LIVE and PAPER —
  nothing about the LIVE path skips or weakens any existing check.

**Permission lifecycle (immutable, revocation-based).** The persisted
permission fact, `AutomaticExitLiveDecisionGatePermissionV1`, is permanently
immutable — the backing table,
`automatic_exit_live_decision_gate_permission_v1` (migration artifact only:
`db/migrations/20260818_automatic_exit_live_decision_gate_permission_v1.sql`,
not applied), rejects every `UPDATE` and `DELETE` at the DB layer via
trigger, including the "close the open window" transition. Ending or
superseding an open-ended grant is expressed exclusively through an
immutable, append-only fact in a companion table,
`automatic_exit_live_decision_gate_permission_revocation_v1` (also
`UPDATE`/`DELETE`-rejecting), bound to its permission row by a composite
`(permission_id, trading_account_id)` foreign key so MariaDB itself rejects
a structurally corrupt cross-account revocation at `INSERT` time. This is
the exact lifecycle already proven for `account_protection_policy_config_v1`
(see the revision-2/3 updates above), reused deliberately rather than
re-deriving the same fix independently. A permission row is revoked at
evaluation time `T` if any of its revocation facts has
`effective_ts_utc <= T`; multiple revocation facts per row are valid by
design so a future-scheduled revocation can never block a later, immediate
one from also taking effect.

The pure resolver, `src/decision_gate/automatic_exit_live_permission_contract_v1.py`
(`resolve_automatic_exit_live_decision_gate_permission_v1`), takes both
permission rows and revocation facts and returns the single effective,
non-revoked, supported-version permission row (or `None` if no row is
currently effective — default-denied, not an error). It fails closed
(raises) on: more than one simultaneously effective non-revoked row
(ambiguous), a malformed window, a malformed/cross-account/unsupported-
version revocation, or an unsupported permission version. A row belonging
to a different account is excluded from consideration and can never grant
or affect permission for the wrong account. DB reads are isolated in
`src/decision_gate/automatic_exit_live_permission_repository_v1.py`
(`load_automatic_exit_live_permission_history_v1` /
`load_automatic_exit_live_permission_revocation_history_v1`).

**Composition seam and ownership.** A new decision_gate-owned seam,
`src/decision_gate/automatic_exit_live_permission_evaluation_v1.py`
(`evaluate_automatic_exit_live_permission_v1`, mirroring
`account_protection_evaluation_v1.py` exactly), is the sole place LIVE
permission semantics are resolved: it loads persisted evidence, resolves it
through the pure contract, and always returns a typed
`AutomaticExitLivePermissionEvaluationV1` (`GRANTED`/`DENIED`, reason code,
permission id/version, evaluated timestamp) rather than raising or
returning a bare boolean — missing evidence resolves to a typed `DENIED`
evaluation, and malformed/ambiguous evidence resolves to a typed fail-closed
`DENIED` evaluation (`REASON_LIVE_PERMISSION_EVIDENCE_UNRESOLVED`) rather
than propagating an exception that would abort a whole runtime cycle — the
same design already used for `account_protection_evaluation_v1.py`.
`automatic_exit_runtime_orchestrator_v1.evaluate_automatic_exit_runtime_item_v1`
calls this seam directly (immediately alongside its existing
`evaluate_account_protection_for_automatic_exit_v1` call) and forwards its
typed result unchanged into `AutomaticExitGateContextV1`.
`src/exit_policy/automatic_exit_runtime_repository_v1.py` and `RuntimeItemV1`
carry **no** LIVE permission field and import **no** decision-gate LIVE
permission module at all — `exit_policy` never resolves LIVE permission
semantics itself, matching its existing relationship to
`account_protection_evaluation`
(`tests/test_automatic_exit_runtime_architecture_guards_v1.py::test_exit_policy_repository_does_not_resolve_decision_gate_live_permission`
/ `::test_orchestrator_forwards_decision_gate_owned_live_permission_evaluation`
prove this ownership split directly).

**Critical invariant, restated:** decision-gate LIVE permission is *not*
executor operational LIVE authority. An `APPROVED` LIVE result from this
gate means only "this account/candidate is permitted to proceed as a LIVE
automatic exit at the decision-gate layer." It does **not** mean "the
executor is operationally authorized to submit this order." Executor LIVE
authority (`src/executor/execution_live_authority_v1.py`), the kill switch,
and TRADE_EXECUTION credential resolution remain a wholly separate,
downstream gate that this change does not touch, call, or import. There
remains no direct path from `decision_gate` to `executor` or to any broker
call — `automatic_exit_gate_v1.py` and all three new decision-gate
LIVE-permission modules import none of `src.executor`, `src.manual_execution`,
or any broker/credential/kill-switch module (proved by
`tests/test_automatic_exit_gate_v1.py::test_gate_has_no_planner_executor_broker_or_manual_dependencies`
and the new
`tests/test_automatic_exit_live_permission_contract_v1.py::test_contract_module_has_no_db_broker_credential_or_executor_imports`
/ `::test_repository_module_has_no_broker_credential_or_executor_imports`
/ `::test_evaluation_seam_has_no_broker_credential_or_executor_imports`).

Tests added/updated:
`tests/test_automatic_exit_live_permission_contract_v1.py` (rewritten pure
resolver, now revocation-aware: no row denies, single row resolves by flag,
wrong-account row never leaks permission, overlapping non-revoked rows fail
closed, unsupported version fails closed, malformed window/provenance fails
closed, window expiry and future-dated-not-yet-effective deny, open-ended
permission revoked immutably, permission inactive at/after effective
revocation timestamp, future revocation does not revoke early, future
revocation does not block a later immediate one, malformed/cross-account/
unsupported-version revocation fails closed, replay deterministic
independent of ordering, account isolation, no forbidden imports);
`tests/test_automatic_exit_live_permission_evaluation_v1.py` (new;
decision_gate composition seam over the fixtures DB: no row denies without
raising, granted permission resolves a typed grant, flag-false denies,
revoked open-ended permission denies, future revocation does not revoke
early, conflicting active permissions fail closed to a typed DENIED
evaluation, strict account isolation, deterministic replay);
`tests/test_automatic_exit_live_permission_mariadb_ddl_v1.py` (new;
disposable-MariaDB proof that permission/revocation `UPDATE`/`DELETE` are
always rejected, revocation requires non-empty actor/reason, multiple
revocations per permission row are permitted, and a cross-account revocation
is rejected by the composite FK — registered in
`.github/workflows/pr_mariadb_ddl_validation.yml`);
`tests/test_automatic_exit_gate_v1.py` (LIVE matrix rewritten around the
typed evaluation object, plus a new binding-mismatch case);
`tests/test_automatic_exit_runtime_repository_v1.py` (the four now-obsolete
LIVE-permission-in-`RuntimeItemV1` tests removed — that field no longer
exists);
`tests/test_automatic_exit_runtime_orchestrator_v1.py` (end-to-end LIVE
cases rewritten to seed the persisted permission table and let the
orchestrator resolve it via the decision_gate seam, rather than constructing
a bool directly on the runtime item);
`tests/test_automatic_exit_runtime_architecture_guards_v1.py` (two new
ownership-boundary guards, see above).

Safety markers for this change:

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
live_gate_extension=1
```

`live_gate_extension=1` means software contract support only (the
decision_gate contract can now express and approve a LIVE decision given
explicit permission evidence) — it does not mean operational activation. No
production account has a provisioned `automatic_exit_live_decision_gate_permission_v1`
row; provisioning one (in addition to the existing automatic-exit planning
permission and account-protection policy config rows) remains an
operational prerequisite before any account's automatic-exit candidates
could ever reach an `APPROVED` LIVE decision, and even then blocker A (the
#392 -> #206 executor handoff adapter) must still be built, reviewed, and
merged before an `APPROVED` LIVE decision can reach an order at all.

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

`GO_LIVE_READY = NO`. `SOFTWARE_PHASE6_BLOCKERS = 0` (all three software
blockers A, B, and C are RESOLVED). `GO_LIVE_READY` remains `NO` independent
of that — see the dependency ordering below for what is still outstanding
(production migration/provisioning/deployment/authorization).

Three actual Phase 6 blockers were identified; all three are now RESOLVED
in software:

- ~~**A. #392 -> #206 typed adapter / runtime seam.**~~ **RESOLVED
  2026-08-18.** `src/execution_planner/
  automatic_exit_execution_handoff_adapter_v1.py` is a pure function
  `AutomaticExitPlanV1 -> ApprovedExecutionPlanV1`: lossless field mapping
  (no quantity/price recompute, no re-rounding, no leg reorder/merge/split,
  no side rewrite), fail-closed structural validation, and a deterministic,
  retry-stable `plan_reference_id` derived from the plan's full logical
  identity (trading_account_id, position_reference, venue, asset_id,
  market, side, REDUCE/EXIT action, evidence id, exit profile id/version,
  gate approval provenance, planner version, and every leg's exact
  index/side/price/quantity) — excluding only the wall-clock
  `planning_ts_utc`. `automatic_exit_execution_handoff_application_v1.py`
  is the seam that adapts the plan and then selects
  `ExecutionHandoffRepositoryV1.intake` for DRY_RUN/PAPER or
  `.intake_live_authorized` for LIVE, without pre-checking or duplicating
  #206's credential-scope, LIVE-authority, or kill-switch checks.
  `src/exit_policy/run_automatic_exit_policy_with_handoff_once_v1.py` is the
  new composition-root runner that wires the real candidate ->
  account-protection -> gate -> planner path to this seam, consuming only
  the in-memory `RuntimeItemOutcomeV1.plan` produced in the same evaluation
  cycle — the `automatic_exit_evaluation_audit_v1` audit table is never read
  as executor input, by this runner or anywhere else. The pre-existing
  audit-only `run_automatic_exit_policy_once_v1.py` runner and its
  `src.executor`-import architecture guard are unchanged. The runner's
  normal executor mode is derived exclusively from the account's own
  `account_mode` (`paper` -> `PAPER`, `live` -> `LIVE`); the **only**
  permitted explicit override is `DRY_RUN` (a deliberate non-production
  acceptance/testing mode), enforced both by the CLI's restricted
  `--executor-mode` choices and defensively inside `run_cycle_with_handoff`
  for direct Python callers. `PAPER` and `LIVE` are never valid override
  values — a paper account's plan can never reach `intake_live_authorized`
  and a live account's plan can never reach ordinary `PAPER` intake by
  passing an override; no override bypasses `decision_gate` evaluation
  itself. See `tests/test_automatic_exit_execution_handoff_adapter_v1.py`,
  `tests/test_automatic_exit_execution_handoff_application_v1.py`,
  `tests/test_run_automatic_exit_policy_with_handoff_once_v1.py`, and
  `tests/test_automatic_exit_execution_handoff_boundary_guards_v1.py`.
- ~~**B. Reviewed LIVE-capable extension of the automatic-exit `decision_gate`.**~~
  **RESOLVED 2026-08-18.** See "LIVE-capable decision-gate extension (Phase B
  finding, RESOLVED)" above. `automatic_exit_gate_v1` can now approve a LIVE
  candidate given explicit, typed, account-scoped, fail-closed decision-gate
  LIVE permission evidence — `account_mode == "live"` alone and any retained
  `live_trading_enabled` flag alone both remain insufficient. This resolves
  the decision-gate half of the former Phase B finding only; it grants no
  executor operational LIVE authority and does not by itself let any LIVE
  candidate reach an order, because blocker A (the executor handoff adapter)
  is still absent.
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
2. ~~LIVE-capable gate contract (blocker B)~~ — DONE. The gate's former
   unconditional paper-only restriction is now a deliberate, typed,
   fail-closed LIVE permission contract (see above). Provisioning an
   `automatic_exit_live_decision_gate_permission_v1` row per production
   account remains a further prerequisite before any account's automatic-exit
   candidates could reach an `APPROVED` LIVE decision. A reviewed,
   append-only grant path for that row now exists (Issue #588, see the
   2026-08-29 update above); no production row has been granted using it.
3. ~~Typed planner -> shared-handoff adapter/runtime seam (blocker A)~~ —
   DONE (see above). Only now that the gate can correctly produce a
   LIVE-eligible `APPROVED` decision did connecting the planner's output to
   #206 become meaningful; building the adapter earlier, against a gate that
   could never approve LIVE, would have invited exactly the kind of
   premature/implicit coupling this audit warns against.
   `tests/test_run_automatic_exit_policy_with_handoff_once_v1.py` exercises
   an end-to-end DRY_RUN/PAPER candidate -> gate (with real protections) ->
   planner -> adapter -> handoff path against a fake in-memory handoff
   repository, still with zero broker calls, zero authority rows, zero
   credentials, zero DB writes.
4. ~~Final repository-level integrated non-broker acceptance against the real
   `executor_execution_handoff` table~~ — **DONE 2026-08-19.** See the
   "item 4 CLOSED" update above: a disposable `synth_acceptance_437` schema
   (exact minimal migration closure, real `ExecutionHandoffRepositoryV1`,
   `executor_mode=DRY_RUN` only) proved initial persisted handoff, idempotent
   retry, distinct-intent-yields-distinct-id, and identity-conflict-fails-
   closed, then was dropped with zero residue and zero production `synth`
   mutation. `REPOSITORY_LEVEL_ACCEPTANCE=PASS`.
5. Only then: work through the Phase J production activation checklist and a
   separately authorized LIVE activation decision. No step in this ordering
   authorizes LIVE by itself, including this one. Production migration
   apply, executor credential provisioning, LIVE authority provisioning,
   kill-switch authoritative state, actual deployment, and an explicit user
   LIVE activation decision all remain outstanding and unauthorized by this
   change.

Additionally, and independent of that ordering: no #392 SELL LIVE authority
row exists (correctly — none was created by this audit), no
executor-invocation runtime owner is registered, and no LIVE service/timer
exists for either lane. Those remain Phase J/K activation-time concerns, not
implementation blockers in themselves.
