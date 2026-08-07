# docs/todo Retirement Readiness — Batch 6A (Final Audit)

agent=claude-code
role=auditor
model=claude-sonnet-5
effort=high

## 1. Executive result

`RETIREMENT_READY=0`

`docs/todo/` cannot be retired yet. Of 68 tracked files: 33 (49%) are
`KEEP_TEMPORARILY` with genuinely unowned open scope (no GitHub Issue at
all covers them), 12 more are `ISSUE_OWNED` with only **partial** Issue
coverage (real residual scope left in the file), 8 are ready for `ARCHIVE`,
1 is a pure redirect ready for `REMOVE`, 11 are fully `ISSUE_OWNED`, 0 are
immediately `CANONICALIZE`-ready, and 3 are the `INFRASTRUCTURE` files
(`README.md`, `MIGRATION_FREEZE.md`, `workflow_standard.md`).

The largest single blocker is that several high-risk, high-content files —
`profit_plan_live_ladder.md` (364 lines, self-described `active P1`),
`fibo_zones.md` (340 lines, self-described `active P0`), `deploy_runtime.md`
(441 lines), `2026-05-19_product_cockpit_strategy_bundle.md` (461 lines),
`native_short_runtime_owner_and_scope_status_v1.md` (248 lines), and
`multi_account_asset_foundation_backlog.md` — carry **no GitHub Issue
migration pointer at all**. They were never touched by the prior Batch
2A/2B/2C Issue-migration passes. This is a materially different situation
from most of the other residuals, which already carry a reviewed
"migration pointer" block naming the exact owning Issue and the exact
unmigrated remainder.

`docs/todo/README.md` also currently understates two of these
(`profit_plan_live_ladder.md` is listed as "A — active P1" with no Issue
reference; `fibo_zones.md` is listed as "P0 repository-ready / activation
pending" with no Issue reference) — this is not materially false (the
file never claimed Issue ownership), so no README correction is required
under the "materially false" bar, but it confirms these two lanes were
never migrated.

Gate results: R1 FAIL, R2 FAIL, R3 PASS, R4 FAIL, R5 FAIL, R6 FAIL, R7 FAIL.
See §11.

## 2. Complete tracked inventory

68 tracked files, each exactly once.

