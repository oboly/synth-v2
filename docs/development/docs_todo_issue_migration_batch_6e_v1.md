# docs/todo Issue Migration — Batch 6E

agent=claude-code
role=implementer (Issue-ownership migration only, no product/runtime code changes)
model=claude-sonnet-5
effort=medium

## 1. Status

`COMPLETE`

All 12 files classified `ISSUE_OWNED (PARTIAL)` in Batch 6A now carry
`unmigrated executable scope: none`. Every residual section was resolved as
implemented, historical, superseded, explicitly deferred/contingent
(not yet ripe), reused under an existing Issue, or covered by a new narrow
follow-up Issue. No parallel manual-execution pipeline, reporting authority,
or research-to-execution shortcut was created.

## 2. Exact 12-file matrix

| Source | Batch 6A owner(s) | Old uncovered scope | Current disposition | Current Issue owner(s) | New Issue(s) | Unmigrated | Status |
|---|---|---|---|---|---|---|---|
| `adaptive_fib_execution_offset_v1.md` | #224 | Steps 3-5 (preview, paper validation, decision-gated consumption) | Steps 3-4 genuinely open; step 5 explicitly deferred/contingent | #224, #317 | #317 | none | migrated |
| `claude_bundle_2_elliott_wave_daily_context_lane_v1.md` | #219, #241 | top-N rollout, §3 hypotheses, §4 manual approval, §5 Phase 2/3 | All contingent on #241 Phase 1 findings; none independently executable yet | #219, #241 | none | none | migrated |
| `decision_gate_account_protections_v1.md` | #227 | P2 minimal runtime implementation | Genuinely open, no implementation exists yet | #227, #318 | #318 | none | migrated |
| `golden_coin_cases_backtest_bundle_v1.md` | #242 | Priority items 7-8 (ladder preview, manual submit safety) | Superseded — same scope as canonical #202/#203/#206 ladder lane | #242, #202, #203, #206 | none | none | migrated |
| `manual_execution_ladder_future_readiness_backlog_v1.md` | #202, #203, #206 | P2 items 13-15, P3 items 16-19 | Item 13 open (new); item 14 not required (NOT_REQUIRED_FOR_V1); item 15 covered by #206; items 16-19 governance-gated/contingent, not ripe | #202, #203, #206, #319 | #319 | none | migrated |
| `native_short_multi_asset_rollout_contract_v1.md` | #198, #199, #200 | Bootstrap-manifest/administration-contract detail, per-scope failure isolation | Implemented (#200 closed) and covered by #276 (evidence-driven bulk rollout); remaining body is historical/canonical record | #198, #199, #200 (closed), #276 | none | none | migrated |
| `news_catalyst_monitor.md` | #228 | Dashboard integration, idiosyncratic catalyst override | Dashboard integration genuinely open (new); "override" reclassified as market-only regime-classification concept under #300, not an execution authority | #228, #300, #321 | #321 | none | migrated |
| `position_rotation_preview.md` | #230 | MVP cockpit itself (historical, unmigrated) | Confirmed historical/implemented record only; no live executable scope | #230 | none | none | migrated |
| `regime_research.md` | #231 | Phase 2 (breath profile, lead-lag, interaction audit), Phase 3 | Phase 2 genuinely open and distinct from #282/#301/#305 (new); Phase 3 gated behind Phase 2 | #231, #322 | #322 | none | migrated |
| `strategy_candidates.md` | #232 | 5 sections (regime classifier/dual-bucket, horizon bucket review, MACRO_DIP_BUDGET_MODE_V1, swing pullback, legacy Synth v1 review) | Classifier build gated behind regime research; dual-bucket/super-bull backtest genuinely open (new); horizon bucket review reused under #243; MACRO_DIP_BUDGET_MODE_V1 and legacy review parked/no evidence; swing pullback genuinely open (new) | #232, #243, #323, #324 | #323, #324 | none | migrated |
| `ui_webview.md` | #233 | UI/chart framework stabilization, "Later UI v2 direction" | Stabilization genuinely open (new); "UI v2" is vague roadmap prose, not filed | #233, #325 | #325 | none | migrated |
| `watchlist_candidates.md` | #234 | Watchlist candidates/research beyond KITE | Not a standing bounded workflow; future candidates get individual Issues per existing #131 precedent | #234 | none | none | migrated |

