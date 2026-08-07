# Docs/TODO Canonicalization — Batch 3A

## 1. Status

`PARTIAL — 2 of 4 completed, 2 deferred (BLOCKED)`

This batch was scoped as a 4-file canonicalization. During inspection, 2 of
the 4 required source files were found to be local-only (never tracked, not
pushed to `origin`), which violates the task's completion guard
("do not commit or report PASS if any source file is untracked or
local-only"). Per explicit user direction, this PR proceeds with only the
2 tracked source files. The 2 local-only files are deferred to a future
batch once they are tracked.

## 2. Scope

| Old path | New canonical path | Canonical role | Move status |
| -------- | ------------------- | --------------- | ----------- |
| `docs/todo/aplus_harmonic_breathline_claim_audit_v1.md` | `docs/research/aplus_harmonic_breathline_claim_audit_v1.md` | Permanent claim-correction reference (Prime-17, 21-day Breathline harmonic audit) | **DEFERRED — BLOCKED (local-only, untracked)** |
| `docs/todo/astro_policy_confluence_research_todo_bundle_v1.md` | `docs/research/astro_policy_confluence_v1.md` | Permanent research design (hypotheses H1-H6) | **DEFERRED — BLOCKED (local-only, untracked)** |
| `docs/todo/external_forecast_event_registry.md` | `docs/research/external_forecast_event_registry_v1.md` | Permanent external-forecast event data contract | **MOVED** |
| `docs/todo/idiosyncratic_catalyst_override.md` | `docs/research/idiosyncratic_catalyst_override_v1.md` | Permanent concept/taxonomy note ("dirty squeeze" catalyst-override model) | **MOVED** |

```text
source_files=4
canonical_destinations=2
moves_completed=2
copies_retained=0
redirect_shells_created=0
deferred_blocked=2
```

### Deferral evidence (untracked/local-only sources)

Both deferred files are excluded from git tracking via `.git/info/exclude`
(local, machine-specific, not part of the tracked repo config), under the
comment header `# Local devlap backlog / scratch docs`:

```text
.git/info/exclude:38: docs/todo/aplus_harmonic_breathline_claim_audit_v1.md
.git/info/exclude:39: docs/todo/astro_policy_confluence_research_todo_bundle_v1.md
```

`git log --oneline -- <path>` returns no history for either file, and
`git ls-files` does not list them. They exist on this developer's local
filesystem only and have never been part of the shared, pushed repository
history. Canonicalizing local-only scratch content into the shared
`docs/research/` tree would silently introduce previously-unreviewed,
unshared content into `origin/main`, which this batch does not do.

## 3. Content handling

### `external_forecast_event_registry.md` → `external_forecast_event_registry_v1.md`

* Permanent content preserved: full field/category/`forecast_type` enum
  design, validation-result schema, BTC 19-June worked example, example
  JSONL record, correct-path/forbidden-path diagram.
* TODO-specific framing removed: `Status: TODO` replaced with
  `Status: Permanent research/ETL data contract`; added canonical-location
  line; added explicit architecture-boundary statement (no authority over
  `selection_engine`, `decision_gate`, `execution_planner`, executor/agents,
  broker).
* Self-reference normalized: the "Proposed doc/data lane" section's
  "Initial document: docs/todo/external_forecast_event_registry.md" line was
  updated to point at the new canonical path (this is the document's own
  self-reference, not an external inbound reference).
* Technical findings changed: **none** — schema, enums, and examples are
  byte-identical apart from the header and the one self-reference line.
* Architecture clarification added: yes (explicit no-authority statement,
  consistent with the file's pre-existing hard-boundaries section).

### `idiosyncratic_catalyst_override.md` → `idiosyncratic_catalyst_override_v1.md`

* Permanent content preserved: full "dirty squeeze" / catalyst-override
  concept model, XLM/DTCC/Stellar case study, source event detail,
  inputs/outputs, strategy implication, target-tracking notes, existing
  `## Boundary` section (research-only, no `decision_gate` bypass, no
  execution/executor/order changes, no global regime flip from a single
  asset).
* TODO-specific framing removed: title changed from
  `TODO — Idiosyncratic Catalyst Override` to
  `Idiosyncratic Catalyst Override`; `Status: Research/TODO lane` replaced
  with `Status: Permanent concept and taxonomy note` plus canonical-location
  line.
* Architecture clarification added: yes — a new `## Architecture boundary`
  section was inserted directly after Status, stating explicitly that
  "override" refers only to a research-layer interpretation exception, and
  that idiosyncratic catalyst context may inform market-only research or
  `selection_engine` inputs only after validation, must not bypass
  `decision_gate`, must not create execution intent, and must not
  submit/modify orders. This is additive to, and consistent with, the
  document's pre-existing `## Boundary` section further down — no
  contradiction was introduced.
* Technical findings changed: **none** — the XLM/DTCC case study, dates,
  source URL, and taxonomy are unchanged.

## 4. Reference handling

### Updated inbound references

* `docs/todo/external_research/ffg_mega_run_target_scenarios_v1.md:93` —
  `Align these target scenarios with docs/todo/external_forecast_event_registry.md.`
  updated to
  `Align these target scenarios with docs/research/external_forecast_event_registry_v1.md.`
  (live inbound reference intended to resolve to the canonical document).

### Intentionally retained historical old-path references

* `docs/development/github_issues_remaining_todo_inventory_v1.md:153,669-674`
  — historical migration-inventory row and evidence block documenting
  `external_forecast_event_registry.md` as a Batch-2B source with
  `recommended_destination=docs/research/external_forecast_event_registry_v1.md`.
  Retained: this is a dated historical migration manifest recording what the
  source path *was*; its recommended destination already matches the actual
  canonical path produced by this batch, so it remains accurate provenance
  and is not rewritten.
* `docs/development/github_issues_remaining_todo_inventory_v1.md:162,683-688`
  — same, for `idiosyncratic_catalyst_override.md` /
  `docs/research/idiosyncratic_catalyst_override_v1.md`. Retained for the
  same reason.
* `docs/development/github_issues_remaining_todo_inventory_v1.md:965-966`
  — Batch 2B file-list line naming both old filenames as part of a
  historical batch plan. Retained: historical planning record, not a live
  pointer.

### Not modified (concept-name mention, not a path reference)

* `docs/todo/news_catalyst_monitor.md:285` — references the concept name
  `idiosyncratic_catalyst_override_v1` (the taxonomy concept itself, as used
  in the destination document's own `## New concept` section), not a file
  path. No change needed; not a broken reference.

### README

* `docs/todo/README.md` — searched; contains no reference to either old
  filename. No change required.

```text
broken_references=0
ambiguous_canonical_references=0
```

## 5. Architecture safety

* No `selection_engine` behavior changed.
* No `decision_gate` account-aware permission behavior changed.
* No `execution_planner` execution-intent behavior changed.
* No executor/order behavior changed.
* No dashboard/runtime behavior changed.
* This is a documentation-only move plus header/architecture-clarification
  text edits; no code, test, database, service, timer, or configuration
  path was touched.
* `idiosyncratic_catalyst_override_v1.md` explicitly does not authorize
  bypassing `decision_gate` or the execution layers — this is stated both
  in the newly added `## Architecture boundary` section and the document's
  pre-existing `## Boundary` section, which were left consistent with each
  other.

## 6. TODO retirement effect

* 2 files removed from `docs/todo/` (the 2 tracked, in-scope files).
* 2 files could not be removed from `docs/todo/` this batch because they are
  local-only/untracked (see §2 deferral evidence); no repository-tracked
  content was lost or altered for these.
* No active GitHub Issue work was lost — neither moved file had an owning
  Issue; both were listed in the historical inventory as `canonical`
  (doc-move only, no Issue required).
* No GitHub Issue ownership was altered (no Issues created or modified).
* No new TODO intake path was created.
* `docs/todo/` contains 2 fewer canonical/permanent documents from this
  batch (2 more remain pending until tracked).

## 7. Acceptance evidence

```text
source_files=4
canonical_destinations=2
moves_completed=2
old_paths_remaining=0
duplicate_canonical_documents=0
copies_retained=0
redirect_shells_created=0
todo_board_language_remaining_in_canonical_headers=0
active_todo_index_entries_remaining=0
broken_references=0
ambiguous_canonical_references=0
issues_created=0
issues_modified=0
code_changes=0
test_changes=0
runtime_changes=0
database_changes=0
broker_writes=0
order_submissions=0
service_timer_changes=0
deferred_files=2
deferred_reason=untracked_local_only_source
```
