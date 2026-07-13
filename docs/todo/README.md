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

| File | Status | Purpose |
|---|---:|---|
| `workflow_standard.md` | standard | TODO creation, update, closure, priority, boundary, and commit rules |
| `short_swing_linked_profile_freshness_and_disk_reliability_v1.md` | **active P0/P1** | 2026-07-05 Odroid disk-exhaustion incident follow-up: paper-advice log containment, linked-profile scheduler ownership, read-only account snapshot ingestion, static UI freshness contract, rollout/rollback, deferred runtime-host decision |
| `profit_plan_live_ladder.md` | **active P0** | Shortest safe route from Profit Plan detail-page ladder rows to authenticated preview, decision gate, execution plan, executor, and a one-account live limit-order canary; cosmetics follow afterward |
| `profit_plan_dashboard_action_truth_and_breathline_demote_v1.md` | **active P0 guardrail** | Profit Plan dashboard action fail-closed gates, Breathline research-only demotion, stale/current evidence cleanup, and numeric/freshness display correctness before live ladder work |
| `profit_plan_target_lifecycle_history_truth_v1.md` | **open P1 / Synth v2.23** | IOST-discovered target lifecycle regression: verify map-cycle history authority, prevent reached/passed targets returning to UPCOMING after pullback, and fail closed when lifecycle history is incomplete |
| `momentum_flow_scanner_matrix_v1.md` | open research / scanner | FFG-style read-only RSI/MFI momentum-flow matrix, 4% minimum target-upside research gate, scanner buckets, and backtest path for best-entry discovery |
| `ffg_curated_rotation_radar_v1.md` | open research / dashboard | Curated-universe laggard/runner interpretation, normalized flow and RSI/MFI confirmation, market-only rotation classifications, and separate account ownership overlay |
| `profit_plan_card_evidence_delta_visibility_v1.md` | done / parked | P0-C card evidence and deterministic current-vs-previous snapshot delta visibility; read-only presentation only |
| `manual_ladder_dashboard.md` | superseded for active priority / historical source | Earlier read-only manual ladder dashboard direction; retain as historical design input, but active Profit Plan work is tracked in `profit_plan_live_ladder.md` |
| `market_breath.md` | characterized/parked | Market Breath V1 characterized as a regime-dependent rhythm/phase sensor; reopen only for downstream regime/profile use-cases |
| `regime_research.md` | parked while P0 executes | Rotation replay, discovered regime review, symbol breath profile design, and regime interaction audits |
| `watchlist_candidates.md` | open intake | User-thesis watchlist candidates such as KITE before validation/promotion |
| `deploy_runtime.md` | MVP cockpit implemented / ops follow-up | Odroid cockpit runner, dashboard render path, and related operational follow-ups |
| `native_short_runtime_owner_and_scope_status_v1.md` | active / PR B review | Existing 4h market-chain owner now wires the locked native SHORT scope-status and map-level status chain; host deployment remains separate |
| `fibo_zones.md` | open research | Fib target maps, leak-free zone/fib touch evaluation, zone context guardrails, exit ladder profiles, and zone UI overlays |
| `ui_webview.md` | open / secondary | UI/Webview upgrades and styling; non-blocking cosmetics stay behind live ladder repair |
| `signal_matrix_dashboard.md` | parked while P0 executes | Transparent per-asset/per-timeframe primitive signal inventory |
| `breath_curve.md` | parked/open | Breath Curve baseline, non-overlap follow-up, partial-cycle, and regime-gated validation continuation |
| `strategy_candidates.md` | parked/open research | Strategy audit, horizon buckets, later classifier/policy research, and research-lead follow-ups |
| `position_rotation_preview.md` | MVP implemented / parked follow-up | Account-aware read-only cockpit/rotation preview with current price and distance semantics |
| `multi_horizon_fib_dashboard_backlog.md` | parked/foundation follow-up | Read-only dashboard backlog depending on multi-horizon fib research outputs |
| `paper_candidate_contract.md` | future design | Safe adapter path from research candidates to decision_gate; not the Profit Plan ladder-repair mutation contract |
| `dev_ops_hygiene.md` | mostly parked | Codex smoke state, DBeaver/MariaDB access recovery, backup/export hygiene, local untracked-file hygiene |
| `parked_backlog.md` | parked/backlog | A+ archive state and external PRO narrative backlog |

## Active next-step recommendation
Reference letters are stable names for easy discussion. Table order is the current execution order.