12 rows, matching the 12-file target set exactly.

## 3. Existing Issue overlap

Full current Issue list surveyed (`gh issue list --state all --limit 400`):
87 issues (#131-#315) inspected at title/state level for overlap; the
following were individually opened and read in full for this batch's
decisions:

| Issue | Relevance | Classification |
|---|---|---|
| #131 | Watchlist/asset-universe intake precedent | full (closed, precedent only) |
| #198, #199 | Native SHORT ETH/XRP promotion | partial (still owns execution, not architecture detail) |
| #200 | Native SHORT per-scope failure isolation | full (CLOSED — implemented) |
| #201 | Linked-profile freshness (adjacent) | none (not applicable to this batch) |
| #202, #203, #206 | Manual execution ladder request/planner/credential | partial (each owns a distinct slice, all still open) |
| #219, #241 | Elliott Wave layering fix / Phase 1 labeler | partial (both still open, scope unchanged) |
| #224 | Adaptive Fib offset dataset/contract | partial (steps 1-2 only) |
| #227 | decision_gate account protections (P1 design) | partial (P1 only) |
| #228 | News catalyst monitor P0 schema | partial (P0 only) |
| #230 | Position rotation research follow-up | full for its own scope |
| #231 | Regime research Phase 1 | partial (Phase 1 only) |
| #232 | Strategy candidates P1 baseline audit | partial (explicitly excludes P2/P3) |
| #233 | UI coin-card scanability | partial (4 accepted items only) |
| #234 | Watchlist KITE checks | partial (remaining KITE task only) |
| #240 | Cockpit/wallet UI cleanup | none (different UI surface) |
| #242 | Golden regression fixtures | partial (priority items 1-5 only) |
| #243 | Multi-horizon strategy architecture contract | partial — reused for horizon-bucket design review |
| #248 | Tokenomics event intelligence | none (distinct from news catalyst) |
| #254 | Multi-account operator intent | none (adjacent, canonical execution chain reference only) |
| #268, #269 | decision_gate/execution_planner for Profit Plan ladder repair | none (different subsystem, not adaptive-fib or golden-coin scope) |
| #270, #271 | Fibo/zone research and UI overlays | none (different file, fibo_zones.md, out of Batch 6E scope) |
| #276 | Native SHORT evidence-driven bulk rollout | full — now owns the bootstrap-manifest/failure-isolation scope |
| #279, #280 | Strategy bucket config, cockpit access model | none (distinct from account_id/trading_account_id fragmentation) |
| #282 | Breath Curve validation | none (distinct from regime_research.md Phase 2) |
| #285 | First paper-track strategy candidate | none (distinct from strategy_candidates residuals) |
| #292 | NEAR shadow-chain reclaim thresholds | none (distinct; confirmed MACRO_DIP_BUDGET_MODE_V1 not covered anywhere) |
| #294 | Multi-account asset schema Phase 1 | none (distinct from account_id/trading_account_id fragmentation) |
| #300 | Catalyst taxonomy/event contract | full — supersedes narrow #228 for taxonomy scope |
| #301 | Composite market regime contract | none (distinct from regime_research.md Phase 2) |
| #305 | Macro regime engine | none (distinct from regime_research.md Phase 2) |
| #311 | FFG rotation radar presentation | none (unrelated dashboard surface) |
| #316 (PR) | 16-scope Native SHORT bootstrap approval batch | full — execution of already-owned #276/#198/#199 pattern |

## 4. New Issues created

| Issue | Source | Architecture owner | Residual scope |
|---|---|---|---|
| #317 | adaptive_fib_execution_offset_v1.md | research | Read-only preview integration + paper-execution validation (steps 3-4) |
| #318 | decision_gate_account_protections_v1.md | decision_gate | P2 minimal runtime protection implementation |
| #319 | manual_execution_ladder_future_readiness_backlog_v1.md | architecture/data-foundation | account_id vs trading_account_id fragmentation (F6) |
| #321 | news_catalyst_monitor.md | reporting | Read-only catalyst context presentation in Manual Ladder Dashboard |
| #322 | regime_research.md | research | Phase 2: symbol breath profile, BTC-to-alt lead-lag replay, regime interaction audit |
| #323 | strategy_candidates.md | research | Dual-bucket allocation and super-bull opportunity-cost backtests |
| #324 | strategy_candidates.md | research | 168h swing-pullback research-lead revalidation |
| #325 | ui_webview.md | reporting | UI/chart framework v1 stabilization/verification pass |

8 unique new Issues. No duplicate creation events; no `gh issue create` errors encountered.

## 5. Existing Issues reused

| Issue | Source | Scope |
|---|---|---|
| #224 | adaptive_fib_execution_offset_v1.md | Steps 1-2 (dataset, policy contract) |
| #219 | claude_bundle_2_elliott_wave_daily_context_lane_v1.md | §0 layering-hygiene fix |
| #241 | claude_bundle_2_elliott_wave_daily_context_lane_v1.md | §2 Phase 1 BTC-EUR labeler |
| #227 | decision_gate_account_protections_v1.md | P1 contract design |
| #242 | golden_coin_cases_backtest_bundle_v1.md | Priority items 1-5 |
| #202, #203, #206 | golden_coin_cases_backtest_bundle_v1.md, manual_execution_ladder_future_readiness_backlog_v1.md | Ladder request/planner/credential boundary (items 7-8, P0-P1, item 15) |
| #198, #199 | native_short_multi_asset_rollout_contract_v1.md | ETH/XRP production promotion |
| #200 | native_short_multi_asset_rollout_contract_v1.md | Per-scope failure isolation (closed/implemented) |
| #276 | native_short_multi_asset_rollout_contract_v1.md | Bootstrap-manifest/administration-contract, evidence-driven bulk rollout |
| #228 | news_catalyst_monitor.md | P0 schema/dry-runner |
| #300 | news_catalyst_monitor.md | Broader catalyst taxonomy/event contract |
| #230 | position_rotation_preview.md | Next Strategy Work / research follow-up |
| #231 | regime_research.md | Phase 1 reruns/discovery comparison |
| #232 | strategy_candidates.md | P1 current strategy audit follow-up |
| #243 | strategy_candidates.md | Horizon bucket design review (reused, not previously mapped to this file) |
| #234 | watchlist_candidates.md | Remaining KITE checks |
| #233 | ui_webview.md | Profit Plan coin-card scanability |

## 6. Implemented/historical/superseded residuals requiring no Issue

- `position_rotation_preview.md` — the MVP cockpit (Purpose, Target output,
  P1 sections, P2 better-candidate comparison, Completed research baseline)
  is a shipped-feature record, not live executable work. It was never
  Issue-owned as active scope and does not need to become one merely
  because Batch 6A's snapshot called it "uncovered."
- `native_short_multi_asset_rollout_contract_v1.md` — per-scope failure
  isolation is implemented and merged (#200 CLOSED); bootstrap-manifest
  generalization, ETH/XRP bootstrap approvals, and the 16-scope batch (PR
  #316) are implemented in the repository per the file's own closing
  section, proven by real (non-mocked) tests. The remaining 1000+ lines are
  a canonical historical/architecture-detail record, not unowned executable
  work. No production/runtime state was touched by this determination.
- `golden_coin_cases_backtest_bundle_v1.md` — priority items 7-8 are not
  distinct scope; they describe the same canonical manual-execution ladder
  capability already tracked by #202/#203/#206. Filing a separate Issue
  would create a second, competing ladder-submission pipeline description,
  which is explicitly forbidden.
- Vague "UI v2" work (`ui_webview.md`, "Later UI v2 direction") — a
  TradingView-style frontend rewrite with no bounded scope, acceptance
  criteria, or scheduling evidence. Not converted into an Issue.
- `MACRO_DIP_BUDGET_MODE_V1` (`strategy_candidates.md`) — re-verified via
  `gh issue list --search "MACRO_DIP_BUDGET"` (zero results). This concept
  recurs across at least three TODO files as a speculative "future
  portfolio lane, no runtime change" idea with no current evidence of
  active pursuit. Treated as parked/not-currently-desired, not executable
  scope.
- Generic future watchlist intake (`watchlist_candidates.md`) — "other
  watchlist candidates" is an open-ended placeholder, not a bounded
  workflow. Current repository practice (precedent: closed Issue #131)
  already files a narrow Issue per concrete candidate when one arises. No
  eternal umbrella backlog Issue was created.
- Legacy Synth v1 regime/strategy prior review (`strategy_candidates.md`,
  P3) — no current Issue, no repository activity on
  `docs/legacy_synth_v1_regime_strategy_priors.md` beyond its original
  authoring commits, no concrete current work evidenced.

## 7. Architecture safety

```text
parallel_manual_execution_pipeline_created=0
reporting_authority_created=0
research_direct_execution_path_created=0
account_state_in_selection_engine=0
issue_creation_grants_runtime_authorization=0
```

Verified explicitly:

- No new Issue duplicates or competes with the canonical operator-intent
  (#254) -> `decision_gate` -> `execution_planner` -> executor/credential
  (#206) manual-execution chain. #317, #318, #319, #321, #322, #323, #324,
  #325 each declare exactly one architecture owner (research: #317, #322,
  #323, #324; decision_gate: #318; architecture/data-foundation: #319;
  reporting: #321, #325) and none grants order/decision/execution
  authority.
- #321 (catalyst dashboard) is explicitly reporting-only, read-only, no
  broker writes, no decision authority — the "idiosyncratic catalyst
  override" naming in the source file was explicitly reclassified as a
  market-only regime-classification concept, not an execution override.
- #325 (UI stabilization) is explicitly a read-only verification pass on
  an existing debug chart app; no write/order path exists in that surface.
- No file edit granted runtime, deployment, or broker authorization. Issue
  creation is documentation/planning only.

## 8. R2 retirement impact

Batch 6A baseline: `issue_owned_partial=12`.

```text
batch_6e_target_files=12
fully_resolved_partial_files=12
remaining_partial_files=0
R2_status_after_batch_6e=PASS
```

This does not claim overall repository retirement readiness. Batch 6A's
other gates (R1, R4, R5, R6, R7) are untouched by this batch and remain
whatever their last-measured state was; R2 alone is verified PASS here.

## 9. Remaining known retirement blockers

- Batch 6C's intentional partial, `multi_account_asset_foundation_backlog.md`
  Phases 2-5, remains intentionally partial pending #294 review. Batch 6E
  did not touch this file. (Note: #294 — Phase 1 skeleton migration — is
  itself still OPEN as of this batch; Phases 2-5 remain correctly gated
  behind it.)
- Batch 6F (archive/remove execution for the 8 `ARCHIVE` + 1 `REMOVE` files
  from Batch 6A §6/§7) has not been performed.
- Batch 6G (infrastructure retirement of `README.md`, `MIGRATION_FREEZE.md`,
  `workflow_standard.md`) has not been performed and remains gated behind
  Batch 6A's R1/R5/R6/R7 blockers, none of which this batch addresses.
- R1 (`unowned_open_scope=0` across the 33 `KEEP_TEMPORARILY` files) is
  unaffected by this batch; those files are outside Batch 6E's scope.

## 10. Acceptance evidence

```text
source_files=12
inventory_rows=12
duplicate_inventory_rows=0
source_files_fully_migrated=12
source_files_partially_migrated=0
existing_issues_inspected=87
existing_issues_reused=20
new_issue_create_events=8
unique_new_issues_created=8
duplicate_issues_created=0
duplicate_issues_remaining_open=0
implemented_residuals=3
historical_residuals=2
superseded_residuals=1
abandoned_or_not_desired_residuals=4
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
