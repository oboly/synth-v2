# Synth v2 TODO Index

## Purpose

`docs/todo/` is the working board for active and parked Synth v2 work.
Canonical architecture, research, status, and operations detail stays in its source documentation, but active task tracking must be represented here.

## Board rules

- Active and parked work belongs under `docs/todo/`.
- `docs/todo/README.md` owns the cross-lane execution order.
- Update the lane TODO and this index together when status or priority changes.
- Do not duplicate one task across multiple lane files.
- Completed lanes retain evidence and standing boundaries, not stale action bullets.

Workflow standard:

```text
docs/todo/workflow_standard.md
```

## Global boundaries

Unless a lane explicitly states otherwise:

- no live trading
- no broker writes
- no order submission
- no executor changes
- no shortcuts across architecture layers
- research remains market-only and account-agnostic

Architecture split:

```text
selection_engine  = market-only candidate ranking
decision_gate     = account-aware permission and conflict resolution
execution_planner = immutable execution intent only
executor / agents = order handling only
```

Reporting/UI may never call the broker directly.

## Synth v2.23 reconciled priority

| Priority | Lane | Board state | Next decision |
|---:|---|---|---|
| P0 | TODO reconciliation / board cleanup | in review; closes when this reconciliation merges | Make the repository board authoritative before opening more work chats. |
| P1 | Profit Plan Live Ladder prerequisites | active | Complete canonical read-model consumption, deterministic row identity, freshness authority, and authenticated preview/audit prerequisites before any mutation path. |
| P1 | IOST target lifecycle history truth | active correctness lane | Prove map-cycle-aligned target history and prevent `PASSED`/`REACHED` targets regressing to `UPCOMING`. |
| P2 | Short Swing / Odroid freshness hygiene | open operational lane | Keep repository implementation separate from installed-host activation; verify ownership, timestamps, disk/log bounds, and multi-cycle freshness. |
| P3 | Research / FFG / scanner | open, non-blocking | Continue read-only rotation and momentum-flow research only after P1 work is controlled. |

Priority is execution order, not architectural importance.

## Native SHORT baseline

The native SHORT map-level runtime line is **done / accepted** in repository scope.

Merged completion chain:

```text
PR #74 cadence profile seed
PR #71 map-level persistence
PR #76 map-level materializer
PR #77 map-level runner
PR #81 runner interruption/observability follow-up
PR #79 scope-status chain integration
PR #87 canonical runtime wiring
```

Accepted evidence:

- PR-branch host acceptance: PASS
- post-merge `origin/main` acceptance: PASS
- current `origin/main` is `38ce625` or newer
- local cleanup complete
- no broker/account/order/decision/planning/execution path was introduced

Installed-host service/timer activation was not part of that closure. Any activation or installed-unit change remains a separate P2 operational action with explicit review.

## Lane index

| File | Status | Purpose |
|---|---:|---|
| `workflow_standard.md` | standard | TODO creation, update, closure, priority, boundary, and commit rules |
| `profit_plan_live_ladder.md` | **active P1 / Synth v2.23** | Safe prerequisites and ordered path from canonical ladder truth to authenticated preview, decision gate, execution plan, executor, and a tightly controlled live canary |
| `profit_plan_target_lifecycle_history_truth_v1.md` | **active P1 / Synth v2.23** | IOST-discovered lifecycle regression: map-cycle-aligned target history, monotonic reached/passed truth, and fail-closed incomplete-history handling |
| `short_swing_linked_profile_freshness_and_disk_reliability_v1.md` | **open P2** | Odroid/runtime ownership, absolute freshness timestamps, disk/log containment verification, rollout, and rollback hygiene |
| `momentum_flow_scanner_matrix_v1.md` | **open P3 research** | Read-only RSI/MFI momentum-flow scanner, target-room research gate, and validation path |
| `profit_plan_dashboard_action_truth_and_breathline_demote_v1.md` | done / parked | Completed Profit Plan action fail-closed, PPP, map-switch, Breathline, evidence-row, and formatting guardrails |
| `native_short_runtime_owner_and_scope_status_v1.md` | done / accepted; host activation separate | Completed native SHORT scope-status, map-level status, chain integration, and canonical runtime ownership |
| `native_short_map_level_status_v1.md` | done / parked | Completed native SHORT current map-level status contract and implementation evidence |
| `position_rotation_preview.md` | MVP implemented / parked follow-up | Account-aware read-only cockpit/rotation preview; no active v2.23 priority |
| `profit_plan_card_evidence_delta_visibility_v1.md` | done / parked | Deterministic current-vs-previous card evidence visibility |
| `manual_ladder_dashboard.md` | historical source / superseded | Earlier read-only ladder direction; active ladder work is tracked only in `profit_plan_live_ladder.md` |
| `deploy_runtime.md` | MVP cockpit implemented / ops follow-up | General Odroid cockpit and deployment follow-ups |
| `market_breath.md` | characterized / parked | Regime-dependent rhythm/phase research |
| `regime_research.md` | parked | Rotation replay, discovered regimes, symbol profiles, and interaction audits |
| `fibo_zones.md` | open research | Fib target maps, zone validation, and overlays |
| `ui_webview.md` | open / secondary | Non-blocking UI and styling work after correctness lanes |
| `signal_matrix_dashboard.md` | parked | Transparent primitive signal inventory |
| `breath_curve.md` | parked / open | Breath Curve validation continuation |
| `strategy_candidates.md` | parked / open research | Strategy audit and later classifier/policy research |
| `multi_horizon_fib_dashboard_backlog.md` | parked | Dashboard follow-up depending on fib research outputs |
| `paper_candidate_contract.md` | future design | Safe adapter from validated research candidates to `decision_gate` |
| `dev_ops_hygiene.md` | mostly parked | Development, database-access, backup, and worktree hygiene |
| `parked_backlog.md` | backlog | Archived A+ and external-narrative follow-ups |
| `watchlist_candidates.md` | open intake | Human-thesis watchlist intake before validation |

## Next-step rule

After this reconciliation merges:

1. Do not reopen native SHORT implementation work unless new evidence identifies a concrete defect.
2. Choose one P1 implementation slice from `profit_plan_live_ladder.md`, or run the bounded IOST forensic audit from `profit_plan_target_lifecycle_history_truth_v1.md`.
3. Keep installed-host activation and freshness verification in the P2 operations lane.
4. Keep research/scanner work non-blocking at P3.
5. Do not create several parallel implementation chats merely because the board now lists several lanes.

## Pre-live safety state

Until an explicitly reviewed live-canary phase is reached:

```text
broker_writes=0
order_submission=0
executor=none
```
