# TODO — Native SHORT Multi-Asset Rollout Contract

## Status

`blocked` — the repository writer-provenance contract, the pure scope-administration request types, the forward-only schema, and the deterministic repository transactions for `ADOPT_LEGACY_SCOPE`, `PROMOTE_SCOPE`, and `REMOVE_SCOPE` (with first-creation serialization, operation-ledger idempotency, and commit-time transaction validation) are now implemented in the repository. One post-merge attributable BTC production run passed devlap host acceptance; its permanent evidence is reviewed in `docs/ops/native_short_writer_provenance_operational_acceptance_20260717.md`, and `WRITER_PROVENANCE_UNATTRIBUTED` is closed by that evidence. A sequential multi-symbol rollout orchestrator (see "Production rollout orchestrator" below) is now implemented in the repository, delegating unchanged to the existing administration transaction and gate; it has not been invoked against production. The `PROMOTION_CONTRACT_MISSING` bootstrap circularity is resolved by design (see "PROMOTE_SCOPE bootstrap-circularity resolution" below) via a narrow, scope-bound, checked-in bootstrap manifest. SOL (exactly `bitvavo/SOL/EUR/SHORT/4h/1h`) is explicitly, human-approved as the first canary (see "SOL bootstrap-promotion closure (corrected in a later lane)" below and `docs/ops/native_short_sol_bootstrap_promotion_approval_v1.md`); the manifest is `accepted: true` for SOL only, and this lane also narrows `BOOTSTRAP_ORCHESTRATION_BLOCKED`/`MULTI_SCOPE_FAILURE_ISOLATION_MISSING` for that exact scope only. Two confirmed design defects from an earlier version of this lane were corrected: (1) `REMOVAL_CONTRACT_MISSING` no longer applies to `PROMOTE_SCOPE` at all (it never created a concrete unsafe/irreversible state for promotion; `REMOVE_SCOPE`'s own gate is unaffected); (2) the manifest no longer attempts an impossible commit-self-reference -- it separates a deterministic approval-evidence digest (over the normalized approval payload plus the evidence module's own file hash) from deployed-checkout authorization (still the unmodified `verify_repository_commit_sha`/writer-capability job), and verifies its `approved_implementation_commit` as an ancestor of `HEAD`, never equal to it. **SOL is genuinely unblocked at the administration-decision layer today** (no remaining `GLOBAL_BLOCKERS_ACTIVE` rejection); a real write still requires the unchanged, unweakened clean-checkout and `native_short_4h_chain` writer-capability authorization. No production database mutation, migration application, or operational acceptance of the administration transactions has been performed. ETH, XRP, and BTC remain unapproved for this bootstrap path. Writer commit-time fencing is implemented in the repository; `NO_CURRENT_MAP` bootstrap and per-symbol failure isolation remain unimplemented. BTC remains the sole approved and proven canonical scope. No additional scope is authorized by this document.

## Sources

- merged and live-accepted PR #105;
- `src/market_data/native_short_multi_asset_audit_v1.py`;
- `src/market_data/run_native_short_multi_asset_audit_v1.py`;
- canonical native SHORT scope, map, lifecycle, generation, cadence, status, health-report, materializer, and 4h-owner implementation on `origin/main`;
- `docs/architecture/native_short_scope_administration_contract_v1.md`;
- `src/market_data/native_short_scope_administration_v1.py` and `db/migrations/20260718_native_short_scope_administration_v1.sql`;
- read-only production evidence captured on 2026-07-16;
- merged PR #114 / merge commit
  `38346fc1460453469ca5bd3bc2f45159f0dc303e`;
- reviewed devlap operational acceptance evidence:
  `docs/ops/native_short_writer_provenance_operational_acceptance_20260717.md`.

## Current state / facts

Canonical identity is exactly:

```text
(bitvavo, <SYMBOL>, EUR, SHORT, 4h, 1h)
```

BTC proved only that this exact BTC key can run through the existing single-scope 4h-owned chain, retain a complete generation/lifecycle ledger, project one active current map, rerun idempotently, and remain market-only and account-agnostic. It did not prove multi-scope transactions, per-symbol failure isolation, bootstrap behavior for a scope with no current map, attributable writer provenance, general promotion/removal, broader tick coverage, or any non-BTC production scope.

Read-only measured snapshot:

- 430 Bitvavo EUR markets audited;
- 23 readiness-qualified markets including BTC;
- 407 markets excluded from readiness at the snapshot cutoff;
- 403 market-eligible markets lacked both database and approved static tick-rule coverage (406 of all 430 rows when the three fail-closed ineligible markets are retained in the raw missing-tick count);
- SOL, ETH, and XRP were the three highest-ranked qualified future candidates by trailing-30-day public 4h EUR quote volume;
- safe capacity is currently one scope per failure domain.

The proposed queue is therefore sequential, not a simultaneous cohort:

```text
SOL -> ETH -> XRP
```

This queue is a review order only. SOL, ETH, and XRP are not approved for production. Ranking occurs only after public-market eligibility, exact 4h/1h freshness, context availability, unambiguous tick metadata, and empty/unambiguous native SHORT ledger checks pass. Wallets, balances, orders, portfolio membership, Profit Plan state, account state, and `selection_engine` output are prohibited inputs.

The accepted BTC-only writer run
`b07d897d-6574-4380-98c3-8145c5c41b30` at
`2026-07-17T12:00:00Z` is the first persisted attributable production run.
It was produced through the exact wrapper path on devlap from clean installed
commit `38346fc1460453469ca5bd3bc2f45159f0dc303e`. All 51 pre-contract writer
runs remain exactly as persisted and classify `LEGACY_UNATTRIBUTED`; no
historical ownership was backfilled or inferred. The accepted run did not
publish a map, append a lifecycle event, change support, or write a non-BTC
row.

## Writer provenance contract

Every future writer-capable invocation must supply one immutable `NativeShortWriterProvenance` object before any connection, transaction, lock, run insert, generation attempt, map/lifecycle write, scope write, scope-status upsert, or map-level delete/rebuild can occur.

The independent fields are:

- `writer_entrypoint`: closed stable repository entrypoint identifier;
- `repository_writer_owner`: exactly the existing canonical repository owner, `synth-chain-4h`;
- `runner_name` and `runner_version`: stable runner implementation identity;
- `invocation_uuid`: canonical UUID, persisted as the run UUID and linked to produced writer evidence;
- `execution_mode`: exactly `CHAIN`, `MANUAL`, or `TEST`, supplied explicitly;
- `repository_commit_sha`: explicit validated 40-character source commit; production modes reject the deterministic test identity and require exact equality with the running checkout `HEAD`;
- `host_name` and `process_id`: actual current-process host facts captured at invocation;
- `trigger_type` and `trigger_ref`: explicit reviewed trigger metadata, never derived from cadence, process ancestry, systemd state, timestamps, ordering, file mtimes, or later host inspection; the canonical repository chain uses `CHAIN` plus `REPOSITORY_4H_MARKET_CHAIN`, while direct writer runners remain `MANUAL` with their closed manual trigger types;
- `provenance_contract_version`: exactly `native_short_writer_provenance_v1`.

Repository/build identity remains separate from installed-host identity. No service, timer, unit, invocation, or host-owner name is inferred. `trigger_ref` is not overloaded with the remaining contract.

### Repository source-identity boundary

`native_short_repository_source_identity_v1` is the single explicit source-verification boundary used by every repository-controlled production writer entrypoint. After pure provenance construction and validation, but before any native SHORT database connection, transaction, run insert, or other mutation, it:

1. resolves the repository root from the running source module and requires Git's reported top-level path to match it exactly;
2. resolves `HEAD^{commit}` and requires one lowercase 40-character commit identity;
3. requires the supplied `repository_commit_sha` to equal that exact `HEAD`;
4. reads `git status --porcelain=v1 --untracked-files=all` and rejects every staged change, unstaged change, and untracked repository path;
5. fails closed when Git, the repository root, `HEAD`, status, or any other source-identity input cannot be proven.

