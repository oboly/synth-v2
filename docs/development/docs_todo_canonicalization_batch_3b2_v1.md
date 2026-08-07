# Docs/TODO Canonicalization — Batch 3B2 (Market Breath)

## 1. Status

`COMPLETE`

## 2. Comparison matrix

| TODO section | Canonical counterpart | Classification | Disposition |
| ------------ | --------------------- | -------------- | ----------- |
| `## Status` | Canonical `## Status` | canonical_duplicate | Removed; canonical already states `characterized and parked until a downstream use-case explicitly needs it` and the A+ parked rule. |
| `## Final summary` | Canonical `## Status`, `## Threshold calibration decision`, `## Runtime decision` | canonical_duplicate | Removed; conclusions (regime-dependent classifier, not universal action engine, threshold calibration blocked, no runtime promotion) are already stated in canonical. |
| `## Design rule — regime first` | Canonical `## Core design conclusion` | canonical_duplicate | Removed; identical interpretation path and `Regime first. Signal second. Execution last.` rule already present verbatim in canonical. |
| `## Sources` | Not present in canonical (canonical only had `## Research sequence covered`, a conceptual step list without file paths) | canonical_unique_addition | Added as new `## Research sources` section in canonical (docs/runners/data-output paths). |
| `## Phase classifications` | Canonical `## Phase classifications` | canonical_duplicate | Removed; canonical has the same six phases with the same classification labels plus richer `Finding`/`Interpretation`/`Use` detail than the TODO version. No content lost. |
| `## Completed loop` (P0–P7 sequence) | Canonical `## Research sequence covered` | historical_completed_record / canonical_duplicate | Removed; same seven-step sequence already recorded in canonical (differently labeled: `P0`–`P7` vs. descriptive arrow-chain). No unique historical detail (no dates, PRs, or evidence IDs) beyond what canonical already records. |
| `## Parked state` | Canonical `## Recommended parked state` | canonical_duplicate | Removed; identical four reopen triggers already present verbatim in canonical. |
| `## P1 — Regime cockpit page` | Not present in canonical (out of scope for a research summary) | open_downstream_scope | Handled separately — see Section 4. Field-name list (`symbol_breath_profile_v1`, `regime_interaction_audit_v1`, per-asset display fields) preserved in this manifest, not copied into the research summary (dashboard backlog content, not research content). |
| `## P1 — Regime cockpit page` → "Language rule" (breath/participation/breadth spelling) | Not present in canonical | canonical_unique_addition | Added as new `## Terminology` section in canonical — this is a general research-writing/terminology rule, not cockpit-specific, and applies to the summary doc's own field names (e.g. `breadth_alignment_score`). |
| `## Boundary` | Canonical `## Boundaries` | canonical_duplicate | Removed; TODO's boundary list enumerates more line items (no broker calls, no broker writes, no order submission, no decision_gate/execution_planner/executor changes) but these are conceptually covered by canonical's `No operational chain changes` and `No runtime promotion` plus the `Runtime decision` section. Not added — avoids duplicating concepts already present. |
| `## Non-goals` | Canonical `## Non-goals` | canonical_duplicate | Removed; TODO's "do not promote characterized contexts without downstream use-case + validation" duplicates canonical's "do not add candidate promotion"; "do not convert Market Breath directly into action logic" duplicates canonical's `Runtime decision` section and core design conclusion. |

## 3. Canonical additions

Added to `docs/research/market_breath_v1_sensor_classification_summary.md`:

1. `## Research sources` — the detailed docs/runners/data-output path list from the TODO file's `## Sources` section (not previously recorded anywhere in canonical form).
2. `## Terminology` — the breath/participation/breadth spelling rule from the TODO file's P1 section (general terminology rule, applicable beyond the cockpit use-case).

No phase classification, threshold-calibration decision, runtime-promotion decision, parked-state criteria, or architecture-boundary text was changed.

```text
duplicate_content_copied=0
research_findings_changed=0
```

## 4. P1 regime cockpit ownership analysis

### Inspected

