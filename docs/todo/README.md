# Synth v2 TODO Index

## Purpose

Central TODO workspace for active and parked Synth v2 lanes.

This folder is the working TODO board. Canonical design details stay in their source docs under `docs/research/`, `docs/status/`, `docs/architecture/`, or `docs/ops/`.

## Rule

If a TODO is active or likely to be resumed later, it belongs in this folder.

Avoid scattering active TODOs across chat history, temporary notes, or unrelated research docs.

Workflow standard:

```text
docs/todo/workflow_standard.md
```

## Global boundaries

Unless a task explicitly says otherwise:

- no live trading
- no broker calls
- no broker writes
- no order submission
- no executor changes
- no `run_chain_4h.sh` changes
- no selection/advice/decision/execution changes unless the task explicitly belongs to that layer
- research tasks remain market-only and account-agnostic

Explicit exception:

- `profit_plan_live_ladder.md` is the active controlled execution lane.
- It may introduce authenticated live limit-order mutation only through:
  `decision_gate -> execution_planner -> executor -> broker client`.
- Reporting/UI may never call the broker directly.

Architecture split:

```text
selection_engine = market-only candidate ranking
decision_gate = account-aware permission / conflict resolution
execution_planner = execution intent only
executor / agents = order handling only
```

Do not bypass layers.

## Files

| File | Status | Purpose |
|---|---:|---|
| `workflow_standard.md` | standard | TODO creation, update, closure, priority, boundary, and commit rules |
| `short_swing_linked_profile_freshness_and_disk_reliability_v1.md` | **active P0/P1** | 2026-07-05 Odroid disk-exhaustion incident follow-up: paper-advice log containment, linked-profile scheduler ownership, read-only account snapshot ingestion, static UI freshness contract, rollout/rollback, deferred runtime-host decision |
| `profit_plan_live_ladder.md` | **active P0** | Shortest safe route from Profit Plan detail-page ladder rows to authenticated preview, decision gate, execution plan, executor, and a one-account live limit-order canary; cosmetics follow afterward |
| `manual_ladder_dashboard.md` | superseded for active priority / historical source | Earlier read-only manual ladder dashboard direction; retain as historical design input, but active Profit Plan work is tracked in `profit_plan_live_ladder.md` |
| `market_breath.md` | characterized/parked | Market Breath V1 characterized as a regime-dependent rhythm/phase sensor; reopen only for downstream regime/profile use-cases |
| `regime_research.md` | parked while P0 executes | Rotation replay, discovered regime review, symbol breath profile design, and regime interaction audits |
| `watchlist_candidates.md` | open intake | User-thesis watchlist candidates such as KITE before validation/promotion |
| `deploy_runtime.md` | MVP cockpit implemented / ops follow-up | Odroid cockpit runner, dashboard render path, and related operational follow-ups |
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

```text
1. Execute docs/todo/profit_plan_live_ladder.md as the active P0 lane.
2. First finish only the minimum detail-page and ladder-row semantics needed for safe selection:
   stable map_cycle_id, deterministic row identity, MISSING/STALE-only selection, and complete source timestamps.
3. Audit the authenticated write path, CSRF, account/profile ownership, live permissions,
   decision_gate, execution_planner, executor idempotency, broker create/cancel semantics,
   open-order freshness, and audit persistence.
4. Build server-side preview with explicit sizing and zero broker writes.
5. Build decision-gate approval and deterministic dry-run execution plan.
6. Review all safety assertions.
7. Run one account, one market, low-cap, limit-order-only live canary.
8. Expand to additional coins only after idempotency, audit, revalidation, and refreshed open-order state are proven.
9. After live Fix selected ladder is usable, continue structured scanner filtering/sorting and cosmetic cleanup.
10. Keep 5m Trade Path, historical zone path, T0, wallet styling, deliverability, and mobile polish in later lanes.
```

## Active P0 safety rule

Before the live canary:

```text
broker_writes=0
order_submission=0
executor=none
```

The live canary is allowed only when all of these are explicit and server-derived:

```text
authenticated user
profile/account ownership
live execution permission
broker-write permission
allowlisted account
allowlisted market
approved immutable plan
idempotency key
fresh map, price, balance, position, and open-order snapshots
```

## 2026-05-19 Product/Cockpit/Strategy bundle

- [2026-05-19 Product, Cockpit, Strategy TODO Bundle](2026-05-19_product_cockpit_strategy_bundle.md)