The shell-provided commit value is a claim, not proof. `run_chain_4h.sh` invokes the same boundary before its first database-capable chain step, and the native SHORT Python writer independently re-verifies it immediately before its own DB access. This second check prevents changes introduced during earlier chain phases from reaching the writer. A dirty state is never persisted as attributable provenance. The inspector is injectable for deterministic tests, but production entrypoints use only the real running-checkout inspector.

`TEST` remains a closed deterministic mode with the all-zero test commit and does not inspect or require a Git checkout. This exception cannot be selected by any production CLI.

`CHAIN` identifies the canonical repository execution path only. `REPOSITORY_4H_MARKET_CHAIN` makes no scheduler claim. `SCHEDULED_4H_MARKET_CHAIN` is rejected because PR #114 supplies no reviewed installed-host scheduler evidence. Installed service/timer/unit identity remains absent and is not inferred. A manual start of either repository shell path is therefore described truthfully as the repository chain path, while direct manual Python writers remain distinguishable as `MANUAL`.

Persisted classification is deterministic:

- `ATTRIBUTABLE`: every mandatory field is present, valid, and mutually consistent for its explicit mode;
- `LEGACY_UNATTRIBUTED`: `provenance_contract_version` is absent on a historical row; partial historical host/trigger fields do not change that result;
- `INVALID_PROVENANCE`: a row claims the new contract but its fields are missing, malformed, contradictory, or unsupported. Application writers reject this state before database mutation, so repository-controlled future writers cannot persist it.

`TEST` is a distinct closed mode with a deterministic test commit identity and cannot use a production runner identity. It is never accepted as production provenance.

## Audited writer entrypoints

The complete reachable repository surface is:

1. `scripts/run_chain_4h.sh` / shell entrypoint — verifies the exact clean checkout through the shared boundary, fails closed on a SELECT-only expected 4h candle boundary check, then indirectly invokes the canonical scope-status writer without owning candle ETL; owns the outer 4h lock/step ordering, creates no native SHORT DB transaction or UUID itself, explicitly supplies `CHAIN`, the verified repository commit claim, `scripts/run_chain_4h.sh` entrypoint/ref, and the truthful `REPOSITORY_4H_MARKET_CHAIN` trigger; repository 4h owner; inspected by runtime-wiring tests.
2. `scripts/run_native_short_scope_status_chain_once.sh` / shell wrapper — indirectly invokes the Python scope-status runner; owns the native chain lock but no DB transaction; resolves or receives one explicit repository commit claim, supplies `CHAIN` plus `REPOSITORY_4H_MARKET_CHAIN`, and can be called manually without fabricating scheduler provenance; invoked by the 4h chain and inspected by runtime-wiring tests.
3. `src/market_data/run_native_short_scope_status_chain_v1.py` / `main` and `execute_runtime` — direct canonical writer; verifies exact clean repository source identity before DB access, owns one bounded DB transaction, creates one invocation UUID, inserts/finalizes `native_short_materializer_run_v1`, and can mutate `native_short_scope_observation_v1`, `native_short_map_generation_event_v1`, `native_short_map_v1`, `native_short_map_lifecycle_event_v1`, `native_short_scope_status_v1`, and `native_short_map_level_status_v1`; callable directly in explicit `CHAIN` or `MANUAL` mode; invoked by the wrapper and directly by tests.
4. `src/market_data/run_native_short_map_materializer_v1.py` / `main` — direct manual map-ledger writer; verifies exact clean repository source identity before DB access, owns the exact-one-symbol write transaction, creates one invocation UUID/run row, and can mutate `native_short_materializer_run_v1`, `native_short_map_generation_event_v1`, `native_short_map_v1`, and `native_short_map_lifecycle_event_v1`; manual only, not invoked by the 4h chain, and directly tested.
5. `src/market_data/run_native_short_map_level_status_materializer_v1.py` / `main` and `run_scope` — direct manual current-level writer; verifies exact clean repository source identity before DB access, owns run start/final transactions plus the existing per-scope rebuild transaction, creates one invocation UUID/run row, and can mutate `native_short_materializer_run_v1` and `native_short_map_level_status_v1`; manual only, not invoked by the 4h chain, and directly tested.
6. `src/market_data/run_native_short_map_scope_seed_canary_v1.py` / `main` and `run_write_symbol` — existing direct manual scope-registry canary; verifies exact clean repository source identity before DB access, owns its existing exact-one-symbol write transaction, now creates one attributable invocation/run row, and can mutate `native_short_materializer_run_v1` and `native_short_map_scope_v1`; manual only, not invoked by the 4h chain, and directly tested. PR #114 does not invoke it or add any scope.
7. Internal writer APIs and persistence helpers — `native_short_scope_status_materializer_v1.run_native_short_scope_status_materializer`, `evaluate_scope`, `rebuild_scope_projection`, `upsert_scope_status_projection`, `_insert_run`, `_finalize_run`, `_insert_observation`, and its lifecycle insert; `native_short_map_materializer_v1.materialize_scope_symbol` and its generation/map/lifecycle inserts; `native_short_map_level_status_materializer_v1.materialize_native_short_map_level_status_for_scope`; `native_short_map_level_status_v1.replace_native_short_map_level_status_for_scope` and `delete_native_short_map_level_status_for_scope`; and `run_native_short_map_scope_seed_canary_v1.run_write_symbol` and `insert_scope_row`. These are direct caller-owned-transaction helpers behind the reviewed runners. Each write boundary either requires and validates the immutable provenance object or accepts a run record that has already validated it; invocation UUID linkage is derived only from that object. Tests invoke the reusable boundaries directly with explicit `TEST` provenance.

`run_native_short_fib_context_snapshot_v1` is also reached by `scripts/run_chain_4h.sh`, but it is a read-only database consumer and filesystem snapshot publisher, not a native SHORT ledger writer. It creates no ledger row and cannot bypass writer enforcement. Reporting health/audit runners are likewise SELECT-only consumers.

## Deterministic audit contract

For every symbol, the audit reports three independent layers:

1. market readiness: canonical metadata flags, 4h and 1h counts/latest closed candle/freshness, context availability, tick state, and trailing-30-day 4h quote volume;
2. ledger readiness: exact-key scope cardinality/state, map/current-map state, lifecycle evidence, and generation-chain validity;
3. global rollout readiness: provenance, promotion, removal, bootstrap, capacity, and failure-isolation blockers.

Output is ordered by symbol. Volume is a ranking field only for rows already classified `READY_FOR_SEQUENTIAL_CANARY_REVIEW`. While any global blocker remains, `production_promotable` must be false.

## Promotion acceptance contract

A later single-symbol promotion may be accepted only when all of the following are evidenced:

- exact canonical identity and no alternate/partial scope key;
- an attributable writer owner, host, process, trigger type, and trigger reference;
- an explicit all-or-nothing single-scope promotion transaction;
- idempotent reruns with exactly one active map candidate;
- one `ATTEMPT_STARTED` plus exactly one terminal generation event per attempt, with every publication linked to its immutable map;
- source freshness `CURRENT` against the expected closed 4h and 1h cadence;
- no ambiguous scope, map, current-status, lifecycle, generation, or tick state;
- bounded completion within the existing 4h owner budget;
- a failure confined to the selected symbol, with deterministic retry and no partial evidence from another symbol;
- three consecutive real 4h cycles after promotion;
- the existing 4h owner remains the only timer/runtime owner.

The first administration boundary establishes `native_short_map_scope_v1` as the sole canonical identity and current support-generation owner, an attributable operation ledger, append-only generation-linked support evidence, and database-enforced single-active-cadence state. It performs no scope mutation. The required later promotion transaction must lock and validate the exact key, establish the supported scope, append its support evidence, and activate its cadence atomically. It must not materialize a map inside that transaction. A retry must either observe the identical completed state or fail closed on conflict; it must never add a duplicate logical scope.

