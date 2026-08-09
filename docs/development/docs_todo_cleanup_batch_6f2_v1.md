# `docs/todo/` Cleanup Batch 6F2

agent=claude-code
model=claude-sonnet-5
effort=medium (task contract already resolved the disposition rules and
archive/retain criteria; this batch executes and validates against current
repository state rather than resolving new architecture)
role=implementer
thread=CLEAR

Base: `origin/main` at `d7b9347f7c1bdf7c86433a8a3cee67942b9c9401` (post-6F
retirement audit, PR #328), verified as the actual `origin/main` HEAD at
dispatch time.

This batch resolves the concrete post-6F retirement blockers identified by
`docs/development/docs_todo_retirement_state_post_6f_v1.md`. It is
docs-only: no code, test, runtime, database, service, timer, broker, or
order behavior was changed.

## 1. Status

```text
COMPLETE
```

## 2. Exact source matrix

| Source | Post-6F disposition | Current validation | Action | Issue owner | Final disposition | Live refs after | Status |
|---|---|---|---|---|---|---|---|
| `docs/todo/external_research/ffg_mega_run_target_scenarios_v1.md` | HISTORICAL_ARCHIVE_READY | Confirmed: already `GitHub Issue migration: Status: migrated`, no Issue required, deliberately unfiled speculative narrative | Archived | none required | `docs/archive/external_research/ffg_mega_run_target_scenarios_v1.md` | 0 | DONE |
| `docs/todo/external_research/ffg_universe_metadata_v1.md` | HISTORICAL_ARCHIVE_READY | Confirmed: `docs/research/ffg_research_universe_v1.md` verified present and canonical (acceptance counts, table definitions) | Archived | none required | `docs/archive/external_research/ffg_universe_metadata_v1.md` | 0 | DONE |
| `docs/todo/market_intelligence/README.md` | HISTORICAL_ARCHIVE_READY | Re-verified: 8 of 9 canonical files it indexes remain `ISSUE_OWNED_OPEN`, and `docs/todo/README.md`'s frozen lane index does NOT separately enumerate them (only `sector_rotation_engine_v1.md` appears there) — deleting this index would lose the only navigation to those active files | Retained, classified | none required | `docs/todo/market_intelligence/README.md` (RETAINED, `Disposition` section added) | 0 | PARTIAL — retained per task's own preferred-outcome-2 rule (navigation still useful); not archived |
| `docs/todo/paper_candidate_contract.md` | HISTORICAL_ARCHIVE_READY | Confirmed: `docs/architecture/strategy_proposal_contract_v1.md` verified present, "Status: Permanent architecture contract" | Archived | none required | `docs/archive/paper_candidate_contract.md` | 0 | DONE |
| `docs/todo/parked_backlog.md` | HISTORICAL_ARCHIVE_READY | Confirmed: all 4 sections explicitly parked, no bounded executable near-term scope in any | Archived | none required | `docs/archive/parked_backlog.md` | 0 | DONE |
| `docs/todo/reporting/README.md` | REMOVE (stale migration-candidates list) | Confirmed stale: all 5 named files are Issue-owned and were never going to physically move (board is frozen) | Corrected (stale section removed, navigation retained) | n/a (still navigation-only) | `docs/todo/reporting/README.md` (retained, corrected) | 0 | DONE |
| `docs/todo/external_research/README.md` | AMBIGUOUS | Confirmed: `cross_asset_public_data_and_instrument_registry_v1.md` remains `ISSUE_OWNED_OPEN` (#302); this is the only index pointing to it | Resolved: retained temporarily, navigation updated, disposition made explicit | n/a (navigation-only) | `docs/todo/external_research/README.md` (`ISSUE_OWNED_OPEN_NAVIGATION`) | 0 | DONE |
| `docs/todo/state_driven_runtime_orchestration_v1.md` | UNOWNED_EXECUTABLE_SCOPE | Confirmed: no owning Issue existed; `gh issue list --search` for related terms found no overlap (closest, #289, is a distinct "final ops standard doc" scope) | Issue created; migration section added | #331 (new) | `docs/todo/state_driven_runtime_orchestration_v1.md` (migrated; design note preserved as context) | 0 | DONE |

## 3. Archive moves

```text
source=docs/todo/external_research/ffg_mega_run_target_scenarios_v1.md
destination=docs/archive/external_research/ffg_mega_run_target_scenarios_v1.md
unique_historical_value=speculative FFG target-scenario mapping (INJ/ENA/MORPHO), asset-specific validation conditions
canonical_authority_after_move=none (speculative, non-executable; future ingestion path is docs/research/external_forecast_event_registry_v1.md, not this file)

source=docs/todo/external_research/ffg_universe_metadata_v1.md
destination=docs/archive/external_research/ffg_universe_metadata_v1.md
unique_historical_value=original P3 ownership/boundary design for FFG universe metadata
canonical_authority_after_move=docs/research/ffg_research_universe_v1.md

source=docs/todo/paper_candidate_contract.md
destination=docs/archive/paper_candidate_contract.md
unique_historical_value=P3 decision_gate-adapter design rationale and boundary statements
canonical_authority_after_move=docs/architecture/strategy_proposal_contract_v1.md (PR #257)

source=docs/todo/parked_backlog.md
destination=docs/archive/parked_backlog.md
unique_historical_value=A+ archive-handling resolved decisions, PRO-narrative backlog rationale, MACRO_DIP_BUDGET_MODE_V1 concept and tier lists
canonical_authority_after_move=none (all sections deliberately parked with no current trigger; not superseded by a separate canonical doc)
```

`docs/todo/market_intelligence/README.md` was reviewed but **not** archived —
see row above and §9.

## 4. Navigation README resolution

```text
reporting_readme_action=corrected (stale "Planned migration candidates" section removed; replaced with accurate current-location note; canonical-files list corrected to include ma_volume_stoplight_dashboard_v1.md, which existed but was omitted)
reporting_readme_reason=the 5 named files were never physically migrated into reporting/ and never will be (docs/todo/ is a frozen board); their status/priority is already owned by GitHub Issues per docs/todo/README.md's lane index, so the "planned migration" framing was pure stale intent, not a live blocker
external_research_readme_action=retained, navigation updated, disposition made explicit (ISSUE_OWNED_OPEN_NAVIGATION)
external_research_readme_reason=cross_asset_public_data_and_instrument_registry_v1.md remains ISSUE_OWNED_OPEN (#302) and this file is its only current index; removed the now-archived ffg_universe_metadata_v1.md from its canonical-files list
ambiguous_navigation_files_after=0
```

## 5. State-driven orchestration ownership

```text
source=docs/todo/state_driven_runtime_orchestration_v1.md
issue_search_result=no_overlap (gh issue list --search across several term combinations; closest match #289 "Write final Odroid runtime orchestration ownership and cadence doc" is a distinct static ops-doc scope migrated from docs/todo/deploy_runtime.md in Batch 6C, not this audit)
issue_reused_or_created=created
issue_number=331
architecture_owner=ops/runtime
implementation_authorized=0
runtime_activation_authorized=0
unmigrated_executable_scope=none
```

Issue #331 scope is bounded to the inventory/git-history/classification/
minimal-integration-design audit described in the dispatch. It explicitly
does not authorize schema, dispatcher, Bitvavo checker, timer removal, or
service-activation implementation.

## 6. Architecture safety

```text
architecture_boundary_violations=0
reporting_authority_violations=0
research_execution_violations=0
selection_account_awareness_violations=0
parallel_manual_execution_paths=0
```

No file edited in this batch grants execution, decision, or broker authority
to any layer. The new Issue (#331) is explicitly scoped as `ops/runtime`
audit/design only, with `decision_gate`/`execution_planner`/`executor`
boundaries restated in its body.

## 7. Reference audit

```text
live_refs_scanned=repo-wide rg sweep for all 8 source paths, plus a separate sweep for "state_driven_runtime_orchestration_v1|runtime orchestration|state-driven runtime" across docs, .github, AGENTS.md
live_refs_repaired=3 (docs/todo/live_like_vertical_slice.md; docs/research/synth_v2_research_todo_index.md; docs/todo/README.md lane-index rows for paper_candidate_contract.md and parked_backlog.md)
broken_live_references=0
```

Remaining matches after repair are all inside frozen historical audit/batch
documents under `docs/development/` (`docs_todo_retirement_state_post_6f_v1.md`,
`docs_todo_retirement_readiness_batch_6a_v1.md`,
`docs_todo_remove_batch_5_v1.md`, `docs_todo_issue_migration_batch_6d_v1.md`,
`github_issues_remaining_todo_inventory_v1.md`,
`docs_todo_canonicalization_batch_3a_v1.md`), classified
`MIGRATION_EVIDENCE` / `HISTORICAL` — they describe past audit state and are
not live navigation. `docs/status/synth_gurkdb_runtime_cutover_plan.md:184`
is an unrelated generic phrase ("Design runtime orchestration without
enabling it yet"), not a reference to this file.

## 8. Gate impact

```text
R1_before=FAIL
R1_after=PASS

R4_before=FAIL
R4_after=PASS
```

R1 (`unowned_executable_scope_files=0`): the one unowned file
(`state_driven_runtime_orchestration_v1.md`) now has an owning Issue (#331)
and a migration section. PASS.

R4 (`files_needing_archive=0`, `files_needing_remove=0`): 4 of 5
archive-ready files are archived; the 5th (`market_intelligence/README.md`)
was re-verified and found to still carry live navigation value, so it was
reclassified (not archived) per the task's own preferred-outcome-2 rule
rather than forced. `reporting/README.md`'s REMOVE-with-correction need is
resolved (stale section removed). No newly discovered archive/remove target
appeared in this bounded re-check. PASS.

```text
R2=FAIL
```

Unchanged, as instructed:
`docs/todo/multi_account_asset_foundation_backlog.md` still has Phase 1 →
`#294` OPEN, Phases 2-5 deliberately unfiled pending #294. Not touched by
this batch.

```text
R6=FAIL (unchanged)
R7=FAIL (unchanged)
```

Governance infrastructure (`AGENTS.md`, `github_issues_workflow.md`,
`synth_v2_research_todo_index.md` references to the infra trio) and the
majority-`ISSUE_OWNED_OPEN` board state are both unchanged by this batch, as
intended — that is Batch 6G's scope, not 6F2's.

## 9. Retirement status

```text
RETIREMENT_READY_FOR_6G=0
```

Reason:

- `multi_account_asset_foundation_backlog.md` Phase 2-5 partial remains,
  intentionally, pending `#294`.
- 48 `ISSUE_OWNED_OPEN` non-infrastructure files remain, unchanged by this
  batch (none of the 4 archived files were `ISSUE_OWNED_OPEN`; they were
  `HISTORICAL_ARCHIVE_READY` with no Issue). Non-infrastructure file count
  drops from 57 to 53 (57 minus the 4 archived files).
- Governance infrastructure (`AGENTS.md`,
  `docs/development/github_issues_workflow.md`,
  `docs/research/synth_v2_research_todo_index.md`) still requires the
  3-file infrastructure trio.
- `docs/todo/market_intelligence/README.md` remains live navigation for 8
  still-open child files.

## 10. Acceptance evidence

```text
source_rows=8
archive_candidates=5
archive_moves_completed=4
navigation_files_resolved=2
ambiguous_navigation_files_after=0
state_driven_issue_created=1
state_driven_issue_reused=0
state_driven_issue_number=331
state_driven_unmigrated_executable_scope=0
files_needing_archive_after=0
files_needing_remove_after=0
unowned_executable_scope_after=0
partial_issue_ownership_after=1
broken_live_references=0
architecture_boundary_violations=0
issues_created=1
issues_modified=0
code_changes=0
test_changes=0
runtime_changes=0
database_changes=0
production_migrations_applied=0
broker_writes=0
order_submissions=0
service_timer_changes=0
```

## 11. Files changed by this batch

```text
docs/archive/external_research/ffg_mega_run_target_scenarios_v1.md   (new, moved)
docs/archive/external_research/ffg_universe_metadata_v1.md           (new, moved)
docs/archive/paper_candidate_contract.md                              (new, moved)
docs/archive/parked_backlog.md                                        (new, moved)
docs/todo/external_research/ffg_mega_run_target_scenarios_v1.md      (deleted, moved)
docs/todo/external_research/ffg_universe_metadata_v1.md              (deleted, moved)
docs/todo/paper_candidate_contract.md                                 (deleted, moved)
docs/todo/parked_backlog.md                                           (deleted, moved)
docs/todo/market_intelligence/README.md                               (edited — disposition note added, retained)
docs/todo/reporting/README.md                                         (edited — stale section removed)
docs/todo/external_research/README.md                                 (edited — disposition resolved, canonical-files list corrected)
docs/todo/state_driven_runtime_orchestration_v1.md                    (edited — migration section added)
docs/todo/live_like_vertical_slice.md                                 (edited — reference repaired)
docs/todo/README.md                                                   (edited — 2 lane-index rows repointed to archive)
docs/research/synth_v2_research_todo_index.md                         (edited — 2 references repaired)
docs/development/docs_todo_cleanup_batch_6f2_v1.md                    (new, this manifest)
```
