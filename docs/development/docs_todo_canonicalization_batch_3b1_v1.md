# Docs/TODO Canonicalization — Batch 3B1

## 1. Status

COMPLETE

## 2. Source section classification

Source: `docs/todo/external_research_ingestion.md` (confirmed tracked on
`origin/main` at blob `7e7a020` before removal).

| Source section | Lines | Classification |
| --- | --- | --- |
| Header / Purpose | 1-25 | ingestion_contract |
| Hard boundaries | 27-37 | ingestion_contract |
| Core strategy idea (`external_support_shoulder_reaction_strategy_v1`) | 39-64 | ingestion_contract |
| Martee signal horizon model (`signal_kind`, `signal_horizon`, `zone_precision`, `source_confidence_prior`) | 66-105 | ingestion_contract |
| Extraction schema | 107-139 | ingestion_contract |
| `level_role` values | 141-150 | ingestion_contract |
| `confirmation_type` values | 152-159 | ingestion_contract |
| `target_usage` values | 161-168 | ingestion_contract |
| Currency handling | 170-183 | ingestion_contract |
| Validation metrics (extraction) | 185-198 | ingestion_contract |
| Questions to answer | 200-206 | ingestion_contract |
| Latest unsaved research examples (Martee 2026-05-25, VET, KITE, PLUME, Terafab, NEAR live observation, macro bond-confidence score) | 208-409 | historical_example |
| Elliott Wave header / Purpose | 411-427 | elliott_wave_validation |
| Source examples (trigger, existing PRO-note asset list) | 429-444 | elliott_wave_validation |
| Proposed research lane name | 446-448 | elliott_wave_validation |
| Extracted fields (Elliott) | 450-477 | elliott_wave_validation |
| Allowed `wave_structure_type` | 479-490 | elliott_wave_validation |
| Validation metrics (Elliott) | 492-506 | elliott_wave_validation |
| Important rules (Elliott) | 508-517 | elliott_wave_validation |
| Key research questions (Elliott) | 519-527 | elliott_wave_validation |
| First manual candidates (XRP, VET, KITE, ENJ, BTC dated price levels) | 529-555 | historical_example |
| Output (self-proposed future file paths) | 557-569 | obsolete_duplicate |

No section was classified `ambiguous`. `unclassified_substantive_sections=0`.

## 3. Canonical ownership table

| Document | Owns |
| --- | --- |
| `docs/research/external_research_ingestion_v1.md` | extraction schema, source identity/provenance, publication/date fields, confidence/validation metadata, deterministic FX normalization, dedup/idempotency implied by schema fields, research-only architecture boundaries for the ingestion lane |
| `docs/research/external_elliott_wave_claim_validation_v1.md` | Elliott Wave external-claim schema, wave-structure enums, invalidation/re-anchor (`invalidation_level`, `shoulder_line`, `confirmation_level`) semantics, forecast-window/outcome validation metrics, claim-vs-observed comparison rules, research-only/market-only boundaries |
| `docs/archive/external_research_ingestion_historical_examples_v1.md` | dated raw-notes examples, stale "latest" snapshots, historical unsaved Elliott candidate examples, provenance explaining the split |

## 4. Content moved to ingestion contract

All rows classified `ingestion_contract` above, moved verbatim (values/enums
unchanged) into `docs/research/external_research_ingestion_v1.md`, with the
canonical status/scope/architecture-boundary header used by prior Batch 3A
research docs (see `docs/research/external_forecast_event_registry_v1.md`).
Added a "Related documents" section cross-linking the Elliott Wave doc, the
archive doc, and the existing overlay contract / forecast registry docs.

## 5. Content moved to Elliott Wave validation

All rows classified `elliott_wave_validation` above, moved verbatim into
`docs/research/external_elliott_wave_claim_validation_v1.md`. The dated
"Source examples" list (article trigger, per-asset PRO-note inventory) was
kept as scope-defining context, since it names asset categories with no
price/level data of its own, and points to the archive doc for the actual
dated per-asset claims. Added a canonical header and "Related documents"
section.

## 6. Content archived as historical examples

Both dated blocks — "Latest unsaved research examples" (Martee 2026-05-25,
VET, KITE, PLUME, Terafab AI chip window, NEAR live observation, macro
bond-confidence score) and "First manual candidates" (XRP, VET, KITE, ENJ,
BTC) — moved verbatim (values unchanged) into
`docs/archive/external_research_ingestion_historical_examples_v1.md`, each
under an "as captured <date>" heading. A provenance section at the top of the
archive doc explains the split and names both canonical destinations.

## 7. Removed obsolete duplicates

The source's "Output" section (lines 557-569) proposed the Elliott Wave
report's own future filename (`docs/research/external_elliott_wave_claim_validation_v1.md`),
an optional runner path, and a data target path. Since this batch creates
that exact document, the proposal is fulfilled rather than carried forward.
The runner and data-target paths were preserved as an "Output targets"
section in the Elliott Wave canonical doc (they are still-open future work
pointers, not duplicated narrative).

## 8. Reference updates

Live inbound reference updated:

- `docs/architecture/external_research_overlay_contract_v1.md` — "Related
  Documents" list entry `docs/todo/external_research_ingestion.md` replaced
  with both new canonical paths (`docs/research/external_research_ingestion_v1.md`,
  `docs/research/external_elliott_wave_claim_validation_v1.md`).

Reference intentionally retained (protected file, explicit do-not-touch
scope for this batch):

- `docs/todo/synth_v214_signal_dashboard_strategy_bridge_backlog.md:285` —
  lists `docs/todo/external_research_ingestion.md` under "Existing Overlap".
  This file is on the batch's explicit do-not-touch list. The reference is
  now stale (points to a removed path) and is recorded here as a known,
  intentionally-unfixed broken reference pending a future batch that is
  scoped to touch that backlog file.

References intentionally retained as dated provenance (planning/inventory
document, not a live pointer):

- `docs/development/github_issues_remaining_todo_inventory_v1.md` (5
  matches: lines 154, 676, 677, 965, 970) — this is a dated analysis/planning
  document that recorded the pre-split recommendation for this exact file.
  The old path there is historical record of the split plan, not a live
  reference to a document that still needs to exist.

## 9. Architecture safety

- No changes to `selection_engine`, `decision_gate`, `execution_planner`,
  `executor`, broker integrations, or any runtime/DB code.
- No new execution paths, no order logic, no account-aware logic introduced.
- Both canonical documents restate the research-only / market-only
  boundaries from the source (no promotion to `selection_engine`, no
  `decision_gate` bypass, no order creation).
- Documentation-only change; no code, test, runtime, or database files
  touched.

## 10. Acceptance evidence

```text
source_files=1
canonical_documents_created=2
archive_documents_created=1
source_paths_removed=1
redirect_shells_created=0
duplicate_sections=0
unclassified_substantive_sections=0
broken_references=1
ambiguous_canonical_references=0
active_todo_index_entries_remaining=0
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

`broken_references=1` is the intentionally retained
`docs/todo/synth_v214_signal_dashboard_strategy_bridge_backlog.md:285`
reference, per the batch's explicit do-not-touch scope (see Section 8).
