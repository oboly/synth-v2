# docs/TODO Cleanup — Batch 4B

## 1. Status

`PARTIAL`

One of three candidates archives safely. Two remain genuinely open and are deferred, per the completion guard (no Issue creation permitted in this batch, and "parked" alone is not sufficient evidence for closure).

## 2. Candidate disposition matrix

| Source | Section counts | Existing owners | Remaining open scope | Disposition | Reason |
| ------ | -------------: | --------------- | --------------------- | ----------- | ------ |
| `docs/todo/manual_ladder_dashboard.md` | implemented=6, canonical_owner=0, issue_owned=1, historical=3, superseded=4, parked_but_still_open=0, genuinely_unowned=0, ambiguous=0 | `src/reporting/run_manual_ladder_static_dashboard_v1.py`, `docs/research/manual_ladder_dashboard_v1.md`, `docs/research/breath_fibo_strategy_static_dashboard_v1.md`, `docs/todo/profit_plan_live_ladder.md`, Issues #202/#203/#206 | none | ARCHIVED | P0 implemented; P1/P2 superseded by the canonical fib/zone map + strategy dashboard; execution-automation mentions are already Issue-owned; `docs/todo/README.md` already carried a frozen "historical source / superseded" disposition for this file prior to this batch |
| `docs/todo/breath_curve.md` | implemented=0, canonical_owner=1, issue_owned=0, historical=0, superseded=0, parked_but_still_open=2, genuinely_unowned=1, ambiguous=0 | `docs/research/breath_curve_live_v1.py` family (display-only promotion, not strategy validation); `docs/todo/strategy_candidates.md` (unmigrated "P2 — Horizon bucket design review" section references `BREATH_CURVE_RESEARCH` graduation rules but is not Issue-owned) | regime-difference diagnostic; older-history vs. winning-window comparison; non-overlap re-validation; graduation rules from `BREATH_CURVE_RESEARCH` to runtime-eligible buckets | DEFERRED | Findings docs from 2026-05-13 explicitly recommend follow-up work ("build a regime-difference diagnostic", "compare winning Jan-Apr 2026 windows vs failed older windows") that was never built; no Issue or canonical doc closes it; the later `breath_curve_live_v1` promotion is a market-only *display* matcher, not a resolution of the strategy-validation continuation |
| `docs/todo/dev_ops_hygiene.md` | implemented=0, canonical_owner=1, issue_owned=0, historical=2, superseded=0, parked_but_still_open=0, genuinely_unowned=1, ambiguous=0 | git/untracked hygiene is covered by `AGENTS.md` and `docs/development/github_issues_workflow.md` staging discipline | MariaDB export/backup procedure decision (P3) | DEFERRED | No canonical backup/export doc exists under `docs/ops/` or `docs/database/`, and no Issue owns it; `docs/development/github_issues_remaining_todo_inventory_v1.md` recommended "spin a 1-line Issue only if backup procedure genuinely still missing," but this batch is not permitted to create an Issue to manufacture archivability, so the file must stay live per the completion guard |

## 3. Manual ladder analysis

- **P0 dashboard**: `implemented`. `src/reporting/run_manual_ladder_static_dashboard_v1.py` and `docs/research/manual_ladder_dashboard_v1.md` exist, match the required display fields (T1/next/runner target separation, ALGO/WLD fallback rows, neutral state labels), and predate this batch by weeks.
- **External-zone display scope (P1)**: `superseded`. A full canonical fib/zone map system (`docs/research/canonical_fib_zone_map_v1.md`, `src/market_data/run_canonical_fib_zone_map_v1.py`, `src/market_data/fib_navigation_map_v1.py`) now feeds `docs/research/breath_fibo_strategy_static_dashboard_v1.md`, which explicitly documents itself as the "strategy-oriented" successor and `manual_ladder_dashboard_v1` as its "downstream manual level-reading surface." This is a materially more complete implementation of the P1 idea than a CSV-based normalization layer.
- **Regime-label scope (P2)**: `superseded`. No file defines the literal `CONTINUATION_LADDER_CONTEXT`/`REACTION_RELOAD_CONTEXT`/etc. labels, but `breath_fibo_strategy_static_dashboard_v1` implements a richer regime-aware candidate-state model (`SUPPORT_REACTION_CANDIDATE`, `FIB_RETEST_CONTINUATION_CANDIDATE`, `INVALIDATION_NEAR`, etc.) sourced from `active_regime_observation`, covering the same "regime as first interpretation layer" intent.
- **Future-execution mentions**: `issue_owned`, correctly out of scope for a reporting TODO per this task's own instruction. `paper_candidate_contract -> decision_gate adapter` and `execution_planner ladder integration` map to the currently open manual-execution-ladder Issues #202 (request/plan-snapshot contract), #203 (authoritative execution-planner leg validation), and #206 (credential/executor boundary).

## 4. Breath Curve analysis

None of the open research-continuation groups are complete or Issue-owned; none are collapsed into a single "parked" bucket:

