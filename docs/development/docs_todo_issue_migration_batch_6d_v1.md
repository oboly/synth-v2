# docs/todo Issue Migration — Batch 6D

## 1. Status

```text
COMPLETE
```

All 18 tracked files under `docs/todo/external_research/`,
`docs/todo/market_intelligence/`, and `docs/todo/reporting/` carry a
`## GitHub Issue migration` block with `Unmigrated executable scope: none`.
This closes Batch 6A's three remaining folder-based lanes. This is a
folder-scope-only COMPLETE; it does not imply repository-wide TODO
retirement is complete (see Section 11).

## 2. Exact folder inventory

| Path | Folder | Classification | Issue owner(s) | Unmigrated scope | Status |
| ---- | ------ | -------------- | -------------- | ---------------- | ------ |
| docs/todo/external_research/README.md | external_research | navigation | none (README) | none | migrated |
| docs/todo/external_research/cross_asset_public_data_and_instrument_registry_v1.md | external_research | active/open | #302 | none | migrated |
| docs/todo/external_research/ffg_mega_run_target_scenarios_v1.md | external_research | speculative/parked | none required | none | migrated |
| docs/todo/external_research/ffg_universe_metadata_v1.md | external_research | implemented/superseded | none required (see `docs/research/ffg_research_universe_v1.md`) | none | migrated |
| docs/todo/market_intelligence/README.md | market_intelligence | navigation | none (README) | none | migrated |
| docs/todo/market_intelligence/catalyst_engine_v1.md | market_intelligence | active/open (delta) | #228 (existing, narrow), #300 (new, broader) | none | migrated |
| docs/todo/market_intelligence/composite_market_regime_v1.md | market_intelligence | active/open | #301 | none | migrated |
| docs/todo/market_intelligence/cross_asset_rotation_research_v1.md | market_intelligence | active/open | #303 (dep: #302) | none | migrated |
| docs/todo/market_intelligence/ffg_rotation_classification_v1.md | market_intelligence | active/open | #304 | none | migrated |
| docs/todo/market_intelligence/macro_regime_engine_v1.md | market_intelligence | active/open | #305 | none | migrated |
| docs/todo/market_intelligence/momentum_flow_scanner_research_v1.md | market_intelligence | active/open (delta) | #277 (existing, narrower), #306 (new, broader) | none | migrated |
| docs/todo/market_intelligence/narrative_engine_v1.md | market_intelligence | active/open | #307 | none | migrated |
| docs/todo/market_intelligence/sector_rotation_engine_v1.md | market_intelligence | implemented/accepted | #204 (existing, remaining acceptance actions) | none | migrated |
| docs/todo/market_intelligence/sector_rotation_master_plan_v1.md | market_intelligence | mixed (implemented + open Phase B2 + unscoped Phase D) | #204 (existing), #309 (new, Phase B2) | none | migrated |
| docs/todo/reporting/README.md | reporting | navigation | none (README) | none | migrated |
| docs/todo/reporting/ffg_rotation_radar_presentation_v1.md | reporting | active/open | #311 | none | migrated |
| docs/todo/reporting/ma_volume_stoplight_dashboard_v1.md | reporting | active/open (split: research + reporting) | #310 (research), #315 (new, reporting) | none | migrated |
| docs/todo/reporting/profit_plan_opportunity_presentation_v1.md | reporting | active/open (delta) | #233 (existing), #256 (existing, closed), #313 (new, residual) | none | migrated |

18 tracked files, 18 inventory rows, 0 duplicates, 0 unclassified.

## 3. Existing Issue overlap

Inspected in full (title + body):