The required later removal/rollback transaction must lock the same exact key, withdraw support, deactivate cadence, and make the scope non-actionable atomically. It must retain immutable maps and append-only generation/lifecycle/observation/run history, must not mislabel removal as a market lifecycle outcome, and must leave the sole 4h owner able to continue without selecting the removed scope. Until schema and projection behavior can meet those exact semantics without partial state, removal remains blocked.

## Open tasks by priority

The remaining blocker order is fixed:

1. **Scope-administration repository transactions.** *Implemented* in `src/market_data/native_short_scope_administration_transaction_v1.py` and `src/market_data/run_native_short_scope_administration_v1.py`: `ADOPT_LEGACY_SCOPE`, `PROMOTE_SCOPE`, and `REMOVE_SCOPE` are handled separately against the accepted types and schema, with deterministic first-creation serialization, operation-ledger idempotency, complete managed operation-lineage validation, commit-time transaction validation, and no map materialization. Production application and operational acceptance are not part of that repository slice.
2. **Writer commit-time fencing.** *Implemented* in `src/market_data/native_short_writer_commit_fence_v1.py` and the canonical scope-status chain: the bounded writer captures exact scope identity, current support state, support generation, and full active-cadence identity/state from the existing authorities, then performs a locking re-read immediately before either commit path. Drift fails into whole-transaction rollback; no persistent fence ledger is added. Repository tests cover withdrawn support, generation drift, cadence drift, unchanged commit, no partial evidence, and BTC idempotent rerun. No production invocation or database write was performed for this repository slice.
3. **`NO_CURRENT_MAP` bootstrap semantics.** Make the expected newly supported bootstrap state non-fatal without hiding real failures.
4. **Per-symbol failure isolation.** Prove one symbol cannot leave another symbol's partial evidence.
5. **Sequential SOL review/canary.** Consider only SOL and accept three consecutive real 4h cycles.
6. **ETH only after SOL acceptance.** Re-evaluate all gates before any ETH decision.
7. **XRP only after ETH acceptance.** Re-evaluate all gates before any XRP decision.
8. **Broader rollout.** Revisit only after measured capacity and tick-rule coverage improve.

## Blockers / dependencies

- `WRITER_COMMIT_TIME_FENCING_MISSING`: closed in the repository by the transient start-snapshot and commit-time locking revalidation in the canonical 4h writer transaction; production invocation and operational acceptance were not part of this slice;
- `ADMINISTRATION_TRANSACTION_OPERATIONAL_ACCEPTANCE_PENDING`: the promotion/removal/adoption repository transactions are implemented but have never been applied against production or operationally accepted;
- `BOOTSTRAP_ORCHESTRATION_BLOCKED`: current `NO_CURRENT_MAP` semantics are fatal for a new scope;
- `MULTI_SCOPE_FAILURE_ISOLATION_MISSING`: current orchestration does not isolate failures by symbol;
- one-scope current failure-domain-safe capacity;
- 403 markets without database/static tick-rule coverage.

Writer-provenance closure state (narrative record of the reviewed 2026-07-17 acceptance, not live runtime state):

```text
provenance_contract_implemented=true
attributable_production_run_observed=true
operational_acceptance_completed=true
writer_provenance_blocker_active=false
```

The reviewed attributable run and its persisted linkage close only the writer-provenance blocker. The repository-only writer commit-time fence was implemented later and has not been production-invoked or operationally accepted. Neither change implements bootstrap semantics, failure isolation, or authorization for any non-BTC production scope.

`src/market_data/native_short_multi_asset_audit_v1.py` no longer emits `global_blocker_codes`, `writer_provenance_blocker_active`, and `operational_acceptance_completed` as an unconditional hardcoded constant. `evaluate_global_blockers()` now derives each blocker from explicit evaluated evidence, fails closed on absent/invalid/ambiguous evidence, and never infers acceptance from code or tests existing, or from this narrative record alone. `WRITER_PROVENANCE_UNATTRIBUTED` is wired to the existing canonical provenance evaluation (`classify_persisted_native_short_writer_provenance` applied to the reviewed accepted run row); if that row does not currently classify `ATTRIBUTABLE`, the blocker stays active regardless of what this narrative snapshot claims. `REMOVAL_CONTRACT_MISSING` remains unconditionally active: the removal transaction is implemented and unit-tested, but no canonical, explicitly owned, machine-readable production-operational-acceptance evidence source exists for it, so implementation and tests alone are not treated as acceptance. `BOOTSTRAP_ORCHESTRATION_BLOCKED` and `MULTI_SCOPE_FAILURE_ISOLATION_MISSING` remain unconditionally active pending their own separate implementation lanes. The audit report also now exposes an additive `global_blocker_evidence` map giving the per-blocker reason (`EVIDENCE_CONFIRMS_CLOSED`, `EVIDENCE_ABSENT_OR_INVALID`, `NO_CANONICAL_EVIDENCE_SOURCE`, or `IMPLEMENTATION_PENDING_SEPARATE_LANE`) so a blocker that is active because evidence failed can be distinguished from one active because no canonical evidence source exists yet. This lane changes audit correctness only; it does not itself close any blocker, perform any promotion/removal, or implement bootstrap/isolation semantics.

### PROMOTION_CONTRACT_MISSING evidence contract (this lane, corrected)

`PROMOTION_CONTRACT_MISSING` is wired to a canonical, machine-readable
PROMOTE_SCOPE operational-acceptance evidence contract defined in
`src/market_data/native_short_promotion_acceptance_evidence_v1.py`, evaluated
by `evaluate_promotion_acceptance_evidence` and threaded into
`evaluate_global_blockers()` via `promotion_accepted` /
`promotion_evidence_reason`. This lane introduces the contract and evaluator
only; **it does not itself constitute production promotion acceptance**, and
it does not perform, request, or wrap any promotion transaction.

An earlier version of this lane pinned a bare `ACCEPTED_PROMOTION_OPERATION_UUID`
constant in Python. That was corrected: a Python constant is exactly the
stale-reference failure mode already fixed once for writer provenance
(`PROVENANCE_AUDIT_RUN_UUID`, see the note above), and an operation-ledger row
by itself proves only that a transaction executed and committed with some
terminal result -- it does not prove a human reviewed and accepted that
specific result for that specific scope as production promotion. The
corrected design keeps those two facts as two independent, cross-validated
sources of evidence rather than one bare identifier.

Concepts are kept explicit and separate:

- **promotion contract definition** — the constants in
  `native_short_promotion_acceptance_evidence_v1.py`
  (`PROMOTION_ACCEPTANCE_CONTRACT_VERSION`,
  `REQUIRED_MANIFEST_SCHEMA_VERSION`, `REQUIRED_ADMINISTRATION_SCHEMA_VERSION`,
  the accepted operation type and result codes, and the fixed canonical
  non-symbol scope fields) plus `compute_promotion_contract_digest()`, a
  deterministic SHA-256 digest over those exact invariants;
- **controlled acceptance execution** — a separately reviewed, out-of-band
  invocation of the existing `native_short_scope_administration_transaction_v1`
  `PROMOTE_SCOPE` path against one authorized symbol (not part of this lane);
- **persisted acceptance result** — two independent sources that must both
  agree, not one:
  1. the existing `native_short_scope_admin_operation_v1` operation ledger
     row for that operation (proves the transaction executed and its
     terminal result; no new schema or migration is introduced -- this
     table, added by `db/migrations/20260718_native_short_scope_administration_v1.sql`,
     already persists immutable `operation_uuid`, `operation_type`, a
     database-CHECK-enforced canonical six-part scope key, terminal
     `result_class`/`result_code`, `schema_version`, and a SHA-256
     `metadata_digest`);
  2. a new versioned, repository-owned, machine-readable **acceptance
     manifest**, `src/market_data/native_short_promotion_acceptance_manifest_v1.json`
     (proves a human reviewed and explicitly accepted that exact result for
     that exact scope). No existing canonical machine-readable
     reviewed-acceptance pattern was found to reuse: operational acceptances
     to date are narrative markdown under `docs/ops/`, and
     `data/research/**/manifest_v1.json` files are a different,
     research-domain artifact with different ownership and semantics. This
     is therefore the smallest new versioned evidence artifact, owned by
     native SHORT market-data and co-located with the code that defines its
     schema;
