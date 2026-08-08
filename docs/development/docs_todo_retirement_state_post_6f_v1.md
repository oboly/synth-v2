# `docs/todo/` Retirement State — Post Batch 6F

agent=claude-code
model=claude-sonnet-5
effort=high (synthesis/judgment portions: cross-referencing ~90 Issues against
file claims, Native SHORT production-vs-approval distinction, multi-account
partial re-audit); medium/low for mechanical file/issue enumeration delegated
to subagents
role=auditor
thread=CLEAR

This is an **audit-only** document. No `docs/todo/` file was moved, archived,
deleted, or edited. No GitHub Issue was created or modified. No code, test,
runtime, database, broker, or timer changes were made.

Base: `origin/main` at `d86b332c9abf203b9590006033d8360ee62f60f6` (Batch 6F,
"Archive completed TODO records and remove redirect"), verified as the actual
`origin/main` HEAD at audit time (`git fetch origin main` confirmed no
advance).

This document supersedes
`docs/development/docs_todo_retirement_readiness_batch_6a_v1.md` for forward
planning. Batch 6A is preserved unedited as historical evidence.

## 1. Executive result

```text
RETIREMENT_READY_FOR_6G=0
tracked_todo_files=60
non_infrastructure_todo_files=57
infrastructure_files=3
```

Batch 6G (infrastructure retirement) **cannot** safely begin yet. This is not
a close call: 48 of 57 non-infrastructure files are `ISSUE_OWNED_OPEN` —
correctly and legitimately so, because their owning Issues are genuinely
still open (normal engineering backlog, not a documentation defect). Beyond
that expected majority, this audit found:

- **1 genuinely unowned file** (`state_driven_runtime_orchestration_v1.md`,
  `UNOWNED_EXECUTABLE_SCOPE`) — no Issue, no migration pointer, describes a
  concrete next step.
