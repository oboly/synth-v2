# docs/todo Removal — Batch 5

## 1. Status

`COMPLETE`

All five reviewed candidates (2 primary + 3 additional) were verified as pure
redirect/pointer shells with fully split canonical ownership, no open Issue
source dependency, and no unique permanent content. All five were removed and
every live inbound reference was repaired to point at the current canonical
owner.

## 2. Candidate matrix

| Source | Classification counts | Verified current owners | Inbound refs | Disposition | Reason |
| ------ | --------------------- | ------------------------ | -----------: | ----------- | ------ |
| `docs/todo/cross_asset_metals_miners_food_rotation_v1.md` | redirect_pointer=1, duplicate_content=0, historical_context=1, unique_permanent_content=0, active_requirement=0, current_owner_reference=2, ambiguous=0 | `docs/todo/external_research/cross_asset_public_data_and_instrument_registry_v1.md` (108 lines), `docs/todo/market_intelligence/cross_asset_rotation_research_v1.md` (119 lines) | 5 (1 index row, 1 folder README historical split-note, 1 frozen-inventory analysis + 2 provenance lines) | REMOVED | Self-declared compatibility pointer; both split owners exist with full substantive content; no open Issue references it |
| `docs/todo/ffg_curated_rotation_radar_v1.md` | redirect_pointer=1, duplicate_content=0, historical_context=1, unique_permanent_content=0, active_requirement=0, current_owner_reference=3, ambiguous=0 | `docs/todo/external_research/ffg_universe_metadata_v1.md` (46 lines), `docs/todo/market_intelligence/ffg_rotation_classification_v1.md` (54 lines), `docs/todo/reporting/ffg_rotation_radar_presentation_v1.md` (55 lines) | 7 (1 index row, 1 folder README historical split-note, 3 "Historical umbrella specification" provenance lines in the split owners, 1 frozen-inventory analysis) | REMOVED | Self-declared "no longer owns active work... board is frozen"; all three split owners exist with substantive content; no open Issue references it |
| `docs/todo/momentum_flow_scanner_matrix_v1.md` | redirect_pointer=1, duplicate_content=0, historical_context=1, unique_permanent_content=0, active_requirement=0, current_owner_reference=2, ambiguous=0 | `docs/todo/market_intelligence/momentum_flow_scanner_research_v1.md` (57 lines), `docs/todo/reporting/profit_plan_opportunity_presentation_v1.md` (53 lines) | 8 (1 index row, 1 folder README historical split-note, 1 live cross-reference in `profit_plan_dashboard_action_truth_and_breathline_demote_v1.md`, 2 "Historical umbrella specification" provenance lines, 1 frozen-inventory analysis, 2 frozen-inventory bookkeeping lines) | REMOVED | Self-declared "former umbrella TODO no longer owns active work"; both split owners exist; only live (non-historical) reference was the cross-reference line, repaired to the research owner |
| `docs/todo/sector_rotation_master_plan_v1.md` | redirect_pointer=1, duplicate_content=0, historical_context=0, unique_permanent_content=0, active_requirement=0, current_owner_reference=1, ambiguous=0 | `docs/todo/market_intelligence/sector_rotation_master_plan_v1.md` (144 lines) | 6 (1 index row, 1 self-reference already inside `market_intelligence/README.md`'s own canonical-files list, 4 live "Sources" citations in `narrative_engine_v1.md`, `catalyst_engine_v1.md`, `composite_market_regime_v1.md`, `macro_regime_engine_v1.md`) | REMOVED | Pure "Moved" pointer with no independent status; canonical owner exists and is substantive (144 lines, active Phase B2 status); all 4 live "Sources" citations repaired to the canonical path |
| `docs/todo/sector_taxonomy_database_seed_v1.md` | redirect_pointer=1, duplicate_content=0, historical_context=0, unique_permanent_content=0, active_requirement=0, current_owner_reference=2, ambiguous=0 | `docs/todo/completed/sector_taxonomy_database_seed_v1.md` (51 lines), `docs/research/sector_taxonomy_database_seed_v1.md` (194 lines) | 9 (1 index row, 1 live "Sources" citation in `narrative_engine_v1.md`, 1 live dependency citation in `sector_rotation_dashboard_v1.md`, 4 references already pointing at the correct completed/research paths, 1 unrelated DB-migration filename match, 1 frozen-inventory analysis) | REMOVED | Self-declared "This completed lane moved to..."; both successor documents exist and are substantive; the 2 live references to the old root path were repaired to `docs/todo/completed/sector_taxonomy_database_seed_v1.md` |

## 3. Removal proof

For all five removed files:

- Each source file's entire body is either a compatibility-pointer
  declaration ("this file remains only to preserve historical context",
  "no longer owns active work", "Moved", "This completed lane moved to")
  or boundary language repeating that it owns no status/priority/execution
  authority. None contain schema, acceptance criteria, task lists, or
  requirements not already present in the split/canonical owner.
- Every named replacement/owner document was opened and confirmed to exist
  on current `main` with full substantive content (line counts recorded in
  the matrix above) — not stub files.
- `gh issue list --search "<old filename>"` returned no results for any of
  the five old filenames (`cross_asset_metals_miners_food_rotation_v1`,
  `ffg_curated_rotation_radar_v1`, `momentum_flow_scanner_matrix_v1`,
  `sector_rotation_master_plan_v1`, `sector_taxonomy_database_seed_v1`) —
  no open Issue treats any of them as an active source.
- Git history preserves the exact deleted content and the historical
  provenance lines already embedded in the surviving split-owner files
  (each split owner already carries a "Historical umbrella specification"
  or equivalent line pointing at the old path) — no archive copy is needed
  because there is nothing in the deleted files beyond what those retained
  provenance lines and git history already capture.

## 4. Deferred candidates

None. All five reviewed candidates (2 primary + 3 additional) qualified for
removal under the completion guard.

## 5. Reference repairs

Old path → new current owner (live navigation repaired):

- `docs/todo/momentum_flow_scanner_matrix_v1.md` → `docs/todo/market_intelligence/momentum_flow_scanner_research_v1.md`
  (in `docs/todo/profit_plan_dashboard_action_truth_and_breathline_demote_v1.md`)
- `docs/todo/sector_rotation_master_plan_v1.md` → `docs/todo/market_intelligence/sector_rotation_master_plan_v1.md`
  (in `docs/todo/market_intelligence/narrative_engine_v1.md`,
  `docs/todo/market_intelligence/catalyst_engine_v1.md`,
  `docs/todo/market_intelligence/composite_market_regime_v1.md`,
  `docs/todo/market_intelligence/macro_regime_engine_v1.md`)
- `docs/todo/sector_taxonomy_database_seed_v1.md` → `docs/todo/completed/sector_taxonomy_database_seed_v1.md`
  (in `docs/todo/market_intelligence/narrative_engine_v1.md`,
  `docs/todo/sector_rotation_dashboard_v1.md`)

TODO index rows removed (`docs/todo/README.md` "Lane index" table):

- `momentum_flow_scanner_matrix_v1.md`
- `ffg_curated_rotation_radar_v1.md`
- `sector_rotation_master_plan_v1.md`
- `sector_taxonomy_database_seed_v1.md`
- `cross_asset_metals_miners_food_rotation_v1.md`

Historical old-path references intentionally retained (git history and
migration/provenance context; not live navigation):

- `docs/todo/market_intelligence/README.md` "Split ownership" text block
  (documents the old umbrella filenames → new owners mapping as historical
  record; not a broken link)
- "Historical umbrella specification: `../<old file>.md`" lines in
  `docs/todo/external_research/ffg_universe_metadata_v1.md`,
  `docs/todo/market_intelligence/ffg_rotation_classification_v1.md`,
  `docs/todo/reporting/ffg_rotation_radar_presentation_v1.md`,
  `docs/todo/market_intelligence/momentum_flow_scanner_research_v1.md`,
  `docs/todo/reporting/profit_plan_opportunity_presentation_v1.md`
- All `source=`, table-row, and bookkeeping mentions of the five old
  filenames inside `docs/development/github_issues_remaining_todo_inventory_v1.md`
  (frozen historical analysis document, left unchanged except for the
  unrelated stale-entry correction in §7)

## 6. Additional-candidate discovery

Inspected the frozen inventory (`docs/development/github_issues_remaining_todo_inventory_v1.md`)
for all rows classified `remove`. Five such rows exist total; two were the
assigned primary candidates. Of the remaining three, all three were pulled
into this batch (the maximum allowed):

- `docs/todo/momentum_flow_scanner_matrix_v1.md` — REMOVE. Pure compatibility
  pointer; both split owners (`market_intelligence/momentum_flow_scanner_research_v1.md`,
  `reporting/profit_plan_opportunity_presentation_v1.md`) verified to exist
  with substantive content; no open Issue source; one live cross-reference
  repaired.
- `docs/todo/sector_rotation_master_plan_v1.md` — REMOVE. Pure "Moved"
  pointer (9 lines, no independent status); canonical owner
  `docs/todo/market_intelligence/sector_rotation_master_plan_v1.md` verified
  to exist with active, substantive content (144 lines); no open Issue
  source; four live "Sources" citations repaired.
- `docs/todo/sector_taxonomy_database_seed_v1.md` — REMOVE. Pure compatibility
  pointer (15 lines); both successors
  (`docs/todo/completed/sector_taxonomy_database_seed_v1.md`,
  `docs/research/sector_taxonomy_database_seed_v1.md`) verified to exist with
  substantive content; no open Issue source; two live references repaired.

No other `remove`/`redirect`/`pointer-only`/`superseded pointer`/`no unique
content` rows remained beyond these five in the frozen inventory's `remove`
column.

## 7. Stale inventory correction

Corrected. The `docs/development/github_issues_remaining_todo_inventory_v1.md`
row for `card_actionability_map_completed_navigation_v1.md` (line ~146)
previously recommended "Archive as closed" for a file that does not exist.
Batch 4A (`docs/development/docs_todo_archive_batch_4a_v1.md`) already
verified the file is absent from the tracked tree and has no discoverable
git history under that filename, and deferred any action.

This batch made one narrow correction to that row's final recommendation
column: it now states the source file is already absent as of Batch 4A
verification, references `docs/development/docs_todo_archive_batch_4a_v1.md`,
and clarifies no archive action is needed or possible. The row's original
historical analysis (PR #10 evidence, gating-PR context) is preserved
unchanged; no fabricated deletion commit or history was invented.

## 8. Architecture safety

Zero changes to `selection_engine`, `decision_gate`, `execution_planner`,
executor/agents, reporting code, tests, DB/schema/data, runtime, deployment,
services, timers, or broker/account integration. This batch touched only
files under `docs/todo/` and `docs/development/`.

## 9. Acceptance evidence

```text
primary_candidates=2
additional_candidates_inspected=3
removed_files=5
deferred_files=0
source_paths_removed=docs/todo/cross_asset_metals_miners_food_rotation_v1.md, docs/todo/ffg_curated_rotation_radar_v1.md, docs/todo/momentum_flow_scanner_matrix_v1.md, docs/todo/sector_rotation_master_plan_v1.md, docs/todo/sector_taxonomy_database_seed_v1.md
archive_paths_created=0
redirect_shells_created=0
unique_permanent_content_lost=0
active_requirements_lost=0
active_issue_sources_removed=0
active_todo_index_entries_remaining_for_removed_files=0
broken_references=0
ambiguous_reference_dispositions=0
issues_created=0
issues_modified=0
code_changes=0
test_changes=0
runtime_changes=0
database_changes=0
broker_writes=0
order_submissions=0
service_timer_changes=0
```
