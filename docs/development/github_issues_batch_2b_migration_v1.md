# GitHub Issues Batch 2B Migration v1

## 1. Status

`COMPLETE`

This document records the third bounded migration batch from the frozen
`docs/todo/` board to GitHub Issues, following:

- `docs/development/github_issues_first_batch_migration_v1.md` (PR #209,
  Issues #198-#206)
- `docs/development/github_issues_remaining_todo_inventory_v1.md` (PR #215,
  disposition proposal)
- `docs/development/github_issues_batch_2a_migration_v1.md` (PR #222,
  Issues #217-#221)

It does not authorize runtime changes, database writes, broker access, order
submission, service/timer changes, bulk TODO deletion, or automatic
conversion of remaining TODO files.

## 2. Scope

| Legacy source | Migrated scope | Owning Issue | Ownership type | Unmigrated remainder |
|---|---|---:|---|---|
| `docs/todo/adaptive_fib_execution_offset_v1.md` | "Follow-up Sequence" steps 1-2: offline near-miss/fill replay dataset and versioned execution-offset policy contract | #224 | partial | Steps 3-5: read-only proposal preview integration, paper-execution validation, any later decision-gated runtime consumption |
| `docs/todo/breathline_backtest_campaign_and_coin_calibration_v1.md` | Whole file | #225 | full | none |
| `docs/todo/breathline_ui_phase_path_history_v1.md` | Whole file | #226 | full | none |
| `docs/todo/decision_gate_account_protections_v1.md` | "Open tasks by priority" §P1 sections: "P1 — Research and contract design" and "P1 — Replay and validation design" | #227 | partial | "P2 — Minimal implementation" (runtime implementation inside `decision_gate`) |
| `docs/todo/news_catalyst_monitor.md` | "P0 design task" (DB schema/migration draft proposal and read-only/dry-run ingestion skeleton for `external_catalyst_monitor_v1`) | #228 | partial | Production selection/dashboard consumption of catalyst context ("Dashboard integration", "Relationship to idiosyncratic catalyst override") |
| `docs/todo/position_rotation_preview.md` | "Next Strategy Work" section (research-validation and regime follow-up) | #230 | partial | The already-implemented MVP cockpit (Purpose, Target output, P1 sections, P2 — Better-candidate comparison, Completed research baseline) — historical record, not active scope |
| `docs/todo/regime_research.md` | Phase 1: "P1 — Immediate reruns and reads" and "P1 — Discovered regime pass" | #231 | partial | Phase 2 ("P2 — Symbol participation and breath profile design", "P2 — BTC-to-alt shock propagation / lead-lag replay", "P2 — Regime interaction audit design") and Phase 3 ("P3 — Later classifier work") |
| `docs/todo/strategy_candidates.md` | "P1 — Current strategy audit follow-up" only | #232 | partial | "P1 — Long-term regime classifier and dual-bucket research" (the file's *other* P1 section), "P2 — Horizon bucket design review", "P2 — `MACRO_DIP_BUDGET_MODE_V1`", "P2 — Swing pullback 168h research lead", "P3 — Legacy Synth v1 regime/strategy prior review" |
| `docs/todo/ui_webview.md` | The 4 accepted-but-unbuilt items in "### Profit Plan coin-card scanability decisions" (PPP display compaction, tooltip registry entry, duplicate Current-price tile removal, variable-field alignment follow-up) | #233 | partial | Already-implemented sections (historical, not active scope); "P2 — Stabilize UI/chart framework v1" and "Later UI v2 direction" (unrelated, still-open, unmigrated work) |
| `docs/todo/watchlist_candidates.md` | The single remaining unchecked KITE task: "Check liquidity, spread, candle history length, and minimum order constraints before any research promotion" | #234 | partial | Other watchlist candidates and research not named above |

```text
legacy_source_files=10
full_migrations=2
partial_migrations=8
mapped_issues=10
```

The two full migrations are `#225` and `#226`. All other mappings are
partial, exactly as specified for this batch.

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
status, and no owning Issue.

## 4. Partial migration boundaries

```text
#224: unmigrated remainder = read-only proposal preview integration,
      paper-execution validation with realistic fee/slippage modelling, and
      any later decision-gated runtime/live/paper execution adoption
      ("Follow-up Sequence" steps 3-5).

#227: unmigrated remainder = "P2 — Minimal implementation" — adding
      protections inside decision_gate after the contract and replay design
      are accepted; read-only reporting of active/expired protections.

#228: unmigrated remainder = production selection/dashboard consumption of
      catalyst context, i.e. everything past the P0 schema/dry-runner design
      (Dashboard integration section, idiosyncratic-catalyst-override
      feed relationship).

#230: unmigrated remainder = the completed MVP cockpit itself (Purpose,
      Target output, P1 — Schema/source inventory, P1 — Read-only preview
      runner, P1 — Current-price and distance semantics, P1 —
      Target/risk-aware rotation classification, P2 — Better-candidate
      comparison, Completed research baseline) — this is historical record
      of already-shipped work, not open scope, and is not migrated by this
      batch; no Issue owns it as live work.

#231: unmigrated remainder = Phase 2 (symbol/breath-profile design,
      BTC-to-alt shock propagation replay design, regime interaction audit
      design) and Phase 3 (later classifier work, blocked on Phase 2).

#232: unmigrated remainder = the file's *other* P1 section ("P1 —
      Long-term regime classifier and dual-bucket research" — note this
      file has two sections both labeled P1; only "P1 — Current strategy
      audit follow-up" is migrated), plus both P2 sections and the P3
      section.

#233: unmigrated remainder = already-implemented UI work described
      elsewhere in the file (historical, not active scope) and unrelated
      still-open webview work ("P2 — Stabilize UI/chart framework v1",
      "Later UI v2 direction") that this batch does not touch.

#234: unmigrated remainder = all other watchlist candidates and research
      questions in the file not naming the specific liquidity/spread/
      candle-history/min-order check.
```

## 5. Architecture ownership

```text
selection_engine  = market-only, account-agnostic
decision_gate     = account-aware permission layer
execution_planner = execution intent only
executor / agents = order handling only
dashboards        = read-only consumers
```

Issue ownership (no Issue grants cross-layer authority):

- `#224` — offline research only; no live or paper execution wiring.
- `#225` — research calibration only.
- `#226` — dashboard/reporting read model only.
- `#227` — `decision_gate` contract design only; no market ranking or
  execution authority.
- `#228` — research/ETL schema and dry runner only.
- `#230` — research only.
- `#231` — research Phase 1 only.
- `#232` — research/selection analysis only.
- `#233` — dashboard/reporting only.
- `#234` — research/market-data validation only.

Explicitly:

- No market ranking authority was added outside `selection_engine`.
- No account permission authority was added outside `decision_gate`.
- No execution intent authority was added outside `execution_planner`.
- No order handling authority was added outside executor/agents.
- All dashboard/reporting scopes (`#226`, `#233`, and the dashboard-adjacent
  parts of `#228`/`#230`) remain read-only consumers.

## 6. README handling

`docs/todo/README.md`'s "Lane index" table contains a row for 6 of the 10
migrated sources. All 6 were updated in place, preserving the original
historical status text and appending an explicit partial-ownership note:

- `decision_gate_account_protections_v1.md` → Issue #227 (partial)
- `position_rotation_preview.md` → Issue #230 (partial)
- `regime_research.md` → Issue #231 (partial)
- `ui_webview.md` → Issue #233 (partial)
- `strategy_candidates.md` → Issue #232 (partial)
- `watchlist_candidates.md` → Issue #234 (partial)

The other 4 source files have **no row** in the README "Lane index" table
and none was invented for symmetry — they were never part of the frozen
`v2.23` lane snapshot the table records:

- `adaptive_fib_execution_offset_v1.md`
- `breathline_backtest_campaign_and_coin_calibration_v1.md`
- `breathline_ui_phase_path_history_v1.md`
- `news_catalyst_monitor.md`

Their pointer headers are the sole in-repo migration marker for these four
files.

```text
readme_rows_updated=6
readme_rows_not_present=4
readme_rows_invented=0
```

## 7. Live-language classification

Every "still-live-looking" status/priority/blocker/next-action/
execution-order passage found across the ten source files and the six
affected README rows was individually classified:

| Location | Passage | Classification |
|---|---|---|
| `adaptive_fib_execution_offset_v1.md` `Status: TODO` line | Top-level status | neutralized (pointer redirects migrated scope to #224) |
| `adaptive_fib_execution_offset_v1.md` §Architecture, §V1 Scope, §Initial Policies, §Research Metrics, §Safety | Design content | historical_preserved (preserved as design context for both migrated and unmigrated scope) |
| `adaptive_fib_execution_offset_v1.md` "Follow-up Sequence" steps 1-2 | Concrete next actions | neutralized (owned by #224) |
| `adaptive_fib_execution_offset_v1.md` "Follow-up Sequence" steps 3-5 | Concrete next actions | unmigrated_scope (explicitly disclaimed in pointer header) |
| `breathline_backtest_campaign_and_coin_calibration_v1.md` `## Status` | `Todo / research campaign specification.` | neutralized (owned by #225) |
| `breathline_ui_phase_path_history_v1.md` `## Status` | `Todo / UI specification.` | neutralized (owned by #226) |
| `decision_gate_account_protections_v1.md` `## Status` block | `future design`, `priority: P2`, owner line | neutralized (migrated scope owned by #227) |
| `decision_gate_account_protections_v1.md` "P1 — Research and contract design", "P1 — Replay and validation design" | Task lists | neutralized (owned by #227) |
| `decision_gate_account_protections_v1.md` "P2 — Minimal implementation" | Task list | unmigrated_scope (explicitly disclaimed in pointer header) |
| `news_catalyst_monitor.md` `## Status` | `Research / read-only ingestion lane.` | historical_preserved (this line covers the whole file, not just migrated scope; migrated scope is separately pointed at #228 in the pointer header, not by editing this line) |
| `news_catalyst_monitor.md` "P0 design task" | Concrete deliverables list | neutralized (owned by #228) |
| `news_catalyst_monitor.md` "Dashboard integration", "Relationship to idiosyncratic catalyst override" | Design content | unmigrated_scope (explicitly disclaimed in pointer header) |
| `position_rotation_preview.md` `## Status` | `MVP implemented / parked follow-up lane.` | historical_preserved (whole-file status line predates this batch; migrated scope is separately pointed at #230) |
| `position_rotation_preview.md` P1 sections, P2 section | `Status: implemented for MVP cockpit.` / `Status: implemented.` / `Status: MVP implemented; future refinements only.` | historical_preserved (already-closed implementation record, correctly past-tense, not a live board) |
| `position_rotation_preview.md` "Next Strategy Work" | `Status: separate research lane.` + task bullets | neutralized (owned by #230) |
| `regime_research.md` `## Status` | `Active next research lane.` | historical_preserved (whole-file status line; migrated scope is separately pointed at #231 in the pointer header) |
| `regime_research.md` "P1 — Immediate reruns and reads", "P1 — Discovered regime pass" | `Status: next.` + task bullets | neutralized (owned by #231) |
| `regime_research.md` P2/P3 sections | `Status: design next.` / `Status: observation logged...` / `Status: later / blocked...` | unmigrated_scope (explicitly disclaimed in pointer header) |
| `strategy_candidates.md` `## Status` | `Open design questions. No implementation yet.` | historical_preserved (whole-file status line; migrated scope is separately pointed at #232) |
| `strategy_candidates.md` "P1 — Current strategy audit follow-up" | `Status: open.` + task bullets | neutralized (owned by #232) |
| `strategy_candidates.md` other P1/P2/P3 sections | `Status: open.` / `Status: open research, but not next.` / `Status: future portfolio/research lane...` / `Status: research lead / not paper-ready.` / `Status: parked research prior.` | unmigrated_scope (explicitly disclaimed in pointer header, including the same-labeled second P1 section) |
| `ui_webview.md` `## Status` | `Active / read-only freshness and zone display updated.` | historical_preserved (whole-file status line; migrated scope is separately pointed at #233) |
| `ui_webview.md` "### Profit Plan coin-card scanability decisions" | `Status: accepted design / implementation later.` | neutralized (owned by #233) |
| `ui_webview.md` other sections | `Status: open / parked.` / `Status: done / keep current.` / `Status: done for read-only freshness v1.` / `Status: implemented in feature/ui-local-time-only-v1.` | historical_preserved / unmigrated_scope as applicable (already-closed items are historical_preserved; "P2 — Stabilize UI/chart framework v1" and "Later UI v2 direction" are unmigrated_scope) |
| `watchlist_candidates.md` `## Status` | `Open watchlist / research intake lane.` | historical_preserved (whole-file status line; migrated scope is separately pointed at #234) |
| `watchlist_candidates.md` "P2 — KITE moonshot asymmetry candidate" | `Status: research-watchlist-ready.` + mostly-`Done` task list | historical_preserved for the done items; neutralized for the one remaining unchecked liquidity/spread check (owned by #234) |
| `docs/todo/README.md` rows for the 6 affected files | Original status cells | neutralized (each updated in place with an explicit partial-ownership note; original text preserved inline) |

```text
still_live_blocker=0
```

No passage was found, across any of the ten files or the six affected
README rows, that remains a live status/priority/blocker/next-action/
execution-order board for migrated scope after this batch's pointer headers
and README updates. Unmigrated scope was deliberately left exactly as it
was — it was never claimed as Issue-owned, so there is nothing to
neutralize there; it is correctly classified `unmigrated_scope`, not
`still_live_blocker`.

## 8. Acceptance evidence

```text
legacy_source_files=10
full_migrations=2
partial_migrations=8
issues_mapped=10
issues_verified=#224,#225,#226,#227,#228,#230,#231,#232,#233,#234
legacy_pointer_headers=10/10
duplicate_status_owners=0
duplicate_priority_owners=0
duplicate_blocker_owners=0
duplicate_next_action_owners=0
duplicate_execution_order_owners=0
unmigrated_scope_accidentally_claimed=0
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