- Issue #239 (`Build read-only bullrun-start dashboard module`) — scope is the `FLUSH`/`BOTTOM_CLOSE`/`BTC_RECLAIM` bullrun-start dashboard; no Market Breath or regime content in its acceptance criteria.
- Issue #240 (`Complete cockpit and wallet UI cleanup scope`) — scope is Profit Plan cockpit/wallet presentation cleanup; no Market Breath or regime content in its acceptance criteria.
- Issue #231 (`Run regime research Phase 1 replay and discovery comparison`) — scope is rerunning `rotation_destination_historical_replay_audit_v2` and `market_regime_discovery_v1` and reviewing their CSV outputs; a research task, not a dashboard/reporting deliverable, and does not mention Market Breath or a cockpit page.
- `docs/todo/signal_matrix_dashboard.md` — a still-parked TODO (not an Issue) for a future `signal_matrix_static_dashboard_v1`. Lists "Regime context" as one of eight required display layers (line 75) and "regime context" again in required-fields checklists (lines 119, 137, 171, 208, 218, 228, 232), but this is a general multi-layer signal-inventory concept, not a Market-Breath-specific regime page, and it is not implemented and not filed as an Issue.
- `docs/research/breath_fibo_strategy_static_dashboard_v1.md` — covers `active_regime_observation` / `regime_context` fields, but this is the discovered-regime/backtest regime layer (`src/regime/run_active_regime_observation_v1.py`), a different regime concept than Market Breath's per-asset phase/context state.
- `docs/research/paper_advice_manual_trading_cockpit_v1.md` — explicitly lists "Market Breath or breathline context when explicitly available" as decision-context row content (line 203) and a `REGIME_CONTEXT_V1` field (lines 233, 241). This document describes the currently implemented manual-trading cockpit design.
- `docs/ops/market_breath_context_bridge_v1.md` — describes `src/reporting/market_breath_context_bridge_v1.py`, an already-implemented, read-only reporting bridge that outputs exactly the per-asset field set the TODO's P1 section requested for the regime page: `market_breath_phase`, `market_breath_state`, `market_breath_context_state`, `momentum_score`, `relative_strength_score`, `btc_alignment_score`, `breadth_alignment_score`, plus A+ legacy freshness fields.
- `src/reporting/run_paper_advice_static_dashboard_v1.py` and `src/reporting/run_manual_ladder_static_dashboard_v1.py` — both already import/consume `market_breath_context_bridge_v1` output fields (`market_breath_phase`, `market_breath_context_state`, etc.) and render them in existing read-only dashboards.
- `docs/research/symbol_breath_profile_v1.md` / `src/research/run_symbol_breath_profile_v1.py` — the TODO's "downstream candidate if reopened later" `symbol_breath_profile_v1` already exists as a completed research lane.
- `docs/research/rotation_destination_regime_interaction_audit_v1.md` / `src/research/run_rotation_destination_regime_interaction_audit_v1.py` — the TODO's other named downstream candidate, `regime_interaction_audit_v1`, already exists (as `rotation_destination_regime_interaction_audit_v1`).

### Overlap evidence

The TODO's P1 section asked for a dedicated `/synth/regime.html` page displaying, per asset: `market_breath_phase`, `market_breath_state`, `market_breath_context_state`, `momentum_score`, `relative_strength_score`, `btc_alignment_score`, `breadth_alignment_score`, and A+ legacy freshness/context. Every one of those fields is already produced by the implemented, read-only `market_breath_context_bridge_v1` reporting bridge and already consumed by the existing `run_paper_advice_static_dashboard_v1.py` and `run_manual_ladder_static_dashboard_v1.py` dashboards. The two named "downstream candidates if reopened later" (`symbol_breath_profile_v1`, `regime_interaction_audit_v1`) have also already been built as research lanes since the TODO was written.

No standalone page literally named `/synth/regime.html` exists, and no open GitHub Issue names that literal deliverable. Issues #239/#240 are dashboard Issues but their acceptance scope does not cover Market Breath or a regime page — they were not assigned this scope merely because they are also dashboard Issues, per the task's explicit prohibition.

