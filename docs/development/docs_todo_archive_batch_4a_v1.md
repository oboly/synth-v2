# docs/TODO Cleanup Batch 4A — Archive Completed Historical TODO Records

## 1. Status

`PARTIAL`

One of six candidates (`card_actionability_map_completed_navigation_v1.md`) does not
exist anywhere in the current tree (`docs/todo/`, `docs/archive/`, or
`docs/todo/completed/`), and has no matching git history under that filename.
It is deferred rather than archived. The other five candidates were verified
and archived.

## 2. Candidate verification matrix

| Source | Verification | Current owner/replacement | Disposition | Reason |
| ------ | ------------ | -------------------------- | ----------- | ------ |
| `docs/todo/card_actionability_map_completed_navigation_v1.md` | File does not exist in `docs/todo/`, `docs/archive/`, `docs/todo/completed/`, or anywhere in the tracked tree; no git history found under this filename | n/a | `DEFERRED` | Fails guard #1 (source exists and is tracked). Prior inventory (`docs/development/github_issues_remaining_todo_inventory_v1.md:716`) still lists it as present in `docs/todo/`, but that record is stale — the file is already gone. |
| `docs/todo/claude_bundle_1_pipeline_contracts_v1.md` | Confirmed present; confirmed `docs/architecture/pipeline_contracts.md`, `src/market_context/contracts_v1.py`, and `tests/test_pipeline_contract_boundaries_v1.py` all exist | `docs/architecture/pipeline_contracts.md` | `ARCHIVED` | Original was an agent-handoff task spec; canonical doc and guard tests are implemented and current. No open requirement remains. |
| `docs/todo/fib_navigation_map_rebuild_v1.md` | File itself states `Status: IMPLEMENTED`; confirmed `src/market_data/fib_navigation_map_v1.py`, `tests/test_fib_navigation_map_v1.py`, `tests/test_fib_navigation_map_exhaustion_rebuild_v1.py` exist | `src/market_data/fib_navigation_map_v1.py` | `ARCHIVED` | Explicit self-declared implementation; historical record only. |
| `docs/todo/historical_breath_regime_context_backlog.md` | File itself says `Status: active` / `PARTIAL_CONTEXT_EXISTS`, but confirmed the described P0 builder `src/research/run_historical_breath_regime_context_builder_v1.py` exists and is referenced as an already-inspected source by the (also archived) recompute backlog file; canonical doc confirmed present | `docs/research/historical_breath_regime_context_backbone_v1.md` | `ARCHIVED` | File's own `active` status is stale relative to actual implementation state. No open GitHub Issue treats this file as active source. |
| `docs/todo/historical_market_breath_source_enrichment_backlog.md` | File itself says `Status: active`, but confirmed `src/research/run_historical_market_breath_source_enrichment_v1.py` exists and its output is referenced as an existing input by the (also archived) recompute backlog file | `src/research/run_historical_market_breath_source_enrichment_v1.py` | `ARCHIVED` | Runner already implemented and run; backlog status stale. |
| `docs/todo/historical_market_breath_source_recompute_backlog.md` | File itself says `Status: active`, but confirmed `src/research/run_historical_market_breath_source_recompute_v1.py` and `tests/test_historical_market_breath_source_recompute_v1.py` both exist | `src/research/run_historical_market_breath_source_recompute_v1.py` | `ARCHIVED` | Runner and test already implemented; backlog status stale. |

Open GitHub Issues (checked via `gh issue list --state open`) were searched for
all six filenames in title/body — no matches found for any candidate.

## 3. Archive moves

```text
docs/todo/claude_bundle_1_pipeline_contracts_v1.md               -> docs/archive/claude_bundle_1_pipeline_contracts_v1.md
docs/todo/fib_navigation_map_rebuild_v1.md                       -> docs/archive/fib_navigation_map_rebuild_v1.md
docs/todo/historical_breath_regime_context_backlog.md            -> docs/archive/historical_breath_regime_context_backlog.md
docs/todo/historical_market_breath_source_enrichment_backlog.md  -> docs/archive/historical_market_breath_source_enrichment_backlog.md
docs/todo/historical_market_breath_source_recompute_backlog.md   -> docs/archive/historical_market_breath_source_recompute_backlog.md
```

All moves used `git mv` semantics (git recorded as renames, similarity 88-91%
due to the added archive banner).

## 4. Deferred candidates

### `docs/todo/card_actionability_map_completed_navigation_v1.md`

- **Blocker**: source file does not exist anywhere in the current tracked
  tree, and no git history exists under this exact filename. Cannot archive
  a file that is not present.
- **Remaining active scope**: none identified — the prior inventory
  (`docs/development/github_issues_remaining_todo_inventory_v1.md:716`)
  describes it as verified-implemented, consistent with it already having
  been removed/archived through some other prior action not reflected in
  that inventory's own text.
- **Owner**: unknown — no open GitHub Issue references it.
- **Recommended next action**: a follow-up batch (or a small doc fix) should
  correct the stale `docs/development/github_issues_remaining_todo_inventory_v1.md`
  record (line 716-720) to note the file no longer exists, rather than
  re-listing it as a pending archive candidate. No code or doc content is at
  risk since nothing referencing it as active was found.

## 5. Reference repairs

- **Live reference -> archive path**: `docs/todo/backtest_capability_contract_v1.md`
  line 24 (`## Sources` list) changed from
  `docs/todo/historical_breath_regime_context_backlog.md` to
  `docs/archive/historical_breath_regime_context_backlog.md` (with an inline
  note pointing to the canonical research owner). This file is itself frozen
  under GitHub Issue #218 per its own migration banner; only the stale path
  in its Sources list was corrected, not its status/priority/blockers/next
  action/execution order.
- **Live reference -> canonical owner**: none required beyond the above (the
  path repair already points readers to the canonical doc via the inline
  note).
- **TODO-index removal**: none required. `docs/todo/README.md` and
  `docs/research/synth_v2_research_todo_index.md` were both searched and
  contain no rows for any of the six candidate filenames.
- **Retained historical provenance**: `docs/development/github_issues_remaining_todo_inventory_v1.md`
  lines 716, 722, 734, 740, 746, 752 retain the old `docs/todo/...` paths.
  This is a frozen, dated inventory manifest documenting the prior
  archive-candidate analysis that this batch is executing; the old paths are
  the literal dated provenance for that analysis and were left untouched.

## 6. Content preservation

- All five archived files retain their full original substantive body
  unchanged below the added banner (verified: no historical content, dated
  observations, commands, or acceptance criteria were removed).
- No open/unowned requirement was silently deleted. The three "backlog" files
  had file-internal `Status: active` framing that is superseded by verified
  implementation evidence (documented per-file in the matrix above and noted
  inline in each archived file's banner); the original active-framing text
  itself was preserved verbatim in the body, not rewritten.
- Archive banners state "Active ownership: none" and point to canonical
  replacements/implementations; they do not claim current authority over any
  ongoing design decision.

## 7. Architecture safety

Zero changes to `selection_engine`, `decision_gate`, `execution_planner`,
executor/agents, reporting code, tests, DB/schema, runtime, deployments,
services, timers, or broker integration. This batch touched only files under
`docs/todo/`, `docs/archive/`, and this manifest under `docs/development/`.

## 8. Acceptance evidence

```text
candidate_files=6
archived_files=5
deferred_files=1
source_paths_removed=5
archive_paths_created=5
redirect_shells_created=0
active_requirements_lost=0
active_todo_index_entries_remaining_for_archived_files=0
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
