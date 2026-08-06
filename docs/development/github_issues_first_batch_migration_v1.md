# GitHub Issues First-Batch Migration v1

## Status

`IN_PROGRESS`

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
| existing GitHub Issue | already migrated | #131 — ENA, ARB and PENDLE asset universe | `status:ready` |

A single legacy document may map to multiple bounded Issues when it previously
mixed separate owner layers or independent closure gates. This is intentional
and preferable to one oversized cross-layer Issue.

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

## Remaining work in this migration PR

- add a compact migration pointer to each listed legacy source file;
- state that current status and priority live in the owning Issue(s);
- preserve all historical/design content below the pointer;
- run repository-wide checks for duplicate status ownership and new TODO intake;
- update this document to `COMPLETE` only after those checks pass.

## Acceptance evidence

```text
files_classified=8 legacy source files + existing issue #131
issues_created=9 (#198-#206)
canonical_moves=0
archived_files=0
removed_files=0
legacy_pointer_headers=pending
duplicate_status_owners=pending
broken_references=pending
runtime_changes=0
database_changes=0
broker_writes=0
order_submissions=0
service_timer_changes=0
```