| Path | Disposition | Issue owner(s) | Ownership | Unique permanent content | Open scope | Exact next action |
|---|---|---|---|---|---|---|
| `docs/todo/2026-05-19_product_cockpit_strategy_bundle.md` | KEEP_TEMPORARILY | none | — | dashboard-label clarity narrative, already-superseded live status snapshot | dashboard semantics, auth-UX already-verified-token UX fix, systemd ownership cleanup, live-safety checklist | File a bounded Issue-migration batch (6B) splitting this 461-line bundle into discrete Issues; most content predates and is now covered by later label-registry work — re-verify before filing |
| `docs/todo/MIGRATION_FREEZE.md` | INFRASTRUCTURE | none | — | freeze rules/disposition taxonomy | none (governance doc) | Retire only after Gate R7 |
| `docs/todo/README.md` | INFRASTRUCTURE | none | — | frozen v2.23 lane snapshot, Rotation Pressure history, native SHORT baseline record | none (frozen index) | Retire only after Gate R7; migrate unique historical snapshot content to `docs/archive/` first |
| `docs/todo/account_provisioning.md` | ISSUE_OWNED | #217 (OPEN) | FULL | Batches 1-3 + Hotfix A/B completion evidence | none beyond #217 | Archive once #217 closes; historical batches move to `docs/archive/` |
| `docs/todo/adaptive_fib_execution_offset_v1.md` | ISSUE_OWNED | #224 (OPEN) | PARTIAL | selection/decision_gate/execution_planner/executor split design | Steps 3-5 (read-only preview integration, paper validation, decision-gated consumption) — no Issue | File follow-up Issue for steps 3-5 or fold into #224 scope explicitly |
| `docs/todo/backtest_capability_contract_v1.md` | ISSUE_OWNED | #218 (OPEN) | FULL | cross-lane capability-contract design | none beyond #218 | Canonicalize design to `docs/architecture/` once #218 closes; then archive |
| `docs/todo/breath_curve.md` | KEEP_TEMPORARILY | none | — | non-overlap/regime-difference research findings pointers | regime-difference diagnostic, older-history re-validation, optional 4h partial-cycle test, graduation rules (task-flagged residual, re-verified unowned) | File Issue for Breath Curve research continuation or explicit abandonment decision |
| `docs/todo/breathline_backtest_campaign_and_coin_calibration_v1.md` | ISSUE_OWNED | #225 (OPEN) | FULL | per-coin calibration campaign spec | none beyond #225 | Archive once #225 closes |
| `docs/todo/breathline_ui_phase_path_history_v1.md` | ISSUE_OWNED | #226 (OPEN) | FULL | UI phase/path-history spec | none beyond #226 | Archive once #226 closes |
| `docs/todo/claude_bundle_2_elliott_wave_daily_context_lane_v1.md` | ISSUE_OWNED | #219, #241 (both OPEN) | PARTIAL | full Elliott Wave design bundle (repo ground-truth section, labeler spec, ledger) | top-N/multi-symbol rollout, §3 trade hypotheses, §4 manual-approval path beyond Phase 1, §5 Phase 2/3 strategy coupling — no Issue | File follow-up Issue(s) for Phase 2/3 scope before archiving |
| `docs/todo/completed/README.md` | ARCHIVE | none | — | folder navigation only, one index line | none | Fold into `docs/archive/` index when `completed/` folder is retired |
| `docs/todo/completed/sector_taxonomy_database_seed_v1.md` | ARCHIVE | none | — | operational acceptance evidence (migration sha256, row counts, sector map) not duplicated elsewhere | none | Move to `docs/archive/` alongside canonical `docs/research/sector_taxonomy_database_seed_v1.md` |
| `docs/todo/credential_scope_and_manual_ladder_execution_boundary_v1.md` | ISSUE_OWNED | #206 (OPEN) | FULL | remaining-purpose framing (credential contract itself already canonicalized to `docs/architecture/account_credential_binding_contract_v1.md`) | none beyond #206 | Archive once #206 closes |
| `docs/todo/decision_gate_account_protections_v1.md` | ISSUE_OWNED | #227 (OPEN) | PARTIAL | account-protection contract design, lock model | "P2 — Minimal implementation" (runtime `decision_gate` implementation) — no Issue (task-flagged, re-verified still unowned) | File follow-up Issue for P2 runtime implementation |
| `docs/todo/deploy_runtime.md` | KEEP_TEMPORARILY | none | — | Odroid deployment history, ownership-correction chronology | market damage hysteresis, A+ DB integration, dashboard quality display, final ops cleanup checklist, several `open`/`blocked` sub-sections | File bounded Issue-migration batch splitting completed vs. open runtime items (task-flagged mixed file) |
| `docs/todo/dev_ops_hygiene.md` | KEEP_TEMPORARILY | none | — | Codex/DBeaver historical hygiene notes (mostly done) | P3 MariaDB export/backup procedure decision (task-flagged; re-verified — no canonical `docs/ops/` backup doc and no Issue found) | File a small Issue or write `docs/ops/mariadb_backup_procedure_v1.md`, then archive the done sections |
| `docs/todo/external_research/README.md` | KEEP_TEMPORARILY | none | — | folder navigation, split-ownership map | depends on child files below | Retire folder README once both child files below get dispositions |
| `docs/todo/external_research/cross_asset_public_data_and_instrument_registry_v1.md` | KEEP_TEMPORARILY | none | — | provider-acceptance criteria, neutral instrument identity contract | full P3 provider feasibility / instrument allowlist scope — no Issue | File Issue if this research is still desired, else park explicitly |
| `docs/todo/external_research/ffg_mega_run_target_scenarios_v1.md` | KEEP_TEMPORARILY | none | — | external target-scenario data (BASE/MEGA/BLOW_OFF) | scenario tracking itself is the open scope — no Issue | File Issue or explicitly park as external narrative context only |
| `docs/todo/external_research/ffg_universe_metadata_v1.md` | KEEP_TEMPORARILY | none | — | FFG universe metadata ownership contract | full P3 scope — no Issue | File Issue or park |
| `docs/todo/fibo_zones.md` | KEEP_TEMPORARILY | none | — | exit-profile research findings (LINK/XLM/SOL/XRP/HOT buckets), zone-context guardrails, native-map calibration observation protocol | self-described `active P0 repository-ready / activation pending` production cutover, plus P2/P3 exit-profile continuation, zone-context guardrails, leak-free zone/fib evaluator, native-map calibration replay, UI overlays, target-box normalization — **zero Issue coverage of any of it** (task-flagged; confirmed no owning Issue exists) | File Issue(s) for the P0 production-cutover item first (highest risk), then the P2/P3 research items |
| `docs/todo/golden_coin_cases_backtest_bundle_v1.md` | ISSUE_OWNED | #242 (OPEN) | PARTIAL | SXT emergency-rebuild regression record | priority items 7-8 (ladder-preview dry-run, manual-ladder-submit safety) — no Issue | File follow-up Issue for items 7-8 or fold into #202/#203 |
| `docs/todo/invalidation_confirmation_backtest_v1.md` | KEEP_TEMPORARILY | none | — | graded invalidation-confirmation state-machine hypothesis | entire file is queued/unimplemented research — no Issue | File Issue or park explicitly |
| `docs/todo/live_like_vertical_slice.md` | KEEP_TEMPORARILY | none | — | shadow-mode vertical-slice design, `MACRO_DIP_BUDGET_MODE_V1` concept | entire file open, `mode: shadow`, no Issue | File Issue or park explicitly |
| `docs/todo/manual_execution_ladder_future_readiness_backlog_v1.md` | ISSUE_OWNED | #202, #203, #206 (all OPEN) | PARTIAL | F1-F17 audit-finding cross-reference, P0 implementation evidence (73 new tests, 2026-07-25) | P2 "Multi-account/multi-venue readiness" and P3 "Usability and profile flexibility" sections — not explicitly claimed by #202/#203/#206 | Confirm with #202/#203/#206 scope owners whether P2/P3 are in-scope; if not, file follow-up Issues |
| `docs/todo/manual_execution_ladder_profiles_v1.md` | ISSUE_OWNED | #202 (OPEN) | FULL | ladder-profile UX/execution-tray design | none beyond #202 | Archive once #202 closes |
| `docs/todo/market_intelligence/README.md` | KEEP_TEMPORARILY | none | — | split-ownership map for 3 former umbrella TODOs (historical) | depends on child files below | Retire folder README once all child files below get dispositions |
| `docs/todo/market_intelligence/catalyst_engine_v1.md` | KEEP_TEMPORARILY | none | — | catalyst taxonomy design (future design / P3) | entire file — no Issue (distinct from #228, which owns `news_catalyst_monitor.md`'s narrower P0 schema task only) | File Issue if pursued, else park |
| `docs/todo/market_intelligence/composite_market_regime_v1.md` | KEEP_TEMPORARILY | none | — | composite-classifier design (future design / P3) | entire file — no Issue | File Issue or park |
| `docs/todo/market_intelligence/cross_asset_rotation_research_v1.md` | KEEP_TEMPORARILY | none | — | cross-asset rotation research design | entire file — no Issue | File Issue or park |
| `docs/todo/market_intelligence/ffg_rotation_classification_v1.md` | KEEP_TEMPORARILY | none | — | market-only FFG rotation classification ownership contract | entire file — no Issue | File Issue or park |
| `docs/todo/market_intelligence/macro_regime_engine_v1.md` | KEEP_TEMPORARILY | none | — | macro-regime engine design (future design / P3) | entire file — no Issue | File Issue or park |
| `docs/todo/market_intelligence/momentum_flow_scanner_research_v1.md` | KEEP_TEMPORARILY | none | — | scanner-research contract (split from former umbrella file) | entire file — no Issue | File Issue or park |
| `docs/todo/market_intelligence/narrative_engine_v1.md` | KEEP_TEMPORARILY | none | — | narrative-vs-sector taxonomy distinction design | entire file — no Issue | File Issue or park |
| `docs/todo/market_intelligence/sector_rotation_engine_v1.md` | KEEP_TEMPORARILY | none | — | Phase B accepted cohort record, runtime-activation prerequisites | writer→publisher production-chain activation (prepared, not installed/enabled) — no Issue | File Issue for runtime activation |
| `docs/todo/market_intelligence/sector_rotation_master_plan_v1.md` | KEEP_TEMPORARILY | none | — | full Phase A-D roadmap, canonical file for the initiative | Phase D not started; no Issue covers the roadmap as a whole (Phase B/C touched by #204 only for the dashboard sibling file) | File Issue for Phase D or explicitly close roadmap after Phase C acceptance |
| `docs/todo/martee_oracle_touch_semantics.md` | KEEP_TEMPORARILY | none | — | Martee Oracle touch-semantics field/state design | entire file, no migration pointer at all | File Issue or park |
| `docs/todo/multi_account_asset_foundation_backlog.md` | KEEP_TEMPORARILY | none | — | Phase 1-5 multi-account schema migration/backfill backlog, account-FK policy | all phases unchecked; not covered by #254/#262 (those own a separate "operator intent" layer, not the `venue_market`/`account_asset` schema backlog) — re-verified no overlap | File Issue for Phase 1 (schema migration is additive/safe) before further phases |
| `docs/todo/multi_horizon_fib_dashboard_backlog.md` | KEEP_TEMPORARILY | none | — | multi-horizon dashboard surface list | parked behind `multi_horizon_fib_backtest_v1` maturity — no Issue | Re-park explicitly or file Issue once backtest foundation lands |
| `docs/todo/native_short_invalidation_confirmation_backtest_v1.md` | ISSUE_OWNED | #220 (OPEN) | FULL | AAVE wick-breach observation, hypothesis framing | none beyond #220 | Archive once #220 closes |
| `docs/todo/native_short_map_level_status_v1.md` | ARCHIVE | none | — | none beyond `docs/architecture/native_short_map_level_status_contract_v1.md` (already canonical) | none (`done / parked`) | Archive; canonical contract already lives at the architecture doc |
| `docs/todo/native_short_multi_asset_rollout_contract_v1.md` | ISSUE_OWNED | #198, #199, #200 (all OPEN) | PARTIAL | 1089-line bootstrap-circularity resolution, scope-administration transaction design, full promotion audit trail (SOL/ETH/XRP) | bootstrap-manifest/administration-contract design detail and per-scope failure-isolation architecture exceed the narrow "promote ETH/promote XRP/failure isolation" Issue titles; task explicitly warns not to archive while operational acceptance still depends on it | Do not archive; re-scope or split into a canonical architecture doc plus the 3 Issues once ETH/XRP promotion completes |
| `docs/todo/native_short_runtime_owner_and_scope_status_v1.md` | KEEP_TEMPORARILY | none | — | writer-capability ownership registry pointer, `UNASSIGNED` lifecycle record | dedicated DB identity provisioning, filesystem reader-group provisioning, installed-host activation — no Issue found (task-flagged; confirmed unowned) | File Issue for host/identity provisioning acceptance |
| `docs/todo/news_catalyst_monitor.md` | ISSUE_OWNED | #228 (OPEN) | PARTIAL | catalyst schema/event-type/impact-model design | "Dashboard integration" and "idiosyncratic catalyst override" production consumption — no Issue | File follow-up Issue for dashboard consumption once #228 lands |
| `docs/todo/paper_candidate_contract.md` | KEEP_TEMPORARILY | none | — | research→decision_gate adapter design | entire file, future design, no Issue | File Issue or park |
| `docs/todo/parked_backlog.md` | KEEP_TEMPORARILY | none | — | A+ archive-handling resolved decisions (mostly done), PRO-narrative normalization backlog, `MACRO_DIP_BUDGET_MODE_V1` concept | P4 PRO-narrative backlog and P3 macro-dip concept remain open/unscheduled — no Issue | Split done sections to `docs/archive/`; file Issue only if backlog items are actually pursued |
| `docs/todo/position_rotation_preview.md` | ISSUE_OWNED | #230 (OPEN) | PARTIAL | implemented MVP cockpit record (Purpose, Target output, P1/P2 sections) | MVP cockpit itself is historical/unmigrated (not Issue-owned as live work) | Archive the MVP record once #230's research follow-up closes |
| `docs/todo/profit_plan_card_evidence_delta_visibility_v1.md` | ARCHIVE | none | — | P0-C evidence/delta implementation record | none (`done / parked`) | Archive |
| `docs/todo/profit_plan_dashboard_action_truth_and_breathline_demote_v1.md` | ARCHIVE | none | — | v2.22 action-truth guardrail implementation record (PR #78, #82) | none (`done / parked`) | Archive |
| `docs/todo/profit_plan_live_ladder.md` | KEEP_TEMPORARILY | none | — | full P0.0-P0.x sequence gates from canonical read-model to executor/Bitvavo mutation | self-described `active P1 / Synth v2.23`, the largest single unmigrated executable lane in the tree — **zero Issue coverage** (task-flagged high-risk downstream lane; confirmed no owning Issue exists anywhere) | Highest-priority follow-up: file Issue(s) for the P0.0-onward execution-ladder-repair sequence before any further work proceeds on this lane |
| `docs/todo/profit_plan_target_lifecycle_history_truth_v1.md` | ARCHIVE | none | — | IOST forensic-audit closure record (PR #105) | future monotonic-lifecycle hardening is explicitly evidence-gated (not current open scope; reopens only on new canonical evidence) | Archive; reopens via new TODO/Issue only on real evidence per its own reopen rule |
| `docs/todo/regime_research.md` | ISSUE_OWNED | #231 (OPEN) | PARTIAL | Phase 1 rerun/read task list, completed-baseline record | Phase 2 (symbol/breath profile, lead-lag replay, interaction-audit design) and Phase 3 (later classifier work) — no Issue | File follow-up Issue(s) for Phase 2/3 |
| `docs/todo/replay_parameter_study_harness_v1.md` | ISSUE_OWNED | #205 (OPEN) | FULL | replay-contract/provenance/adapter design | none beyond #205 | Archive once #205 closes |
| `docs/todo/reporting/README.md` | KEEP_TEMPORARILY | none | — | folder navigation, "planned migration candidates" list | depends on child files below | Retire folder README once all child files get dispositions |
| `docs/todo/reporting/ffg_rotation_radar_presentation_v1.md` | KEEP_TEMPORARILY | none | — | FFG presentation/account-overlay ownership contract | entire file — no Issue | File Issue or park |
| `docs/todo/reporting/ma_volume_stoplight_dashboard_v1.md` | KEEP_TEMPORARILY | none | — | MA/volume stoplight dashboard design | entire file — no Issue | File Issue or park |
| `docs/todo/reporting/profit_plan_opportunity_presentation_v1.md` | KEEP_TEMPORARILY | none | — | Actionable-PPP presentation ownership contract | entire file — no Issue (distinct from #233, which owns `ui_webview.md` items only) | File Issue or park |
| `docs/todo/sector_rotation_dashboard_v1.md` | ISSUE_OWNED | #204 (OPEN) | FULL | Phase C1 publisher implementation record | none beyond #204 | Archive once #204 closes |
| `docs/todo/sector_rotation_engine_v1.md` (root) | REMOVE | none | — | none — pure "Moved" redirect | none | Delete; repoint the 0 remaining live references (already point at `market_intelligence/sector_rotation_engine_v1.md` per Batch 5 repair) |
| `docs/todo/short_swing_linked_profile_freshness_and_disk_reliability_v1.md` | ISSUE_OWNED | #201 (OPEN) | FULL | Odroid disk-incident origin record, host-ownership correction chronology | none beyond #201 | Archive once #201 closes |
| `docs/todo/signal_matrix_dashboard.md` | KEEP_TEMPORARILY | none | — | transparent primitive-signal-inventory design (task-flagged "active current dashboard lane") | entire file, self-described "Active next dashboard lane for Synth v2.14" — no Issue (confirmed) | File Issue |
| `docs/todo/stale_1h_advice_freshness_truth_v1.md` | ISSUE_OWNED | #221 (OPEN) | FULL | freshness-truth observation record | none beyond #221 | Archive once #221 closes |
| `docs/todo/strategy_candidates.md` | ISSUE_OWNED | #232 (OPEN) | PARTIAL | 2 distinct `P1` sections + P2/P3 catalog | "P1 — Long-term regime classifier and dual-bucket research", "P2 — Horizon bucket design review", "P2 — `MACRO_DIP_BUDGET_MODE_V1`", "P2 — Swing pullback 168h research lead", "P3 — Legacy Synth v1 regime/strategy prior review" — none Issue-owned | File follow-up Issue(s) per remaining section |
| `docs/todo/synth_v2_development_roadmap_v1.md` | ARCHIVE | none | — | historical architecture-rule snapshot tied to stale commit `d7c57af` | none current (superseded by later architecture docs / AGENTS.md) | Archive; verify no unique rule is missing from current `AGENTS.md`/`docs/architecture/` before archiving |
| `docs/todo/todo_information_architecture_v1.md` | ARCHIVE | none | — | historical subfolder-plan record | none (self-declared `SUPERSEDED — no remaining authority`, already pending archive per its own text and per `github_issues_remaining_todo_inventory_v1.md`) | Archive exactly as the file itself requests |
| `docs/todo/ui_webview.md` | ISSUE_OWNED | #233 (OPEN) | PARTIAL | UI/chart framework stabilization notes, local-timestamp implementation record | "P2 — Stabilize UI/chart framework v1" and "Later UI v2 direction" — explicitly unmigrated per its own boundary block | File follow-up Issue(s) for remaining webview work |
| `docs/todo/watchlist_candidates.md` | ISSUE_OWNED | #234 (OPEN) | PARTIAL | watchlist intake boundary contract | other watchlist candidates/research beyond the KITE check — no Issue | File follow-up Issue(s) if watchlist intake continues to be used |
| `docs/todo/workflow_standard.md` | INFRASTRUCTURE | none | — | legacy P0-P4 / status-word vocabulary needed to read the frozen board | none (governance doc) | Retire only after Gate R7 |

## 3. Disposition totals

```text
total_tracked_todo_files=68
issue_owned=23
canonicalize=0
archive=8
remove=1
keep_temporarily=33
infrastructure=3
```

Reconciliation: 23 + 0 + 8 + 1 + 33 + 3 = 68. Matches inventory row count.

`issue_owned` breakdown: `issue_owned_full=11`, `issue_owned_partial=12`.

## 4. ISSUE_OWNED files

FULL (11) — exit path is archive once the owning Issue closes and any
unique design content is confirmed already canonical or copied to
`docs/archive/`:

- `account_provisioning.md` — #217 (OPEN)
- `backtest_capability_contract_v1.md` — #218 (OPEN)
- `breathline_backtest_campaign_and_coin_calibration_v1.md` — #225 (OPEN)
- `breathline_ui_phase_path_history_v1.md` — #226 (OPEN)
- `credential_scope_and_manual_ladder_execution_boundary_v1.md` — #206 (OPEN)
- `manual_execution_ladder_profiles_v1.md` — #202 (OPEN)
- `native_short_invalidation_confirmation_backtest_v1.md` — #220 (OPEN)
- `replay_parameter_study_harness_v1.md` — #205 (OPEN)
- `sector_rotation_dashboard_v1.md` — #204 (OPEN)
- `short_swing_linked_profile_freshness_and_disk_reliability_v1.md` — #201 (OPEN)
- `stale_1h_advice_freshness_truth_v1.md` — #221 (OPEN)

PARTIAL (12) — each is a retirement blocker until the uncovered scope
below is resolved (Issue-migrated or explicitly abandoned):

- `adaptive_fib_execution_offset_v1.md` — #224; uncovered: steps 3-5 (preview integration, paper validation, decision-gated consumption)
- `claude_bundle_2_elliott_wave_daily_context_lane_v1.md` — #219 + #241; uncovered: top-N rollout, §3 trade hypotheses, §4 manual-approval beyond Phase 1, §5 Phase 2/3
- `decision_gate_account_protections_v1.md` — #227; uncovered: P2 minimal runtime implementation
- `golden_coin_cases_backtest_bundle_v1.md` — #242; uncovered: priority items 7-8 (ladder-preview dry-run, manual-submit safety)
- `manual_execution_ladder_future_readiness_backlog_v1.md` — #202/#203/#206; uncovered: P2 multi-account/multi-venue, P3 usability/profile flexibility (pending confirmation)
- `native_short_multi_asset_rollout_contract_v1.md` — #198/#199/#200; uncovered: bootstrap-manifest/administration-contract architecture detail, per-scope failure-isolation design
- `news_catalyst_monitor.md` — #228; uncovered: dashboard integration / idiosyncratic catalyst override
- `position_rotation_preview.md` — #230; uncovered: the implemented MVP cockpit itself (historical, unmigrated)
- `regime_research.md` — #231; uncovered: Phase 2 (breath profile, lead-lag replay, interaction-audit design), Phase 3
- `strategy_candidates.md` — #232; uncovered: 5 of 7 sections (see inventory row)
- `ui_webview.md` — #233; uncovered: UI/chart framework stabilization, "Later UI v2 direction"
- `watchlist_candidates.md` — #234; uncovered: watchlist candidates/research beyond the one KITE check

## 5. CANONICALIZE files

None this batch. No file was found where the *entire* remaining content is
permanent knowledge cleanly separable from open scope and ready to move
without a bounded review of what stays behind. Several `KEEP_TEMPORARILY`
research-design files (all of `market_intelligence/*`, `fibo_zones.md`,
`decision_gate_account_protections_v1.md`'s design sections,
`sector_rotation_master_plan_v1.md`) are **future CANONICALIZE
candidates** once their open scope is Issue-migrated or explicitly
closed — see §12 follow-up batches.

## 6. ARCHIVE files

- `docs/todo/completed/README.md` — folder navigation only; fold into `docs/archive/` index.
- `docs/todo/completed/sector_taxonomy_database_seed_v1.md` — operational acceptance evidence (migration sha256, row counts) not duplicated elsewhere; move to `docs/archive/`.
- `docs/todo/native_short_map_level_status_v1.md` — `done/parked`; canonical contract already lives at `docs/architecture/native_short_map_level_status_contract_v1.md`.
- `docs/todo/profit_plan_card_evidence_delta_visibility_v1.md` — `done/parked` P0-C implementation record.
- `docs/todo/profit_plan_dashboard_action_truth_and_breathline_demote_v1.md` — `done/parked` v2.22 guardrail bundle (PR #78/#82).
- `docs/todo/profit_plan_target_lifecycle_history_truth_v1.md` — IOST defect contained/closed (PR #105); future hardening is evidence-gated, not current scope.
- `docs/todo/synth_v2_development_roadmap_v1.md` — stale snapshot tied to commit `d7c57af`; superseded by current architecture docs.
- `docs/todo/todo_information_architecture_v1.md` — self-declared `SUPERSEDED — no remaining authority`.

All eight retain unique historical/evidence value (PR numbers, exact
acceptance metrics, or forensic-audit conclusions) not fully duplicated
in `docs/archive/` or `docs/architecture/` today, so `REMOVE` is not
proven for any of them without a dedicated archive-move batch.

## 7. REMOVE files

- `docs/todo/sector_rotation_engine_v1.md` (root, 9 lines) — proof of zero
  unique content: the entire body is `# Moved — Sector Rotation Engine v1`
  plus a pointer to `docs/todo/market_intelligence/sector_rotation_engine_v1.md`
  and one boundary sentence ("This compatibility pointer owns no status,
  priority, or work."). Verified current owner:
  `docs/todo/market_intelligence/sector_rotation_engine_v1.md` exists and is
  substantive (Phase B accepted content, see inventory row). This is the
  same shape as the 5 files already removed in Batch 5 and was apparently
  missed by that batch. `gh issue list --search "sector_rotation_engine_v1"`
  returns no result naming the root-path file specifically.

## 8. KEEP_TEMPORARILY blockers

Grouped by exact blocker type (33 files total; full per-file blocker text
is in the §2 inventory table "Open scope" column):

**No Issue exists at all (24 files)** — `2026-05-19_product_cockpit_strategy_bundle.md`,
`breath_curve.md`, `deploy_runtime.md`, `dev_ops_hygiene.md`,
`external_research/README.md`, `external_research/cross_asset_public_data_and_instrument_registry_v1.md`,
`external_research/ffg_mega_run_target_scenarios_v1.md`, `external_research/ffg_universe_metadata_v1.md`,
`fibo_zones.md`, `invalidation_confirmation_backtest_v1.md`, `live_like_vertical_slice.md`,
`market_intelligence/README.md` + all 9 `market_intelligence/*.md` files,
`martee_oracle_touch_semantics.md`, `multi_account_asset_foundation_backlog.md`,
`multi_horizon_fib_dashboard_backlog.md`, `native_short_runtime_owner_and_scope_status_v1.md`,
`paper_candidate_contract.md`, `parked_backlog.md`, `profit_plan_live_ladder.md`,
`reporting/README.md`, `reporting/ffg_rotation_radar_presentation_v1.md`,
`reporting/ma_volume_stoplight_dashboard_v1.md`, `reporting/profit_plan_opportunity_presentation_v1.md`,
`signal_matrix_dashboard.md`.

Architectural owner for all of the above: whichever layer the file's own
boundary section names (`research`/`market_intelligence` → research
layer, `reporting/*` → reporting layer, `profit_plan_live_ladder.md` →
`decision_gate`/`execution_planner`/`executor` chain under explicit human
authorization). Recommended bounded follow-up: file one Issue per file
(or per closely related cluster, e.g. all `market_intelligence/*` P3
research files as one Issue) in a dedicated Batch 6B/6C migration pass —
this audit does not create Issues.

Two files carry additional weight and should be prioritized first:

- `profit_plan_live_ladder.md` — active P1 execution-repair lane touching
  `decision_gate`/`execution_planner`/`executor`/broker mutation. Highest
  risk of the entire residual set; must not be silently left unowned.
- `fibo_zones.md` — active P0 production-cutover lane (merge/deploy/timer
  activation for the canonical 4h FibNavigationMap writer).

## 9. Architecture violations / mixed-responsibility docs

No residual TODO instructs code that merges layers in violation of
`AGENTS.md`. Several documents narrate a multi-layer flow within one file
for design purposes (`profit_plan_live_ladder.md`,
`manual_execution_ladder_future_readiness_backlog_v1.md`,
`adaptive_fib_execution_offset_v1.md`,
`decision_gate_account_protections_v1.md`, `fibo_zones.md`) — this is
documentation practice, not an implemented shortcut, and each explicitly
states the correct sequencing (`selection_engine` → `decision_gate` →
`execution_planner` → `executor`) and repeats boundary/safety rules
(`broker_writes=0`, `order_submission=0`, `executor=none` where
applicable). No fix is required or performed in this batch.

## 10. Infrastructure dependency audit

`docs/todo/README.md`:

- **Current dependency**: `AGENTS.md` (canonical operating contract) —
  "`docs/todo/` is a frozen legacy board during controlled migration...
  Do not resume status, priority, or execution-order tracking in
  `docs/todo/README.md`; GitHub Issues own current status and priority."
  AGENTS.md operationally instructs agents to treat this file as the
  frozen index and governs how it may be edited. This is a live
  governance dependency, not mere provenance.
- **Historical provenance**: `docs/ops/sticky_dashboard_identity_target_columns_v1.md`,
  `docs/ops/market_rotation_pressure_runtime_owners_v1.md`,
  `docs/reviews/manual_execution_ladder_p0_round2_independent_review_20260726.md`,
  all `docs/development/docs_todo_*_v1.md` and `docs/development/github_issues_*_migration_v1.md`
  batch reports, `docs/archive/manual_ladder_dashboard.md` — these record
  what a prior batch did to `docs/todo/README.md`; they do not require it
  to keep existing.
- **Migration-only reference**: `docs/research/synth_v2_research_todo_index.md`
  (self-declared `superseded`, points readers at the frozen board and at
  `docs/development/github_issues_workflow.md`).

`docs/todo/MIGRATION_FREEZE.md`:

- **Current dependency**: `AGENTS.md` — "`docs/todo/` is a frozen legacy
  board during controlled migration. See `docs/todo/MIGRATION_FREEZE.md`."
  and the "Instruction File Ownership" table lists it as
  "legacy TODO board freeze and dispositions."
- **Historical/migration-only reference**: `docs/research/synth_v2_research_todo_index.md`,
  every `docs/development/docs_todo_*` and `docs/development/github_issues_*_migration_v1.md`
  batch report.

`docs/todo/workflow_standard.md`:

- **Safe-to-repoint-later**: no live inbound reference outside
  `docs/todo/README.md` and `docs/todo/MIGRATION_FREEZE.md` themselves was
  found. It is reachable only by navigation from the other two
  infrastructure files, not required directly by `AGENTS.md` or any
  runner/workflow doc.

## 11. Retirement gate matrix

| Gate | Requirement | Result | Blockers |
|---|---|---|---|
| R1 | `unowned_open_scope=0` | FAIL | 33 `KEEP_TEMPORARILY` files carry scope with no owning Issue (§8) |
| R2 | `partially_issue_owned_files=0` | FAIL | 12 `ISSUE_OWNED` files have uncovered residual scope (§4) |
| R3 | `files_needing_canonicalization=0` | PASS | 0 files classified `CANONICALIZE` this batch (§5) |
| R4 | `files_needing_archive=0`, `files_needing_remove=0` | FAIL | 8 files need `ARCHIVE` (§6), 1 file needs `REMOVE` (§7) |
| R5 | `live_dependencies_on_docs_todo_infrastructure=0` | FAIL | `AGENTS.md` currently requires `docs/todo/README.md` and `docs/todo/MIGRATION_FREEZE.md` as governance references, not just provenance (§10) |
| R6 | No current instruction/workflow/template/canonical doc requires the 3 infra files except as historical provenance | FAIL | Same `AGENTS.md` dependency as R5 |
| R7 | Only `README.md`, `MIGRATION_FREEZE.md`, `workflow_standard.md` remain tracked under `docs/todo/` | FAIL | 65 other tracked files remain (§2/§3) |

## 12. Follow-up batch plan

Minimum bounded sequence to reach retirement. Each batch is
Issue-migration or archive/remove execution only — no code, no runtime,
no live-trading changes.

**Batch 6B — File Issues for the two highest-risk unowned lanes**
Exact file set: `profit_plan_live_ladder.md`, `fibo_zones.md`. File one
Issue per lane (or a small number of scoped Issues per lane given their
size), add the standard migration-pointer boundary block to each file,
update `docs/todo/README.md`'s lane-index rows for A and (implicitly)
Fibo accordingly. Highest priority because both touch
`decision_gate`/`execution_planner`/`executor`/broker-adjacent scope.

**Batch 6C — File Issues for remaining unowned single-file lanes**
Exact file set: `2026-05-19_product_cockpit_strategy_bundle.md`,
`breath_curve.md`, `deploy_runtime.md`, `dev_ops_hygiene.md`,
`invalidation_confirmation_backtest_v1.md`, `live_like_vertical_slice.md`,
`martee_oracle_touch_semantics.md`, `multi_account_asset_foundation_backlog.md`,
`multi_horizon_fib_dashboard_backlog.md`,
`native_short_runtime_owner_and_scope_status_v1.md`,
`paper_candidate_contract.md`, `parked_backlog.md`, `signal_matrix_dashboard.md`.

**Batch 6D — File Issues (or one clustered Issue) for research-design folders**
Exact file set: `external_research/*` (3 content files + README),
`market_intelligence/*` (9 content files + README),
`reporting/*` (3 content files + README not already Issue-owned).
These are natural candidates for a small number of clustered Issues
(e.g. one per folder) rather than one Issue per file, since they share a
single P3 research-only boundary.

**Batch 6E — Close residual PARTIAL scope on the 12 `ISSUE_OWNED (PARTIAL)` files**
Exact file set: the 12 files in §4 "PARTIAL". For each, either extend the
existing Issue's scope explicitly (human decision, not this audit) or
file a narrow follow-up Issue for the uncovered section named in §4.

**Batch 6F — Archive/remove execution**
Exact file set: the 8 `ARCHIVE` files (§6) move to `docs/archive/` with
provenance headers preserved; the 1 `REMOVE` file (§7,
`docs/todo/sector_rotation_engine_v1.md` root) is deleted with its (zero)
live references already repaired. Update `docs/todo/README.md` lane-index
rows accordingly.

**Batch 6G — Infrastructure retirement**
Only after 6B-6F leave `docs/todo/` containing exactly `README.md`,
`MIGRATION_FREEZE.md`, `workflow_standard.md` (Gate R7 PASS) and after
`AGENTS.md` is rewritten to drop its operational dependency on
`docs/todo/README.md`/`MIGRATION_FREEZE.md` (Gate R5/R6 PASS): move any
remaining unique historical content (frozen v2.23 lane snapshot, Rotation
Pressure history, native SHORT baseline record) from `README.md` into
`docs/archive/`, then delete all three infrastructure files and the
`docs/todo/` directory, and update `AGENTS.md`'s "Work coordination"
section to remove the `docs/todo/` reference.

## 13. Final retirement action

Once Gates R1-R7 all pass, the final retirement PR must:

1. Confirm `docs/todo/` contains no tracked files (directory removed;
   Git does not track empty directories, so no placeholder is needed).
2. Confirm every permanent doc that was extracted lives under its
   canonical destination (`docs/architecture/`, `docs/research/`,
   `docs/ops/`, or `docs/archive/`).
3. Confirm all executable work exists only as GitHub Issues.
4. Update `AGENTS.md`'s "Project Structure & Module Organization" section
   to remove the `docs/todo/` reference and its "Documentation Rules"
   section to remove the `docs/todo/MIGRATION_FREEZE.md` / frozen-board
   rules, replacing them with a short historical note plus a pointer to
   the archived record.
5. Update `docs/development/github_issues_workflow.md` if it references
   `docs/todo/` as a migration source.
6. Run `git diff --check` and a repository-wide
   `rg -n "docs/todo/"` sweep to confirm zero remaining live references
   (historical mentions inside `docs/archive/` and
   `docs/development/docs_todo_*` batch reports are expected and fine).
7. State explicit safety markers: `code_changes=0`, `runtime_changes=0`,
   `database_changes=0`, `broker_writes=0`, `order_submissions=0`.

## 14. Acceptance evidence

```text
total_tracked_todo_files=68
inventory_rows=68
duplicate_inventory_rows=0
unclassified_files=0
issue_owned_full=11
issue_owned_partial=12
unowned_open_scope_files=33
files_needing_canonicalization=0
files_needing_archive=8
files_needing_remove=1
keep_temporarily_files=33
infrastructure_files=3
live_infrastructure_dependencies=1
broken_references=0
ambiguous_reference_dispositions=0
issues_created=0
issues_modified=0
files_moved=0
files_deleted=0
code_changes=0
test_changes=0
runtime_changes=0
database_changes=0
broker_writes=0
order_submissions=0
service_timer_changes=0
retirement_ready=0
```
