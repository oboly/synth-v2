# GitHub Issues Remaining TODO Inventory v1

## 1. Status

`PROPOSAL_ONLY`

This document is a disposition proposal for every remaining file directly
under `docs/todo/`. It authorizes no Issue creation, file move, archive,
deletion, or code/runtime change. It is an additive continuation after the
first migration batch (PR #209, merge commit `4db27ed4a4e7c279914d9234524e836154a949d8`).

### Revalidation record (this correction pass)

```text
MAIN_SHA=20fd299a04cb783d7ea570c260d8d26235530825
PREVIOUS_MAIN_SHA_IN_DOCUMENT=4db27ed4a4e7c279914d9234524e836154a949d8
```

Local `main` was fetched and confirmed already fast-forwarded to
`origin/main` at `20fd299a04cb783d7ea570c260d8d26235530825` (merge of PR #213,
closing Issue #212). `git log 4db27ed4..20fd299a` shows exactly two commits:
`8ea5eedd` ("Add explicit visibility_class to Profit Plan cards (Issue
#212)") and its merge `20fd299a`. `git diff --name-only 4db27ed4..20fd299a`
touches only `src/reporting/manual_short_trader_profit_plan_v1.py`,
`src/reporting/run_manual_short_trader_profit_plan_v1.py`,
`src/reporting/run_manual_short_trader_profit_plan_input_audit_v1.py`, and
two test files — **zero files under `docs/`**. PR #213 resolves Issue #212
(the audit this session performed earlier) but does not touch any
`docs/todo/` file, any canonical destination cited below, or any Issue
scope relevant to this inventory. Conclusion: no TODO current-state
evidence, canonical replacement, Issue-overlap, or archive/remove
recommendation changes as a result of PR #211/#213 or Issues #210/#212 —
PR #211 was already fully accounted for in the prior pass (it landed before
`4db27ed4`, inside `64a6acc4`). This correction pass instead fixes three
independent defects found in the prior document: a duplicated table row, an
unpaginated/title-only Issue-overlap claim, and two under-verified
dispositions (`sector_rotation_engine_v1.md`, `signal_matrix_dashboard.md`)
— see the updated rows and evidence below.

## 2. Scope and safety

```text
issues_created=0
files_moved=0
files_archived=0
files_removed=0
existing_files_modified=0
runtime_changes=0
database_changes=0
broker_writes=0
order_submissions=0
service_timer_changes=0
```

## 3. Summary counts

```text
total_todo_files=69
already_migrated_issue_sources=7
new_issue_candidates=27
canonical_candidates=7
archive_candidates=20
remove_candidates=5
infrastructure_files=3
architecture_violations=5
uncertain_items=2
```

Reconciliation: `7 + 27 + 7 + 20 + 5 + 3 = 69`. Matches `total_todo_files`.
(Changed from the prior pass: `signal_matrix_dashboard.md` moved
`issue -> archive` after confirming its content is already superseded by two
existing canonical docs; `sector_rotation_engine_v1.md` moved
`remove -> archive` after finding an unresolved functional test dependency;
`martee_oracle_touch_semantics.md` moved `issue -> archive` (confidence
remains `blocked`) — reactivation requires evidence of an active consumer or
implementation lane, none of which was found.
Net effect: `new_issue_candidates` 29→27, `archive_candidates` 17→20,
`remove_candidates` 6→5. `architecture_violations` and `uncertain_items` are
annotations only and do not enter the sum.)

### Exact-once inventory proof

```text
inventory_row_count=69
inventory_unique_file_count=69
duplicate_inventory_paths=0
missing_inventory_paths=0
unexpected_inventory_paths=0
```

Verified by `find docs/todo -maxdepth 1 -type f -printf '%f\n' | sort` (69
paths) diffed against the primary table's file-path column (69 unique paths,
0 duplicates, 0 missing, 0 unexpected). The prior pass's duplicate anchor row
for `manual_execution_ladder_future_readiness_backlog_v1.md` has been removed
from the primary table; the multi-Issue mapping detail it carried lives only
in the prose note beneath the table (unchanged) and in §5/§10, never inside
the one-row-per-file table itself.

## Method note

Full file contents were read for all 69 files (batched across four parallel
research passes, one per ~15 files, each instructed to extract evidence only,
not classify). Every disposition below was then independently checked by the
orchestrating pass against: `docs/todo/README.md` (frozen lane-index
snapshot), `docs/todo/MIGRATION_FREEZE.md`, `docs/development/
github_issues_migration_proposal_v1.md`, `docs/development/
github_issues_first_batch_migration_v1.md`, the live GitHub Issue list
(`gh issue list --state all`), and targeted repository checks (`git log`,
`gh pr view`, `ls`/`find` for cited canonical files, runners, and data
artifacts). Several files' self-reported "active"/"TODO" status was found to
be **stale** — the described work was already implemented and run — and are
reclassified to `archive` below with the verifying evidence cited. This is
exactly the class of correction `MIGRATION_FREEZE.md` permits ("correct
unsafe or materially false information").

---

## 4. Complete inventory table

Confidence: `high` = independently verified (git/gh/ls/grep). `medium` =
strong textual evidence, not independently re-run. `blocked` = conflicting or
insufficient evidence; needs human decision.

| File | Primary disposition | Secondary action | Existing owner | Architecture area | Current-state evidence | Unique permanent content | Canonical replacement | Recommended next action | Confidence |
|---|---|---|---|---|---|---|---|---|---|
| `README.md` | infrastructure | Retire only after every row below has a reviewed disposition; do not resync status/priority | none | board index | Self-declared `MIGRATION_FROZEN`; frozen lane snapshot | Frozen A–E lane snapshot history | `docs/development/github_issues_workflow.md` | Hold as infra; final retirement is Batch 2E | high |
| `MIGRATION_FREEZE.md` | infrastructure | None | none | governance | Defines allowed dispositions | Freeze rule text itself | n/a | Hold until legacy board fully retired | high |
| `workflow_standard.md` | infrastructure | None | none | governance | `SUPERSEDED FOR NEW WORK`; legacy vocabulary glossary | P0–P4 / status-word glossary needed to read frozen files | `docs/development/github_issues_workflow.md` | Hold as reading aid until Batch 2E | high |
| `native_short_multi_asset_rollout_contract_v1.md` | issue | Extract remaining canonical audit sections to `docs/ops/` once ETH/XRP promotion completes | #198, #199, #200 (open) | selection/market-data | Pointer header present (PR #209); SOL promoted, ETH/XRP approved not promoted | 1089-line rollout audit, still partially live | `docs/ops/native_short_{eth,xrp}_bootstrap_promotion_approval_v1.md` (partial) | Keep as issue source; no action needed this batch | high |
| `short_swing_linked_profile_freshness_and_disk_reliability_v1.md` | issue | None | #201 (open, `status:blocked`) | runtime/dashboard | Pointer header present | Odroid freshness/disk hygiene detail | none yet | Keep as issue source | high |
| `manual_execution_ladder_future_readiness_backlog_v1.md` | issue | None | #202, #203, #206 (open) | decision_gate/execution_planner | Pointer header present; P0 items 1-6 reviewed BLOCK/REJECT | Remediation audit detail | `docs/architecture/manual_execution_ladder_future_readiness_audit_v1.md` (partial) | Keep as issue source | high |
| `manual_execution_ladder_profiles_v1.md` | issue | None | #202 (open) | execution_planner | Pointer header present | Ladder profile detail | none yet | Keep as issue source | high |
| `sector_rotation_dashboard_v1.md` | issue | None | #204 (open, `status:needs-design`) | dashboard | Pointer header present; Phase C1 implemented | Dashboard review detail | none yet | Keep as issue source | high |
| `replay_parameter_study_harness_v1.md` | issue | None | #205 (open, `status:ready`) | research/selection | Pointer header present | Replay contract detail | none yet | Keep as issue source | high |
| `credential_scope_and_manual_ladder_execution_boundary_v1.md` | issue | None | #206 (open, `status:needs-design`) | decision_gate/executor | Pointer header present | Credential-binding detail | `docs/architecture/account_credential_binding_contract_v1.md` (partial) | Keep as issue source | high |
| `2026-05-19_product_cockpit_strategy_bundle.md` | issue | split_required=yes — separate Issues for dashboard-label semantics, entry-candidate view, strategy-bucket config, multi-user cockpit, website auth fix, systemd/HTTPS ops | none | dashboard + decision_gate + execution_planner (mixed) | No completion markers; 9+ distinct initiatives bundled; cites `src/web/website_registration_v1.py::verify_email_token` | Product-cockpit direction; multi-user data model | none | Split into ≥5 bounded Issues before filing (see §9) | medium |
| `account_provisioning.md` | issue | Batches 1-3 + Hotfix A/B are closed; only Batch 4 (Bitvavo private-read validation) is open | none | broker credential (read-only) | Batches 1-3 marked `✅ DONE` with named commits; Batch 4 unchecked | Batch-by-batch closure record | `docs/ops/account_provisioning_v1.md` | File one Issue for Batch 4 only; archive rest inline as closure record | high |
| `adaptive_fib_execution_offset_v1.md` | issue | None required now | none | selection/decision_gate/execution_planner (V1 scoped to research-only) | `Status: TODO`; no completion evidence; 5-step follow-up sequence defined | Execution-offset policy taxonomy (EXACT_LEVEL, STATIC_BUFFER, etc.) | none yet | File Issue scoped to V1 offline research/proposal layer only | medium |
| `aplus_harmonic_breathline_claim_audit_v1.md` | canonical | Move to `docs/research/`; no Issue unless a new validation lane is separately prioritized | none | research | `Status: research-only`, dated 2026-06-09; explicit market-only safety markers | Claim-correction audit (Prime-17, 21-day Breathline harmonic integration) | proposed: `docs/research/aplus_harmonic_breathline_claim_audit_v1.md` | Canonicalize; do not treat as open task | medium |
| `astro_policy_confluence_research_todo_bundle_v1.md` | canonical | File one bounded Issue for the "research-skeleton build" (Codex prompt section) after the design doc is canonicalized — do not carry the full 679-line bundle into an Issue body | none | research | `Status: TODO / research-only`; file itself proposes its own canonical destination | Full H1-H6 hypothesis/statistical design | proposed: `docs/research/astro_policy_confluence_v1.md` (self-named target) | Split canonicalization from build-task Issue | medium |
| `backtest_capability_contract_v1.md` | issue | Promote finished capability schema to `docs/architecture/` after acceptance | none | research/backtest infra | `future design`, `priority: P2`; ordered P1/P2 task list | `replay_support`/`data_scope`/`asof_policy` enum contract | none yet | File one Issue (P1 inventory + contract) | high |
| `breath_curve.md` | archive | Fold any renewed interest into one consolidated Breathline research Issue rather than reopening this file | none | research | `Status: Parked / open research continuation`; vague "continue where useful" | Pointer to 5 dated findings docs | `docs/research/breath_curve_template_partial_v1.md` (existing) + 4 findings docs (existing) | Archive; do not treat as standalone open item | medium |
| `breathline_backtest_campaign_and_coin_calibration_v1.md` | issue | None | none | research | `Todo / research campaign specification`; named existing runners | Per-coin campaign artifact spec | none | File one bounded Issue | high |
| `breathline_ui_phase_path_history_v1.md` | issue | None | none | dashboard-reporting | `Todo / UI specification`; detailed read-model field contract | Breathline card field contract | none yet | File one bounded Issue (reporting layer only) | high |
| `bullrun_start_dashboard_cockpit_refresh_v1.md` | issue | split_required=yes — Scope A (new dashboard module) and Scope B (cockpit/wallet UI cleanup) are separable | none | dashboard-reporting | Explicit `PLAN / INSPECT MODE only` gate; two distinct scopes bundled | Indicator/state taxonomy (FLUSH/BOTTOM_CLOSE/BTC_RECLAIM) | none | Split into 2 Issues | medium |
| `card_actionability_map_completed_navigation_v1.md` | archive | None | none | dashboard-reporting | **Verified implemented**: PR #10 (`feature/profit-plan-card-actionability-map-completed-navigation-v1`, commits `035e173b`, `9c664225`); gating PR #5 merged 2026-06-13 | Historical gating-note record only | n/a | Archive as closed; correct file's own live-looking framing | high |
| `claude_bundle_1_pipeline_contracts_v1.md` | archive | None | none | market_context/architecture | **Verified implemented**: `docs/architecture/pipeline_contracts.md` and `tests/test_pipeline_contract_boundaries_v1.py` both exist in repo | Architecture-primer content, now superseded by the actual doc | `docs/architecture/pipeline_contracts.md` (exists) | Archive as closed | high |
| `claude_bundle_2_elliott_wave_daily_context_lane_v1.md` | issue | Canonicalize labeler/validation design to `docs/research/` once Issue is scoped | none | research | File explicitly self-instructs: "file a GitHub Issue... legacy TODO board is frozen: do not add a new TODO entry" | Labeler spec, 3-phase validation protocol, promotion criteria | none yet | File one Issue exactly as the file requests; also flags a small layering-hygiene bug (`native_short_fib_context_v1.py` importing from `src.research`) worth a linked small Issue | medium |
| `cross_asset_metals_miners_food_rotation_v1.md` | remove | Update incoming references in `docs/todo/README.md` and `docs/todo/market_intelligence/README.md` before deletion | none | research (superseded pointer) | Self-declared: "remains only to preserve historical context... status owned by the canonical split TODOs" | none — pure redirect | **Verified exists**: `docs/todo/external_research/cross_asset_public_data_and_instrument_registry_v1.md`, `docs/todo/market_intelligence/cross_asset_rotation_research_v1.md` | Remove after reference update (Batch 2D) | high |
| `decision_gate_account_protections_v1.md` | issue | None | none | decision_gate | `future design`, `priority: P2`; ordered P1/P2 task list; cross-refs `backtest_capability_contract_v1.md` | Protection-contract schema (MAX_ACCOUNT_DRAWDOWN_BLOCK etc.) | `docs/core/decision_gate_v1.md` (partial, exists) | File one Issue (P1 design) | high |
| `deploy_runtime.md` | issue | split_required=yes — candle-ingestion cutover as one Issue; fold webview items into `ui_webview.md`'s Issue instead of duplicating; archive already-`done`/committed subsections inline | none | market_data/ETL + dashboard-reporting (bundled) | Mixed done/open markers; incident-driven correction dated 2026-07-18/19 overriding an earlier section; concrete bounded cutover sequence given | Ownership-contract and runner-deployment plan detail | `docs/ops/synth_runtime_runners_v1.md` (exists) | Split into ≤3 Issues (candle cutover; timer-restart gate shared with `short_swing_...`; P3 ops-standard doc) | medium |
| `dev_ops_hygiene.md` | archive | Small optional Issue only if the DB backup procedure is still undecided | none | dev/ops (no trading layer) | `Mostly done / parked`; 3 of 4 sections `Status: done` | Known-good MariaDB verification command | none needed | Archive; spin a 1-line Issue only if backup procedure genuinely still missing | medium |
| `external_forecast_event_registry.md` | canonical | No Issue unless implementation is explicitly prioritized | none | research | `Status: TODO / research-only`; no implementation exists | Full forecast-event schema/enum design | proposed: `docs/research/external_forecast_event_registry_v1.md` | Canonicalize as a design doc, not an open task | medium |
| `external_research_ingestion.md` | canonical | split_required=yes — schema/strategy sections to `docs/research/`; dated raw research notes (Martee 2026-05-25, VET/KITE/PLUME/Terafab/NEAR) are stale capture and should go to `docs/archive/`, not forward | none | research | `Status: TODO / research-only` (two separate status blocks in one file); contains a raw dated research diary mixed into a schema spec | Extraction-schema + Elliott Wave validation sub-lane design | proposed: `docs/research/external_research_ingestion_v1.md` + `docs/research/external_elliott_wave_claim_validation_v1.md` (self-proposed) | Split diary from spec before any move | medium |
| `ffg_curated_rotation_radar_v1.md` | remove | Update `docs/todo/README.md` reference before deletion | none | research (superseded pointer) | Self-declared: "no longer owns active work... board is frozen" | none — pure redirect | **Verified exists**: `docs/todo/external_research/ffg_universe_metadata_v1.md`, `docs/todo/market_intelligence/ffg_rotation_classification_v1.md`, `docs/todo/reporting/ffg_rotation_radar_presentation_v1.md` | Remove after reference update (Batch 2D) | high |
| `fib_navigation_map_rebuild_v1.md` | archive | None | none | market-only fib navigation | **Verified**: `Status: IMPLEMENTED`, branch `feature/fib-navigation-map-rebuild-v1` = PR #1 = commit `d7c57af4` (confirmed via `git log`) | Required-states/rebuild-trigger enum not fully duplicated elsewhere | none | Archive as closed implementation record | high |
| `fibo_zones.md` | issue | split_required=yes — (a) production cutover for `canonical_fib_zone_map` publication, (b) P2 native-map calibration investigation (dated trigger 2026-07-13); move correct-path diagrams/exit-profile taxonomy to `docs/research/` or `docs/architecture/` | none | research + zone/execution boundary discussion | `Active P0 repository-ready / activation pending`; several sub-lanes each independently `open`/`parked`/`backlog` | Exit-profile bucket taxonomy; correct-path diagrams | `docs/research/fib_exit_ladder_v1_findings.md` (partial, exists) | Split into ≥2 Issues; canonicalize diagrams separately | medium |
| `golden_coin_cases_backtest_bundle_v1.md` | issue | Golden fixture cases themselves become canonical test reference under `tests/` or `docs/research/` once implemented | none | research/market-only | Mixed: SXT sub-item done (PR #1 / `d7c57af`), BreathlineState/ImpulseHealthState/TimingState explicitly still open; numbered priority order given | 7-coin golden regression fixture set | none yet | File one Issue for the priority-ordered remaining items | high |
| `historical_breath_regime_context_backlog.md` | archive | Correct the file's `Status: active` marker — materially stale | none | research | `Status: active`, `decision: PARTIAL_CONTEXT_EXISTS` — but **verified**: `src/research/run_historical_breath_regime_context_builder_v1.py` already exists and has been run (`data/research/historical_breath_regime_context_builder_v1/` output present) | P0 field-contract detail, now historical | `docs/research/historical_breath_regime_context_backbone_v1.md` (exists) | Archive; the described P0 task is already done | high |
| `historical_market_breath_source_enrichment_backlog.md` | archive | Correct the file's `Status: active` marker — materially stale | none | research | `Status: active` — but **verified**: `src/research/run_historical_market_breath_source_enrichment_v1.py` exists (commit `1310c7f3`) and produced output rows | P0 task detail, now historical | `docs/research/historical_market_breath_source_enrichment_v1.md` (self-proposed) | Archive; superseded by `..._recompute_backlog.md`'s own evidence that this ran | high |
| `historical_market_breath_source_recompute_backlog.md` | archive | Correct the file's `Status: active` marker — materially stale | none | research | `Status: active`, cites unchanged-coverage numbers as trigger — but **verified**: `src/research/run_historical_market_breath_source_recompute_v1.py` and its test exist (commit `cbbc8f20`), plus `Use enriched market breath source in context builder` (commit `97b1a02c`) shows the wiring already happened | Coverage-metric trigger evidence, now historical | none | Archive; the full enrich→recompute→wire chain is already implemented and run | high |
| `idiosyncratic_catalyst_override.md` | canonical | No Issue unless someone commits to implementing `idiosyncratic_catalyst_override_v1` | none | research | `Status: Research/TODO lane`; concept/taxonomy only, no runner/path named | "Dirty squeeze" catalyst-override model | proposed: `docs/research/idiosyncratic_catalyst_override_v1.md` | Canonicalize as concept note | medium |
| `invalidation_confirmation_backtest_v1.md` | issue | status_recommendation=blocked | none | research | `Status: Queued research task. Do not implement yet` — explicitly self-gated | Invalidation-state enum (VALID/HARD_INVALIDATED/etc.) | none | File as a blocked/low-priority Issue | medium |
| `live_like_vertical_slice.md` | issue | Check overlap with `deploy_runtime.md`'s "first paper strategy lane" before filing, to avoid a duplicate | none | selection_engine + decision_gate + execution_planner (bridge by design, shadow-mode only) | `phase 1 contracts/docs defined`; 4 ordered immediate next steps | Expansion-path (NEAR→HYPE→RENDER via config) guidance | none | Resolve overlap with `deploy_runtime.md` first, then file one Issue | medium |
| `manual_ladder_dashboard.md` | archive | None | none | dashboard-reporting | README's own frozen disposition: `historical source / superseded — active ladder work is tracked only in profit_plan_live_ladder.md` | Neutral label taxonomy, two worked examples | superseded by `profit_plan_live_ladder.md` | Archive per README's own authoritative note (overrides the file's internal "Active" framing) | high |
| `market_breath.md` | canonical | Archive the TODO shell after confirming the summary doc is complete; P1 cockpit idea becomes an Issue only if reopened | none | research | `Characterized / parked until downstream use-case` | Phase-classification taxonomy (COLLAPSE_RESET, EXHALE_EXPANSION, etc.) | `docs/research/market_breath_v1_sensor_classification_summary.md` (exists) | Canonicalize/confirm, then archive shell | medium |
| `martee_oracle_touch_semantics.md` | archive | Reactivation requires evidence of an active consumer or implementation lane (e.g. a runner, test, or canonical doc that depends on Martee Oracle touch semantics) before this is ever filed as an Issue — no date, no evidence, generic `Status: TODO` | none | research | `Status: TODO`, no date, no completion evidence | Touch-semantics field model | none | Archive; do not file as an Issue absent new evidence of active use | blocked |
| `momentum_flow_scanner_matrix_v1.md` | remove | Update the stale cross-reference in `profit_plan_dashboard_action_truth_and_breathline_demote_v1.md` and `docs/todo/README.md` before deletion | none | research (superseded pointer) | Self-declared: "former umbrella TODO no longer owns active work" | none — pure redirect | **Verified exists**: `docs/todo/market_intelligence/momentum_flow_scanner_research_v1.md`, `docs/todo/reporting/profit_plan_opportunity_presentation_v1.md` | Remove after reference update (Batch 2D) | high |
| `multi_account_asset_foundation_backlog.md` | issue | split_required=yes — one Issue per phase (DB migration/backfill; asset-table column migration; selection_engine venue param; dashboard account filter; Hugo account onboarding); FK policy sentence → `docs/architecture/` | none | DB/ETL + selection_engine + dashboard + account-onboarding (bundled across 5 phases) | Unchecked checkbox task list; no completion markers | Canonical FK policy statement (`trading_account` is canonical FK) | `docs/research/multi_account_asset_foundation_v1.md` (exists) | Split into ≥3 Issues | medium |
| `multi_horizon_aplus_breathline_strategy_integration_v1.md` | issue | Architecture-rules subsection → `docs/architecture/` once drafted | none | selection_engine + decision_gate + execution_planner (boundary-contract doc, not implementation) | `Local backlog / next architecture lane`; first deliverable named | Layer-boundary doctrine for Breathline/Fibo/Strategy-State/Decision-Gate | none yet | File one Issue: "create multi-horizon architecture contract" | medium |
| `multi_horizon_fib_dashboard_backlog.md` | issue | status_recommendation=blocked | none | dashboard-reporting | `Parked behind research foundation maturity` | none new | none | File as blocked-on-dependency Issue | medium |
| `native_short_invalidation_confirmation_backtest_v1.md` | issue | None | none | research | `Status: Open research / calibration lane`; 6-policy replay design with defined criteria | none yet (states unapproved until replay evidence exists) | none | File one Issue | high |
| `native_short_map_level_status_v1.md` | archive | None | none | research/market-data | **Verified closed**: PRs #68/#71/#76/#77/#79/#81/#87; `done / parked` with two dated correction addenda | none new beyond closure record | `docs/architecture/native_short_map_level_status_contract_v1.md` (exists) | Archive | high |
| `native_short_runtime_owner_and_scope_status_v1.md` | issue | split_required=yes — archive the historical implementation section; keep/open an Issue only for the still-open production-ownership-assignment gap (`UNASSIGNED`) and the P3 deferred hardening item | none | ops/runtime/DB-binding | Implementation `done/accepted (historical)`; production owner explicitly `UNASSIGNED`, activation `NOT_AUTHORIZED` | Ownership-registry pointer, safety-marker template | `deploy/ownership/writer_capability_ownership_v1.json` (exists) | Split: archive historical half, Issue for the open ownership gap | medium |
| `news_catalyst_monitor.md` | issue | None | none | research/ETL/DB | `Status: Research / read-only ingestion lane`; explicit P0 design task with deliverables list | none yet | none | File one Issue (P0 schema/dry-runner design) | high |
| `paper_candidate_contract.md` | archive | No Issue until the P3 adapter-design item is actually prioritized | none | research→decision_gate boundary | `Status: Future adapter design allowed. No execution wiring`; content duplicates AGENTS.md boundary rules | none — boundary restatement only | `docs/research/paper_candidate_contract_v1.md` (exists) | Archive; canonical content already lives elsewhere | medium |
| `parked_backlog.md` | archive | None | none | research/DB archive | 4 sub-lanes, all `Status: parked`/`backlog`/`done / parked`; A+ archive sub-section has migration+loader evidence | none new; restates AGENTS.md boundary rules | none | Archive whole file | high |
| `position_rotation_preview.md` | issue | Archive the MVP-implemented sections inline; consider moving the output-label contract (HOLD/REDUCE_CANDIDATE/etc.) to `docs/architecture/` or `docs/status/` | none | dashboard-reporting (account-aware, read-only) | `Status: MVP implemented / parked follow-up lane`; "Next Strategy Work" section lists concrete unstarted follow-ups | Implemented output-label schema | `docs/research/current_strategy_audit_v1.md` (partial, exists) | File one Issue for "Next Strategy Work" only | medium |
| `profit_plan_card_evidence_delta_visibility_v1.md` | archive | None | none | dashboard-reporting | `Status: done / parked`; "No active P0-C implementation tasks remain" | none new | `docs/research/profit_plan_card_forensic_replay_contract_v1.md` (exists) | Archive | high |
| `profit_plan_dashboard_action_truth_and_breathline_demote_v1.md` | archive | Confirm the Breathline demotion contract (`RESEARCH_ONLY_DISABLED`, weights=0) is captured in `docs/architecture/` before archiving — **checked: not currently found there**, so this is unique content worth preserving in the archived copy | none | dashboard-reporting | `Status: done / parked`; PRs #78, #82, #75, #84, #85, #86 | Breathline demotion governance fact | none currently — recommend adding to `docs/architecture/` on canonicalization | high |
| `profit_plan_live_ladder.md` | issue | split_required=yes — P0.0-P0.8 mutation-safety phases should become sub-issues, each gated on the previous | none | selection_engine (unchanged) + reporting + decision_gate + execution_planner + executor (full gated chain in one file) | `active P1 / Synth v2.23`; concrete unimplemented next slice named | Full P0.0-P0.8 mutation-safety procedure | `docs/ops/manual_short_trader_profit_plan_v1.md` (partial, exists) | Split into phase-gated sub-issues | medium |
| `profit_plan_target_lifecycle_history_truth_v1.md` | archive | None | none | market-data history / reporting (read-only) | `CONTAINED / COMPLETED` by PR #105; addendum work already implemented; future hardening explicitly evidence-gated with no current trigger | Root-cause/forensic-audit record | `docs/architecture/native_short_map_level_status_contract_v1.md` (exists) | Archive | high |
| `regime_research.md` | issue | None | none | research | `Active next research lane`; multi-stage sequenced backlog (P1/P2/P3) | none new beyond sequencing | `docs/research/rotation_destination_historical_replay_audit_v2.md` (partial, exists) | File one Issue (or split by phase) | high |
| `sector_rotation_engine_v1.md` | archive | **Downgraded from `remove`**: `tests/test_sector_taxonomy_import_v1.py::test_sector_rotation_public_contract_uses_participation_terms` reads and asserts on this exact file's content (`positive_participation_pct`, `participation_ratio`, `INSUFFICIENT_PARTICIPATION` must be present, "breadth" must be absent) — a genuine functional dependency, not textual. The test is **already failing on current `main`** (verified: `pytest -k participation_terms` fails because the root file is now only a 9-line redirect and no longer contains those terms) — pre-existing breakage, not caused by this proposal. Deletion is unsafe until the test is repointed at `docs/todo/market_intelligence/sector_rotation_engine_v1.md` | none | research (superseded pointer; but load-bearing for one test) | Pure redirect, no own status; test dependency confirmed broken independent of this proposal | none — pure redirect | **Verified exists**: `docs/todo/market_intelligence/sector_rotation_engine_v1.md` (this is almost certainly the intended test target) | Archive only after `tests/test_sector_taxonomy_import_v1.py` is repointed to the canonical path — file a separate small test-fix Issue first; do not remove until then | blocked |
| `sector_rotation_master_plan_v1.md` | remove | Update `docs/todo/README.md` reference before deletion | none | research (superseded pointer) | Pure redirect, no own status | none — pure redirect | **Verified exists**: `docs/todo/market_intelligence/sector_rotation_master_plan_v1.md` | Remove after reference update (Batch 2D) | high |
| `sector_taxonomy_database_seed_v1.md` | remove | Update `docs/todo/README.md` reference before deletion | none | research (superseded pointer) | Explicitly: "This completed lane moved to: `docs/todo/completed/sector_taxonomy_database_seed_v1.md`" | none — pure redirect | **Verified exists**: `docs/todo/completed/sector_taxonomy_database_seed_v1.md`, `docs/research/sector_taxonomy_database_seed_v1.md` | Remove after reference update (Batch 2D) | high |
| `signal_matrix_dashboard.md` | archive | **Resolved (was `blocked`)**: `git log` shows `docs/research/signal_matrix_static_dashboard_v1.md` (577 lines) and `docs/research/signal_matrix_single_asset_replay_v1.md` (477 lines) were both committed within 7 minutes of this TODO file, same day (2026-05-30), and both are **verified to exist now**; the replay design's runner `src/research/run_signal_matrix_single_asset_replay_v1.py` also exists (implemented). The dashboard runner itself (`src/reporting/run_signal_matrix_static_dashboard_v1.py`) does not yet exist. If the dashboard build is still wanted, a fresh Issue should cite the two existing canonical docs directly rather than this stale TODO stub | none | dashboard-reporting | `Active next dashboard lane for Synth v2.14` — version tag stale; content superseded by same-day canonical docs | none new — superseded | **Verified exists**: `docs/research/signal_matrix_static_dashboard_v1.md`, `docs/research/signal_matrix_single_asset_replay_v1.md` | Archive; if the dashboard build is reprioritized, file a fresh Issue against the two existing canonical docs, not this file | medium |
| `stale_1h_advice_freshness_truth_v1.md` | issue | None | none | selection_engine (market-only) | Dated defect observation (2026-08-05) with 11 named example assets | none | none | File one Issue despite the file's own "not an execution queue item" framing — it is concrete and reproducible | high |
| `strategy_candidates.md` | issue | split_required=yes — one Issue per P1/P2/P3 section (audit follow-up; regime; macro-dip; swing-pullback; legacy priors); "asset != strategy" rule and MACRO_DIP_BUDGET_MODE_V1 design → `docs/research/` or `docs/strategy/` | none | selection_engine + decision_gate + execution_planner (discussed per-section, not implemented together) | `Open design questions. No implementation yet`; explicit cross-reference to `regime_research.md` | Candidate-unit rule, MACRO_DIP_BUDGET_MODE_V1 design | `docs/research/current_strategy_audit_v1.md` (partial, exists) | Split into ≥3 Issues | medium |
| `synth_v214_signal_dashboard_strategy_bridge_backlog.md` | canonical | File one bounded Issue only for the un-started "Deferred Implementation Order" steps 1-3, after canonicalization. `signal_matrix_dashboard.md`'s own overlap is now resolved separately (see that row — archived, superseded by `docs/research/signal_matrix_static_dashboard_v1.md`); check that doc before scoping this Issue so the two are not duplicated | none | dashboard + decision_gate + execution_planner + executor (explicitly self-described as "cross-cutting design backlog") | No explicit status marker; version-tagged v2.14 (stale); self-declares overlap with `signal_matrix_dashboard.md` | Strategy-proposal contract (`{ACTION}_{HORIZON}_{SETUP}`), bucket allocation model, anti-patterns list | proposed: `docs/architecture/strategy_proposal_contract_v1.md` | Canonicalize contract; one small Issue for remaining build steps, scoped against `docs/research/signal_matrix_static_dashboard_v1.md` too | medium |
| `synth_v2_development_roadmap_v1.md` | archive | None | none | full pipeline (7-bundle roadmap, historical) | Pinned to commit `d7c57af`; "Completed" section superseded by later native-SHORT/map-level-status/profit-plan-live-ladder work seen elsewhere in this inventory | Historical roadmap record only | AGENTS.md (architecture rules already duplicated there) | Archive as superseded roadmap snapshot | high |
| `todo_information_architecture_v1.md` | archive | None | none | board-maintenance meta | Self-declared: `SUPERSEDED — no remaining authority... pending an archive disposition under MIGRATION_FREEZE.md` | Original subfolder-plan record | `docs/todo/MIGRATION_FREEZE.md` | Archive exactly as the file itself requests | high |
| `ui_webview.md` | issue | split_required=yes — archive completed sections inline; one narrow Issue only for the accepted-but-unbuilt "Cockpit usability / coin-card scanability" work | none | dashboard-reporting | Mixed `done`/`implemented` sections plus one `open / active design follow-up` section with concrete accepted-but-unbuilt items | Timezone/display-boundary rules (largely duplicate AGENTS.md dashboard rules) | `docs/architecture/ui_chart_framework_v1.md` (exists) | File one narrow Issue | medium |
| `watchlist_candidates.md` | issue | None | none | research/market-data ingestion | `Open watchlist / research intake lane`; most itemized KITE tasks marked "Done" inline; one remaining check plus open research questions | none new — restates AGENTS.md candidate-validation rules | `docs/research/watchlist_feature_signal_status_v1.md` (exists) | File one small Issue for the remaining liquidity/spread/min-order check | high |

Note: `manual_execution_ladder_future_readiness_backlog_v1.md` appears exactly
once in the table above (in the already-migrated group, mapped to Issues
#202, #203, and #206). Its multi-Issue mapping is carried entirely in that
one row's "Existing owner" cell and in §10's batch notes — no second table
row is used to hold that detail.

---

## 5. New Issue candidates

```text
candidate_id=NEW-01
source_files=docs/todo/2026-05-19_product_cockpit_strategy_bundle.md
proposed_title=Split cockpit strategy bundle into bounded dashboard/product Issues
type=cleanup
areas=area:dashboard
priority_recommendation=normal
status_recommendation=needs-design
problem=Nine-plus distinct product/dashboard initiatives are bundled in one 462-line file with no single closable outcome.
bounded_scope=Produce a short scoping note that assigns each initiative (dashboard labels, entry-candidate view, strategy-bucket config, multi-user cockpit, website auth fix, systemd/HTTPS ops) to its own future Issue.
out_of_scope=Implementing any of the initiatives in this Issue.
dependencies=none
acceptance_criteria=A written 1-Issue-per-initiative split proposal is reviewed and accepted; no code changes.
architecture_owner=dashboard-reporting (mixed; split removes the mixing)
split_required=yes

candidate_id=NEW-02
source_files=docs/todo/account_provisioning.md
proposed_title=Complete Batch 4 real Bitvavo private-read validation
type=feature
areas=area:data
priority_recommendation=normal
status_recommendation=ready
problem=Batches 1-3 and both hotfixes are closed; Batch 4 (real private-read validation against live Bitvavo) remains unchecked.
bounded_scope=Execute the 4 unchecked Batch-4 validation items against `docs/ops/account_provisioning_v1.md`.
out_of_scope=Any broker write/order permission.
dependencies=Batch 2 + broker read-permission design review (already referenced as prerequisite)
acceptance_criteria=All 4 Batch-4 checklist items pass with evidence; broker_writes=0, order_submission=0.
architecture_owner=broker-read (credential layer, no trading layer)
split_required=no

candidate_id=NEW-03
source_files=docs/todo/adaptive_fib_execution_offset_v1.md
proposed_title=Build offline execution-offset near-miss/fill replay dataset (V1 research layer)
type=research
areas=area:research
priority_recommendation=low
status_recommendation=ready
problem=No offline dataset exists yet to evaluate candidate execution-offset policies (EXACT_LEVEL, STATIC_BUFFER, etc.).
bounded_scope=Steps 1-2 of the file's follow-up sequence only: build the replay dataset and define the versioned policy contract.
out_of_scope=Any live/paper execution wiring, decision_gate consumption.
dependencies=none
acceptance_criteria=Dataset + policy contract exist and are reviewed; no runtime path touched.
architecture_owner=research (offline only)
split_required=no

candidate_id=NEW-04
source_files=docs/todo/backtest_capability_contract_v1.md
proposed_title=Inventory and define backtest capability contract schema
type=research
areas=area:research
priority_recommendation=normal
status_recommendation=ready
problem=No machine-readable contract yet describes replay support, data scope, as-of policy for backtestable components.
bounded_scope=P1 inventory + P1 composition-preflight design only, per the file's own ordering.
out_of_scope=P2 implementation (separate future Issue).
dependencies=none
acceptance_criteria=Contract schema documented and reviewed; no component behavior changed.
architecture_owner=research/backtest infra
split_required=no

candidate_id=NEW-05
source_files=docs/todo/breathline_backtest_campaign_and_coin_calibration_v1.md
proposed_title=Run per-coin Breathline backtest campaign against canonical A+ baseline
type=research
areas=area:research
priority_recommendation=low
status_recommendation=ready
problem=Existing runners (`backtest_breath_curve_partial_to_full_v1.py`, `run_breath_curve_phase_calibration_v2.py`) have not been run per-coin against the canonical baseline.
bounded_scope=Execute the named runner chain and produce the specified artifact set.
out_of_scope=Any change to A+ baseline, selection_engine, decision_gate, execution_planner, executors, UI, DB, or broker behavior.
dependencies=none
acceptance_criteria=Artifact set produced and reviewed.
architecture_owner=research
split_required=no

candidate_id=NEW-06
source_files=docs/todo/breathline_ui_phase_path_history_v1.md
proposed_title=Add Breathline phase/path-history card to Profit Plan coin detail
type=feature
areas=area:dashboard
priority_recommendation=low
status_recommendation=ready
problem=No card currently surfaces Breathline phase/path/duration/history on the coin detail view.
bounded_scope=Presentation and read-model only, per the file's field contract.
out_of_scope=Any change to Breathline calculation, selection_engine, decision_gate, execution_planner, executor.
dependencies=none
acceptance_criteria=Card renders with the specified field contract; acceptance criteria in the source file pass.
architecture_owner=dashboard-reporting
split_required=no

candidate_id=NEW-07
source_files=docs/todo/bullrun_start_dashboard_cockpit_refresh_v1.md
proposed_title=Bullrun-start dashboard module (Scope A)
type=feature
areas=area:dashboard
priority_recommendation=low
status_recommendation=needs-design
problem=No dashboard currently surfaces FLUSH/BOTTOM_CLOSE/BTC_RECLAIM-style bullrun-start indicators.
bounded_scope=New `src/reporting/run_bullrun_start_dashboard_v1.py` module only (Scope A of the source file).
out_of_scope=Cockpit/wallet UI cleanup (see NEW-08); any broker/account/decision/execution change.
dependencies=none
acceptance_criteria=Inspect-only report delivered first per the file's own "Required first response" gate, then implementation on approval.
architecture_owner=dashboard-reporting
split_required=yes (Scope A of 2)

candidate_id=NEW-08
source_files=docs/todo/bullrun_start_dashboard_cockpit_refresh_v1.md
proposed_title=Cockpit/wallet UI cleanup (Scope B)
type=cleanup
areas=area:dashboard
priority_recommendation=low
status_recommendation=needs-design
problem=Cockpit/wallet UI cleanup items are bundled with the unrelated bullrun-start dashboard build.
bounded_scope=Scope B only, as defined in the source file.
out_of_scope=Scope A (see NEW-07).
dependencies=none
acceptance_criteria=Per source file's Scope B acceptance list.
architecture_owner=dashboard-reporting
split_required=yes (Scope B of 2)

candidate_id=NEW-09
source_files=docs/todo/claude_bundle_2_elliott_wave_daily_context_lane_v1.md
proposed_title=Elliott Wave daily-context labeler Phase 1 (BTC-EUR, market-only)
type=research
areas=area:research
priority_recommendation=normal
status_recommendation=ready
problem=No labeler/ledger exists yet for daily Elliott Wave context; file explicitly requests this become an Issue rather than stay in docs/todo.
bounded_scope=Phase 1 only: labeler + ledger + 2 metrics on BTC-EUR, per the file's own Section 7.
out_of_scope=Multi-symbol rollout (top-N) until Phase 1 promotion criteria are met; any selection/decision/execution change.
dependencies=fix layering violation: `src/market_data/native_short_fib_context_v1.py` should not import from `src.research`
acceptance_criteria=Labeler + ledger implemented; pre-registered promotion criteria evaluated.
architecture_owner=research (market-only)
split_required=no (linked small hygiene fix, see NEW-09b)

candidate_id=NEW-09b
source_files=docs/todo/claude_bundle_2_elliott_wave_daily_context_lane_v1.md
proposed_title=Remove src.research import from native_short_fib_context_v1.py
type=cleanup
areas=area:selection
priority_recommendation=normal
status_recommendation=ready
problem=`src/market_data/native_short_fib_context_v1.py` importing from `src.research` is a layering violation (market_data must not depend on research).
bounded_scope=Remove the import / relocate shared logic.
out_of_scope=Any behavior change.
dependencies=none
acceptance_criteria=Import removed; existing tests still pass.
architecture_owner=market_data
split_required=no

candidate_id=NEW-10
source_files=docs/todo/decision_gate_account_protections_v1.md
proposed_title=Design account-aware drawdown/loss/cooldown protection contract
type=feature
areas=area:decision-gate
priority_recommendation=normal
status_recommendation=ready
problem=No typed protection contract yet exists for MAX_ACCOUNT_DRAWDOWN_BLOCK, DAILY_REALIZED_LOSS_BLOCK, etc.
bounded_scope=P1 research/contract design only, per the file's ordering.
out_of_scope=P2 implementation (separate future Issue); any selection_engine/execution_planner/executor change.
dependencies=none
acceptance_criteria=Contract schema documented; acceptance criteria in source file satisfied.
architecture_owner=decision_gate
split_required=no

candidate_id=NEW-11
source_files=docs/todo/deploy_runtime.md
proposed_title=Complete candle-ingestion authorization cutover and timer activation
type=feature
areas=area:infra
priority_recommendation=high
status_recommendation=ready
problem=A reviewed authorization change is merged but not yet deployed/activated on the production candle-ingestion host.
bounded_scope=Merge authorization change; deploy exact commit to gurkDB; run one service cycle; verify freshness/coverage/lock/duplicate-writer state; enable timer.
out_of_scope=Any unrelated deploy_runtime.md subsection (webview items belong with `ui_webview.md`'s Issue; P3 ops-standard doc is separate).
dependencies=`docs/todo/short_swing_linked_profile_freshness_and_disk_reliability_v1.md` (#201) timer-restart gate
acceptance_criteria=Timer active; freshness verified; zero duplicate writers.
architecture_owner=market_data/ETL
split_required=yes (deploy_runtime.md bundles ≥3 lanes; only this one is filed now)

candidate_id=NEW-12
source_files=docs/todo/fibo_zones.md
proposed_title=Complete canonical_fib_zone_map production cutover
type=feature
areas=area:infra
priority_recommendation=high
status_recommendation=ready
problem=Repository-ready publication change is merge/deploy/activation-pending.
bounded_scope=Merge, DB migration/grant application, exact-commit deployment, controlled publication/render, timer observation.
out_of_scope=P2/P3 sub-lanes in the same file (see NEW-13).
dependencies=none
acceptance_criteria=Timer observed active with correct publication; no selection/decision/execution change.
architecture_owner=market_data
split_required=yes (1 of 2)

candidate_id=NEW-13
source_files=docs/todo/fibo_zones.md
proposed_title=Investigate native map-level calibration bias (2026-07-13 RED-EUR observation)
type=research
areas=area:research
priority_recommendation=normal
status_recommendation=needs-design
problem=A dated observed calibration discrepancy has not been replayed/quantified.
bounded_scope=Replay published levels vs. realized price, compute signed error, stratify by regime/volatility/setup.
out_of_scope=Any runtime map-generation change until findings are reviewed.
dependencies=none
acceptance_criteria=Findings doc produced with stratified error analysis.
architecture_owner=research
split_required=yes (2 of 2)

candidate_id=NEW-14
source_files=docs/todo/golden_coin_cases_backtest_bundle_v1.md
proposed_title=Implement MarketNavigationState / BreathlineState / ImpulseHealthState / TimingState and golden regression fixtures
type=feature
areas=area:research
priority_recommendation=normal
status_recommendation=ready
problem=Only the SXT emergency-rebuild sub-item (PR #1) is implemented; four state classes and the regression fixture set remain open.
bounded_scope=Priority-ordered items 1-5 from the source file (states through regression fixtures); ladder preview dry-run and manual-submit safety are later phases.
out_of_scope=Any executor/broker/order change.
dependencies=none
acceptance_criteria=Named golden test IDs pass for all 7 coin cases.
architecture_owner=research/market-only
split_required=no (internally already priority-ordered)

candidate_id=NEW-15
source_files=docs/todo/live_like_vertical_slice.md
proposed_title=Add market-only candidate emitter and shadow decision/execution preview for INTRADAY_RETEST_RECLAIM_V1
type=feature
areas=area:selection, area:decision-gate, area:execution-planning
priority_recommendation=normal
status_recommendation=needs-design
problem=Phase-1 contracts are defined but the emitter, decision preview, execution-plan preview, and shadow log/report are not built.
bounded_scope=The 4 ordered immediate-next-steps from the source file, shadow mode only (no broker writes).
out_of_scope=Live/paper order submission; NEAR/HYPE/RENDER expansion (config-only, later).
dependencies=Resolve scope overlap with `deploy_runtime.md`'s "first paper strategy lane" first — likely the same lane described twice.
acceptance_criteria=Shadow event log + report produced; broker_writes=0, order_submission=0.
architecture_owner=selection_engine + decision_gate + execution_planner (explicitly a narrow read-only bridge)
split_required=no (already the narrowest bounded slice), but verify no duplicate Issue exists first

candidate_id=NEW-16
source_files=docs/todo/multi_account_asset_foundation_backlog.md
proposed_title=Multi-account asset foundation — DB migration and backfill (Phase 1)
type=feature
areas=area:data
priority_recommendation=normal
status_recommendation=ready
problem=`venue_market`/`account_asset` backfill and `trading_account` FK migration are unchecked.
bounded_scope=Phase 1 (migration + backfill) only.
out_of_scope=Phases 2-5 (see NEW-16b..16e); any account/order mutation beyond schema.
dependencies=none
acceptance_criteria=Migration applied; backfill verified against `docs/research/multi_account_asset_foundation_v1.md`.
architecture_owner=DB/ETL
split_required=yes (1 of 5 phases; file separate Issues for Phases 2-5 following the same pattern before implementation)

candidate_id=NEW-17
source_files=docs/todo/multi_horizon_aplus_breathline_strategy_integration_v1.md
proposed_title=Create multi-horizon architecture contract (Breathline/Fibo/Strategy-State/Decision-Gate boundaries)
type=cleanup
areas=area:architecture
priority_recommendation=normal
status_recommendation=needs-design
problem=No written contract yet defines how Breathline, Fibo structural maps, Synth Confirmation, Strategy State, decision_gate, and execution_planner responsibilities compose for multi-horizon strategies.
bounded_scope=Write the architecture-contract doc and guard tests only; no implementation.
out_of_scope=Any strategy implementation.
dependencies=none
acceptance_criteria=Contract doc reviewed and moved to `docs/architecture/`.
architecture_owner=cross-layer (documentation only, not implementation)
split_required=no

candidate_id=NEW-18
source_files=docs/todo/native_short_invalidation_confirmation_backtest_v1.md
proposed_title=Replay native SHORT invalidation-confirmation policies (leak-free, map-cycle-aligned)
type=research
areas=area:research
priority_recommendation=normal
status_recommendation=ready
problem=6 candidate invalidation-confirmation policies are undecided without replay evidence.
bounded_scope=Run the defined leak-free replay across all 6 policies and report the decision-criteria comparison.
out_of_scope=Any selection_engine/decision_gate/execution_planner/executor change.
dependencies=none
acceptance_criteria=Comparison report produced with defined measurements/aggregates.
architecture_owner=research
split_required=no

candidate_id=NEW-19
source_files=docs/todo/native_short_runtime_owner_and_scope_status_v1.md
proposed_title=Assign production runtime owner for native SHORT writer capability
type=cleanup
areas=area:infra
priority_recommendation=normal
status_recommendation=needs-design
problem=`market_rotation_pressure`-adjacent native SHORT writer capability has production owner `UNASSIGNED` and activation `NOT_AUTHORIZED`.
bounded_scope=Human-reviewed owner assignment and the 12-step installed-host activation procedure (already tracked jointly with `short_swing_linked_profile_freshness_and_disk_reliability_v1.md` #201 — verify before filing to avoid duplication).
out_of_scope=Any selection/decision/execution/broker change; P3 deferred hardening (separate, lower-priority item).
dependencies=#201
acceptance_criteria=Owner registry (`deploy/ownership/writer_capability_ownership_v1.json`) updated; activation evidence recorded.
architecture_owner=ops/runtime
split_required=yes (ownership-assignment only; historical implementation section archives instead)

candidate_id=NEW-20
source_files=docs/todo/news_catalyst_monitor.md
proposed_title=Design external_catalyst_monitor_v1 schema and dry runner
type=research
areas=area:research
priority_recommendation=low
status_recommendation=needs-design
problem=No schema/dry-runner exists yet for read-only external catalyst ingestion.
bounded_scope=P0 design task only, per the file's minimum v1 deliverables list.
out_of_scope=Any selection_engine consumption until validated; any decision_gate/execution_planner/executor/order/broker touch.
dependencies=none
acceptance_criteria=Schema + dry runner reviewed.
architecture_owner=research/ETL
split_required=no

candidate_id=NEW-21
source_files=docs/todo/position_rotation_preview.md
proposed_title=Rotation-preview "Next Strategy Work" follow-up (regime discovery comparison)
type=research
areas=area:research
priority_recommendation=low
status_recommendation=ready
problem=MVP cockpit is implemented; the follow-up research comparison (discovered regimes vs. existing labels, symbol-breath-profile/regime-interaction-audit design) is not done.
bounded_scope=Rerun `rotation_destination_historical_replay_audit_v2` and `market_regime_discovery_v1`, then design `symbol_breath_profile_v1` and `regime_interaction_audit_v1`.
out_of_scope=Any change to the already-implemented MVP cockpit; any broker/order/decision/execution change.
dependencies=none
acceptance_criteria=Comparison report produced; two design docs reviewed.
architecture_owner=research
split_required=no

candidate_id=NEW-22
source_files=docs/todo/profit_plan_live_ladder.md
proposed_title=Profit Plan live-ladder P0.0 — canonical read-model prerequisites
type=feature
areas=area:dashboard, area:decision-gate
priority_recommendation=high
status_recommendation=needs-design
problem=The reviewed mutation-safety prerequisite slice (canonical consumer of scope-status + map-level status, deterministic row identity, freshness/account authority) is not yet implemented.
bounded_scope=P0.0 only: canonical read-model prerequisites and read-only tests.
out_of_scope=P0.1-P0.8 (decision_gate wiring, execution_planner, executor, live canary) — each becomes its own gated sub-issue only after the prior phase is accepted.
dependencies=#201 (freshness/ownership), native SHORT map-level status (archived, already closed)
acceptance_criteria=Read-only tests pass; no executor/broker/order change.
architecture_owner=reporting (P0.0 only; later phases touch decision_gate/execution_planner/executor)
split_required=yes (9 phases; file P0.0 now, gate the rest)

candidate_id=NEW-23
source_files=docs/todo/regime_research.md
proposed_title=Regime research Phase 1 — replay audit rerun and regime-discovery comparison
type=research
areas=area:research
priority_recommendation=normal
status_recommendation=ready
problem=Sequenced multi-phase regime research backlog has a concrete, current first step not yet executed.
bounded_scope=Rerun `rotation_destination_historical_replay_audit_v2` full-ish and `market_regime_discovery_v1` full-ish; review named outputs.
out_of_scope=P2/P3 phases until P1 findings are reviewed.
dependencies=none
acceptance_criteria=Named CSV summaries reviewed and reported.
architecture_owner=research
split_required=yes (file P1 now; P2/P3 as follow-on Issues)

candidate_id=NEW-24
source_files=docs/todo/stale_1h_advice_freshness_truth_v1.md
proposed_title=Fix stale 1h advice freshness truth for named assets
type=bug
areas=area:selection
priority_recommendation=high
status_recommendation=ready
problem=Dated observation (2026-08-05, `scripts/run_chain_1h.sh`) shows 11 named assets (IMU, ZORA, IRYS, NOT, RUNE, RED, DEEP, KAIA, INX, SAND, GRT) with stale 1h advice freshness truth.
bounded_scope=Diagnose and correct the freshness-truth path for the 1h advice chain.
out_of_scope=decision_gate/execution_planner/executor.
dependencies=none
acceptance_criteria=Named assets show correct freshness truth on rerun.
architecture_owner=selection_engine (market-only)
split_required=no

candidate_id=NEW-25
source_files=docs/todo/strategy_candidates.md
proposed_title=Current-strategy-audit follow-up — buy-and-hold baselines and replay validation
type=research
areas=area:research
priority_recommendation=normal
status_recommendation=ready
problem=P1 current-strategy-audit follow-up (baselines, replay validation per candidate) is not complete.
bounded_scope=P1 section only, per the file's own sequencing note (before any paper-execution work).
out_of_scope=P2 macro-dip / swing-pullback and P3 legacy-priors sections (separate future Issues).
dependencies=none
acceptance_criteria=Baseline + replay validation reviewed against `docs/research/current_strategy_audit_v1.md`.
architecture_owner=research/selection_engine
split_required=yes (file P1 now; P2/P3 later)

candidate_id=NEW-26
source_files=docs/todo/synth_v214_signal_dashboard_strategy_bridge_backlog.md
proposed_title=File bounded first steps for the v2.14 signal-dashboard/strategy-bridge backlog
type=cleanup
areas=area:dashboard
priority_recommendation=low
status_recommendation=needs-design
problem=Version-pinned to a stale v2.14 tag, describes unstarted cross-cutting dashboard work. Its self-declared overlap with `signal_matrix_dashboard.md` is now resolved independently (that file is archived as superseded by `docs/research/signal_matrix_static_dashboard_v1.md`).
bounded_scope=Check the existing `docs/research/signal_matrix_static_dashboard_v1.md` canonical doc for scope overlap first, then file one Issue for Deferred-Implementation-Order steps 1-3 (freshness audit, signal inventory, horizon-separated matrix) only.
out_of_scope=Full strategy-proposal-contract implementation.
dependencies=none
acceptance_criteria=Overlap check against docs/research/signal_matrix_static_dashboard_v1.md recorded; one bounded Issue filed.
architecture_owner=dashboard-reporting
split_required=no (single source file now that signal_matrix_dashboard.md is independently archived)

candidate_id=NEW-27
source_files=docs/todo/ui_webview.md
proposed_title=Profit Plan coin-card scanability — accepted design implementation
type=feature
areas=area:dashboard
priority_recommendation=low
status_recommendation=ready
problem=Accepted-but-unbuilt design items remain: MAP|ACTIONABLE PPP compact field, tooltip registry, duplicate Current-price tile removal, variable-field alignment fix.
bounded_scope=Exactly the 4 accepted items named in the source file.
out_of_scope=Already-implemented sections (local-time display, freshness/zone display).
dependencies=none
acceptance_criteria=4 items implemented and reviewed; no decision/execution/order/account/balance/position table writes.
architecture_owner=dashboard-reporting
split_required=no

candidate_id=NEW-28
source_files=docs/todo/watchlist_candidates.md
proposed_title=KITE watchlist promotion — liquidity/spread/min-order check
type=research
areas=area:research
priority_recommendation=low
status_recommendation=ready
problem=One remaining pre-promotion check (liquidity, spread, candle-history length, minimum order constraints) is not done.
bounded_scope=Execute the named check against `docs/research/watchlist_feature_signal_status_v1.md`.
out_of_scope=Any selection_engine/advice_engine/decision_gate/execution/order change.
dependencies=none
acceptance_criteria=Check completed with pass/fail evidence recorded.
architecture_owner=research/market-data
split_required=no

```

`martee_oracle_touch_semantics.md` is no longer a new-Issue candidate as of
this pass — it moved to `archive` (see §4 row and §7 entry) since no active
consumer or implementation lane could be found. It is not listed here to
avoid double-counting; do not file it as an Issue unless new evidence of
active use surfaces.

---

## 6. Canonicalization candidates

```text
source=docs/todo/aplus_harmonic_breathline_claim_audit_v1.md
recommended_destination=docs/research/aplus_harmonic_breathline_claim_audit_v1.md
canonical_role=Permanent claim-correction reference (Prime-17, 21-day Breathline harmonic integration)
content_to_preserve=Full audit body, corrected claims, date (2026-06-09)
content_to_drop_or_archive=none — whole file moves
reference_updates_required=docs/todo/README.md pointer only (no other inbound references found)

source=docs/todo/astro_policy_confluence_research_todo_bundle_v1.md
recommended_destination=docs/research/astro_policy_confluence_v1.md (file's own proposed name)
canonical_role=Permanent research design (hypotheses H1-H6, data schema, statistical methodology)
content_to_preserve=Full research design sections
content_to_drop_or_archive=none identified — content is coherent as a single design doc
reference_updates_required=none found

source=docs/todo/external_forecast_event_registry.md
recommended_destination=docs/research/external_forecast_event_registry_v1.md
canonical_role=Permanent data-contract design (field/category/forecast_type enums)
content_to_preserve=Full schema and example JSONL
content_to_drop_or_archive=none — no dated raw-notes section in this file (unlike its sibling)
reference_updates_required=none found

source=docs/todo/external_research_ingestion.md
recommended_destination=docs/research/external_research_ingestion_v1.md (schema/strategy sections) + docs/research/external_elliott_wave_claim_validation_v1.md (self-proposed, Elliott Wave sub-lane)
canonical_role=Permanent extraction-schema and strategy-design reference
content_to_preserve=external_support_shoulder_reaction_strategy_v1 schema, Martee signal-horizon model, FX handling rules, Elliott Wave validation schema
content_to_drop_or_archive=The "Latest unsaved research examples" block (dated 2026-05-25 raw market-level notes for VET/KITE/PLUME/Terafab/NEAR/macro-bond) — stale capture, not a spec; recommend docs/archive/ instead of forward-carrying
reference_updates_required=none found

source=docs/todo/idiosyncratic_catalyst_override.md
recommended_destination=docs/research/idiosyncratic_catalyst_override_v1.md
canonical_role=Permanent concept/taxonomy note ("dirty squeeze" catalyst-override model)
content_to_preserve=Full concept definition and XLM/DTCC case study
content_to_drop_or_archive=none — single coherent concept note
reference_updates_required=none found

source=docs/todo/market_breath.md
recommended_destination=docs/research/market_breath_v1_sensor_classification_summary.md (already exists — confirm it fully captures this file's phase-classification table before archiving the TODO shell)
canonical_role=Permanent phase-classification taxonomy record
content_to_preserve=Verify COLLAPSE_RESET/EXHALE_EXPANSION/etc. table is present in the existing summary doc
content_to_drop_or_archive=TODO shell itself, after confirmation
reference_updates_required=none found

source=docs/todo/synth_v214_signal_dashboard_strategy_bridge_backlog.md
recommended_destination=docs/architecture/strategy_proposal_contract_v1.md (proposed new canonical file — does not currently exist)
canonical_role=Permanent strategy-proposal contract (ACTION/HORIZON/SETUP enums, bucket allocation model, LLM/agent bridge boundary, anti-patterns)
content_to_preserve=Proposal contract format, enums, bucket model, anti-patterns list
content_to_drop_or_archive=Version-specific "v2.14" framing and any content fully covered by signal_matrix_dashboard.md after consolidation (see NEW-26)
reference_updates_required=docs/todo/signal_matrix_dashboard.md cross-reference should point at the new canonical file
```

---

## 7. Archive candidates

```text
source=docs/todo/breath_curve.md
archive_reason=Parked with no bounded next action
unique_evidence=Pointer list to 5 dated findings docs (all already exist under docs/research/)
recommended_archive_path=docs/archive/todo/breath_curve.md
references_to_update=docs/todo/README.md

source=docs/todo/card_actionability_map_completed_navigation_v1.md
archive_reason=Verified implemented — PR #10, gating PR #5 both merged
unique_evidence=Original inline gating instructions and branch/PR names for provenance
recommended_archive_path=docs/archive/todo/card_actionability_map_completed_navigation_v1.md
references_to_update=none found

source=docs/todo/claude_bundle_1_pipeline_contracts_v1.md
archive_reason=Verified implemented — docs/architecture/pipeline_contracts.md and tests/test_pipeline_contract_boundaries_v1.py both exist
unique_evidence=Original agent-handoff framing and full-layer architecture primer text (largely superseded by the actual doc, retained for provenance only)
recommended_archive_path=docs/archive/todo/claude_bundle_1_pipeline_contracts_v1.md
references_to_update=none found

source=docs/todo/dev_ops_hygiene.md
archive_reason=3 of 4 sections closed; 4th (DB backup procedure) is a small optional residual, not a bounded task
unique_evidence=Known-good MariaDB verification command block
recommended_archive_path=docs/archive/todo/dev_ops_hygiene.md
references_to_update=none found

source=docs/todo/fib_navigation_map_rebuild_v1.md
archive_reason=Verified implemented — PR #1 / commit d7c57af4
unique_evidence=Required-states enum (FRESH/STALE/EXHAUSTED/FALLBACK/EMERGENCY_REBUILT/NO_DATA/LOW_CONFIDENCE) and rebuild-trigger definitions, not fully duplicated in golden_coin_cases_backtest_bundle_v1.md
recommended_archive_path=docs/archive/todo/fib_navigation_map_rebuild_v1.md
references_to_update=none found

source=docs/todo/historical_breath_regime_context_backlog.md
archive_reason=Verified implemented and run — src/research/run_historical_breath_regime_context_builder_v1.py exists with output data; file's own `Status: active` is stale
unique_evidence=Original canonical field-contract definition and precedence-decision rationale
recommended_archive_path=docs/archive/todo/historical_breath_regime_context_backlog.md
references_to_update=none found

source=docs/todo/historical_market_breath_source_enrichment_backlog.md
archive_reason=Verified implemented and run — src/research/run_historical_market_breath_source_enrichment_v1.py exists (commit 1310c7f3) with output rows; file's own `Status: active` is stale
unique_evidence=Original upstream-coverage-gap analysis
recommended_archive_path=docs/archive/todo/historical_market_breath_source_enrichment_backlog.md
references_to_update=none found

source=docs/todo/historical_market_breath_source_recompute_backlog.md
archive_reason=Verified implemented and run — src/research/run_historical_market_breath_source_recompute_v1.py + test exist (commit cbbc8f20), and the recomputed source is already wired into the context builder (commit 97b1a02c); file's own `Status: active` is stale
unique_evidence=Coverage-metric trigger evidence (377->377, 157->157) documenting why enrichment alone was insufficient
recommended_archive_path=docs/archive/todo/historical_market_breath_source_recompute_backlog.md
references_to_update=none found

source=docs/todo/manual_ladder_dashboard.md
archive_reason=README's own frozen disposition: "historical source / superseded — active ladder work is tracked only in profit_plan_live_ladder.md"
unique_evidence=Neutral label taxonomy and two worked examples (ALGO-style, WLD-style rows), useful design provenance
recommended_archive_path=docs/archive/todo/manual_ladder_dashboard.md
references_to_update=docs/todo/README.md lane-index row already reflects this; no other inbound references found

source=docs/todo/native_short_map_level_status_v1.md
archive_reason=Verified closed — PRs #68/#71/#76/#77/#79/#81/#87; `done / parked` with explicit reopen criteria
unique_evidence=Two dated correction addenda (2026-07-31) recording an additive companion ledger and a same-day cross-provider-review fix
recommended_archive_path=docs/archive/todo/native_short_map_level_status_v1.md
references_to_update=none found

source=docs/todo/paper_candidate_contract.md
archive_reason=Content duplicates AGENTS.md boundary rules; canonical doc already exists (docs/research/paper_candidate_contract_v1.md); remaining item is unscheduled
unique_evidence=none beyond restatement — low archival value, candidate for eventual removal once confirmed fully duplicate
recommended_archive_path=docs/archive/todo/paper_candidate_contract.md
references_to_update=none found

source=docs/todo/parked_backlog.md
archive_reason=Four parked micro-lanes, all explicitly deferred with no bounded action; A+ archive sub-section already closed
unique_evidence=A+ archive migration/loader evidence (db/migrations/20260516_aplus_report_archive_v1.sql, src/research/load_aplus_reports_to_db_v1.py)
recommended_archive_path=docs/archive/todo/parked_backlog.md
references_to_update=none found

source=docs/todo/profit_plan_card_evidence_delta_visibility_v1.md
archive_reason=`Status: done / parked`; no active tasks remain
unique_evidence=Implementation-file inventory for the evidence-delta feature
recommended_archive_path=docs/archive/todo/profit_plan_card_evidence_delta_visibility_v1.md
references_to_update=none found

source=docs/todo/profit_plan_dashboard_action_truth_and_breathline_demote_v1.md
archive_reason=`Status: done / parked`; PRs #78, #82, #75, #84, #85, #86
unique_evidence=Breathline demotion governance fact (RESEARCH_ONLY_DISABLED, weights=0) — checked and NOT currently found in docs/architecture/ or docs/status/, so this is the only record; recommend copying that fact into docs/architecture/ before archiving
recommended_archive_path=docs/archive/todo/profit_plan_dashboard_action_truth_and_breathline_demote_v1.md
references_to_update=docs/todo/momentum_flow_scanner_matrix_v1.md's stale cross-reference to this file (being removed anyway, see §8)

source=docs/todo/profit_plan_target_lifecycle_history_truth_v1.md
archive_reason=`CONTAINED / COMPLETED` by PR #105; addendum already implemented; future hardening explicitly evidence-gated with no current trigger
unique_evidence=Root-cause/forensic-audit record for the original IOST defect
recommended_archive_path=docs/archive/todo/profit_plan_target_lifecycle_history_truth_v1.md
references_to_update=none found

source=docs/todo/synth_v2_development_roadmap_v1.md
archive_reason=Pinned to old commit d7c57af; "Completed" section superseded by later native-SHORT/map-level-status/profit-plan-live-ladder work
unique_evidence=Historical 7-bundle roadmap snapshot
recommended_archive_path=docs/archive/todo/synth_v2_development_roadmap_v1.md
references_to_update=none found

source=docs/todo/todo_information_architecture_v1.md
archive_reason=File itself explicitly requests this exact disposition
unique_evidence=Original subfolder-plan proposal, useful migration provenance
recommended_archive_path=docs/archive/todo/todo_information_architecture_v1.md
references_to_update=docs/todo/README.md, docs/todo/MIGRATION_FREEZE.md (both already reference it correctly; no change needed beyond the archive move itself)

source=docs/todo/signal_matrix_dashboard.md
archive_reason=Content superseded by two already-existing canonical docs committed the same day (docs/research/signal_matrix_static_dashboard_v1.md, docs/research/signal_matrix_single_asset_replay_v1.md); the replay design's runner is already implemented
unique_evidence=None beyond what the two canonical docs already contain — confirm before archiving that nothing in this file is missing from them
recommended_archive_path=docs/archive/todo/signal_matrix_dashboard.md
references_to_update=docs/todo/synth_v214_signal_dashboard_strategy_bridge_backlog.md's "Existing Overlap" cross-reference

source=docs/todo/sector_rotation_engine_v1.md
archive_reason=Downgraded from `remove` this pass — real successor content is confirmed to exist at docs/todo/market_intelligence/sector_rotation_engine_v1.md, but tests/test_sector_taxonomy_import_v1.py::test_sector_rotation_public_contract_uses_participation_terms has a functional (not textual) dependency on this exact root file's content, and that test is already failing on current main
unique_evidence=None beyond the redirect — archival is a safety fallback until the test dependency is resolved, not because this file has independent value
recommended_archive_path=docs/archive/todo/sector_rotation_engine_v1.md (only after the test is repointed; see Batch 2D note)
references_to_update=docs/todo/README.md, docs/todo/sector_rotation_dashboard_v1.md, docs/todo/market_intelligence/sector_rotation_engine_v1.md, and — before any move — tests/test_sector_taxonomy_import_v1.py (functional dependency, must be repointed at the market_intelligence/ path first)

source=docs/todo/martee_oracle_touch_semantics.md
archive_reason=No implementation, canonical consumer, adequate Issue, or dated evidence of current relevance found anywhere in the repository; generic undated `Status: TODO`
unique_evidence=Touch-semantics field model concept, preserved for provenance in case the lane is reactivated
recommended_archive_path=docs/archive/todo/martee_oracle_touch_semantics.md
references_to_update=none found — reactivation requires evidence of an active consumer or implementation lane (a runner, test, or canonical doc depending on Martee Oracle touch semantics) before this is ever filed as an Issue
```

---

## 8. Removal candidates

```text
source=docs/todo/cross_asset_metals_miners_food_rotation_v1.md
canonical_duplicate=docs/todo/external_research/cross_asset_public_data_and_instrument_registry_v1.md, docs/todo/market_intelligence/cross_asset_rotation_research_v1.md
unique_content_absent=Verified — file is a self-declared pure redirect ("remains only to preserve historical context and existing links"); both successor files confirmed to exist and contain the substantive content
incoming_references=docs/todo/README.md, docs/todo/market_intelligence/README.md
reference_resolution_plan=Point both README rows directly at the two successor files, then delete
removal_risk=Low — content is fully preserved in confirmed-existing successor files; only the redirect layer is removed

source=docs/todo/ffg_curated_rotation_radar_v1.md
canonical_duplicate=docs/todo/external_research/ffg_universe_metadata_v1.md, docs/todo/market_intelligence/ffg_rotation_classification_v1.md, docs/todo/reporting/ffg_rotation_radar_presentation_v1.md
unique_content_absent=Verified — file states "no longer owns active work"; all three successor files confirmed to exist
incoming_references=docs/todo/README.md
reference_resolution_plan=Point README row directly at the three successor files, then delete
removal_risk=Low

source=docs/todo/momentum_flow_scanner_matrix_v1.md
canonical_duplicate=docs/todo/market_intelligence/momentum_flow_scanner_research_v1.md, docs/todo/reporting/profit_plan_opportunity_presentation_v1.md
unique_content_absent=Verified — file states "former umbrella TODO no longer owns active work"; both successor files confirmed to exist
incoming_references=docs/todo/README.md, docs/todo/profit_plan_dashboard_action_truth_and_breathline_demote_v1.md (stale cross-reference — that file also claims this TODO owns "minimum 4% target-room / RSI-MFI entry research", which contradicts this file's own disclaimer)
reference_resolution_plan=Correct the stale cross-reference in profit_plan_dashboard_action_truth_and_breathline_demote_v1.md before or during its own archival; update README row; then delete
removal_risk=Low-medium — one stale inbound cross-reference must be corrected first, not just README

source=docs/todo/sector_rotation_master_plan_v1.md
canonical_duplicate=docs/todo/market_intelligence/sector_rotation_master_plan_v1.md
unique_content_absent=Verified — pure redirect; successor confirmed to exist
incoming_references=docs/todo/README.md
reference_resolution_plan=Update README pointer, then delete
removal_risk=Low

source=docs/todo/sector_taxonomy_database_seed_v1.md
canonical_duplicate=docs/todo/completed/sector_taxonomy_database_seed_v1.md, docs/research/sector_taxonomy_database_seed_v1.md
unique_content_absent=Verified — file explicitly states "This completed lane moved to: docs/todo/completed/sector_taxonomy_database_seed_v1.md"; both successors confirmed to exist
incoming_references=docs/todo/README.md, docs/todo/sector_rotation_dashboard_v1.md, docs/todo/market_intelligence/sector_rotation_engine_v1.md
reference_resolution_plan=Update all three inbound pointers to reference docs/todo/completed/... or docs/research/... directly, then delete
removal_risk=Low-medium — three separate inbound references to update, but all content is independently confirmed preserved elsewhere
```

§8 now lists 5 removal candidates (down from 6). `sector_rotation_engine_v1.md`
was removed from this section this pass and moved to §7 (archive) after
`tests/test_sector_taxonomy_import_v1.py` was found to have a **functional**
dependency on its exact content — proving deletion safety requires fixing
that test first, which this proposal does not do. See its §7 entry.

A file was **not** classified `remove` merely for looking old or completed — every
row above required an independently verified, currently-existing successor
location, **and** a check for functional (not just textual) inbound
references, before this disposition was assigned. Files where a plausible
successor was mentioned but not verified to exist, or where a functional
dependency was found and not yet resolved, receive `archive` with `blocked`
confidence instead of `remove`.

---

## 9. Architecture violations

Files that bundle more than one architecture layer's concerns into a single
proposed unit of work (not merely *describing* the full layer chain as
documentation, which several boundary-contract docs legitimately do):

```text
file=docs/todo/2026-05-19_product_cockpit_strategy_bundle.md
mixes=dashboard-reporting display work + decision_gate-adjacent strategy-bucket
      permission config + a mention of execution_planner follow-on, all as one
      "bundle"
required_split=Separate Issues per initiative (see NEW-01); the
      dashboard-only items must not be filed in the same Issue as the
      bucket-permission config item

file=docs/todo/live_like_vertical_slice.md
mixes=selection_engine-adjacent candidate emission + decision_gate preview +
      execution_planner preview, explicitly as "the first narrow bridge"
required_split=Acceptable as designed ONLY because every piece stays
      shadow-mode/read-only with broker_writes=0; flagged here so any future
      expansion of this lane is reviewed as a new architecture decision, not
      an incremental broadening of the same Issue

file=docs/todo/multi_account_asset_foundation_backlog.md
mixes=DB schema/ETL + selection_engine candidate-fetch venue param +
      account-aware dashboard filter + account onboarding, across 5 phases
      in one backlog file
required_split=One Issue per phase (see NEW-16); the selection_engine
      change (Phase 4.2, adding a venue param) must stay market-only and not
      be bundled with the account-onboarding phase

file=docs/todo/profit_plan_live_ladder.md
mixes=reporting + decision_gate + execution_planner + executor + broker,
      explicitly sequenced as P0.0 through P0.8 in one file
required_split=Phase-gated sub-issues (see NEW-22); each phase must be
      individually accepted before the next is scoped — this file's own P0.x
      structure already enforces this, it must be preserved in Issue form,
      not collapsed into one Issue

file=docs/todo/deploy_runtime.md
mixes=market_data/ETL candle-ingestion cutover + dashboard-reporting webview
      refresh + a market-trigger-engine design mention + ops-standard
      documentation, bundled as one 441-line file
required_split=Separate Issues per lane (see NEW-11); do not let the
      candle-ingestion cutover Issue silently absorb the webview or ops-standard
      items
```

No file was found that mixes `decision_gate` permission logic directly with
`execution_planner`/`executor` order construction in a way that bypasses
`decision_gate`, and no file proposes a `reporting`-to-`broker` shortcut.
The violations above are all **planning-bundle** violations (multiple layers
described as one unit of future work), not code-level boundary violations.

---

## 10. Proposed bounded migration batches

```text
Batch 2A — clear active Issue candidates
files=account_provisioning.md (Batch 4 only), adaptive_fib_execution_offset_v1.md,
      backtest_capability_contract_v1.md, breathline_backtest_campaign_and_coin_calibration_v1.md,
      breathline_ui_phase_path_history_v1.md, decision_gate_account_protections_v1.md,
      golden_coin_cases_backtest_bundle_v1.md, native_short_invalidation_confirmation_backtest_v1.md,
      news_catalyst_monitor.md, stale_1h_advice_freshness_truth_v1.md, watchlist_candidates.md,
      claude_bundle_2_elliott_wave_daily_context_lane_v1.md
issues_to_create=NEW-02, NEW-03, NEW-04, NEW-05, NEW-06, NEW-09, NEW-09b, NEW-10, NEW-14,
      NEW-18, NEW-20, NEW-24, NEW-28
moves=none
archives=none
removals=none
dependencies=none
merge_order=first — smallest, single-layer, highest-confidence rows
risk=low

Batch 2B — canonical contract moves
files=aplus_harmonic_breathline_claim_audit_v1.md, astro_policy_confluence_research_todo_bundle_v1.md,
      external_forecast_event_registry.md, external_research_ingestion.md,
      idiosyncratic_catalyst_override.md, market_breath.md,
      synth_v214_signal_dashboard_strategy_bridge_backlog.md
issues_to_create=NEW-26 (only — the rest are pure doc moves, no Issue)
moves=7 files (or split portions) to docs/research/ or docs/architecture/ per §6
archives=external_research_ingestion.md's dated raw-notes block, split out separately
removals=none
dependencies=confirm market_breath.md's destination doc already contains the phase table before archiving the shell
merge_order=second — no code risk, but requires careful content-splitting review (external_research_ingestion.md, synth_v214 backlog)
risk=medium (content-splitting judgment calls, not technical risk)

Batch 2C — completed historical archives
files=breath_curve.md, card_actionability_map_completed_navigation_v1.md,
      claude_bundle_1_pipeline_contracts_v1.md, dev_ops_hygiene.md,
      fib_navigation_map_rebuild_v1.md, historical_breath_regime_context_backlog.md,
      historical_market_breath_source_enrichment_backlog.md,
      historical_market_breath_source_recompute_backlog.md, manual_ladder_dashboard.md,
      martee_oracle_touch_semantics.md, native_short_map_level_status_v1.md,
      paper_candidate_contract.md, parked_backlog.md,
      profit_plan_card_evidence_delta_visibility_v1.md,
      profit_plan_dashboard_action_truth_and_breathline_demote_v1.md,
      profit_plan_target_lifecycle_history_truth_v1.md, signal_matrix_dashboard.md,
      synth_v2_development_roadmap_v1.md, todo_information_architecture_v1.md
issues_to_create=none
moves=none
archives=19 files to docs/archive/todo/ (sector_rotation_engine_v1.md is
      deliberately excluded from this batch — see Batch 2D note below)
removals=none
dependencies=Copy the Breathline demotion governance fact out of
      profit_plan_dashboard_action_truth_and_breathline_demote_v1.md into
      docs/architecture/ before archiving (only file in this batch with content
      not otherwise preserved)
merge_order=third — zero runtime risk, but should follow 2A/2B so nothing
      genuinely-open gets archived by mistake
risk=low

Batch 2C-2 — blocked archive (test dependency must be fixed first)
files=sector_rotation_engine_v1.md
issues_to_create=one small test-fix Issue: repoint
      tests/test_sector_taxonomy_import_v1.py::test_sector_rotation_public_contract_uses_participation_terms
      at docs/todo/market_intelligence/sector_rotation_engine_v1.md (note: this
      test is already failing on current main, independent of this proposal)
moves=none
archives=1 file, only after the test-fix Issue merges and the test passes
      against the new target
removals=none
dependencies=test-fix Issue above
merge_order=after 2C, before 2D
risk=low once the test is repointed; unsafe to archive/remove before then

Batch 2D — proven duplicate removals
files=cross_asset_metals_miners_food_rotation_v1.md, ffg_curated_rotation_radar_v1.md,
      momentum_flow_scanner_matrix_v1.md, sector_rotation_master_plan_v1.md,
      sector_taxonomy_database_seed_v1.md
issues_to_create=none
moves=none
archives=none
removals=5 files, only after each file's incoming references (README.md rows,
      market_intelligence/README.md, one profit_plan_dashboard_action_truth_...
      stale cross-reference) are individually confirmed and updated first.
      sector_rotation_engine_v1.md is EXCLUDED from this batch (moved to
      Batch 2C-2 — it has a functional test dependency, not just a doc
      reference, so it cannot be a same-batch removal candidate)
dependencies=Batch 2C for the profit_plan_dashboard_action_truth_... stale
      cross-reference correction
merge_order=fourth — do last, since it touches the most files outside docs/todo/
risk=medium (reference correctness must be re-verified at merge time, not just
      at proposal time, since other agents may touch these files concurrently)

Batch 2E — TODO infrastructure retirement
files=README.md, MIGRATION_FREEZE.md, workflow_standard.md
issues_to_create=none
moves=none
archives=none
removals=none
dependencies=All of Batch 2A-2D complete, i.e. every one of the other 66 files
      has a closed disposition
merge_order=last
risk=low, but must not be attempted early — README still serves as the
      disposition checklist until every row is closed
```

Do not combine Batch 2A (Issue creation) with 2B (canonical moves), 2C
(archives), or 2D (removals) in one PR — each batch has an independent
reviewable diff shape and independent risk profile.

---

## 11. Final acceptance evidence

### Issue-inventory pagination

```text
repository_issues_checked=13
open_issues_checked=9
closed_issues_checked=4
highest_issue_number_seen=212
pagination_complete=yes
```

Retrieved via `gh api repos/oboly/synth-v2/issues --paginate -f state=all -f
per_page=100` (the raw REST endpoint, which includes PRs, to guarantee no
pagination gap) and cross-checked against `gh issue list --state all --limit
500` (which returns issues only). Both return exactly 13 issues:
`#131` (closed), `#198`-`#206` (all open), `#207` (closed), `#210` (closed),
`#212` (closed — resolved by PR #213, merged into the `main` head this pass
revalidated against). The highest-numbered item in the repository overall is
PR `#213`; the highest **Issue** is `#212`. No gap exists between `#131` and
`#212` other than genuinely absent numbers (deleted/never-created), so
pagination is complete — a single `--limit 500` call already returned every
issue with room to spare, and the paginated raw-API call confirms the same
13-issue set.

### Issue-overlap verification (scope comparison, not title matching)

Full bodies of all 9 open Issues (`#198`-`#206`) were fetched and read; the 4
closed Issues (`#131`, `#207`, `#210`, `#212`) were already known in detail
from this session's earlier work (the `#212` audit and the `#209` migration
manifest that created `#198`-`#206`). Every one of the 28 new-Issue
candidates was compared against all 13 on problem, bounded scope, acceptance
criteria, architecture owner, and dependencies — not title text.

| Candidate ID | Existing Issues checked | Closest overlap | Result | Reason |
|---|---|---|---|---|
| NEW-02 (account_provisioning Batch 4) | all 13 | none | new_issue | No existing Issue touches broker-credential read-validation |
| NEW-03 (adaptive_fib_execution_offset) | all 13 | none | new_issue | No existing Issue covers execution-offset policy research |
| NEW-04 (backtest_capability_contract) | #205 | #205 (replay harness) | new_issue | #205 is a specific replay harness implementation; this is a separate, earlier-stage capability-schema/inventory task it would eventually consume, not duplicate |
| NEW-05 (breathline_backtest_campaign) | all 13 | none | new_issue | No existing Issue touches Breathline per-coin calibration |
| NEW-06 (breathline_ui_phase_path_history) | all 13 | none | new_issue | No existing Issue covers this reporting card |
| NEW-07/08 (bullrun_start_dashboard, 2 scopes) | #204 | #204 (Sector Rotation dashboard) | new_issue | #204's canonical source and scope are explicitly Sector Rotation only; different dashboard entirely |
| NEW-09/09b (Elliott Wave Phase 1 + layering fix) | all 13 | none | new_issue | No existing Issue covers this research lane or the import-layering bug |
| NEW-10 (decision_gate_account_protections) | #202, #203, #206 | #206 (credential/executor boundary) | new_issue | #206's scope is the credential/executor handoff boundary specifically; this candidate is upstream permission-contract design (drawdown/loss/cooldown), a different decision_gate concern not covered by #206's listed scope |
| NEW-11 (deploy_runtime candle-ingestion cutover) | #201 | #201 (linked-profile freshness) | new_issue | #201's canonical source and out-of-scope line explicitly exclude "public-market writer ownership changes unrelated to this runtime path" — candle ingestion is a different writer/lane |
| NEW-12/13 (fibo_zones cutover + calibration) | all 13 | none | new_issue | No existing Issue covers canonical_fib_zone_map production activation or this calibration investigation |
| NEW-14 (golden_coin_cases states/fixtures) | all 13 | none | new_issue | No existing Issue covers MarketNavigationState/BreathlineState/etc. |
| NEW-15 (live_like_vertical_slice) | all 13 | deploy_runtime.md's own "first paper strategy lane" (not an Issue) | new_issue | Confirmed no Issue exists for either description; both are the same undescribed lane in two TODO files — flagged as a same-batch duplication risk between two *candidates*, not against an existing Issue |
| NEW-16 (multi_account_asset_foundation Phase 1) | all 13 | none | new_issue | No existing Issue covers account/asset schema work |
| NEW-17 (multi_horizon architecture contract) | all 13 | none | new_issue | No existing Issue covers Breathline/Fibo/Strategy-State boundary documentation |
| NEW-18 (native_short_invalidation_confirmation_backtest) | #198, #199, #200 | #200 (per-scope failure isolation) | new_issue | #200's scope is orchestration/failure-domain isolation, not invalidation-confirmation policy research; distinct concern on the same subsystem |
| NEW-19 (native_short runtime owner assignment) | #200, #201 | #201 (linked-profile freshness / host-ownership revalidation) | partial_overlap_split_required | #201's scope bullet "Revalidate installed system- and user-level owners on the actual runtime host" is host-ownership language that may already extend to this writer capability if it runs on the same host; #201's canonical source is specifically the short_swing file, not this one — needs a human check of whether #201's acceptance already covers native-SHORT writer ownership before NEW-19 is filed as fully separate |
| NEW-20 (news_catalyst_monitor design) | all 13 | none | new_issue | No existing Issue covers external catalyst ingestion |
| NEW-21 (position_rotation_preview follow-up) | all 13 | none | new_issue | No existing Issue covers rotation-preview regime-discovery comparison |
| NEW-22 (profit_plan_live_ladder P0.0) | #202, #203, #206 | #202/#203 (manual execution request/ladder construction) | partial_overlap_split_required | #202 explicitly assumes "the request contract, unapplied migration, and service entrypoint exist" already — it does not cover the Profit Plan card-level read-model/row-identity prerequisite this candidate scopes (P0.0 only). Later phases of the same source file (P0.5+, decision_gate/execution_planner wiring) will likely merge into #202/#203/#206 rather than becoming new Issues — this is called out explicitly so P0.0 is filed now and P0.5+ is filed later against #202/#203/#206, not as a fresh Issue |
| NEW-23 (regime_research Phase 1) | all 13 | none | new_issue | No existing Issue covers this research replay |
| NEW-24 (stale_1h_advice_freshness_truth) | #207, #210, #212 | none | new_issue | #207/#210/#212 are all specifically about Profit Plan's canonical-4h-context card classification (now fully resolved by PR #211/#213); this candidate is a 1h advice-freshness defect in a different reporting path (`scripts/run_chain_1h.sh`) |
| NEW-25 (strategy_candidates P1 audit follow-up) | all 13 | none | new_issue | No existing Issue covers this |
| NEW-26 (synth_v214 signal-dashboard backlog first steps) | #204 | #204 (Sector Rotation dashboard) | new_issue | #204's canonical source and scope are Sector Rotation only; this is an unrelated signal/strategy-bridge dashboard |
| NEW-27 (ui_webview coin-card scanability) | all 13 | none | new_issue | No existing Issue covers this accepted-but-unbuilt design |
| NEW-28 (watchlist_candidates liquidity check) | all 13 | none | new_issue | No existing Issue covers this |
`martee_oracle_touch_semantics.md` (previously NEW-29) is no longer a
new-Issue candidate as of this pass — see §4/§7 (moved to `archive`,
confidence remains `blocked`) and the resolution note below. It is excluded
from the table above to avoid double-counting a file that is no longer
proposed as an Issue.

Result: 25 of the remaining 27 new-Issue candidates are clean `new_issue`
(no overlap with any of the 13 existing Issues on
problem/scope/acceptance-criteria/owner/dependencies, not merely on title).
2 are `partial_overlap_split_required` (NEW-19, NEW-22) — both already
carried an explicit dependency note in §5 before this pass; that note is now
upgraded to a required pre-filing check against the named Issue and both
remain explicitly deferred pending human overlap review, not filed. 0 are
`already_owned` or `merge_with_candidate`.

```text
inventory_complete=yes — all 69 files under docs/todo/ (direct children only, per instruction) read in full and appear exactly once in §4
all_files_classified_once=yes
counts_reconcile=yes (7 + 27 + 7 + 20 + 5 + 3 = 69)
existing_issue_overlap_checked=yes — full-body scope comparison against all 13 issues (9 open bodies fetched and read in full, 4 closed already known in session detail), not title matching; see overlap table above
canonical_replacements_verified=yes — every "Verified exists" / existing canonical path cited in §4/§6/§7/§8 was checked with `ls`/`find`; unverified proposed destinations are explicitly marked "proposed"
architecture_boundaries_checked=yes — see §9
remove_candidates_have_unique_content_proof=yes — see §8, all 5 remaining removal candidates have a confirmed-existing successor location AND a confirmed absence of functional (not just textual) inbound references; sector_rotation_engine_v1.md was downgraded to archive+blocked this pass specifically because a functional reference was found
new_issue_candidates_are_bounded=yes — each NEW-* candidate has explicit out_of_scope and acceptance_criteria; 8 large source files were split rather than proposed as one oversized Issue
repository_files_modified=1
issues_created=0
files_moved=0
files_archived=0
files_removed=0
runtime_changes=0
database_changes=0
broker_writes=0
order_submissions=0
service_timer_changes=0
```

### Resolution of the two previously-uncertain rows

```text
SECTOR_ROTATION_ENGINE_REFERENCE_TYPE=functional_dependency
```
`tests/test_sector_taxonomy_import_v1.py::test_sector_rotation_public_contract_uses_participation_terms`
opens and asserts directly on `docs/todo/sector_rotation_engine_v1.md`'s
text content (requires `positive_participation_pct`, `participation_ratio`,
`INSUFFICIENT_PARTICIPATION` present; requires `"breadth"` absent). Ran
`pytest tests/test_sector_taxonomy_import_v1.py -k participation_terms`
against current `main` (`20fd299a`): **it already fails**, because the root
file is now only a 9-line redirect and no longer contains those terms. This
is a pre-existing defect on `main`, not something this proposal introduces or
would worsen. `SECTOR_ROTATION_ENGINE_DISPOSITION=archive` (downgraded from
`remove`, confidence `blocked` — see §4/§7 rows and Batch 2C-2).

```text
MARTEE_DISPOSITION=archive (confidence=blocked)
```
No implementation, canonical consumer, adequate Issue, or dated evidence of
current relevance was found anywhere in the repository for
`martee_oracle_touch_semantics.md` (`grep -rli martee` outside `docs/todo/`
returns only unrelated `historical_breath_regime_*`/`historical_market_breath_*`
files that happen to also mention "Martee" as an unrelated proper noun in
their own text, and `git log --grep=martee` returns only the original 2026-05
authoring commit). Primary disposition is now `archive` (changed from
`issue` this pass) — genuine absence of evidence of an active consumer or
implementation lane is treated as grounds to archive, not as grounds to file
an Issue on spec. Confidence remains `blocked` because the underlying
question (is this lane still wanted at all) cannot be answered from repo
evidence either way. **Reactivation condition**: this should only move back
to `issue` if new evidence surfaces of an active consumer or implementation
lane — e.g. a runner, test, or canonical doc that comes to depend on Martee
Oracle touch semantics. Absent that, it stays archived.

```text
SIGNAL_MATRIX_DISPOSITION=archive (confidence=medium)
```
Resolved this pass (previously `blocked`) — see §4 row and §7 entry.
`docs/research/signal_matrix_static_dashboard_v1.md` and
`docs/research/signal_matrix_single_asset_replay_v1.md` both verified to
exist, committed the same day as the TODO file; the replay design's runner
is already implemented.

### Open items for human review

- `martee_oracle_touch_semantics.md`: disposition set to `archive` this pass
  (confidence remains `blocked`). It stays archived and is not filed as an
  Issue unless new evidence of an active consumer or implementation lane
  surfaces — see the reactivation condition above.
- NEW-19 (native SHORT runtime-owner assignment) and NEW-22 (Profit Plan
  live-ladder P0.0) remain explicitly **deferred pending human overlap
  review** against #201 and #202/#203 respectively (see the overlap table)
  — do not file either until that review happens.
- `sector_rotation_engine_v1.md`: **resolved this pass** — the reference
  inside `tests/test_sector_taxonomy_import_v1.py` is a confirmed
  `functional_dependency` (the test reads and asserts on the file's exact
  content), and that test is already failing on current `main` independent of
  this proposal. File is now `archive` with `blocked` confidence pending a
  small test-fix Issue (Batch 2C-2) rather than a `remove` candidate.
- `profit_plan_dashboard_action_truth_and_breathline_demote_v1.md`'s
  Breathline-demotion governance fact (`RESEARCH_ONLY_DISABLED`, all
  weights=0) was not found already captured under `docs/architecture/` or
  `docs/status/` — recommend copying it forward before this file is archived,
  so it is not lost.