- **1 intentional partial** (`multi_account_asset_foundation_backlog.md`,
  Phase 1 → `#294` still OPEN, Phases 2–5 still deliberately unfiled — matches
  Batch 6C's original design, unchanged).
- **1 stale/ambiguous navigation file** (`external_research/README.md`).
- **1 factually stale REMOVE candidate** (`reporting/README.md` — its
  "Planned migration candidates" list names 5 files that are already fully
  migrated).
- **5 files now archive-ready** (`HISTORICAL_ARCHIVE_READY`, none processed
  by Batch 6F) — R4 reopens.
- **2 genuine live *code/test* dependencies** on specific non-infrastructure
  `docs/todo/` files (not the infra trio) that must be repointed before those
  exact files can ever be deleted.
- **Live governance dependencies** on the infrastructure trio remain in
  `AGENTS.md`, `docs/development/github_issues_workflow.md`, and
  `docs/research/synth_v2_research_todo_index.md` — expected, and exactly
  what Batch 6G itself must retire.

None of this is a crisis. It is the normal, healthy state of a board that is
~84% Issue-owned. But per the completion guard, `RETIREMENT_READY_FOR_6G=1`
cannot be claimed while any non-infrastructure file lacks a proven-safe
disposition, and 57 non-infra files still exist.

## 2. Exact current inventory

One row per tracked file (`git ls-files 'docs/todo/**'`, 60 files, each
appears exactly once).

| Path | Current disposition | Issue owner(s) | Issue state | Executable scope | Unique permanent content | Live dependency | Exact next action |
|---|---|---|---|---|---|---|---|
| `docs/todo/README.md` | INFRASTRUCTURE | — | — | N/A (frozen index) | Yes — frozen lane snapshot, PR completion chains | LIVE_GOVERNANCE (AGENTS.md, github_issues_workflow.md, research index) | Retire as part of 6G governance repoint |
| `docs/todo/MIGRATION_FREEZE.md` | INFRASTRUCTURE | — | — | N/A | Yes — disposition taxonomy | LIVE_GOVERNANCE (AGENTS.md) | Retire as part of 6G governance repoint |
| `docs/todo/workflow_standard.md` | INFRASTRUCTURE | — | — | N/A | Yes — legacy P0-P4 vocabulary needed to read remaining frozen files | LIVE_GOVERNANCE (AGENTS.md) | Retire only after all remaining files stop needing legacy vocabulary |
| `docs/todo/2026-05-19_product_cockpit_strategy_bundle.md` | ISSUE_OWNED_OPEN | #277,#278,#279,#280,#281,#288 | all OPEN | Yes | Some | none | Wait on Issues |
| `docs/todo/account_provisioning.md` | ISSUE_OWNED_OPEN | #217 | OPEN | Yes (Batch 4 items) | Yes (Batches 1-3 history) | none | Wait on #217 |
| `docs/todo/adaptive_fib_execution_offset_v1.md` | ISSUE_OWNED_OPEN | #224, #317 | both OPEN | Yes (steps 1-4) | Yes (layer-split design) | none | Wait on Issues |
| `docs/todo/backtest_capability_contract_v1.md` | ISSUE_OWNED_OPEN | #218 | OPEN | Yes | Yes (schema/enum contract) | none | Wait on #218 |
| `docs/todo/breath_curve.md` | ISSUE_OWNED_OPEN | #282 | OPEN | Yes | Some | none | Wait on #282; #283 confirmed a duplicate-creation retry, correctly CLOSED pointing to #282 |
| `docs/todo/breathline_backtest_campaign_and_coin_calibration_v1.md` | ISSUE_OWNED_OPEN | #225 | OPEN | Yes | Yes (artifact spec) | none | Wait on #225 |
| `docs/todo/breathline_ui_phase_path_history_v1.md` | ISSUE_OWNED_OPEN | #226 | OPEN | Yes | Yes (large UI/read-model spec) | none | Canonicalize spec once #226 closes |
| `docs/todo/claude_bundle_2_elliott_wave_daily_context_lane_v1.md` | ISSUE_OWNED_OPEN | #219, #241 | both OPEN | §0/§2 yes; §3-5/top-N intentionally deferred pending #241 findings | Yes (labeler spec) | none | Wait on #219/#241 |
| `docs/todo/credential_scope_and_manual_ladder_execution_boundary_v1.md` | ISSUE_OWNED_OPEN | #206 | OPEN | Yes (10 tasks) | Some | none | Wait on #206 |
| `docs/todo/decision_gate_account_protections_v1.md` | ISSUE_OWNED_OPEN | #227, #318 | both OPEN | Yes | Yes (protection taxonomy) | none | Wait on Issues |
| `docs/todo/deploy_runtime.md` | ISSUE_OWNED_OPEN | #284,#285,#286,#289 | all OPEN | Yes | Yes (ops history) | none | Wait on Issues; low-numbered `#100/#101/#124/#201` refs verified as historical PRs, not open-Issue claims |
| `docs/todo/dev_ops_hygiene.md` | ISSUE_OWNED_OPEN | #290 | OPEN | Yes | No | none | Wait on #290 |
| `docs/todo/external_research/README.md` | AMBIGUOUS | none | — | No independent scope | Minimal, restates AGENTS.md | none | Needs a reviewed disposition (index-only vs. REMOVE) |
| `docs/todo/external_research/cross_asset_public_data_and_instrument_registry_v1.md` | ISSUE_OWNED_OPEN | #302 | OPEN | Yes | Yes (instrument identity contract) | none | Wait on #302 |
| `docs/todo/external_research/ffg_mega_run_target_scenarios_v1.md` | HISTORICAL_ARCHIVE_READY | none (deliberately unfiled) | — | No | Yes (scenario data) | none | Archive-ready |
| `docs/todo/external_research/ffg_universe_metadata_v1.md` | HISTORICAL_ARCHIVE_READY | none (superseded by `docs/research/ffg_research_universe_v1.md`) | — | No | Some | none | Archive-ready |
| `docs/todo/fibo_zones.md` | ISSUE_OWNED_OPEN | #249, #270, #271 (`#171`/`#173` are merged PRs, not Issues) | all OPEN | Yes | Yes (exit-profile findings) | none | Wait on Issues |
| `docs/todo/golden_coin_cases_backtest_bundle_v1.md` | ISSUE_OWNED_OPEN | #242 (items 1-5); #202/#203/#206 (items 7-8) | all OPEN | Yes | Yes (7 golden-case records) | none | Wait on Issues |
| `docs/todo/invalidation_confirmation_backtest_v1.md` | ISSUE_OWNED_OPEN | #291 | OPEN | Yes | Some | none | Wait on #291 |
| `docs/todo/live_like_vertical_slice.md` | ISSUE_OWNED_OPEN | #292 | OPEN | Yes (Open Design Questions) | Yes (parked concept note) | none | Wait on #292 |
| `docs/todo/manual_execution_ladder_future_readiness_backlog_v1.md` | ISSUE_OWNED_OPEN | #202,#203,#206 (P0/P1); #319 (item 13) | all OPEN | Yes; items 14/16-19 correctly gated/no-Issue-yet | Yes (F1-F17 rationale) | none | Wait on Issues |
| `docs/todo/manual_execution_ladder_profiles_v1.md` | ISSUE_OWNED_OPEN | #202 | OPEN | Yes | Yes (4-table schema design) | none | Canonicalize once #202 closes |
| `docs/todo/market_intelligence/README.md` | HISTORICAL_ARCHIVE_READY | none (index) | — | No | No independent value beyond index | none | Archive-ready as index, or retain as navigation aid |
| `docs/todo/market_intelligence/catalyst_engine_v1.md` | ISSUE_OWNED_OPEN | #228, #300 | both OPEN | Yes | Yes (taxonomy) | none | Wait on Issues |
| `docs/todo/market_intelligence/composite_market_regime_v1.md` | ISSUE_OWNED_OPEN | #301 | OPEN | Yes | Yes | none | Wait on #301 |
| `docs/todo/market_intelligence/cross_asset_rotation_research_v1.md` | ISSUE_OWNED_OPEN | #303 (+ #302 dependency) | both OPEN | Yes | Yes | none | Wait on Issues |
| `docs/todo/market_intelligence/ffg_rotation_classification_v1.md` | ISSUE_OWNED_OPEN | #304 | OPEN | Yes | Yes | none | Wait on #304 |
| `docs/todo/market_intelligence/macro_regime_engine_v1.md` | ISSUE_OWNED_OPEN | #305 | OPEN | Yes | Yes | none | Wait on #305 |
| `docs/todo/market_intelligence/momentum_flow_scanner_research_v1.md` | ISSUE_OWNED_OPEN | #306 (+ #277 adjacent) | both OPEN | Yes | Yes | none | Wait on Issues |
| `docs/todo/market_intelligence/narrative_engine_v1.md` | ISSUE_OWNED_OPEN | #307 | OPEN | Yes | Yes | none | Wait on #307 |
| `docs/todo/market_intelligence/sector_rotation_engine_v1.md` | ISSUE_OWNED_OPEN | Phase C → #204 | OPEN | Yes (Phase C) | Yes, strong archive/canonical candidate once #204 closes | **LIVE_OPERATIONAL** — `tests/test_sector_taxonomy_import_v1.py::test_sector_rotation_public_contract_uses_participation_terms` reads this file's content directly | Wait on #204; test dependency must be repointed before this file can ever move |
| `docs/todo/market_intelligence/sector_rotation_master_plan_v1.md` | ISSUE_OWNED_OPEN | Phase B2 → #309; Phase C → #204 | both OPEN | Yes | Yes, strong canonical-doc candidate | none | Wait on Issues |
| `docs/todo/martee_oracle_touch_semantics.md` | ISSUE_OWNED_OPEN | #293 | OPEN | Yes | Yes | none | Wait on #293 |
| `docs/todo/multi_account_asset_foundation_backlog.md` | PARTIAL_ISSUE_OWNERSHIP (intentional, unchanged since Batch 6C) | Phase 1 → #294; Phases 2-5 deliberately unfiled | #294 OPEN, no migration applied | Phase 1 yes; Phases 2-5 explicitly contingent | Yes (5-phase migration design) | none | Re-file Phases 2-5 only after #294 lands and is reviewed |
| `docs/todo/multi_horizon_fib_dashboard_backlog.md` | ISSUE_OWNED_OPEN | #295 | OPEN | Yes (blocked/gated) | Yes | none | Wait on #295 |
| `docs/todo/native_short_invalidation_confirmation_backtest_v1.md` | ISSUE_OWNED_OPEN | #220 | OPEN | Yes | Yes | none | Wait on #220 |
| `docs/todo/native_short_multi_asset_rollout_contract_v1.md` | ISSUE_OWNED_OPEN | #198, #199 (production promotion); #200 (CLOSED, isolation, implemented); #276 (bulk rollout) | #198/#199/#276 OPEN, #200 CLOSED | Yes — ETH/XRP production promotion execution remains | Yes, very large (writer-provenance contract, blocker matrix, bootstrap-circularity resolution) — strong canonicalization candidate | none | See §4 Native SHORT detail below |
| `docs/todo/native_short_runtime_owner_and_scope_status_v1.md` | ISSUE_OWNED_OPEN | #296 (installed-host activation); #201 (cross-ref, not duplicated) | both OPEN | Yes (installed-host DB identity activation) | Yes (ownership registry) | none | Wait on #296/#201 |
| `docs/todo/news_catalyst_monitor.md` | ISSUE_OWNED_OPEN | #228, #300, #321 | all OPEN | Yes | Yes | none | Wait on Issues |
| `docs/todo/paper_candidate_contract.md` | HISTORICAL_ARCHIVE_READY | none (superseded by merged PR #257 → `docs/architecture/strategy_proposal_contract_v1.md`) | — | No | Low | none | Archive-ready (borderline REMOVE) |
| `docs/todo/parked_backlog.md` | HISTORICAL_ARCHIVE_READY | none (all 4 sections explicitly parked, no current trigger) | — | No | Yes (A+ archive disposition, MACRO_DIP concept) | none | Archive-ready |
| `docs/todo/position_rotation_preview.md` | ISSUE_OWNED_OPEN | #230 | OPEN | Yes (Next Strategy Work) | Yes (MVP spec, historical) | none | Wait on #230 |
| `docs/todo/profit_plan_live_ladder.md` | ISSUE_OWNED_OPEN | #267,#268,#269,#273,#254,#202,#203,#206,#201 | all OPEN | Yes (large P0.0-P0.8 lane) | Yes, substantial | none | Canonicalize once gates close; wait on Issues |
| `docs/todo/regime_research.md` | ISSUE_OWNED_OPEN | #231, #322 | both OPEN | Yes | Yes | none | Wait on Issues |
| `docs/todo/replay_parameter_study_harness_v1.md` | ISSUE_OWNED_OPEN | #205 | OPEN | Yes (PR1-PR5 contract) | Yes | **LIVE_OPERATIONAL** — `src/market_data/native_short_repository_source_identity_v1.py:CONTROLLED_CHAIN_4H_UNTRACKED_PATH`, `scripts/run_chain_4h.sh`, and 2 tests hardcode this exact path as the production clean-checkout allowlist exception | Wait on #205; repoint the allowlist constant before this file can ever be deleted (see §8) |
| `docs/todo/reporting/README.md` | REMOVE | none (index only) | — | No | No | none | Its "Planned migration candidates" list is factually stale — all 5 named files (`sector_rotation_dashboard_v1.md`, `ui_webview.md`, `signal_matrix_dashboard.md`, `multi_horizon_fib_dashboard_backlog.md`, `position_rotation_preview.md`) are already fully migrated. Needs correction or removal, not left as-is. |
| `docs/todo/reporting/ffg_rotation_radar_presentation_v1.md` | ISSUE_OWNED_OPEN | #311 | OPEN | Yes | Yes | none | Wait on #311 |
| `docs/todo/reporting/ma_volume_stoplight_dashboard_v1.md` | ISSUE_OWNED_OPEN | #310, #315 | both OPEN | Yes | Yes | none | Wait on Issues |
| `docs/todo/reporting/profit_plan_opportunity_presentation_v1.md` | ISSUE_OWNED_OPEN | #233, #313 (open); #256 (closed, folded) | mixed | Yes (via #233/#313) | Yes | none | Wait on Issues |
| `docs/todo/sector_rotation_dashboard_v1.md` | ISSUE_OWNED_OPEN | #204 | OPEN | Yes (asset cards, drilldown, macro views) | Yes, substantial | **LIVE_OPERATIONAL** — same `tests/test_sector_taxonomy_import_v1.py` test reads this file's content (see above) | Wait on #204; same test-dependency remediation needed |
| `docs/todo/short_swing_linked_profile_freshness_and_disk_reliability_v1.md` | ISSUE_OWNED_OPEN | #201 | OPEN (P2-C multi-cycle acceptance explicitly open) | Yes | Yes, very substantial (incident/PR A/PR B history) | none | Wait on #201; low PR numbers (#54,#72,#87,#100,#101,#106,#112,#113,#115,#117,#151) confirmed historical merged PRs, not Issue claims |
| `docs/todo/signal_matrix_dashboard.md` | ISSUE_OWNED_OPEN | #297 | OPEN | Yes | Yes | none | Wait on #297 |
| `docs/todo/stale_1h_advice_freshness_truth_v1.md` | ISSUE_OWNED_OPEN | #221 | OPEN | Yes | Yes | none | Wait on #221 |
| `docs/todo/state_driven_runtime_orchestration_v1.md` | **UNOWNED_EXECUTABLE_SCOPE** | none | — | Yes — describes a concrete next step ("perform a repository/git-history audit... then propose implementation issues") | Yes, substantial (dispatcher/requirement architecture) | none | No migration section, no `#NNN` reference at all; confirmed via `gh issue list --search` no matching Issue exists. Needs an owning Issue filed (not done in this audit — reporting only) or explicit re-classification if genuinely non-executable |
| `docs/todo/strategy_candidates.md` | ISSUE_OWNED_OPEN | #232,#243,#323,#324 | all OPEN | Yes | Yes | none | Wait on Issues |
| `docs/todo/ui_webview.md` | ISSUE_OWNED_OPEN | #233, #325 | both OPEN | Yes | Yes | none | Wait on Issues |
| `docs/todo/watchlist_candidates.md` | ISSUE_OWNED_OPEN | #234 | OPEN | Yes (KITE check) | Yes (intake precedent) | none | Wait on #234 |

## 3. Disposition totals

```text
infrastructure=3
issue_owned_open=48
issue_owned_closed_archive_ready=0
partial_issue_ownership=1
unowned_executable_scope=1
historical_archive_ready=5
remove=1
ambiguous=1
```

Reconciliation: 3+48+0+1+1+5+1+1 = 60 = `tracked_todo_files`. ✓

## 4. Issue ownership validation

Every referenced Issue was checked via `gh issue view`/`gh issue list --state
all` against its actual title, state, and (for ambiguous cases) body — not
trusted from file text alone. No file was found citing a closed Issue as open
or vice versa. `#282`/`#283` (`breath_curve.md`) were the one pair worth
double-checking given near-identical titles: `#283` is a confirmed
duplicate-creation retry from Batch 6C, correctly `CLOSED` with `#282` named
as canonical owner — no error.

Several low `#NN`/`#1NN` numbers referenced across multiple files (`#54,
#71, #72, #74, #76, #77, #79, #81, #87, #92, #100, #101, #105, #106, #112,
#113, #114, #115, #117, #118, #124, #151, #165, #171, #173, #207, #210,
#212, #214, #223, #255, #256(mixed—see below), #257, #262, #266, #274,
#287, #298`) were verified via `gh api .../issues/<n>` — the low ones
(≤124, plus #151/#165/#171/#173/#274/#287) are confirmed **merged PRs**,
correctly used as historical implementation evidence, never as claimed
open-Issue ownership. `#207/#210/#212/#214/#223/#255/#262/#266/#298` are
confirmed real Issues, all `CLOSED`, correctly cited only as closed
implementation history where referenced.

### Native SHORT — `#198 #199 #200 #201 #276 #296`, PR `#316`, and subsequent work

Confirmed by direct commit-ancestry check (`git merge-base --is-ancestor`):

- PR `#316` ("Approve 16 readiness-qualified Native SHORT scopes as a bounded
  batch", merge commit `cdfcc918`) **is** an ancestor of current `origin/main`
  HEAD (`d86b332c`).
- Its correction commit `b7ea7765` ("Fix overstated audit evidence in the 16
  batch approval docs") **is also** an ancestor of HEAD. Both are merged and
  reflected in the audited state — this resolves the primary checkout's dirty
  state noted in the dispatch (that checkout was mid-work on an already-merged
  branch).
- `#198`/`#199` (OPEN) own ETH/XRP **production promotion execution**
  specifically. `#200` (CLOSED) owned per-scope failure isolation, implemented
  and merged (PR `#274`). `#276` (OPEN) owns making the remaining rollout
  blockers evidence-driven and generalizing the bootstrap manifest — the
  16-scope batch approval (PR `#316`) is execution of this already-owned
  `#276`/`#198`/`#199` pattern, not new uncovered scope.
- `#296` (OPEN) owns `native_short_4h_chain` DB writer identity / installed-host
  activation — distinct from and does not overlap `#276`/`#198`/`#199`.
- **Repository approval vs. production activation, distinguished:** SOL is
  promoted and production-accepted. ETH, XRP, and the 16-symbol batch are
  **administratively approved** (bootstrap-manifest entries exist,
  `PROMOTE_SCOPE` would pass the bootstrap-evidence check) but **have not been
  executed against production** — `native_short_multi_asset_rollout_contract_v1.md`
  states explicitly: "no scope is currently authorized [as executed], and even
  a fully authorized scope would still be blocked by two other unconditional
  blockers" and the rollout orchestrator's checked-in `APPROVED_ROLLOUT_UNIVERSE_V1`
  requires a **separate reviewed repository change** per symbol before any
  write. This audit does not infer live runtime authorization from repository
  approval, per the task's explicit instruction.
- Conclusion: `native_short_multi_asset_rollout_contract_v1.md` remains
  correctly `ISSUE_OWNED_OPEN` (owners `#198`/`#199`/`#276` open, `#200`
  closed) — no residual uncovered scope, matching the file's own Batch 6E
  re-audit note, independently re-verified here against current `main` and
  current Issue state rather than trusted.

### Multi-account asset backlog (`#294`) — critical intentional partial

- `#294` ("Run Phase 1 multi-account asset schema skeleton migration and
  backfill") is confirmed **OPEN** (`closedAt: null`).
- The additive migration file `db/migrations/20260603_multi_account_asset_foundation_v1.sql`
  exists in the repository, and `docs/ops/bitvavo_market_sync_v1.md` /
  `docs/ops/multi_account_wallet_refresh_v1.md` both document it as a
  **prerequisite/dependency**, not as applied — no in-repo evidence states the
  migration has actually been run against production. (This audit did not
  query the live database — that is out of scope for a docs-only audit — so
  "applied" status is genuinely unresolved from repository evidence alone and
  is reported as such rather than guessed.)
- `gh issue list --search "multi_account_asset OR venue_market OR
  account_asset"` returns only `#294` and `#319` (identifier-fragmentation
  cleanup, unrelated to Phases 2-5) — **no newer Issue has claimed Phases
  2-5**.
- Phases 2-5 remain genuinely contingent (column-drop migrations across
  3/12/19 call sites, Hugo account onboarding) — not yet executable, exactly
  as Batch 6C designed. No Phase 2-5 Issues were created by this audit, per
  instruction.
- Conclusion: the file remains correctly `PARTIAL_ISSUE_OWNERSHIP`, unchanged
  in substance since Batch 6C. This is the one intentional, reviewed partial
  and does not indicate a process failure.

## 5. Newly archive-ready files (not processed by Batch 6F)

Batch 6F only processed the 8 files + 1 redirect identified in the original
Batch 6A audit. Re-auditing against current content found **5 files now
archive-ready** that were not in that set:

```text
docs/todo/external_research/ffg_mega_run_target_scenarios_v1.md
docs/todo/external_research/ffg_universe_metadata_v1.md
docs/todo/market_intelligence/README.md            (navigation index; low-priority archive)
docs/todo/paper_candidate_contract.md              (superseded by PR #257 -> canonical doc)
docs/todo/parked_backlog.md
```

Plus **1 file needing a REMOVE/correction disposition** that was not
previously flagged:

```text
docs/todo/reporting/README.md   (stale "planned migration candidates" list)
```

R4 (`files_needing_archive=0`, `files_needing_remove=0`) therefore **FAILs**
again in this cycle, exactly as the Batch 6F manifest itself warned it might.

## 6. Remaining partial/unowned scope

```text
partial_issue_ownership=1   (multi_account_asset_foundation_backlog.md — intentional, documented in §4)
unowned_executable_scope=1  (state_driven_runtime_orchestration_v1.md — NOT intentional)
```

`state_driven_runtime_orchestration_v1.md` is the one genuine process gap
found in this audit. It has no `## GitHub Issue migration` section, no
`#NNN` reference anywhere, and its content ends with a concrete proposed next
action (perform a repository/git-history audit, then propose implementation
Issues). A repository-wide Issue search
(`gh issue list --search "state driven runtime orchestration"` and related
terms) found no matching Issue. This audit does **not** file an Issue for it
(that would be scope creep for an audit-only task) — it is reported as the
exact blocker it is.

## 7. Canonicalization blockers

The following files carry substantial unique architecture/design content that
is not yet duplicated in `docs/architecture/`, `docs/research/`, or
`docs/ops/`, and should be canonicalized before eventual archive (once their
owning Issues close) so the knowledge is not lost when the TODO file is
retired:

```text
docs/todo/native_short_multi_asset_rollout_contract_v1.md   (writer-provenance contract, global-blocker matrix, bootstrap-circularity resolution — ~1100 lines, largest single candidate)
docs/todo/profit_plan_live_ladder.md                         (P0.0-P0.8 contract specs)
docs/todo/manual_execution_ladder_profiles_v1.md             (4-table schema/sizing design)
docs/todo/short_swing_linked_profile_freshness_and_disk_reliability_v1.md (incident/PR A/PR B operational history)
docs/todo/market_intelligence/sector_rotation_engine_v1.md   (rotation-score formula, snapshot schema, acceptance evidence)
docs/todo/market_intelligence/sector_rotation_master_plan_v1.md (program roadmap/dependency boundaries)
docs/todo/breathline_ui_phase_path_history_v1.md             (UI/read-model spec)
```

None of these block Batch 6G by themselves — they are legitimately
`ISSUE_OWNED_OPEN` and can be canonicalized at archive time once their Issues
close, per the task's own "does not need to wait for Issue close if not
depended on" guidance (these files' content is actively read by their
authors during open implementation work, so moving them now would be
premature). `files_needing_canonicalization` is reported as a forward-looking
list, not a current blocking count, since none of these Issues are closed yet.

## 8. Infrastructure dependency audit

**`AGENTS.md`** — lines 270, 585, 593-594, 598, 600, 616 directly name
`docs/todo/`, `docs/todo/README.md`, and `docs/todo/MIGRATION_FREEZE.md` as
canonical governance (Project Structure, Documentation Rules, Instruction
File Ownership sections). **LIVE_GOVERNANCE.**

**`docs/development/github_issues_workflow.md`** — line 22 lists `docs/todo/`
in its canonical-locations table ("Frozen legacy board during controlled
migration only"); line 146 states a migration rule ("Do not mass-convert
`docs/todo/` files into Issues"). **LIVE_GOVERNANCE.**

**`docs/research/synth_v2_research_todo_index.md`** — self-declared
"superseded," but still contains live (non-broken) links to
`docs/todo/README.md`, `docs/todo/MIGRATION_FREEZE.md`, and 5 other still-
tracked files. **LIVE_GOVERNANCE** (a superseded pointer whose links would
break on retirement).

**`workflow_standard.md` self-dependency** — the file itself states 43 of the
(then) 89 frozen files still used `P0`-`P4` tokens and 13 still used the
legacy status words. This audit did not recount that exact figure (stale
counts in the file are expected and not a defect — the file's own text
already flags them as counted "at the time"), but the qualitative dependency
holds: most of the 48 `ISSUE_OWNED_OPEN` files retain legacy priority tokens
inside frozen prose, so `workflow_standard.md` remains a genuine reading
dependency for as long as those files exist un-canonicalized.

**Test/code dependencies on non-infrastructure files** (not README/
MIGRATION_FREEZE/workflow_standard, but still genuine live blockers to full
directory removal):

```text
src/market_data/native_short_repository_source_identity_v1.py:23-25
  CONTROLLED_CHAIN_4H_UNTRACKED_PATH = "docs/todo/replay_parameter_study_harness_v1.md"
scripts/run_chain_4h.sh:17
  CONTROLLED_UNTRACKED_PATH="docs/todo/replay_parameter_study_harness_v1.md"
src/operations/run_native_short_production_readiness_v1.py (consumes the same constant)
tests/test_chain_4h_market_boundary_v1.py:283,330,456 (asserts the literal path string)
tests/test_native_short_repository_source_identity_v1.py (path-matching fixtures; NOT a real directory dependency — uses tmp_path)

tests/test_sector_taxonomy_import_v1.py:523-536
  test_sector_rotation_public_contract_uses_participation_terms()
  reads docs/todo/market_intelligence/sector_rotation_engine_v1.md
  AND docs/todo/sector_rotation_dashboard_v1.md directly (.read_text())
```

These are real, currently-passing production/test dependencies (the sector
taxonomy one already has a known unrelated pre-existing "breadth" assertion
mismatch, flagged by Batch 6F's own manifest as a separate follow-up). They
do not block Batch 6G's infrastructure-trio retirement, but they **do** block
ever deleting `replay_parameter_study_harness_v1.md`,
`market_intelligence/sector_rotation_engine_v1.md`, or
`sector_rotation_dashboard_v1.md` without a prior remediation batch that
repoints the allowlist constant and the two test assertions.

## 9. Architecture safety

```text
architecture_boundary_violations=0
reporting_authority_violations=0
research_execution_violations=0
selection_account_awareness_violations=0
parallel_manual_execution_paths=0
```

No migrated Issue was found assigning `decision_gate`-owned scope (account
protections, ladder-repair approval) to `execution_planner`/`executor`, or
vice versa; account-aware scope (`#227`, `#318`, `#268`, `#269`, `#273`) is
consistently framed as `decision_gate`/`execution_planner`-owned across the
files that reference it, and market-only scope (`selection_engine`,
research lanes) does not read account/balance state in any reviewed file.
This audit reviewed documentation only — no source diff was introduced by
this batch, so there is no new violation surface to check beyond ownership
text.

## 10. Retirement gate matrix

| Gate | Requirement | Result | Exact blockers |
|---|---|---|---|
| R1 | `unowned_executable_scope_files=0` | **FAIL** | `state_driven_runtime_orchestration_v1.md` (1 file, no Issue) |
| R2 | `partially_issue_owned_files=0` | **FAIL** | `multi_account_asset_foundation_backlog.md` (1 file, intentional per Batch 6C, `#294` still open) |
| R3 | `files_needing_canonicalization=0` | **FAIL** (forward-looking, non-blocking today) | 7 files listed in §7 carry unique design content not yet in canonical docs; none are due for canonicalization until their Issues close |
| R4 | `files_needing_archive=0`, `files_needing_remove=0` | **FAIL** | 5 newly archive-ready files + 1 REMOVE-with-correction file (§5) |
| R5 | `live_operational_dependencies_on_todo_infrastructure=0` | **PASS** (for the 3 infra files specifically) | No code/test reads `README.md`, `MIGRATION_FREEZE.md`, or `workflow_standard.md` directly. (2 separate live code/test dependencies exist on *other*, non-infra files — see §8 — relevant to full-directory removal, not to this specific gate.) |
| R6 | `live_governance_dependencies_on_todo_infrastructure=0` | **FAIL** | `AGENTS.md`, `docs/development/github_issues_workflow.md`, `docs/research/synth_v2_research_todo_index.md` all still require the infra trio |
| R7 | Only retirement infrastructure remains | **FAIL** | 57 non-infrastructure files remain; 48 legitimately (`ISSUE_OWNED_OPEN`), 9 need a disposition action first (§5, §6) |

## 11. Minimum remaining sequence

```text
6F2 — small archive/remove/disposition correctness batch
  - archive the 5 HISTORICAL_ARCHIVE_READY files (§5)
  - correct or remove reporting/README.md's stale migration-candidates list
  - resolve external_research/README.md's AMBIGUOUS disposition
  - file (or explicitly re-justify as non-executable) an owning Issue for
    state_driven_runtime_orchestration_v1.md

6C2 — migrate multi-account asset backlog Phases 2-5
  - only after #294 (Phase 1) lands and is reviewed; not ready yet

(ongoing, not a docs batch) — normal Issue-closure work
  - the 48 ISSUE_OWNED_OPEN files clear naturally as their ~46 distinct
    owning Issues close through regular engineering work; no docs/todo
    batch can accelerate this without duplicating Issue tracking

6F3 (optional, lower priority) — code/test dependency remediation
  - repoint CONTROLLED_CHAIN_4H_UNTRACKED_PATH away from
    docs/todo/replay_parameter_study_harness_v1.md
  - update tests/test_sector_taxonomy_import_v1.py to stop reading
    docs/todo/{market_intelligence/sector_rotation_engine_v1.md,
    sector_rotation_dashboard_v1.md} directly (also resolves the
    pre-existing "breadth" assertion mismatch flagged in Batch 6F)
  - only required before those 3 specific files can ever be deleted, not
    before 6G

6G — infrastructure + governance-reference retirement
  - repoint AGENTS.md, docs/development/github_issues_workflow.md, and
    docs/research/synth_v2_research_todo_index.md away from the infra trio
  - decide the disposition of docs/todo/ itself while ~40+ ISSUE_OWNED_OPEN
    files still legitimately exist (see §12) — this is a real design
    decision this audit surfaces but does not resolve
```

## 12. Exact Batch 6G preconditions

Machine-checkable:

```text
[ ] disposition_matrix_reconciles: len(git ls-files 'docs/todo/**') == sum(all disposition categories)   (currently TRUE: 60==60)
[ ] unowned_executable_scope_files == 0                                    (currently 1, FAIL)
[ ] partially_issue_owned_files == 0 OR explicitly accepted as intentional and documented (currently 1, ACCEPTED per §4/§6)
[ ] files_needing_archive == 0                                             (currently 5, FAIL)
[ ] files_needing_remove == 0                                              (currently 1, FAIL)
[ ] ambiguous_files == 0                                                   (currently 1, FAIL)
[ ] grep -rn "docs/todo" AGENTS.md returns 0 matches (post-repoint)        (currently >0, expected until 6G itself repoints it)
[ ] grep -rn "docs/todo" docs/development/github_issues_workflow.md returns 0 matches (post-repoint)
[ ] grep -rn "docs/todo" docs/research/synth_v2_research_todo_index.md returns 0 matches (post-repoint, or file itself archived)
[ ] a reviewed decision exists for what happens to docs/todo/ files that are still ISSUE_OWNED_OPEN when 6G runs (delete infra trio only vs. wait for full closure)
```

## 13. Acceptance evidence

```text
tracked_todo_files=60
inventory_rows=60
duplicate_inventory_rows=0
unclassified_files=0
infrastructure_files=3
non_infrastructure_files=57
issue_owned_open=48
issue_owned_closed_archive_ready=0
partial_issue_ownership=1
unowned_executable_scope=1
historical_archive_ready=5
remove=1
ambiguous=1
files_needing_canonicalization=7
live_operational_dependencies=2
live_governance_dependencies=3
broken_references=0
architecture_boundary_violations=0
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
RETIREMENT_READY_FOR_6G=0
```