- **Same-window buy-and-hold baseline**: `docs/research/breath_curve_policy_baseline_report_v1.md` exists — baseline comparison work was done for the policy-backtest track, but the TODO's own P2 items (checkpoint 0.618 vs 0.786, offset-match-only variant) are not separately closed out anywhere; treated as part of `parked_but_still_open`.
- **Random-anchor baseline**: findings exist (`breath_curve_random_anchor_baseline_findings_20260512/13.md`, wider-window variant) — done as a data point, but feeds into the still-open regime-gated conclusion below, not a standalone closure.
- **4h partial-cycle test**: explicitly `still unowned`. `breath_curve_partial_to_full_backtest_v1_findings.md` lists "4h candles" as future work, never built.
- **Regime-difference diagnostic**: `still unowned`. `breath_curve_regime_gate_findings_20260513.md` and `breath_curve_non_overlap_validation_findings_20260513.md` both recommend building this before any promotion discussion reopens; no such diagnostic file exists.
- **Older-history / non-overlap comparison**: `still unowned`. `breath_curve_non_overlap_validation_findings_20260513.md` concludes "fails non-overlap / older-history validation" and "paper/live readiness: blocked," with an explicit unbuilt next step (compare winning Jan-Apr 2026 windows vs. failed older windows).
- **Graduation rules to runtime-eligible buckets**: `still unowned`. `docs/todo/strategy_candidates.md`'s unmigrated "P2 — Horizon bucket design review" section lists "Define graduation rules from `BREATH_CURVE_RESEARCH` to runtime-eligible candidate buckets only after validation" with no Issue owner (only the file's separate "P1 — Current strategy audit follow-up" section is Issue #232-owned).
- **`breath_curve_live_v1` promotion**: this is a separate, already-shipped market-only *display* matcher (`docs/profit_plan_breath_curve_live_v1.md`) feeding the Profit Plan card as context only ("not a forecast, trade signal, or execution instruction"). It does not resolve the strategy-validation questions above and is not treated as closing them.

## 5. Dev/Ops analysis

- **DB backup/export ownership**: unowned. No `docs/ops/` or `docs/database/` doc defines a MariaDB export/backup procedure; no Issue references backup/export. `docs/development/github_issues_remaining_todo_inventory_v1.md` had proposed closing this with a throwaway Issue, which this batch is explicitly barred from creating.
- **Git/untracked hygiene ownership**: `canonical_owner`. Covered by `AGENTS.md` ("Before committing" / avoid `git add .` and `git add data/`) and `docs/development/github_issues_workflow.md` staging discipline — the file's P4 guidance duplicates already-canonical rules but introduces no new unowned scope.
- **Completed historical sections**: `historical`. The Codex smoke lane and DBeaver/MariaDB access-recovery sections are marked done in the source file and no contradicting evidence was found.

## 6. Archive moves

| Old path | New path |
| -------- | -------- |
| `docs/todo/manual_ladder_dashboard.md` | `docs/archive/manual_ladder_dashboard.md` |

## 7. Deferred candidates

### `docs/todo/breath_curve.md`

- Unresolved scope: regime-difference diagnostic; older-history/non-overlap re-validation; 4h partial-cycle test; `BREATH_CURVE_RESEARCH` graduation-rule definition.
- Current owner: none (research-only, unmigrated).
- Why archive is unsafe: the file's own named findings explicitly call for follow-up work that was never built, and a separate unmigrated TODO section (`strategy_candidates.md`) still references the same open graduation question with no Issue owner.
- Recommended later disposition: file a scoped Issue (in a future batch, not this one) covering "Breath Curve regime-difference diagnostic and non-overlap re-validation," or explicitly abandon the strategy-promotion track in favor of keeping Breath Curve as display-only context, with a canonical doc recording that decision.

### `docs/todo/dev_ops_hygiene.md`

- Unresolved scope: MariaDB export/backup procedure decision (P3).
- Current owner: none.
- Why archive is unsafe: no canonical doc or Issue exists for backup/export hygiene, and this batch may not create an Issue solely to enable archiving.
- Recommended later disposition: either write a short canonical `docs/ops/` backup/export procedure doc (closing the gap directly) or open a small scoped Issue for it, then archive the file once that scope has a home.

## 8. Reference handling

Live references repaired (path updated from `docs/todo/manual_ladder_dashboard.md` to `docs/archive/manual_ladder_dashboard.md`, with a pointer to the current owner):

- `docs/todo/signal_matrix_dashboard.md` (Sources list)
- `docs/research/signal_matrix_static_dashboard_v1.md` (Supporting docs / priors)
- `docs/architecture/strategy_proposal_contract_v1.md` (canonical-doc reference list; also split the "active dashboard lanes" bullet since only `signal_matrix_dashboard.md` is still active)

TODO index rows removed:

- `docs/todo/README.md` — removed the `manual_ladder_dashboard.md` row.

Historical references retained unchanged (dated provenance describing a past state, not live navigation):

- `docs/archive/synth_v214_signal_dashboard_strategy_bridge_backlog_history_v1.md` (4 occurrences)
- `docs/development/github_issues_remaining_todo_inventory_v1.md` (1 occurrence — prior-batch analysis snapshot)
- `docs/development/docs_todo_canonicalization_batch_3b3_v1.md` (6 occurrences — frozen Batch 3B3 record)

No references to `docs/todo/breath_curve.md` or `docs/todo/dev_ops_hygiene.md` were modified, since both files are deferred and unchanged.

## 9. Architecture safety

No operational architecture, runtime behavior, code, tests, database, broker, or service/timer files were touched. This batch is documentation-only (7 `.md` files changed: 1 rename + banner, 1 index-row removal, 3 reference repairs already counted, plus this manifest).

## 10. Acceptance evidence

```text
candidate_files=3
archived_files=1
deferred_files=2
source_paths_removed=1
archive_paths_created=1
redirect_shells_created=0
active_requirements_lost=0
unowned_scope_archived=0
ambiguous_scope_archived=0
active_todo_index_entries_remaining_for_archived_files=0
broken_references=0
ambiguous_reference_dispositions=0
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
