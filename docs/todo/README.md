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
| `market_breath.md` | active | Market Breath V1.1 calibration, neutral rest-bucket review, optional threshold patch, outcome validation path |
| `watchlist_candidates.md` | open intake | User-thesis watchlist candidates such as KITE before validation/promotion |
| `deploy_runtime.md` | open/future ops | Odroid deploy, candle ingestion runners, webview data refresh runners, runtime orchestration |
| `fibo_zones.md` | parked/open | Fib target maps, zone context guardrails, exit ladder profiles, and zone UI overlays |
| `ui_webview.md` | parked/open | Read-only chart/UI/Webview upgrades and documentation |
| `breath_curve.md` | parked/open | Breath Curve baseline, partial-cycle, and regime-gated validation continuation |
| `strategy_candidates.md` | open design | Horizon bucket design and same-asset candidate conflict rules |
| `paper_candidate_contract.md` | future design | Safe adapter path from research candidates to decision_gate |
| `dev_ops_hygiene.md` | mostly parked | Codex smoke state, DBeaver/MariaDB access recovery, MariaDB backup/export hygiene, local untracked-file hygiene |
| `parked_backlog.md` | parked/backlog | A+ archive state and external PRO narrative backlog |

## Active next-step recommendation

```text
1. Finish Market Breath V1.1 audit interpretation cleanup.
2. Review whether NEUTRAL_TRANSITION should remain the large rest bucket.
3. Decide whether a Market Breath threshold-calibration patch is needed or skipped.
4. Only then open Market Breath outcome validation.
5. Keep Watchlist, Deploy/Runtime, Fibo/Zones, UI/Webview, Dev/Ops, Breath Curve, A+, and PRO lanes parked unless directly needed.
```