```text
#228  Design external catalyst monitor schema and dry runner            -> narrow news-catalyst P0 schema only; catalyst_engine_v1.md delta not covered
#239  Build read-only bullrun-start dashboard module                    -> no overlap with these 3 folders
#240  Complete cockpit and wallet UI cleanup scope                      -> no overlap
#243  Define multi-horizon strategy architecture contract               -> no overlap
#248  Add tokenomics event intelligence (unlocks/emissions/burns)       -> supply-event feature layer; distinct from catalyst taxonomy/calendar
#249  Fibo Map dashboard only renders A-C symbols                       -> no overlap
#254  Add multi-account operator intent and ladder-request state        -> no overlap
#256  Fix Profit Plan Sort-PPP ordering in both directions (CLOSED)     -> already covers null-last sort/tie-break scope in profit_plan_opportunity_presentation_v1.md
#266  Restore fresh Market Rotation Pressure runtime publication        -> different capability (market_rotation_pressure, not sector_rotation_snapshot); no overlap
#270  Validate Fibo/zone exit-profile...                                -> no overlap
#271  Add Fibo/zone UI overlays...                                      -> no overlap
#277  Add volume-flow candle classification to Profit Plan              -> narrower display-only feature; momentum_flow_scanner_research_v1.md is broader research contract
#278  Expose research backtest/visual-review outputs through cockpit    -> no overlap
#285  Select and validate first paper-track strategy candidate          -> no overlap
#286  Decide market trigger engine watch/event/state schema             -> no overlap
#297  Implement Signal Matrix Static Dashboard V1                       -> no overlap
#204  Review and accept Sector Rotation dashboard against canonical contracts -> owns Phase C dashboard acceptance and the activation-gate definition for sector_rotation_engine_v1.md
#233  Implement accepted Profit Plan coin-card scanability improvements -> covers compact field/tooltips/dedup/alignment subset of profit_plan_opportunity_presentation_v1.md
```