- **audit evaluation** — `evaluate_promotion_acceptance_evidence`, a pure,
  read-only, deterministic function with no mutation; its only I/O is a
  read of the manifest file.

The manifest binds, at minimum: `acceptance_schema_version`,
`promotion_contract_version`, `promotion_contract_digest`, `accepted` (must be
the JSON literal `true`), the exact `operation_uuid`, the exact six-part
scope including `symbol`, `operation_type`, `expected_request_metadata_digest`,
the `immutable_request_identity` used to *reconstruct* the immutable request
object and *recompute* that digest via the existing contract's own dataclasses
and canonical digest function
(`NativeShortScopeAdministrationRequest.request_digest` in
`native_short_scope_administration_v1.py` -- no duplicated hashing or
validation logic), and a non-empty `reviewed_acceptance_reference` pointing at
a reviewed operational-acceptance document.

`promotion_contract_digest` is a SHA-256 over the contract's fixed invariants
-- operation type, accepted result codes, required administration schema
version, fixed canonical scope fields, **and** the explicit
`ALLOWED_PRODUCTION_ACTOR_TYPES` (`HUMAN_OPERATOR`, `SERVICE_PRINCIPAL`) /
`ALLOWED_PRODUCTION_TRIGGER_TYPES` (`MANUAL_CLI`, `AUTOMATION`) allowlists --
so a contract change to any of those invariants, including a future weakening
of the actor/trigger allowlist, changes the digest and fails any manifest
written against the old contract closed instead of silently reinterpreting it.

Recomputing the digest alone is not sufficient, because a manifest could be
internally self-consistent (its identity recomputes to its own declared
digest) while still naming a different operation, scope, or provenance than
the one it claims to review, or while recording `TEST` provenance (a closed
deterministic unit-test fixture mode that must never stand in for a reviewed
production promotion). The evaluator therefore reconstructs the identity as a
real `NativeShortScopeAdministrationRequest`/`...Provenance` object and checks
each load-bearing field explicitly, before ever comparing digests:

- `identity_request.operation_type == PROMOTE_SCOPE` (rejects e.g. a
  `REMOVE_SCOPE` identity even if it is otherwise self-consistent);
- `identity_request.scope_key.as_dict() == manifest["scope"]` exactly
  (including `symbol` -- rejects an identity naming a different scope/symbol
  than the manifest declares);
- `identity_request.provenance.operation_uuid == manifest["operation_uuid"]`
  (rejects an identity whose own provenance names a different operation);
- `identity_request.provenance.schema_version == REQUIRED_ADMINISTRATION_SCHEMA_VERSION`;
- `identity_request.provenance.actor_type` in `ALLOWED_PRODUCTION_ACTOR_TYPES`
  **and** `identity_request.provenance.trigger_type` in
  `ALLOWED_PRODUCTION_TRIGGER_TYPES` -- `TEST`/`TEST` (or any other value) is
  rejected outright as reviewed production evidence.

Evidence closes the blocker only when **all** of the following hold:

- the manifest file exists, parses as JSON, and is a well-formed mapping;
- its schema version, contract version, and contract digest all match the
  live contract exactly;
- it is explicitly `accepted: true` with a non-empty reviewed reference;
- its scope is the fixed canonical non-symbol fields plus a specific,
  well-formed symbol (not merely any well-formed ticker);
- its recorded `immutable_request_identity` reconstructs without error, binds
  every field above exactly (operation type, scope+symbol, operation_uuid,
  schema version, non-`TEST` actor/trigger type), and recomputes -- via the
  existing contract's own digest function -- to exactly its own declared
  `expected_request_metadata_digest`;
- exactly one `native_short_scope_admin_operation_v1` row matches the
  manifest's `operation_uuid` (no ambiguity);
- that row is `operation_type=PROMOTE_SCOPE`, terminal,
  `result_class=SUCCESS` with `result_code` in
  `{PROMOTED_NEW_SCOPE, PROMOTED_FROM_PRIOR_WITHDRAWAL}`, carries the exact
  manifest scope (including symbol) and the required administration
  `schema_version`, and its persisted `metadata_digest` equals the
  manifest's `expected_request_metadata_digest` exactly (a merely
  well-formed but different digest still fails closed).

Missing, malformed, incomplete, wrong-version, wrong-contract-digest,
not-yet-accepted, wrong-scope, wrong-symbol, `TEST` provenance, mismatched
identity fields, unrelated, stale, or ambiguous/duplicate evidence on either
side fails closed and leaves the blocker active.

The manifest shipped by this lane has `"accepted": false` and null
placeholders for the rest: no controlled production promotion has been
executed, reviewed, or accepted yet, so `PROMOTION_CONTRACT_MISSING` remains
active.

#### GLOBAL_BLOCKERS_ACTIVE enforcement (implemented in a later lane)

An earlier version of this document claimed `PROMOTE_SCOPE` "already fails
closed while required global blockers are active." That claim was traced
across the complete repository and found false at the time and was retracted
here. A subsequent lane (branch
`fix/native-short-global-blocker-gate-v1`) then implemented the missing
executable gate described below. This section documents that implementation;
it does not itself perform, request, or accept any production promotion,
adoption, or removal, and it does not change BTC's existing supported state.

**Exact executable enforcement call path.** The single canonical blocker
evaluator, `native_short_multi_asset_audit_v1.evaluate_global_blockers()`
(unchanged), is now reachable read-only from the authoritative
scope-administration transaction path via a new reusable entrypoint,
`native_short_multi_asset_audit_v1.evaluate_current_global_blockers(conn)`,
which reads the same writer-provenance and `PROMOTE_SCOPE` operation-ledger
rows the audit already reads (via new `fetch_writer_provenance_rows(conn)` /
`fetch_promote_operation_rows(conn)` helpers, factored out of `run_audit` so
the SQL is defined exactly once) and calls the existing evaluator through a
new pure `evaluate_global_blockers_from_rows(writer_rows,
admin_operation_rows)` function. No blocker logic is duplicated; `run_audit`
itself now calls these same functions instead of repeating the query/logic
inline.

`native_short_scope_administration_transaction_v1.py`'s two public
entrypoints call `evaluate_current_global_blockers(conn)` on the *same*
already-open connection (inside `execute_scope_administration`, this is the
same locked, `conn.begin()`'d transaction connection -- no second database
snapshot is opened) and pass the resulting active-blocker tuple into
`decide_administration(operation_type, snapshot, *,
active_global_blockers=...)`. `decide_administration` is the single pure
decision function already used by both entrypoints; the blocker check now
runs there, before any operation-specific dispatch (`_decide_adopt` /
`_decide_promote` / `_decide_remove`), so a blocked operation never reaches
its own classification-specific logic. A replayed (already-completed)
operation is decided via the separate, pre-existing `decide_operation_replay`
path and is untouched by this gate -- replay behavior remains deterministic
and is not re-evaluated against current blocker state.

`active_global_blockers` is a required keyword-only input with no default.
Every direct caller must therefore pass explicitly evaluated state; production
entrypoints obtain that state only from
`evaluate_current_global_blockers(conn)`.

**Authoritative enforcement layer.** The gate lives in
`native_short_scope_administration_transaction_v1.decide_administration`,
called from both `execute_scope_administration` (write mode, the sole
production mutation path) and `plan_scope_administration` (read-only dry
run, so CLI previews are truthful). Both are the only production entrypoints
into this module; the CLI runner
(`run_native_short_scope_administration_v1.py`) calls these same functions
and cannot bypass them. Neither public function's signature accepts a
blocker-state parameter of any kind, so no caller -- direct or via the CLI --
can pass "blockers clear" through the API. The only test-injection seam is
monkeypatching the module-level `evaluate_current_global_blockers` function
itself, the same established pattern already used in this file's test suite
for `read_scope_state_snapshot` / `_insert_support_event`; production code
never does this.

