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
| `market_breath.md` | characterized/parked | Market Breath V1 characterization as a regime-dependent state/risk-timing sensor |
| `watchlist_candidates.md` | open intake | User-thesis watchlist candidates such as KITE before validation/promotion |
| `deploy_runtime.md` | MVP cockpit implemented / ops follow-up | Odroid read-only cockpit runner, dashboard render path, and related operational follow-ups |
| `fibo_zones.md` | open research | Fib target maps, leak-free zone/fib touch evaluation, zone context guardrails, exit ladder profiles, and zone UI overlays |
| `ui_webview.md` | parked/open | Read-only chart/UI/Webview upgrades and documentation |
| `breath_curve.md` | parked/open | Breath Curve baseline, non-overlap follow-up, partial-cycle, and regime-gated validation continuation |
| `strategy_candidates.md` | active next research | Current strategy audit follow-up, forward-return backtests, horizon bucket design, and research-lead follow-ups |
| `position_rotation_preview.md` | MVP implemented / parked follow-up | Account-aware read-only cockpit/rotation preview with current price and distance semantics; strategy/backtests remain separate |
| `paper_candidate_contract.md` | future design | Safe adapter path from research candidates to decision_gate |
| `dev_ops_hygiene.md` | mostly parked | Codex smoke state, DBeaver/MariaDB access recovery, MariaDB backup/export hygiene, local untracked-file hygiene |
| `parked_backlog.md` | parked/backlog | A+ archive state and external PRO narrative backlog |

## Active next-step recommendation

```text
1. Treat the MVP read-only cockpit/timer path, current-price snapshot display,
   and rotation distance semantics as implemented baseline behavior.
2. Keep strategy and backtest work in the research lane; next priority is the
   forward-return sequence in `docs/research/current_strategy_audit_v1.md`.
3. Keep first paper strategy candidate selection blocked until selection/setup
   forward-return validation is complete.
4. Review current Watchlist candidate intake for APT/KITE/SXT before any further
   universe/runtime decision.
5. Keep Market Breath characterized and parked until a downstream regime-aware
   use-case explicitly needs it.
6. Keep A+, PRO, execution, broker, and live/paper lanes parked unless directly
   needed by an explicit task.
```
