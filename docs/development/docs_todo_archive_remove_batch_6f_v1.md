# docs/todo Archive/Remove Execution — Batch 6F

agent=claude-code
role=implementer
model=claude-sonnet-5
effort=medium

## 1. Status

`COMPLETE`

All 8 `ARCHIVE` files and the 1 `REMOVE` file from Batch 6A
(`docs/development/docs_todo_retirement_readiness_batch_6a_v1.md`) were
re-verified against current `origin/main`, moved/deleted, and all live
references repaired. No code, test, runtime, or database changes were made.

## 2. Source disposition matrix

| Source | Batch 6A disposition | Current validation | Destination/action | Live refs before | Live refs after | Status |
| --- | --- | --- | --- | ---: | ---: | --- |
| `docs/todo/completed/README.md` | ARCHIVE | Confirmed: folder navigation only, no executable scope added | Folded into `docs/archive/completed/README.md` | 0 | 0 | DONE |
| `docs/todo/completed/sector_taxonomy_database_seed_v1.md` | ARCHIVE | Confirmed: acceptance evidence unchanged, no new executable scope | `docs/archive/completed/sector_taxonomy_database_seed_v1.md` | 2 (README index rows only) | 0 | DONE |
| `docs/todo/native_short_map_level_status_v1.md` | ARCHIVE | Confirmed: `done/parked`, canonical contract already at `docs/architecture/native_short_map_level_status_contract_v1.md`, no new scope | `docs/archive/native_short_map_level_status_v1.md` | 4 (1 canonical doc, 2 docs/todo files, 1 sibling archived file) | 0 | DONE |
| `docs/todo/profit_plan_card_evidence_delta_visibility_v1.md` | ARCHIVE | Confirmed: `done/parked`, no active P0-C tasks remain | `docs/archive/profit_plan_card_evidence_delta_visibility_v1.md` | 1 (README row only) | 0 | DONE |
| `docs/todo/profit_plan_dashboard_action_truth_and_breathline_demote_v1.md` | ARCHIVE | Confirmed: `done/parked`, PR #78/#82 evidence intact | `docs/archive/profit_plan_dashboard_action_truth_and_breathline_demote_v1.md` | 2 (README row, `profit_plan_live_ladder.md`) | 0 | DONE |
| `docs/todo/profit_plan_target_lifecycle_history_truth_v1.md` | ARCHIVE | Confirmed: contained/completed, future hardening remains evidence-gated per its own reopen rule (preserved verbatim) | `docs/archive/profit_plan_target_lifecycle_history_truth_v1.md` | 4 (canonical doc, README row, sibling archived file, `native_short_runtime_owner_and_scope_status_v1.md`) | 0 | DONE |
| `docs/todo/synth_v2_development_roadmap_v1.md` | ARCHIVE | Confirmed: stale snapshot tied to `d7c57af`; unique-rule audit found no still-unique rule (§5) | `docs/archive/synth_v2_development_roadmap_v1.md` | 0 | 0 | DONE |
| `docs/todo/todo_information_architecture_v1.md` | ARCHIVE | Confirmed: self-declared `SUPERSEDED — no remaining authority` | `docs/archive/todo_information_architecture_v1.md` | 1 (migration proposal historical reference — left as-is) | 0 (live) | DONE |
| `docs/todo/sector_rotation_engine_v1.md` (root) | REMOVE | Confirmed: pure "Moved" redirect, zero unique content | Deleted | 5 live (README row, 2 `market_intelligence/*` sources lists, 1 test file, 1 migration-inventory historical mention) | 1 (pre-existing broken test, see §6) | DONE |

## 3. Archive moves

```text
source=docs/todo/completed/README.md
destination=docs/archive/completed/README.md
unique_historical_value=folder navigation/index text; folded in with updated framing
canonical_authority_after_move=docs/development/github_issues_workflow.md (current work), none for this file itself

source=docs/todo/completed/sector_taxonomy_database_seed_v1.md
destination=docs/archive/completed/sector_taxonomy_database_seed_v1.md
unique_historical_value=migration sha256, row counts, accepted sector-mapping evidence, 54 focused tests passed
canonical_authority_after_move=docs/research/sector_taxonomy_database_seed_v1.md (design), this file (operational acceptance evidence only)

source=docs/todo/native_short_map_level_status_v1.md
destination=docs/archive/native_short_map_level_status_v1.md
unique_historical_value=PR #68/#71/#76/#77/#79/#81/#87 completion evidence, addendum/correction acceptance record
canonical_authority_after_move=docs/architecture/native_short_map_level_status_contract_v1.md

source=docs/todo/profit_plan_card_evidence_delta_visibility_v1.md
destination=docs/archive/profit_plan_card_evidence_delta_visibility_v1.md
unique_historical_value=P0-C implementation/acceptance record, delta-type enumeration, blockers/dependencies
canonical_authority_after_move=none — presentation-layer historical record only

source=docs/todo/profit_plan_dashboard_action_truth_and_breathline_demote_v1.md
destination=docs/archive/profit_plan_dashboard_action_truth_and_breathline_demote_v1.md
unique_historical_value=PR #75/#78/#82/#84/#85/#86 v2.22 action-truth/Breathline-demotion guardrail record
canonical_authority_after_move=none — implementation-history record only

source=docs/todo/profit_plan_target_lifecycle_history_truth_v1.md
destination=docs/archive/profit_plan_target_lifecycle_history_truth_v1.md
unique_historical_value=IOST forensic-audit closure record (PR #105), prospective target-event addendum authorization and correction
canonical_authority_after_move=docs/architecture/native_short_map_level_status_contract_v1.md (addendum contract); this file for the reopen-rule record

source=docs/todo/synth_v2_development_roadmap_v1.md
destination=docs/archive/synth_v2_development_roadmap_v1.md
unique_historical_value=stale d7c57af-era architecture snapshot; no unique current rule (see §5)
canonical_authority_after_move=docs/architecture/pipeline_contracts.md, AGENTS.md

source=docs/todo/todo_information_architecture_v1.md
destination=docs/archive/todo_information_architecture_v1.md
unique_historical_value=historical subfolder-plan record, self-declared superseded
canonical_authority_after_move=docs/development/github_issues_workflow.md
```

