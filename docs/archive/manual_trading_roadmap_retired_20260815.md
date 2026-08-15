# Manual trading roadmap retirement — 2026-08-15

## Decision

Manual BUY/SELL trading is no longer a target Synth v2 execution workflow.

The active roadmap is algorithm-driven and preserves the canonical layer boundaries:

```text
market-only candidate / policy
-> decision_gate account permission
-> execution_planner immutable intent
-> shared executor
-> broker
-> reconciliation
```

Current owning Issues:

- `#392` — algorithm-driven SELL exit lane;
- `#399` — algorithm-driven BUY entry/re-entry lane;
- `#206` — shared side-neutral BUY/SELL executor/runtime boundary.

## Retired TODO documents

The following frozen manual-workflow documents were removed from `docs/todo/`:

- `manual_execution_ladder_profiles_v1.md`;
- `manual_execution_ladder_future_readiness_backlog_v1.md`;
- `credential_scope_and_manual_ladder_execution_boundary_v1.md`.

Their historical content remains available in Git history. It must not be used as current execution order, priority, or product direction.

## Retired Issues

- `#369` manual SELL live submission was closed as superseded/not planned;
- `#368` manual-only `EXIT_PASSIVE_LIMIT` cleanup was closed as superseded/not planned.

Reusable safety/executor work produced by the historical lane is not discarded. Generic primitives such as deterministic client-order identity, per-leg persistence, crash-safe submission, credential binding, broker state handling, and reconciliation are to be generalized/reused under `#206` when appropriate.

## Explicit non-goals

Do not revive as roadmap work:

- manual SELL productization;
- manual BUY order workflow;
- execution tray as a prerequisite for trading;
- typed human confirmation as the normal algorithmic authority path;
- manual SELL canary as a prerequisite for automatic SELL;
- dashboard handlers that directly create broker orders.

Operator safety controls remain required, including kill switch, reconciliation, cancellation/recovery controls, and explicit bounded LIVE authority. Those are operational controls, not a parallel manual trading strategy path.