**Operation-specific blocker matrix: adopted v1 policy.** No authoritative
operation-specific matrix existed anywhere in the repository before this
lane. This lane explicitly adopts the following v1 policy, derived from each
canonical blocker's published semantics and enforced by
`_APPLICABLE_GLOBAL_BLOCKERS_BY_OPERATION` in
`native_short_scope_administration_transaction_v1.py`:

| Operation             | Applicable active blockers |
|------------------------|----------------------------|
| `ADOPT_LEGACY_SCOPE`   | `WRITER_PROVENANCE_UNATTRIBUTED` |
| `PROMOTE_SCOPE`        | all of `GLOBAL_BLOCKERS` (`WRITER_PROVENANCE_UNATTRIBUTED`, `PROMOTION_CONTRACT_MISSING`, `REMOVAL_CONTRACT_MISSING`, `BOOTSTRAP_ORCHESTRATION_BLOCKED`, `MULTI_SCOPE_FAILURE_ISOLATION_MISSING`) |
| `REMOVE_SCOPE`         | `WRITER_PROVENANCE_UNATTRIBUTED`, `REMOVAL_CONTRACT_MISSING` |

Rationale: `WRITER_PROVENANCE_UNATTRIBUTED` gates every writer-capable
operation (all three mutate writer-owned tables and depend on trustworthy
writer identity). `PROMOTE_SCOPE` is rollout expansion, so it is gated by the
complete set, including the rollout-readiness blockers
(`BOOTSTRAP_ORCHESTRATION_BLOCKED`, `MULTI_SCOPE_FAILURE_ISOLATION_MISSING`).
`REMOVE_SCOPE` is a safety/rollback action that reduces scope count rather
than increasing rollout-expansion risk, so it is deliberately **not** gated
by the promotion-specific or rollout-expansion-specific blockers -- only by
its own `REMOVAL_CONTRACT_MISSING` operational-acceptance evidence (which,
like the promotion evidence contract, does not yet exist as a manifest for
removal; this lane does not add one, per its own scope boundary) plus the
universal writer-provenance gate. This matrix is proven by dedicated,
operation-specific tests in
`tests/test_native_short_scope_administration_transaction_v1.py`
(`test_decide_promote_blocked_by_*`, `test_decide_adopt_blocked_by_*`,
`test_decide_remove_blocked_by_*`,
`test_decide_remove_not_blocked_by_promotion_bootstrap_or_isolation_blockers`),
including an explicit proof that removal is *not* incidentally blocked by
unrelated rollout-expansion blockers.

The matrix is settled policy for v1, not an unresolved interpretation. The
only unresolved policy issue retained by this lane is the first
controlled-promotion bootstrap circularity documented below; no bypass is
implemented.

**Scope-state vs. audit-ledger mutation behavior.** A `GLOBAL_BLOCKERS_ACTIVE`
decision is a `REJECT` action, which -- like every other reject/no-op/idempotent
outcome in this module -- is not in the ledgered-action set and therefore
writes no operation-ledger row and performs no scope/cadence/support mutation;
the write-mode transaction is rolled back with `commit_state=ROLLED_BACK` and
`persisted=False`, identical in shape to every other pre-existing rejection.
No materialization or backfill occurs on any path. The blocked decision's
sorted, deterministic blocking blocker codes are exposed on
`AdministrationDecision.blocking_global_blockers` and surfaced in both
`plan_scope_administration` and `execute_scope_administration`'s
`AdministrationTransactionOutcome.current_state["blocking_global_blockers"]`.

