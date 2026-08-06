# GitHub Issues First-Batch Migration v1

## Status

`COMPLETE`

This document records the first bounded migration batch from the frozen
`docs/todo/` board to GitHub Issues.

It does not authorize runtime changes, database writes, broker access, order
submission, service/timer changes, bulk TODO deletion, or automatic conversion
of remaining TODO files.

## Source-of-truth rule

For the work items listed below:

- the GitHub Issue owns current execution status, priority, blockers, acceptance
  criteria, and closure;
- the legacy TODO file is retained as frozen historical/design context until a
  reviewed canonical/archive/remove disposition is completed;
- the legacy TODO file must not be updated as a parallel operational board;
- permanent contracts remain in canonical documentation and must not be copied
  wholesale into Issues.

## First bounded batch

| Legacy source | Disposition | Owning Issue | Current Issue status |
|---|---|---:|---|
| `docs/todo/native_short_multi_asset_rollout_contract_v1.md` | `issue` | #198 — ETH native SHORT promotion | `status:blocked` |
| `docs/todo/native_short_multi_asset_rollout_contract_v1.md` | `issue` | #199 — XRP native SHORT promotion | `status:blocked` |
| `docs/todo/native_short_multi_asset_rollout_contract_v1.md` | `issue` | #200 — native SHORT per-scope failure isolation | `status:ready` |
| `docs/todo/short_swing_linked_profile_freshness_and_disk_reliability_v1.md` | `issue` | #201 — linked-profile freshness and multi-cycle runtime acceptance | `status:blocked` |
| `docs/todo/manual_execution_ladder_future_readiness_backlog_v1.md` and `docs/todo/manual_execution_ladder_profiles_v1.md` | `issue` | #202 — manual execution request snapshot and idempotency | `status:ready` |
| `docs/todo/manual_execution_ladder_future_readiness_backlog_v1.md` | `issue` | #203 — canonical ladder construction and leg validation | `status:ready` |
| `docs/todo/sector_rotation_dashboard_v1.md` | `issue` | #204 — Sector Rotation dashboard review and acceptance | `status:needs-design` |
| `docs/todo/replay_parameter_study_harness_v1.md` | `issue` | #205 — replay parameter-study harness | `status:ready` |
| `docs/todo/credential_scope_and_manual_ladder_execution_boundary_v1.md` and `docs/todo/manual_execution_ladder_future_readiness_backlog_v1.md` | `issue` | #206 — credential and executor runtime boundary | `status:needs-design` |

A single legacy document may map to multiple bounded Issues when it previously
mixed separate owner layers or independent closure gates. This is intentional
and preferable to one oversized cross-layer Issue.

## Scope correction

The asset-universe candidate item from the original migration proposal is
excluded from this batch: ENA, ARB, and PENDLE were already included through
the full Bitvavo-universe import, so that item has no remaining migration
work and is not part of this manifest's Issue count.

## Architecture ownership

```text
selection_engine  = market-only, account-agnostic
decision_gate     = account-aware permission layer
execution_planner = execution intent only
executor / agents = order handling
```

Issue ownership:

- #198, #199, #200: market data / selection only;
- #201: dashboard/runtime freshness, with account permission remaining in
  `decision_gate`;
- #202: `decision_gate` plus `execution_planner`, with explicit separation;
- #203: `execution_planner` only;
- #204: market-only dashboard consumer;
- #205: market-only research/selection evidence;
- #206: `decision_gate` and executor/runtime boundary; no planner or dashboard
  broker access.

## Frozen legacy-file rule for this batch

Until the source files receive explicit pointer headers in this migration PR:

1. no status, priority, blocker, or execution-order update may be made in those
   files;
2. all new progress belongs in the owning Issue;
3. historical implementation evidence may remain unchanged;
4. contradictions must be corrected only when unsafe or materially false;
5. no content may be deleted merely because an Issue now exists.

## Completed work in this migration PR

- added a compact migration pointer to each of the 7 listed legacy source
  files, stating that current status/priority live in the owning Issue(s)
  and preserving all historical/design content below the pointer;
- updated the 6 corresponding `docs/todo/README.md` lane-index rows to point
  to the owning Issue(s) instead of carrying live-looking status text, while
  preserving the original historical status snippet inline (no evidence
  deleted); `manual_execution_ladder_profiles_v1.md` has no README lane-index
  row and required no edit there;
- verified no new file was added under `docs/todo/` since the
  `MIGRATION_FREEZE.md` freeze commit (no new TODO intake);
- verified all 9 owning Issues (#198-#206) exist and are open;
- verified all internal doc-path references added by this batch resolve and
  `git diff --check` is clean.

## Acceptance evidence

```text
files_classified=7 legacy source files
issues_created=9
issues_verified=#198-#206
excluded_asset_universe_item=excluded_completed_via_full_bitvavo_universe_import
canonical_moves=0
archived_files=0
removed_files=0
legacy_pointer_headers=7/7 added
duplicate_status_owners=0 (6 docs/todo/README.md lane-index rows repointed to owning Issues)
broken_references=0
new_todo_intake_since_freeze=0
runtime_changes=0
database_changes=0
broker_writes=0
order_submissions=0
service_timer_changes=0
```