Also inspected: PR #275 (merged, "Prepare gurkDB market_rotation_pressure writer cutover") and
`docs/ops/sector_rotation_runtime_activation_v1.md` to confirm the sector-rotation writer→publisher
chain is prepared-but-not-activated and that `sector_rotation_engine_v1.md` itself explicitly
delegates remaining acceptance work to the Phase C dashboard lane (#204), which already has
"activation requirements are explicit and separate from repository merge" as an acceptance
criterion. No separate ops/runtime activation Issue was created for sector rotation to avoid
duplicating that ownership.

Searched for Issues numbered 299+: none exist (299 was Batch 6C's merge PR, not an Issue).
Searched issue titles/bodies for "sector rotation", "Actionable PPP", "Opportunity Rank",
"SMA150"/"stoplight": no additional overlap found beyond what is listed above.

## 4. New Issues created

| Issue | Source file(s) | Architecture owner | Scope |
| ----- | -------------- | ------------------ | ----- |
| #300 | market_intelligence/catalyst_engine_v1.md | research | Catalyst taxonomy/event contract beyond #228's narrow schema |
| #301 | market_intelligence/composite_market_regime_v1.md | research | Composite market regime contract and state vocabulary |
| #302 | external_research/cross_asset_public_data_and_instrument_registry_v1.md | architecture/data-foundation | Provider feasibility and instrument allowlist |
| #303 | market_intelligence/cross_asset_rotation_research_v1.md | research | Crypto -> metals/miners/food-agriculture rotation research |
| #304 | market_intelligence/ffg_rotation_classification_v1.md | research | Market-only rotation classification for FFG universe |
| #305 | market_intelligence/macro_regime_engine_v1.md | research | Macro regime input inventory and classifiers |
| #306 | market_intelligence/momentum_flow_scanner_research_v1.md | research | Scanner research contract (distinct from #277) |
| #307 | market_intelligence/narrative_engine_v1.md | research | Narrative taxonomy and narrative-strength research |
| #309 | market_intelligence/sector_rotation_master_plan_v1.md (Phase B2 only) | research | Sector Rotation Phase B2 market-filter candidate audit |
| #310 | reporting/ma_volume_stoplight_dashboard_v1.md | research | MA/volume trend-flow feature research and classification design |
| #311 | reporting/ffg_rotation_radar_presentation_v1.md | reporting | FFG rotation radar presentation (market classification + account overlay) |
| #313 | reporting/profit_plan_opportunity_presentation_v1.md | reporting | Opportunity Rank, actionable-candidate counts, empty-state presentation |
| #315 | reporting/ma_volume_stoplight_dashboard_v1.md | reporting | MA/volume stoplight dashboard presentation (consumes #310 output, read-only) |

## 5. Existing Issues reused

| Issue | Source file(s) | Scope |
| ----- | -------------- | ----- |
| #228 | market_intelligence/catalyst_engine_v1.md | Narrow P0 news-catalyst monitor schema/dry-runner |
| #204 | market_intelligence/sector_rotation_engine_v1.md, sector_rotation_master_plan_v1.md | Phase C dashboard acceptance + activation-gate definition |
| #277 | market_intelligence/momentum_flow_scanner_research_v1.md | Display-only volume-flow candle classification |
| #233 | reporting/profit_plan_opportunity_presentation_v1.md | Compact field, tooltip registry, dedup tile, alignment |
| #256 (closed) | reporting/profit_plan_opportunity_presentation_v1.md | Sort-PPP null-last ordering and deterministic tie-breaks |

## 6. external_research migration

- `README.md` — navigation only; migrated, no Issue.
- `cross_asset_public_data_and_instrument_registry_v1.md` — genuinely open provider-feasibility/instrument-allowlist work with no prior owner; migrated to new Issue #302 (architecture/data-foundation).
- `ffg_mega_run_target_scenarios_v1.md` — speculative external FFG price-target narrative for INJ/ENA/MORPHO with no validated operational use; no Issue created to avoid manufacturing implementation work from narrative. The existing canonical `docs/research/external_forecast_event_registry_v1.md` contract already covers the correct ingestion pattern if this narrative is ever promoted to data.
- `ffg_universe_metadata_v1.md` — scope is implemented and superseded by the already-accepted `docs/research/ffg_research_universe_v1.md` (canonical tables, migration, import command, acceptance counts); no Issue required.

## 7. market_intelligence migration

- `README.md` — navigation only; migrated, no Issue.
- `catalyst_engine_v1.md` — narrow schema owned by existing #228; broader taxonomy/event-contract delta migrated to new #300.
- `composite_market_regime_v1.md` — genuinely open, unimplemented; migrated to new #301.
- `cross_asset_rotation_research_v1.md` — genuinely open research question depending on #302's inputs; migrated to new #303.
- `ffg_rotation_classification_v1.md` — genuinely open, unimplemented; migrated to new #304.
- `macro_regime_engine_v1.md` — genuinely open, unimplemented; migrated to new #305.
- `momentum_flow_scanner_research_v1.md` — broader scanner research contract distinct from #277's narrower display-only feature; migrated to new #306.
- `narrative_engine_v1.md` — genuinely open, unimplemented; migrated to new #307.
- `sector_rotation_engine_v1.md` — Phase A/B are implemented and accepted (persisted cohort, audited); the file's own "Remaining acceptance actions" section explicitly delegates all remaining work to the Phase C dashboard lane; no new Issue, existing #204 owns the remainder.
- `sector_rotation_master_plan_v1.md` — Phase A/B implemented; Phase C owned by existing #204; Phase B2 market-filter candidate audit is genuinely open and unowned, migrated to new #309; Phase D has no defined scope in this document and is not started, so no Issue was created for it (would be manufacturing work from an unscoped roadmap placeholder).

## 8. reporting migration

- `README.md` — navigation only; migrated, no Issue.
- `ffg_rotation_radar_presentation_v1.md` — genuinely open read-only presentation lane; migrated to new #311.
- `ma_volume_stoplight_dashboard_v1.md` — split by architecture owner. Feature research, classification-threshold design, and historical validation migrated to new #310 (research). The source file also contains explicit bounded reporting scope (150MA trend stoplight, volume-lifecycle stoplight, machine-readable label plus human-readable reason, compact dashboard row, expandable explanation panel, freshness/insufficient-data presentation); that scope does not vanish because #310 must land first, so it was migrated to new #315 (reporting), which depends on #310 and consumes its persisted, versioned output strictly read-only. Neither Issue crosses the other's boundary: #310 defines no rendering, #315 calculates no features or thresholds.
- `profit_plan_opportunity_presentation_v1.md` — compact-field/tooltip/dedup/alignment scope already owned by existing #233; null-last sort/tie-break scope already delivered by existing closed #256; the residual (Opportunity Rank, actionable-candidate counts, empty-state presentation) migrated to new #313.

## 9. README/navigation disposition

No Issues were created for the three folder README files
(`external_research/README.md`, `market_intelligence/README.md`,
`reporting/README.md`). Each is navigation-only: it lists canonical child
files and split-ownership pointers but defines no independent executable
requirement of its own. With every child file in this batch now carrying its
own migration block and zero unmigrated executable scope, each README's
effective executable scope is also zero. Each README's migration block
states this explicitly. Folder retirement (deleting or archiving the
directories) is a separate, later step not performed by this batch.

## 10. Architecture safety

- External research remains non-authoritative: every new external_research
  Issue (#302) and every migration-block disposition (ffg_mega_run,
  ffg_universe_metadata) preserves "market-only, account-agnostic,
  non-operational, no execution authority" language from the source files;
  none grant `selection_engine`, `decision_gate`, or `execution_planner`
  authority.
- No reporting Issue gains decision/execution authority: #311 and #313 both
  carry `broker_writes=0`, `order_submission=0`, `decision_permission=0`,
  `execution_intent=0` safety boundaries and explicit "not owned here"
  sections excluding market computation and account permission.
- No account state entered market classifiers: all research Issues (#300,
  #301, #303, #304, #305, #306, #307, #309, #310) carry
  `account_awareness=0` and explicitly exclude account/portfolio/permission
  fields from their contracts.
- No runtime authorization implied by Issue creation: none of the 13 new
  Issues touch `decision_gate`, `execution_planner`, or `executor`; none
  authorize service/timer installation, DB migration application, or
  production deployment. Each new Issue's safety-boundary block matches its
  architecture-owner template (research / architecture-data-foundation /
  reporting) from the task's Issue-creation rules. Architecture-owner
  counts across the 13 new Issues: research=9 (#300, #301, #303, #304,
  #305, #306, #307, #309, #310), architecture/data-foundation=1 (#302),
  reporting=3 (#311, #313, #315). #315 explicitly excludes feature
  calculation, threshold definition, predictive-value validation,
  `selection_engine`/`decision_gate` changes, account-state reads, and
  broker/order behavior; it is a strict read-only consumer of #310's
  persisted output.
- No duplicate rotation runtime path: the sector-rotation writer→publisher
  activation described in `docs/ops/sector_rotation_runtime_activation_v1.md`
  is not duplicated by any new Issue; `sector_rotation_engine_v1.md`'s
  remaining scope is explicitly routed to existing #204, and the separate
  `market_rotation_pressure` capability (#266, PR #275) was confirmed to be
  a different capability with no overlap.

## 11. Retirement impact

```text
batch_6a_keep_temporarily_original=33
batch_6b_files_migrated=2
batch_6c_single_file_targets=13
batch_6c_fully_migrated=12
batch_6c_partial_files=1
batch_6d_folder_files=18
batch_6d_fully_migrated=18
batch_6d_partially_migrated=0
remaining_unowned_folder_files=0
```

This batch does not claim global TODO-retirement completion (R1 PASS).
Batch 6C's multi-account Phases 2-5 remain deferred pending #294 review, and
that single-file partial (`multi_account_asset_foundation_backlog.md`) was
explicitly out of scope for this batch and was not touched. Physical
folder/file retirement (deletion or archive of the three target
directories) has not been performed and remains a separate, later step.

## 12. Acceptance evidence

```text
tracked_folder_files=18
inventory_rows=18
duplicate_inventory_rows=0
unclassified_files=0
source_files_fully_migrated=18
source_files_partially_migrated=0
existing_issues_inspected=18
existing_issues_reused=5
new_issue_create_events=13
unique_new_issues_created=13
duplicate_issues_created=0
duplicate_issues_remaining_open=0
unmigrated_executable_scope_items=0
architecture_boundary_violations=0
source_files_deleted=0
source_files_moved=0
code_changes=0
test_changes=0
runtime_changes=0
database_changes=0
production_migrations_applied=0
broker_writes=0
order_submissions=0
service_timer_changes=0
```