**Missing/malformed evidence behavior.** Enforcement depends entirely on
`evaluate_current_global_blockers` succeeding and returning the canonical
evaluator's fail-closed result; if the underlying evaluator determines
evidence is absent, invalid, or ambiguous, the affected blocker(s) are
reported active (unchanged canonical behavior -- see
`evaluate_global_blockers`'s existing fail-closed contract) and the gate
therefore blocks. If the read path itself raises (e.g. a genuinely malformed
database read), `execute_scope_administration`'s existing unmapped-exception
handling rolls back and raises a typed
`NativeShortScopeAdministrationExecutionError` rather than proceeding as if
no blockers were active -- fail-closed either way.

Integration tests exercise the complete unpatched path from
`execute_scope_administration` through `evaluate_current_global_blockers`,
both evidence-row fetches, `evaluate_global_blockers_from_rows`,
`evaluate_global_blockers`, and `decide_administration`. They prove absent
writer evidence, absent promotion evidence, malformed evidence, and unreadable
evidence cannot authorize a mutation or persist an operation-ledger row.

**Removal/rollback semantics.** Proven explicitly, not assumed: dedicated
tests confirm a `REMOVE_SCOPE` unaffected by its narrower applicable-blocker
set still commits successfully even while `PROMOTION_CONTRACT_MISSING`,
`BOOTSTRAP_ORCHESTRATION_BLOCKED`, and `MULTI_SCOPE_FAILURE_ISOLATION_MISSING`
are all active, while a `REMOVE_SCOPE` is correctly blocked when
`REMOVAL_CONTRACT_MISSING` or `WRITER_PROVENANCE_UNATTRIBUTED` is active.

**Promotion-acceptance bootstrap circularity: still unresolved by design.**
This lane deliberately does **not** resolve the circular dependency already
identified above: `PROMOTION_CONTRACT_MISSING` can only close after reviewed
evidence of a completed `PROMOTE_SCOPE` exists, but with this gate now
enforcing, `PROMOTE_SCOPE` fails closed *while* `PROMOTION_CONTRACT_MISSING`
is active -- which it always is until that first controlled promotion is
accepted. `PROMOTE_SCOPE` is therefore now, correctly and by explicit design,
**permanently blocked in production** until a separate, reviewed decision
establishes how the first controlled promotion-acceptance execution is meant
to occur (for example, a distinct reviewed one-time exception procedure, or a
narrower blocker subset specifically for that first controlled run). This
lane implements only the unambiguous safe portion (uniform fail-closed
enforcement) and does not invent an acceptance-mode bypass; the policy
decision for how to break this bootstrap circularity remains open and must be
made explicitly, in its own reviewed lane, before any real production
promotion can ever execute.

No operational scope change occurred in this lane: no database write, no
migration application, no scope promotion/adoption/removal, no
materialization/backfill, no service/timer change, no broker/private API
call, no order submission. BTC remains the sole production-supported native
SHORT scope, unaffected by this change. The shipped promotion manifest
remains `"accepted": false` and `PROMOTION_CONTRACT_MISSING` remains active.

#### Required later controlled operational acceptance procedure (separate lane, dependency-ordered)

The corrected, honest dependency order, updated now that the gate exists:

1. this lane's evidence contract and manifest schema exist in the repository
   (done by PR #165);
2. **the executable global-blocker gate now exists** (done by this lane) --
   `PROMOTE_SCOPE` genuinely fails closed while any applicable blocker is
   active;
3. every other implementation blocker this rollout requires before a
   production `PROMOTE_SCOPE` invocation is safe (at minimum
   `BOOTSTRAP_ORCHESTRATION_BLOCKED` and
   `MULTI_SCOPE_FAILURE_ISOLATION_MISSING`) must be closed by their own
   separate, already-reviewed lanes -- **not** as part of executing the
   promotion;
4. **the promotion-acceptance bootstrap circularity above must be explicitly
   resolved by its own reviewed decision** -- this is now the primary
   remaining blocker to any first controlled promotion, since the gate makes
   the circularity concrete and enforced rather than theoretical;
5. only once (2), (3), and (4) are resolved may an operator select exactly
   one authorized symbol from the sequential review queue (currently
   `SOL -> ETH -> XRP`) after re-confirming every readiness gate;
6. execute `native_short_scope_administration_transaction_v1` `PROMOTE_SCOPE`
   for that exact symbol against the real production database, with full
   provenance (`HUMAN_OPERATOR` or `SERVICE_PRINCIPAL` actor, `MANUAL_CLI` or
   `AUTOMATION` trigger -- never `TEST` -- and a verified clean repository
   commit);
7. confirm the resulting `native_short_scope_admin_operation_v1` row is
   terminal, `SUCCESS`, and carries the correct scope, schema version, and
   digest;
8. write a reviewed operational-acceptance document analogous to
   `docs/ops/native_short_writer_provenance_operational_acceptance_20260717.md`
   naming the exact `operation_uuid`, symbol, and commit;
9. only then, in a follow-on repository change, populate
   `native_short_promotion_acceptance_manifest_v1.json` with that exact
   `operation_uuid`, scope/symbol, the recorded immutable request identity
   (non-`TEST` provenance), the matching `expected_request_metadata_digest`,
   the reviewed-acceptance document reference, and `"accepted": true`;
10. re-run the audit to confirm `PROMOTION_CONTRACT_MISSING` closes and every
    other blocker remains unaffected.

This lane changes audit correctness and adds the evidence contract plus an
unaccepted manifest template only; the global-blocker-gate lane adds
enforcement only. Neither performs any promotion, database write, migration
application, materialization, or backfill, and neither authorizes SOL, ETH,
XRP, or any other non-BTC production scope.

A follow-on correction fixed a second, separate defect: `PROVENANCE_AUDIT_RUN_UUID` in `native_short_multi_asset_audit_v1.py` had been set to `b5d9ca6b-ff24-46eb-8155-4e663b948ebc` — the legacy pre-contract `run_id=30` row (started 2026-07-15, predates the provenance-contract migration) — instead of the actually reviewed and accepted run `b07d897d-6574-4380-98c3-8145c5c41b30` (`run_id=52`) named in this document and in `docs/ops/native_short_writer_provenance_operational_acceptance_20260717.md`. With the corrected constant, a live read-only audit run confirms `provenance_audit_run_attributed=true` and `writer_provenance_blocker_active=false`, while `PROMOTION_CONTRACT_MISSING`, `REMOVAL_CONTRACT_MISSING`, `BOOTSTRAP_ORCHESTRATION_BLOCKED`, and `MULTI_SCOPE_FAILURE_ISOLATION_MISSING` remain active and unaffected. Every regular 4h-chain writer run since `run_id=52` (through at least `run_id=62`, 2026-07-29) independently classifies `ATTRIBUTABLE` under the unchanged classifier, confirming the writer path and classifier were already healthy and only the audit's reference constant was wrong.

## Production rollout orchestrator (this lane)

A single production rollout orchestrator now exists in
`src/market_data/native_short_scope_administration_rollout_v1.py` and
`src/market_data/run_native_short_scope_administration_rollout_v1.py`. It
adds explicit-universe iteration only; it creates no new writer, service,
timer, or direct SQL mutation path, and it changes no gating, blocker,
classification, or transaction behavior in
`native_short_scope_administration_transaction_v1.py`.

- **Checked-in approved rollout universe.** `APPROVED_ROLLOUT_UNIVERSE_V1`
  is a reviewed, ordered tuple of `(symbol, operation_type,
  approval_reference, note)` entries. It currently contains exactly one
  entry: `BTC` via `ADOPT_LEGACY_SCOPE`, adopting the existing legacy
  `MIGRATION_BACKFILL` scope (`support_generation=NULL`,
  `scope_admin_operation_id=NULL`) into administration generation 1. No
  `PROMOTE_SCOPE` entry is added by this lane -- adding SOL, ETH, or XRP
  requires its own separate reviewed repository change to this constant, not
  a CLI argument, and remains additionally gated by the unresolved
  `PROMOTION_CONTRACT_MISSING` bootstrap circularity documented above. `--
  only-symbol` may *select a subset* of this checked-in universe; it fails
  closed (`INVALID_ROLLOUT_SYMBOLS`, before any database connection) if a
  requested symbol is not already present in it. The universe is never
  inferred from wallet holdings, Profit Plan cards, account state, or
  `selection_engine` output.
- **Delegation, not a new authority.** Every scope is processed by calling
  the existing, unmodified `plan_scope_administration` /
  `execute_scope_administration` from
  `native_short_scope_administration_transaction_v1.py` -- the sole
  canonical transaction owner. The orchestrator performs its own writer-
  capability authorization exactly once per invocation
  (`enforce_capability_write_authorization` for the `native_short_4h_chain`
  capability) and repository-source verification once per invocation, then
  reuses that same validated authorization object unchanged for every scope,
  exactly like the existing single-scope CLI. It never calls
  `evaluate_current_global_blockers` or `decide_administration` itself and
  cannot bypass the `GLOBAL_BLOCKERS_ACTIVE` gate: a `PROMOTE_SCOPE` entry
  is rejected by the existing gate exactly as a manual single-scope CLI
  invocation would be.
- **Sequential, stop-on-first-failure.** Entries are processed strictly in
  checked-in universe order, one bounded per-scope transaction at a time on
  one connection. The run stops immediately at the first scope whose result
  is not `SUCCESS`/`IDEMPOTENT_SUCCESS` (including a `GLOBAL_BLOCKERS_ACTIVE`
  rejection or any corrupt/retryable classification) or on the first
  unexpected exception; every remaining symbol is left untouched and
  reported under `remaining_symbols`.
- **Idempotent and restartable without extra state.** Each entry's operation
  UUID is derived deterministically
  (`deterministic_operation_uuid`) from only the operation type and the
  exact canonical scope key -- stable across every rerun. A restarted
  invocation with identical CLI arguments therefore replays already-
  completed entries as `OPERATION_ALREADY_COMPLETED`
  (`IDEMPOTENT_SUCCESS`) via the existing `decide_operation_replay` path and
  continues from the first not-yet-attempted entry; no separate
  orchestrator-side run-state file is introduced. `--requested-at-utc` must
  still be supplied identically across a restart, exactly as for the
  single-scope CLI, since it is part of each entry's immutable request
  digest.
- **No materialization.** The orchestrator does not materialize maps,
  snapshots, Profit Plan state, or reporting output; its safety markers
  (`map_materialization=0`, `snapshot_materialization=0`,
  `profit_plan_writes=0`, `reporting_writes=0`, plus the existing
  broker/decision/execution/executor markers) are emitted on every result.

No operational scope change occurred in this lane: no database write, no
migration application, no scope promotion/adoption/removal was performed by
adding this orchestrator. BTC remains the sole production-supported native
SHORT scope until the orchestrator is actually invoked with `--write`
against the real production database. Exact activation command:

```text
python -m src.market_data.run_native_short_scope_administration_rollout_v1 \
  --actor-type HUMAN_OPERATOR --actor-id <reviewer> \
  --trigger-type MANUAL_CLI \
  --reason "adopt legacy BTC scope into administration generation 1" \
  --request-source native_short_scope_administration_rollout_v1 \
  --repository-commit <verified clean checkout HEAD sha> \
  --requested-at-utc <fixed ISO-8601 UTC timestamp> \
  --write
```

Focused tests: `tests/test_native_short_scope_administration_rollout_v1.py`
(pure orchestration logic against monkeypatched
`plan_scope_administration` / `execute_scope_administration`; no database
required).

## PROMOTE_SCOPE bootstrap-circularity resolution (this lane)

The circularity documented above ("Promotion-acceptance bootstrap
circularity: still unresolved by design") is now resolved by design, but
**remains unopened** as production capability: no scope is currently
authorized, and even a fully authorized scope would still be blocked by two
other unconditional blockers this lane does not touch.

**Repository-approved next canary: none exists.** This lane searched the
canonical sources (this document's "Current state / facts" and "Open tasks
by priority" sections, and `native_short_multi_asset_audit_v1.py`) for an
approved next scope before implementing anything scope-specific. The result
is explicit and unchanged from before this lane: "SOL, ETH, and XRP ... are
not approved for production" -- `SOL -> ETH -> XRP` is documented as "a
review order only." No symbol has passed the sequential-canary review
described under "Open tasks by priority" item 5. This lane therefore does
**not** name a symbol anywhere in checked-in, accepted form; inventing one
would itself be exactly the kind of unreviewed promotion this contract
exists to prevent.

**What was implemented (module signature superseded -- see "SOL
bootstrap-promotion closure (corrected in a later lane)" below for the
current, accurate design).** A new, narrow, evidence-based exception to the
`PROMOTION_CONTRACT_MISSING` sub-check only, structurally distinct from (and
never a replacement for) the existing post-hoc
`native_short_promotion_acceptance_evidence_v1` evidence used for the
second and every later promotion:

- `src/market_data/native_short_promotion_bootstrap_evidence_v1.py` --
  pure, read-only, no database access. Defines the bootstrap contract
  (`BOOTSTRAP_CONTRACT_VERSION`, `compute_bootstrap_contract_digest()`) and
  an evaluator that validates the checked-in manifest and requires its
  `scope` (including `symbol`) to match the exact request under evaluation.
  *(This lane's original evaluator additionally required an exact
  `repository_commit_sha` match against deployed `HEAD` -- an unsound,
  self-referential design corrected in the later lane below to an
  approval-evidence digest plus ancestry check instead.)*
- `src/market_data/native_short_promotion_bootstrap_manifest_v1.json` --
  versioned, repository-owned, ships `accepted: false` with every
  scope/approval field `null`. Authorizes nothing until a **separate**
  reviewed repository change names one exact symbol.
- `native_short_scope_administration_transaction_v1.decide_administration`
  gained an optional keyword-only `bootstrap_promotion_evidence` parameter
  (default `None`, always safe/inert). When, and only when, **all** of the
  following hold, `PROMOTION_CONTRACT_MISSING` alone is narrowed out of the
  blocking set for that one decision (see
  `_bootstrap_promotion_evidence_applies`):
  - the operation is `PROMOTE_SCOPE` (never `ADOPT_LEGACY_SCOPE` or
    `REMOVE_SCOPE`);
  - `PROMOTION_CONTRACT_MISSING` is actually one of the currently applicable
    active blockers;
  - the caller-supplied evaluation is `accepted` (exact scope + exact
    commit match against a valid, `accepted: true` manifest);
  - the requested scope classifies exactly `NO_SCOPE` (no canonical scope
    row, no cadence row, no support event -- structurally only true for a
    scope's first-ever administration attempt, since a successful first
    promotion permanently creates that scope's row);
  - defensively, the scope's own administration-operation ledger is
    completely empty (fails closed on an otherwise-impossible
    NO_SCOPE-with-history state instead of trusting classification alone).
  Every other applicable active blocker (`WRITER_PROVENANCE_UNATTRIBUTED`,
  `BOOTSTRAP_ORCHESTRATION_BLOCKED`, `MULTI_SCOPE_FAILURE_ISOLATION_MISSING`,
  `REMOVAL_CONTRACT_MISSING`) still rejects exactly as before -- this is a
  narrowing of one sub-check, never a second "allow promotion" flag, and the
  existing gate mechanism (`_APPLICABLE_GLOBAL_BLOCKERS_BY_OPERATION` /
  `applicable_active_global_blockers` / the `GLOBAL_BLOCKERS_ACTIVE` reject
  path) is unmodified.
- `plan_scope_administration` and `execute_scope_administration` both
  evaluate bootstrap evidence for every fresh (non-replay) PROMOTE_SCOPE
  decision and surface it unconditionally in
  `AdministrationTransactionOutcome.current_state["bootstrap_evidence"]`
  (accepted/reason/symbol/commit) and
  `current_state["bootstrap_evidence_applied"]`, so plan mode shows the full
  decision and evidence -- including *why* evidence did not apply -- without
  any write. `execute_scope_administration`'s existing
  `require_writer_mutation_authorization` call is unchanged and still runs
  before any mutation regardless of bootstrap evidence.

**Single-use by construction, not a mutable flag.** Because a successful
first promotion permanently creates the scope's row and its ledger row, that
exact scope can never classify `NO_SCOPE` again, so this evidence cannot
re-apply to a second promotion of the same scope. Because the manifest names
one exact symbol, it cannot apply to any other scope. No "consumed" flag is
introduced or required.

**What remains blocked when this lane's manifest ships unaccepted
(historical -- see "SOL bootstrap-promotion closure (corrected in a later
lane)" below for the current state, where SOL is approved and this no
longer applies to SOL).** With the manifest shipped by *this* lane
(`accepted: false`, no symbol named), `BOOTSTRAP_ORCHESTRATION_BLOCKED` and
`MULTI_SCOPE_FAILURE_ISOLATION_MISSING` remain unconditionally active in
`evaluate_global_blockers` and applicable to every `PROMOTE_SCOPE`
decision, and this lane's bootstrap exception narrows only
`PROMOTION_CONTRACT_MISSING` (a later lane widened the narrowed set and
approved SOL specifically -- see below). A later lane also found and
corrected an unrelated defect: `REMOVAL_CONTRACT_MISSING` was, at this
point in the branch's history, still (incorrectly) applicable to
`PROMOTE_SCOPE` too; that is no longer the case.

No operational scope change occurred in this lane: no database write, no
migration application, no scope promotion, no manifest acceptance, no
symbol chosen. The checked-in bootstrap manifest ships unaccepted.

**Update (later lane, same branch): SOL explicitly approved.** The
statement above ("the checked-in bootstrap manifest ships unaccepted...")
described this document's own first lane. A human operator subsequently
gave explicit, scope-specific, out-of-band approval: SOL (exactly
`bitvavo/SOL/EUR/SHORT/4h/1h`, and no other symbol) as the first native
SHORT managed production canary. See "SOL bootstrap-promotion closure"
below for what changed.

Focused tests:
`tests/test_native_short_promotion_bootstrap_evidence_v1.py` (manifest
evaluator, pure) and
`tests/test_native_short_scope_administration_promotion_bootstrap_wiring_v1.py`
(decision-wiring and `execute_scope_administration`/`plan_scope_administration`
integration against the existing fake-connection harness).

## SOL bootstrap-promotion closure (corrected in a later lane)

The original version of this section (SOL approved, manifest updated,
`_bootstrap_promotion_evidence_applies` narrowed to three codes) shipped
with two confirmed design defects, both corrected here. Neither correction
weakens `REMOVE_SCOPE`'s own gate or any check unrelated to the exact SOL
bootstrap path.

### Defect 1: REMOVAL_CONTRACT_MISSING incorrectly gated PROMOTE_SCOPE

`_APPLICABLE_GLOBAL_BLOCKERS_BY_OPERATION` applied the complete
`GLOBAL_BLOCKERS` set (including `REMOVAL_CONTRACT_MISSING`) to
`PROMOTE_SCOPE`, while the SAME comment block's own prose said
"`REMOVAL_CONTRACT_MISSING` gates `REMOVE_SCOPE` only: its own
operational-acceptance evidence is what proves removal is safe to
execute" -- an internal contradiction between the code and its own stated
rationale.

Reviewed and corrected: absent removal-acceptance evidence creates **no**
concrete unsafe or irreversible state for `PROMOTE_SCOPE`.
`_apply_decision`'s `ADOPT`/`PROMOTE_NEW`/`PROMOTE_REACTIVATE` branches
never call `_update_scope_remove`, `_deactivate_cadence`, or write
`ADMIN_REMOVAL_REASON_CODE` -- promotion touches no removal machinery at
all. `_revalidate_post_state` independently re-proves the post-promote
state is coherent before commit, regardless of removal's evidence status.
And the canonical "Promotion acceptance contract" checklist earlier in
this document never lists removal evidence as a prerequisite. `_APPLICABLE_GLOBAL_BLOCKERS_BY_OPERATION[PROMOTE_SCOPE]`
is now `frozenset(GLOBAL_BLOCKERS) - {REMOVAL_CONTRACT_MISSING}`.
`REMOVE_SCOPE`'s own gate (`{WRITER_PROVENANCE_UNATTRIBUTED,
REMOVAL_CONTRACT_MISSING}`) is untouched -- this correction removes an
unrelated blocker from an unrelated operation only. Proven by
`test_decide_promote_not_blocked_by_removal_contract_missing`,
`test_removal_contract_missing_never_blocks_promote_scope`, and the
unchanged `test_decide_remove_blocked_by_removal_contract_missing`.

### Defect 2: the manifest could not contain its own commit's hash

The prior revision required the manifest's `repository_commit_sha` to
equal the exact deployed `HEAD` at invocation. A git commit cannot state
its own hash inside its own tree (the hash is a pure function of the
tree's content, which would need to already contain the hash -- a fixed
point unreachable without brute-force hash-grinding). No finite sequence
of "pin" commits resolves this: each attempt to record a commit's hash
produces a new commit with a different hash. This is corrected by
separating two genuinely different concerns, per
`src/market_data/native_short_promotion_bootstrap_evidence_v1.py`:

- **Approval-evidence identity** -- `approval_evidence_digest`, a
  deterministic SHA-256 (`compute_approval_evidence_digest`) over the
  immutable, normalized approval payload: `accepted`, the exact SOL
  scope, `approval_reference`, `approved_at_utc`, `approved_implementation_commit`,
  and the current SHA-256 of the evidence module's own source file. This
  digest has no relationship to git commit hashing -- it is computed from
  plain fields the manifest also stores, and is recomputed fresh from
  those fields (plus a fresh read of the implementation file) at every
  evaluation. Editing any manifest field, or the evidence module itself,
  without recomputing this digest fails closed
  (`MANIFEST_DIGEST_MISMATCH`) -- proven by
  `test_tampered_scope_without_digest_update_fails_closed`,
  `test_tampered_approval_reference_without_digest_update_fails_closed`,
  and `test_implementation_file_hash_change_is_detected`.
- **Deployed checkout authorization** -- unchanged, and still entirely the
  job of `native_short_repository_source_identity_v1.verify_repository_commit_sha`
  (clean checkout, exact `HEAD` known) and
  `src.operations.writer_capability_authorization_v1` (production writer
  capability), both already required, unmodified, before any write. The
  bootstrap evidence module never re-checks `HEAD` equality.
- **Repository ancestry** -- the manifest's `approved_implementation_commit`
  (`a74ff33121d42a7771eef0654e1526847d5c5d12`, the exact, already-existing,
  ordinary historical commit that introduced the reviewed bootstrap
  mechanism -- never the commit that introduces the manifest's own
  `accepted: true` state) is verified as an **ancestor** of the current
  `HEAD` (`git merge-base --is-ancestor`, injectable as `ancestry_checker`
  for tests), never required to be equal to it. Any real commit created
  after that one, on any branch descended from it, satisfies this by
  construction -- no further "pin" commit is ever required. An
  unavailable or failing ancestry check fails closed
  (`ANCESTRY_CHECK_UNAVAILABLE`), never treated as satisfied.

`docs/ops/native_short_sol_bootstrap_promotion_approval_v1.md`'s prior
"one required follow-up pin commit" framing is superseded by this section;
no such follow-up commit exists or is needed.

### What the manifest now authorizes

Given the explicit SOL approval, `native_short_promotion_bootstrap_manifest_v1.json`
ships `accepted: true` for exactly `bitvavo/SOL/EUR/SHORT/4h/1h` (no
wildcard -- every scope field is a fixed literal), naming
`docs/ops/native_short_sol_bootstrap_promotion_approval_v1.md` as
`approval_reference`, commit `a74ff33121d42a7771eef0654e1526847d5c5d12` as
`approved_implementation_commit`, and a matching `approval_evidence_digest`.
`_bootstrap_promotion_evidence_applies` in
`native_short_scope_administration_transaction_v1.py` narrows a fixed,
named set of three blocker codes (`_BOOTSTRAP_NARROWED_BLOCKER_CODES` =
`{PROMOTION_CONTRACT_MISSING, BOOTSTRAP_ORCHESTRATION_BLOCKED,
MULTI_SCOPE_FAILURE_ISOLATION_MISSING}`) **for the exact bootstrap-matched
scope and decision only**, never globally: the codes are only removed from
one decision's `blocking` tuple when accepted evidence, exact scope match,
`NO_SCOPE` classification, and an empty operation ledger all hold together.
`evaluate_global_blockers` itself (`native_short_multi_asset_audit_v1.py`)
is unmodified -- the audit report continues to show these codes
unconditionally active exactly as before; only the transaction-level
decision for a bootstrap-matched request is narrowed.
`WRITER_PROVENANCE_UNATTRIBUTED` (already closed by real evidence) is
deliberately not in the narrowed set.

Because the manifest names exactly one symbol, this mechanism structurally
cannot apply to ETH, XRP, BTC, or any other scope: their scope key never
matches the manifest's `scope`, so `evaluate_promotion_bootstrap_evidence`
returns `SCOPE_MISMATCH`, leaving every blocker exactly as active as
before for them. Proven by
`test_execute_real_evaluator_fails_closed_for_every_non_sol_symbol` and
`test_shipped_default_manifest_fails_closed_for_every_other_symbol`.

Single-use remains structural, not a mutable flag: once SOL's first
promotion commits, its scope row and operation-ledger row exist
permanently, so it can never classify `NO_SCOPE` again and the bootstrap
exception cannot re-apply to a second SOL promotion attempt (proven by
`test_execute_second_promote_attempt_after_sol_bootstrap_success_is_not_reauthorized`).
A retry of the *same* operation (identical `operation_uuid`) remains
idempotent via the pre-existing, unmodified `decide_operation_replay` path
and creates no second ledger row (proven by
`test_execute_retry_of_same_operation_uuid_is_idempotent_and_creates_no_second_operation`).

**Net effect: SOL is genuinely unblocked at the administration-decision
layer today.** `test_execute_real_evaluators_promote_sol_end_to_end_today`
proves a SOL `PROMOTE_SCOPE` request succeeds end-to-end against the real
(unmodified) `evaluate_current_global_blockers`, the real checked-in
manifest, and the real ancestry check against this repository's actual git
history -- no remaining `GLOBAL_BLOCKERS_ACTIVE` rejection. This is not the
same as "production execution requires nothing further": a real write
still requires, unchanged and unweakened, a clean git checkout with
`--repository-commit` matching the actual deployed `HEAD`
(`verify_repository_commit_sha`) and passing `native_short_4h_chain`
production writer-capability authorization
(`enforce_capability_write_authorization`) -- both ordinary, standing
requirements for every writer-capable invocation, not global blockers, and
not evaluated or weakened by this lane.

No operational scope change occurred in this lane: no database write,
migration, scope promotion, map materialization, snapshot publication,
Profit Plan render, or account/wallet action.

Focused tests: `tests/test_native_short_promotion_bootstrap_evidence_v1.py`
(digest computation, tamper detection, ancestry-checker injection, pure)
and `tests/test_native_short_scope_administration_promotion_bootstrap_wiring_v1.py`
(decision-wiring, `REMOVAL_CONTRACT_MISSING` non-applicability, and the
real end-to-end SOL success proof).

## Boundary

Owner: `market_data`, using public canonical market metadata, public candles, tick metadata, and native SHORT ledgers only.

No live trading. The scope-administration repository work itself performed no production database mutation. The separate accepted host invocation was BTC-only and created only the bounded run, observation, and current-projection evidence documented in the permanent acceptance record. No scope seeding, adoption, promotion, or removal. No map publication or lifecycle action. No account/private-broker reads. No broker writes. No order submission. No `selection_engine`, `decision_gate`, `execution_planner`, or executor input. No second timer or runtime owner.

## Non-goals

- promotion or removal writes;
- bootstrap, map-geometry, lifecycle, or status-semantic changes;
- multi-scope execution;
- runtime deployment or service/timer changes;
- Profit Plan changes;
- production approval of SOL, ETH, XRP, or any other new scope.
