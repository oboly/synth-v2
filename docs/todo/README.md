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
| `market_breath.md` | characterized/parked | Market Breath V1 characterized as a regime-dependent rhythm/phase sensor; reopen only for downstream regime/profile use-cases |
| `regime_research.md` | active next research | Rotation replay rerun/readout, discovered regime full-ish review, symbol breath profile design, regime interaction audit design, and later replay-safe classifier path |
| `watchlist_candidates.md` | open intake | User-thesis watchlist candidates such as KITE before validation/promotion |
| `deploy_runtime.md` | MVP cockpit implemented / ops follow-up | Odroid read-only cockpit runner, dashboard render path, and related operational follow-ups |
| `fibo_zones.md` | open research | Fib target maps, leak-free zone/fib touch evaluation, zone context guardrails, exit ladder profiles, and zone UI overlays |
| `ui_webview.md` | active/open | Read-only chart/UI/Webview upgrades, cockpit sticky columns, reading-flow split, and simplified dashboard design |
| `signal_matrix_dashboard.md` | active next dashboard lane | Transparent per-asset/per-timeframe primitive signal inventory for Synth v2.14, upstream of manual ladder/dashboard composition |
| `breath_curve.md` | parked/open | Breath Curve baseline, non-overlap follow-up, partial-cycle, and regime-gated validation continuation |
| `strategy_candidates.md` | active/open research | Current strategy audit follow-up, horizon bucket design, later classifier/policy research, and research-lead follow-ups |
| `position_rotation_preview.md` | MVP implemented / parked follow-up | Account-aware read-only cockpit/rotation preview with current price and distance semantics; strategy/backtests remain separate |
| `paper_candidate_contract.md` | future design | Safe adapter path from research candidates to decision_gate |
| `dev_ops_hygiene.md` | mostly parked | Codex smoke state, DBeaver/MariaDB access recovery, MariaDB backup/export hygiene, local untracked-file hygiene |
| `parked_backlog.md` | parked/backlog | A+ archive state and external PRO narrative backlog |

## Active next-step recommendation

```text
1. Treat the read-only cockpit, rotation preview semantics, and the committed research runners as completed baseline work.
2. For Synth v2.14 dashboard direction, start with `docs/todo/signal_matrix_dashboard.md`:
   build the transparent primitive signal inventory before more manual ladder/dashboard composition work.
3. Keep `docs/todo/manual_ladder_dashboard.md` downstream from the future signal matrix; do not keep tuning it as the first truth surface.
4. Keep discovered regime comparisons diagnostic only; existing labels may be joined after clustering but must not become clustering input.
5. After the signal-matrix direction is clear, continue `docs/todo/regime_research.md` follow-up work for symbol/profile/regime interaction research.
6. Keep first paper strategy candidate selection blocked until regime/profile research and transparent signal inventory work are in place.
7. Keep Market Breath characterized and parked until a downstream regime-aware or symbol-profile use-case explicitly needs it.
8. Keep astro context parked as external lunar/solar context only; no astro interaction work before discovered regime review and symbol breath profile design exist.
9. Keep A+, PRO, execution, broker, account, and live/paper lanes parked unless directly needed by an explicit task.
```

## 2026-05-19 Product/Cockpit/Strategy bundle

- [2026-05-19 Product, Cockpit, Strategy TODO Bundle](2026-05-19_product_cockpit_strategy_bundle.md)
