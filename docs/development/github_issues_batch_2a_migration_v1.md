# GitHub Issues Batch 2A Migration v1

## 1. Status

`COMPLETE`

This document records the second bounded migration batch from the frozen
`docs/todo/` board to GitHub Issues, following the disposition proposal in
`docs/development/github_issues_remaining_todo_inventory_v1.md` (PR #215)
and the first migration batch in `docs/development/
github_issues_first_batch_migration_v1.md` (PR #209).

It does not authorize runtime changes, database writes, broker access, order
submission, service/timer changes, bulk TODO deletion, or automatic
conversion of remaining TODO files.

## 2. Scope

| Legacy source | Migration scope | Owning Issue | Ownership type |
|---|---|---:|---|
| `docs/todo/account_provisioning.md` | Whole file (Batches 1-3 and both hotfixes are closed historical record; Batch 4 real Bitvavo private-read validation is the only open item) | #217 — Complete Batch 4 real Bitvavo private-read validation | full |
| `docs/todo/backtest_capability_contract_v1.md` | Whole file | #218 — Define machine-readable backtest capability contract | full |
| `docs/todo/claude_bundle_2_elliott_wave_daily_context_lane_v1.md` | **Only** the §0 architecture-hygiene item: `src/market_data/native_short_fib_context_v1.py` must not import from `src.research` | #219 — Remove research-layer import from native SHORT market-data context | partial |
| `docs/todo/native_short_invalidation_confirmation_backtest_v1.md` | Whole file | #220 — Replay native SHORT invalidation-confirmation policies | full |
| `docs/todo/stale_1h_advice_freshness_truth_v1.md` | Whole file | #221 — Fix stale 1h advice freshness truth for named assets | full |

## 3. Source-of-truth rule

For the scope listed above, GitHub Issues own:

- current status;
- priority;
- blockers;
- acceptance criteria;
- closure.

The legacy TODO files retain historical/design content only, for the
migrated scope. They must not be updated as a parallel operational board for
that scope. Permanent contracts remain in canonical documentation and must
not be copied wholesale into Issues.

## 4. Partial migration boundary

`docs/todo/claude_bundle_2_elliott_wave_daily_context_lane_v1.md` is the one
partial migration in this batch.

**Issue #219 owns, and owns only:**

- the single layering-violation item recorded in the file's §0 ("Ground
  truth"): `src/market_data/native_short_fib_context_v1.py` imports from
  `src.research` (`htf_fib_extension_confluence_v1`,
  `htf_fib_reentry_ladder_v1`) and must not; shared pure fib/swing logic
  should be extracted to a module usable by both runtime and research
  without runtime depending on research.

**Explicitly NOT owned by Issue #219, and NOT migrated by this batch:**

- §1 Concept (deterministic incremental Elliott Wave labeler design);
- §2 Labeler specification v1 (pivot rules, hard rules, confirmation,
  invalidation/re-anchor, ambiguity handling, state output);
- §3 Trade hypotheses (regime gate, C-bottom entry, B-wave profit-taking);
- §4 Manual approval path;
- §5 Validation protocol (Phases 1-3);
- §7 "What the coordinating chat should produce" (including its own point 1,
  which asks that a GitHub Issue eventually be filed for the labeler work —
  that request is preserved as historical/design text, not fulfilled by this
  batch; the corresponding candidate is tracked in `docs/development/
  github_issues_remaining_todo_inventory_v1.md` as `NEW-09`, which remains
  proposal-only and unfiled).

This Elliott Wave Phase-1 research/labeler scope has **no owning Issue**
after this batch. It must not be represented, referenced, or reported as
migrated, scheduled, in progress, or owned by Issue #219 in any document.
`NEW-09` was not filed by this batch and is not filed by any other Issue
created so far (`#217`-`#221`).

The file's own migration-pointer header (added by this batch) states this
boundary explicitly and directs readers to this manifest.

## 5. Architecture ownership

```text
selection_engine  = market-only, account-agnostic
decision_gate     = account-aware permission layer
execution_planner = execution intent only
executor / agents = order handling only
dashboards        = read-only consumers
```

Issue ownership (no Issue grants cross-layer authority):

- `#217` — credential / broker-private-read validation only. No
  `decision_gate`, `execution_planner`, executor, or dashboard authority.
- `#218` — research/backtest capability contract only. No
  `selection_engine`, `decision_gate`, `execution_planner`, or executor
  behavior change.
- `#219` — market-data dependency-direction cleanup only (`src/market_data/`
  must not import `src.research`). No behavior change; no `selection_engine`
  ranking, `decision_gate`, `execution_planner`, or executor change.
- `#220` — research replay only, read-only and account-agnostic. No
  `selection_engine`, `decision_gate`, `execution_planner`, or executor
  change; reporting remains a persisted-state consumer only.
- `#221` — market-data / selection freshness truth only. `selection_engine`
  remains market-only and account-agnostic; no `decision_gate`,
  `execution_planner`, or executor involvement.

## 6. Frozen legacy-file rule for this batch

Until the source files receive explicit pointer headers in this migration PR:

1. no status, priority, blocker, or execution-order update may be made in
   the migrated scope of those files;
2. all new progress on migrated scope belongs in the owning Issue;
3. historical implementation evidence may remain unchanged;
4. contradictions must be corrected only when unsafe or materially false;
5. no content may be deleted merely because an Issue now exists;
6. for the one partial migration, the unmigrated scope
   (`claude_bundle_2_elliott_wave_daily_context_lane_v1.md` §1-§5, §7) may
   still be edited as design content, but must not be represented as having
   Issue-backed execution status.

## 7. README rows

`docs/todo/README.md`'s "Lane index" table contains a row for only one of
the five migrated sources:

- `backtest_capability_contract_v1.md` — row updated to point to Issue #218,
  preserving the original historical status text inline.

The other four source files (`account_provisioning.md`,
`claude_bundle_2_elliott_wave_daily_context_lane_v1.md`,
`native_short_invalidation_confirmation_backtest_v1.md`,
`stale_1h_advice_freshness_truth_v1.md`) have **no row** in the README
"Lane index" table and none was invented for symmetry — they were never
part of the frozen `v2.23` lane snapshot the table records. Their pointer
headers are the sole in-repo migration marker for these four files.

## 8. Live-language classification

Every "still-live-looking" passage found across the five source files and
`docs/todo/README.md` was individually classified:

| Location | Passage | Classification |
|---|---|---|
| `account_provisioning.md` Batches 1-3, Hotfix A/B | `✅ DONE` / `✅ SUPERSEDED` markers | historical_preserved (already closed, past tense) |
| `account_provisioning.md` Batch 4 | Unchecked checklist (`⬜ PARKED`) | neutralized (migration pointer redirects current status/priority/blockers to #217; checklist itself preserved as frozen historical/design content) |
| `backtest_capability_contract_v1.md` `## Status` block | `future design`, `priority: P2`, owner line | neutralized (pointer redirects to #218) |
| `backtest_capability_contract_v1.md` `## Open tasks by priority` | P1/P1/P2 task list | neutralized (pointer redirects to #218; task list preserved as design content) |
| `claude_bundle_2_...md` §0 | Layering-violation sentence | neutralized (this exact item is now owned by #219) |
| `claude_bundle_2_...md` §1-§5 | Labeler concept, spec, hypotheses, approval path, validation protocol | historical_preserved (unmigrated design content; partial-migration pointer explicitly marks this as still proposal-only, not live-tracked) |
| `claude_bundle_2_...md` §7 point 1 | "A GitHub Issue for this file... The legacy TODO board is frozen: do not add a new TODO entry" | historical_preserved (preserved verbatim; the partial-migration pointer at the top of the file already clarifies that only the §0 item was filed, so this passage cannot be mistaken for a fulfilled or live instruction) |
| `native_short_invalidation_confirmation_backtest_v1.md` `## Status` | `Open research / calibration lane.` | neutralized (pointer redirects to #220) |
| `native_short_invalidation_confirmation_backtest_v1.md` body | Required backtest / measurements / decision criteria / definition of done | historical_preserved (design content preserved; execution status owned by #220) |
| `stale_1h_advice_freshness_truth_v1.md` `## Status` | `Candidate improvement only. This document is not an execution queue item.` | neutralized (pointer redirects to #221; note this line already explicitly disclaimed being a live queue item before migration) |
| `docs/todo/README.md` row for `backtest_capability_contract_v1.md` | Original status cell | neutralized (updated in place to add the Issue #218 pointer, original text preserved inline) |

```text
still_live_blocker=0
```

No passage was found, across any of the five files or the README, that
remains a live status/priority/blocker/execution-order board after this
batch's pointer headers and the one README row update.

## 9. Acceptance evidence

```text
legacy_source_files=5
full_migrations=4
partial_migrations=1
issues_mapped=5
issues_verified=#217-#221
legacy_pointer_headers=5/5
duplicate_status_owners=0
duplicate_priority_owners=0
duplicate_blocker_owners=0
duplicate_execution_order_owners=0
unmigrated_scope_accidentally_claimed=0
broken_references=0
new_todo_intake_paths=0
runtime_changes=0
database_changes=0
broker_writes=0
order_submissions=0
service_timer_changes=0
```
