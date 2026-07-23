# TODO — Native SHORT Multi-Asset Rollout Contract

## Status

`blocked` — the repository writer-provenance contract is implemented, and the first scope-administration boundary defines pure request types plus forward-only schema constraints only. Runtime adoption, promotion, and removal transactions remain unimplemented. One post-merge attributable BTC production run passed devlap host acceptance; its permanent evidence is reviewed in `docs/ops/native_short_writer_provenance_operational_acceptance_20260717.md`. `WRITER_PROVENANCE_UNATTRIBUTED` is closed by that evidence. BTC remains the sole approved and proven canonical scope. No additional scope is authorized by this document.

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

1. **Scope-administration repository transactions.** Implement `ADOPT_LEGACY_SCOPE`, `PROMOTE_SCOPE`, and `REMOVE_SCOPE` separately against the accepted types and schema; include deterministic first-creation serialization and no map materialization.
2. **Writer commit-time fencing.** Revalidate scope ID, support state, support generation, and active cadence immediately before the bounded writer transaction commits; no persistent fence ledger.
3. **`NO_CURRENT_MAP` bootstrap semantics.** Make the expected newly supported bootstrap state non-fatal without hiding real failures.
4. **Per-symbol failure isolation.** Prove one symbol cannot leave another symbol's partial evidence.
5. **Sequential SOL review/canary.** Consider only SOL and accept three consecutive real 4h cycles.
6. **ETH only after SOL acceptance.** Re-evaluate all gates before any ETH decision.
7. **XRP only after ETH acceptance.** Re-evaluate all gates before any XRP decision.
8. **Broader rollout.** Revisit only after measured capacity and tick-rule coverage improve.

## Blockers / dependencies

- `PROMOTION_TRANSACTION_IMPLEMENTATION_MISSING`;
- `REMOVAL_TRANSACTION_IMPLEMENTATION_MISSING`;
- `BOOTSTRAP_ORCHESTRATION_BLOCKED`: current `NO_CURRENT_MAP` semantics are fatal for a new scope;
- `MULTI_SCOPE_FAILURE_ISOLATION_MISSING`: current orchestration does not isolate failures by symbol;
- one-scope current failure-domain-safe capacity;
- 403 markets without database/static tick-rule coverage.

Writer-provenance closure state:

```text
provenance_contract_implemented=true
attributable_production_run_observed=true
operational_acceptance_completed=true
writer_provenance_blocker_active=false
```

The reviewed attributable run and its persisted linkage close only the writer-provenance blocker. They do not implement scope-administration transactions, writer commit-time fencing, bootstrap semantics, failure isolation, or authorize any non-BTC production scope.

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