| Ref | Priority | Lane | What it is for | Board state | Next decision |
|---:|---:|---|---|---|---|
| **B** | P1 | IOST target lifecycle history truth | Stop a target that was already reached or passed from appearing as still `UPCOMING` after price pulls back below it. | active correctness lane — first | Prove map-cycle-aligned target history and prevent `PASSED`/`REACHED` targets regressing to `UPCOMING`. |
| **C** | P2 | Short Swing / Odroid freshness hygiene | Make sure the displayed pages are genuinely fresh and that disk, timer, or runtime failures cannot silently leave frozen data looking current. | open operational lane — second | Keep repository implementation separate from installed-host activation; verify ownership, timestamps, disk/log bounds, and multi-cycle freshness. |
| **E** | P0 | TODO reconciliation / board maintenance | Keep the repository board truthful so completed work, open work, and priorities are not lost or duplicated across chats. | ongoing maintenance; reconciliation merged in PR #92 | Keep `README.md` and each lane TODO synchronized whenever status or priority changes. |
| **A** | P1 | Profit Plan Live Ladder prerequisites | Make **Fix selected ladder** safe: trustworthy current-map rows, stable identities, fresh account data, and a reviewable server preview before any order mutation. | active, deliberately later | Resume after B/C unless a new dependency changes the order. |
| **D** | P3 | Research / FFG / scanner | Find coins with improving flow, momentum reset, and enough target room across the market without giving research or the scanner trading authority. | open, read-only, deliberately later | Resume as non-blocking research after B/C are controlled. |

Priority is execution order, not architectural importance.

Current shorthand:

```text
B -> C first
E = ongoing board maintenance
A + D = later
```

## Sequencing rationale

B and C are intentionally completed before A:

- **B is a bounded correctness repair.** The native map-level infrastructure already exists; remaining work is the IOST forensic audit, monotonic lifecycle truth, fail-closed history handling, and focused regression coverage.
- **C is a bounded operational prerequisite.** It establishes absolute freshness, installed-host ownership, disk/log bounds, and multi-cycle acceptance that A must later trust. Its implementation surface is smaller than A, although multi-cycle observation may require elapsed runtime rather than more code.
- **A is the larger and higher-risk lane.** It spans canonical ladder consumption, deterministic row identity, authenticated preview, `decision_gate`, `execution_planner`, executor behavior, broker mutation, reconciliation, and a controlled live canary.

Therefore the working order remains:

```text
B correctness truth
-> C freshness and host acceptance
-> A manual ladder-to-trade path
```

Completing B and C first reduces ambiguity and prevents A from building execution authority on lifecycle or freshness assumptions that are still unresolved.

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
| `README.md` | **E — ongoing board maintenance** | Cross-lane execution order, status reconciliation, and stable A–E references |
| `workflow_standard.md` | standard | TODO creation, update, closure, priority, boundary, and commit rules |
| `profit_plan_live_ladder.md` | **A — active P1 / later** | Safe prerequisites and ordered path from canonical ladder truth to authenticated preview, decision gate, execution plan, executor, and a tightly controlled live canary |
| `profit_plan_target_lifecycle_history_truth_v1.md` | **B — active P1 / first** | IOST-discovered lifecycle regression: map-cycle-aligned target history, monotonic reached/passed truth, and fail-closed incomplete-history handling |
| `short_swing_linked_profile_freshness_and_disk_reliability_v1.md` | **C — open P2 / second** | Odroid/runtime ownership, absolute freshness timestamps, disk/log containment verification, rollout, and rollback hygiene |
| `momentum_flow_scanner_matrix_v1.md` | **D — open P3 research / later** | Read-only RSI/MFI momentum-flow scanner, target-room research gate, and validation path |
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
| `dev_ops_hygiene.md` | mostly parked | Development, database-access, backup, worktree hygiene |
| `parked_backlog.md` | backlog | Archived A+ and external-narrative follow-ups |
| `watchlist_candidates.md` | open intake | Human-thesis watchlist intake before validation |

## Next-step rule

With the reconciliation merged:

1. Execute B first.
2. Execute C second.
3. Keep E running as board maintenance.
4. Keep A and D for later.
5. Do not reopen native SHORT implementation work unless new evidence identifies a concrete defect.
6. Do not create several parallel implementation chats merely because the board lists several lanes.

## Pre-live safety state

Until an explicitly reviewed live-canary phase is reached:

```text
broker_writes=0
order_submission=0
executor=none
```