### Final disposition

```text
p1_disposition=superseded
```

The substantive intent of the P1 section — surfacing Market Breath's per-asset phase/state/context fields as read-only cockpit context — is already implemented and already live in existing dashboards via `market_breath_context_bridge_v1`. The literal `/synth/regime.html` standalone-page framing is an implementation detail that was never built and is not required to satisfy the underlying need; a fresh dedicated page is a future product/UX decision, not a lost research or reporting requirement. No uncovered scope remains that requires a new Issue candidate.

```text
P1_EXISTING_OWNER=none (superseded by src/reporting/market_breath_context_bridge_v1.py consumed in run_paper_advice_static_dashboard_v1.py and run_manual_ladder_static_dashboard_v1.py)
P1_UNCOVERED_SCOPE=none — a standalone /synth/regime.html page was never built, but every field and data source it would have needed already exists and is already displayed in existing read-only dashboards
```

No Issue was created or modified: the scope is not genuinely unowned (it is functionally superseded), so no future-Issue candidate was required, and modifying #239/#240 would have been scope creep into Issues whose acceptance criteria do not cover this content.

## 5. Archive handling

No archive file was created.

- `docs/archive/market_breath_todo_retirement_history_v1.md` was not created because the TODO file's `## Completed loop` (P0–P7) history is a duplicate re-labeling of canonical's `## Research sequence covered`, with no unique dates, PR references, or evidence IDs.
- Duplicated canonical prose (status, final summary, design rule, phase classifications, parked state, boundary, non-goals) was not archived, per instruction not to archive every line merely to preserve it.

## 6. Reference handling

### Live references updated

- `docs/todo/README.md` — removed the `market_breath.md` lane-index row (matches the precedent of prior canonicalized files, which are dropped from this table entirely rather than left with a disposition note).
- `docs/research/synth_v2_research_todo_index.md` — removed `docs/todo/market_breath.md` from the "Canonical TODO files" listing (the file no longer exists).
- `docs/ops/sticky_dashboard_identity_target_columns_v1.md` — updated the "TODO Administration" bullet to note the file's Batch 3B2 retirement and point to this manifest and the canonical summary's new Terminology section.

### Historical references retained (dated provenance)

- `docs/research/market_breath_v1_1_neutral_rest_bucket_review.md:18` — lists `docs/todo/market_breath.md` as a reviewed input file for a `Status: complete` research review that predates the classification summary (per canonical's own sequence, the neutral rest-bucket review happened before the sensor classification summary was written). Changing this to point at the summary would misrepresent what was actually read at that point in time, so the old path is retained as a dated historical record.
- `docs/development/github_issues_remaining_todo_inventory_v1.md` (lines 166, 690, 966, 972) — a dated TODO-migration planning manifest (its own "Batch 2B" section) that already recommends the same `canonical` disposition this batch executes. Retained verbatim as dated provenance of the migration plan.

### Not references to the removed file

`market_breath_context_state` matches in `src/research/run_rotation_destination_outcome_audit_v1.py`, `src/reporting/*.py`, `tests/test_rotation_destination_eligibility_v1.py`, `docs/research/historical_breath_regime_context_backbone_v1.md`, and `docs/research/historical_market_breath_source_recompute_v1.md` are the live code/data field name, not references to `docs/todo/market_breath.md`. No change required.

```text
broken_references=0
ambiguous_canonical_references=0
```

## 7. Architecture safety

- No Market Breath calculation changed.
- No threshold changed.
- No selection logic changed.
- No account-aware permission changed.
- No execution intent changed.
- No order handling changed.
- No runtime promotion occurred.
- Any future regime page remains reporting-only per this manifest's Section 4 analysis; this batch did not build one.

## 8. Acceptance evidence

```text
source_files=1
canonical_documents=1
source_paths_removed=1
redirect_shells_created=0
duplicate_canonical_documents=0
unclassified_substantive_sections=0
duplicate_content_copied=0
research_findings_changed=0
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
```