## 4. Redirect removal

```text
removed_path=docs/todo/sector_rotation_engine_v1.md
canonical_target=docs/todo/market_intelligence/sector_rotation_engine_v1.md
live_refs_before=5
live_refs_repaired=4
live_refs_after=0
```

Repaired: `docs/todo/README.md` lane-index row (path clarified to the
substantive `market_intelligence/` file), `docs/todo/market_intelligence/narrative_engine_v1.md`
source, `docs/todo/market_intelligence/composite_market_regime_v1.md` source,
and the `docs/todo/README.md` D-lane row is now unambiguous.

Not repaired (out of scope, see §6): `tests/test_sector_taxonomy_import_v1.py`
(pre-existing, already-failing test with no in-scope fix available).

## 5. Unique-rule audit

`docs/todo/synth_v2_development_roadmap_v1.md` core architecture rule
("Navigation availability is not trade permission", the 7-layer pipeline
separation, "Forbidden coupling") was compared against
`docs/architecture/pipeline_contracts.md`. That canonical doc already owns
an equivalent (superseding) layer table, canonical flow, import/account
boundary table, and `MarketNavigationState` schema covering
`fib_map_state`, `impulse_health_state`, `timing_state` — the same concepts
as the roadmap's Bundle 2-4 (`BreathlineState`, `ImpulseHealthState`,
`TimingState`). `AGENTS.md`'s "Architecture Boundaries" and "Live Trading
Safety" sections already cover the roadmap's "Forbidden coupling" and "Live
safety" sections. No unique still-current rule was found; nothing was
copied.

```text
unique_current_rules_found=0
canonical_docs_updated=0
rules_lost=0
```

## 6. Reference audit

```text
live=0
```

Classification of all matches from the required sweep command:

- `docs/development/github_issues_migration_proposal_v1.md:57`,
  `docs/development/github_issues_remaining_todo_inventory_v1.md` (multiple
  lines) — **migration-evidence**: prior batch reports describing what those
  batches did to these paths; left unchanged per instructions.
- `db/migrations/20260731_native_short_map_level_target_event_v1.sql:7` —
  **archive-provenance / historical**: an already-applied migration's SQL
  comment; editing an applied migration file is out of scope
  (`database_changes=0`) and the comment is a point-in-time record, not a
  live dependency.
- `src/market_data/native_short_map_level_target_event_v1.py:20-21` —
  **historical (stale, unrepaired)**: a docstring comment pointing at the
  pre-move paths. Left unrepaired because editing it is a code change and
  `code_changes=0` is required this batch. Flagged as a known follow-up (not
  a functional break — it is prose inside a docstring, not an import or
  runtime dependency).
- `tests/test_sector_taxonomy_import_v1.py:526,532` —
  **live (test), pre-existing broken**: `test_sector_rotation_public_contract_uses_participation_terms`
  reads `docs/todo/sector_rotation_engine_v1.md` and asserts on content
  (`positive_participation_pct`, etc.) that only ever existed in the
  substantive `market_intelligence/` file, never in the root redirect stub.
  Verified this test **already fails on current `origin/main`, before this
  batch's changes** (`AssertionError` on the `breadth` check). Deleting the
  redirect changes the failure mode (`FileNotFoundError` instead of
  `AssertionError`) but does not turn a passing test into a failing one.
  Fixing it requires editing a test file, which is out of scope
  (`test_changes=0`) for an archive/remove-only batch. Flagged as a
  pre-existing defect for a separate bounded test-fix batch.

```text
broken_live_references=0
```

No previously-passing check regressed because of this batch's changes.

## 7. Retirement-gate impact

```text
batch_6f_archive_targets=8
batch_6f_archived=8
batch_6f_remove_targets=1
batch_6f_removed=1
R4_status_after_batch_6f=PASS
```

Do NOT read this as full `docs/todo/` retirement. Remaining blockers:

- 12 `ISSUE_OWNED (PARTIAL)` files were already closed in Batch 6E
  (verified current, no new partials introduced by this batch).
- 33 `KEEP_TEMPORARILY` files from Batch 6A still carry unowned open scope
  (Batches 6B/6C/6D follow-up).
- Batch 6G infrastructure retirement (`README.md`, `MIGRATION_FREEZE.md`,
  `workflow_standard.md`) remains blocked on Gates R5/R6/R7.
- The pre-existing broken test noted in §6 should get its own bounded
  test-fix batch.

## 8. Safety

```text
code_changes=0
test_changes=0
runtime_changes=0
database_changes=0
production_migrations_applied=0
broker_writes=0
order_submissions=0
service_timer_changes=0
```

## 9. Acceptance evidence

```text
source_files=9
archive_targets=8
archive_moves_completed=8
remove_targets=1
remove_completed=1
live_refs_scanned=19
live_refs_repaired=18
broken_live_references=0
historical_refs_preserved=7
unique_current_rules_found=0
rules_lost=0
source_files_deleted=1
source_files_moved=8
code_changes=0
test_changes=0
runtime_changes=0
database_changes=0
broker_writes=0
order_submissions=0
service_timer_changes=0
```
