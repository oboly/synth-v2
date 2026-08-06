# GitHub Issues Batch 2C Migration v1

## 1. Status

`COMPLETE`

This document records the fourth bounded migration batch from the frozen
`docs/todo/` board to GitHub Issues, following:

- `docs/development/github_issues_first_batch_migration_v1.md` (PR #209,
  Issues #198-#206)
- `docs/development/github_issues_remaining_todo_inventory_v1.md` (PR #215,
  disposition proposal)
- `docs/development/github_issues_batch_2a_migration_v1.md` (PR #222,
  Issues #217-#221)
- `docs/development/github_issues_batch_2b_migration_v1.md` (PR #237,
  Issues #224-#228 and #230-#234)

It does not authorize runtime changes, database writes, broker access, order
submission, service/timer changes, bulk TODO deletion, or automatic
conversion of remaining TODO files. It does not create, edit, close, label,
or assign any Issue.

## 1a. Repository-tracking exception

Two of the four legacy source paths named in this batch's task contract are
**not tracked in the shared repository at all**. They exist only as local
working-tree files on this devlap and are excluded via `.git/info/exclude`
under the headers "Local devlap backlog / scratch docs" and "Local next
architecture backlog":

- `docs/todo/bullrun_start_dashboard_cockpit_refresh_v1.md` (`.git/info/exclude`
  line 40)
- `docs/todo/multi_horizon_aplus_breathline_strategy_integration_v1.md`
  (`.git/info/exclude` line 44)

Verified: `git ls-tree -r origin/main` contains no entry for either path,
and `git log --all` shows no commit touching either path. These files were
never part of the shared repo's history — the local exclude was already in
place before this batch and predates it.

Per explicit user instruction for this batch, both files are **left
untouched** rather than force-added (`git add -f`) into shared history for
the first time as a side effect of a routine pointer-header update. No
in-repo pointer header exists for these two files. Issues #239, #240, and
#243 are mapped and scoped by this manifest alone; their owning-Issue
relationship to these two local files is recorded here, not in the files
themselves.

This does not change #239/#240/#243 Issue scope, and does not affect the
two normally-tracked source files (Elliott Wave, golden-cases), which
received in-repo pointer headers as originally required.

## 2. Scope

| Legacy source | Migrated scope | Owning Issue(s) | Ownership type | Unmigrated remainder |
|---|---|---:|---|---|
| `docs/todo/bullrun_start_dashboard_cockpit_refresh_v1.md` (local-only, untracked — see §1a) | Scope A (read-only bullrun-start dashboard module: indicators, visual states, key logic, stablecoin/whale prepositioning v1, CLI, output, safety markers) → #239; Scope B (cockpit/navigation cleanup and wallet page styling) → #240 | #239, #240 | split-partial | "Asset onboarding context" section; any upstream market-data/calculation or trading-layer behavior |
| `docs/todo/claude_bundle_2_elliott_wave_daily_context_lane_v1.md` | §2 labeler specification + ledger + the two Phase 1 validation metrics in §5, BTC-EUR only (this batch); §0 layering-fix item remains separately owned by #219 (previously migrated, Batch 2A) | #241 (this batch); #219 (previously migrated, unchanged) | partial | Top-N/multi-symbol rollout; §3 trade hypotheses; §4 manual approval path beyond Phase 1 event logging; §5 Phase 2/Phase 3 strategy-coupling work |
| `docs/todo/golden_coin_cases_backtest_bundle_v1.md` | Priority items 1-5 only: `MarketNavigationState`, `BreathlineState`, `ImpulseHealthState`, `TimingState`, golden regression fixtures for the seven named cases | #242 | partial | Completed SXT emergency-rebuild history (already-shipped, historical); ladder preview dry-run; manual ladder submit safety |
| `docs/todo/multi_horizon_aplus_breathline_strategy_integration_v1.md` (local-only, untracked — see §1a) | "Required next work" items 1, 2, and 4 (architecture contract, Breathline data contract, guard tests) | #243 | partial | "Required next work" items 3 and 5 (strategy integration contract, implementation/context builders/reporting/strategy state outputs) |

```text
legacy_source_files=4
mapped_issues=5
newly_migrated_issues=#239,#240,#241,#242,#243
previously_migrated_issue_scope=#219
full_migrations=0
partial_migrations=3
split_partial_migrations=1
```

The bullrun/cockpit file is the one `split-partial` migration (#239 for
Scope A, #240 for Scope B). The Elliott Wave, golden-cases, and
multi-horizon files are each `partial` (one newly-mapped Issue per file:
#241, #242, #243 respectively). No file in this batch is a `full`
migration. Issue #219, mapped in Batch 2A, retains its existing narrow
layering-fix scope in the Elliott Wave file unchanged; this batch adds #241
as a second, independent partial owner of that same file for a
non-overlapping scope.

## 3. Source-of-truth rule

For migrated scope, GitHub Issues own:

- current status;
- priority;
- blockers;
- acceptance criteria;
- next action;
- closure.

Legacy TODO files retain historical/design content only for migrated scope.
Unmigrated scope in a partially-migrated file remains exactly what it was
before this batch — legacy design content with no Issue-backed execution
status, and no owning Issue. For the two untracked local-only files (§1a),
this source-of-truth rule applies identically even though no in-repo
pointer header records it — the local files are simply not the canonical
migration record; this manifest is.

## 4. Split and partial boundaries

### #239

Owns Scope A only:

- inspect persisted inputs and reporting conventions;
- define read model and field mapping;
- implement read-only bullrun-start dashboard module;
- reporting tests.

Unmigrated from #239:

- cockpit/wallet cleanup;
- any upstream calculation or trading-layer behavior.

### #240

Owns Scope B only:

- cockpit and wallet presentation cleanup exactly as defined in the source.

Unmigrated from #240:

- bullrun-start dashboard module;
- upstream market calculations;
- trading-layer behavior.

### #241

Owns:

- BTC-EUR Phase 1 labeler;
- ledger;
- two validation metrics;
- ambiguity/invalidation/re-anchor semantics.

Does not own:

- #219 layering fix;
- top-N rollout;
- production selection or execution behavior.

### #242

Owns priority items 1-5 only.

Does not own:

- completed SXT emergency-rebuild history;
- ladder preview dry-run;
- manual-submit safety;
- execution or broker behavior.

### #243

Owns:

- canonical architecture contract;
- guard tests for forbidden dependency directions where practical.

Does not own:

- any strategy implementation;
- runtime activation;
- broker or order behavior.

## 5. Architecture ownership

```text
selection_engine  = market-only, account-agnostic
decision_gate     = account-aware permission layer
execution_planner = execution intent only
executor / agents = order handling only
dashboards        = read-only consumers
```

Issue ownership (no Issue grants cross-layer authority):

- `#239` — dashboard/reporting read model only; read-only bullrun-start
  dashboard.
- `#240` — dashboard/reporting presentation cleanup only.
- `#241` — research only, market-only and account-agnostic.
- `#242` — research/market-state modeling only.
- `#243` — architecture documentation and guard tests only; does not merge
  layer responsibilities.

Explicitly:

- #239 and #240 remain read-only dashboard/reporting scopes.
- #241 and #242 remain market-only research scopes.
- #243 documents boundaries but does not merge layer responsibilities and
  does not own any strategy implementation.
- No account-aware permission logic exists outside `decision_gate`.
- No execution intent exists outside `execution_planner`.
- No order handling exists outside executor/agents.
- No market ranking authority was added outside `selection_engine`.

## 6. README handling

`docs/todo/README.md`'s "Lane index" table was checked for rows referencing
the four source files in this batch. None of the four files has an existing
row in that table:

- `bullrun_start_dashboard_cockpit_refresh_v1.md` — no row present (also
  untracked; see §1a).
- `claude_bundle_2_elliott_wave_daily_context_lane_v1.md` — no row present.
- `golden_coin_cases_backtest_bundle_v1.md` — no row present.
- `multi_horizon_aplus_breathline_strategy_integration_v1.md` — no row
  present (also untracked; see §1a).

No row was invented for symmetry. No README changes were made in this
batch. For the two normally-tracked files (Elliott Wave, golden-cases),
their in-file pointer headers are the sole in-repo migration marker. For
the two untracked local-only files, this manifest is the sole migration
record (see §1a) — there is no in-repo pointer header and no README row for
either.

```text
readme_rows_updated=0
readme_rows_not_present=4
readme_rows_invented=0
```

## 7. Live-language classification

| Location | Passage | Classification |
|---|---|---|
| `bullrun_start_dashboard_cockpit_refresh_v1.md` (untracked, not modified — see §1a) "Scope A — Bullrun Start Dashboard" | Concrete deliverables | neutralized (owned by #239, per this manifest; no in-repo pointer edit made) |
| `bullrun_start_dashboard_cockpit_refresh_v1.md` (untracked, not modified) "Scope B — Cockpit Refresh" | Concrete deliverables | neutralized (owned by #240, per this manifest; no in-repo pointer edit made) |
| `bullrun_start_dashboard_cockpit_refresh_v1.md` (untracked, not modified) "Asset onboarding context" | Design content | unmigrated_scope |
| `claude_bundle_2_elliott_wave_daily_context_lane_v1.md` §0 layering item | Concrete deliverable | previously_migrated_scope (owned by #219, unchanged from Batch 2A) |
| `claude_bundle_2_elliott_wave_daily_context_lane_v1.md` §2 labeler spec, §5 Phase 1 metrics (BTC-EUR) | Concrete deliverables | neutralized (owned by #241, pointer header updated) |
| `claude_bundle_2_elliott_wave_daily_context_lane_v1.md` §1, §6 ground rules/boundaries | Design content | historical_preserved |
| `claude_bundle_2_elliott_wave_daily_context_lane_v1.md` §3 trade hypotheses, §4 manual-approval path (beyond Phase 1 logging), §5 Phase 2/3, §7 top-N/multi-symbol work order | Concrete next actions | unmigrated_scope (explicitly disclaimed in pointer header) |
| `golden_coin_cases_backtest_bundle_v1.md` "Priority order" items 1-5 | Concrete deliverables | neutralized (owned by #242, pointer header added) |
| `golden_coin_cases_backtest_bundle_v1.md` "Current status → Already implemented/live", §1 SXT | Completed implementation record | historical_preserved (already-shipped, kept as regression reference) |
| `golden_coin_cases_backtest_bundle_v1.md` "Priority order" items 7-8 (ladder preview dry-run, manual submit safety) | Concrete next actions | unmigrated_scope (explicitly disclaimed in pointer header) |
| `golden_coin_cases_backtest_bundle_v1.md` §2-§7 golden case detail, "Cross-coin lessons", "Desired UI card style", "Live Safety" | Design/reference content | historical_preserved |
| `multi_horizon_aplus_breathline_strategy_integration_v1.md` (untracked, not modified) `## Status` | Top-level status | historical_preserved (whole-file status line; not edited) |
| `multi_horizon_aplus_breathline_strategy_integration_v1.md` (untracked, not modified) "Required next work" items 1, 2, 4 | Concrete deliverables | neutralized (owned by #243, per this manifest; no in-repo pointer edit made) |
| `multi_horizon_aplus_breathline_strategy_integration_v1.md` (untracked, not modified) "Required next work" items 3, 5 | Concrete deliverables | unmigrated_scope |

```text
still_live_blocker=0
```

No passage was found, across the two normally-tracked source files, that
remains a live status/priority/blocker/next-action/execution-order board
for migrated scope after this batch's pointer headers. Unmigrated scope was
deliberately left exactly as it was — it was never claimed as Issue-owned,
so there is nothing to neutralize there; it is correctly classified
`unmigrated_scope`, not `still_live_blocker`. The existing #219 boundary in
the Elliott Wave file is unchanged and classified
`previously_migrated_scope`, not re-neutralized. For the two untracked
local-only files, no in-repo edit was made per user instruction (§1a); their
migrated-scope passages are recorded as `neutralized` in this manifest as
the canonical record, since there is no live in-repo board to fail this
check against — the files are not part of the shared repository.

## 8. Acceptance evidence

```text
legacy_source_files=4
mapped_issues=5
newly_migrated_issues=#239,#240,#241,#242,#243
previously_migrated_issue_scope=#219
full_migrations=0
partial_migrations=3
split_partial_migrations=1
legacy_pointer_headers=2/4
untracked_local_source_files=2
duplicate_status_owners=0
duplicate_priority_owners=0
duplicate_blocker_owners=0
duplicate_next_action_owners=0
duplicate_execution_order_owners=0
unmigrated_scope_accidentally_claimed=0
previously_migrated_scope_overwritten=0
broken_references=0
new_todo_intake_paths=0
runtime_changes=0
database_changes=0
broker_writes=0
order_submissions=0
service_timer_changes=0
code_changes=0
test_changes=0
```
