# TODO — Backtest Capability Contract v1

## Status

- `future design`
- priority: `P2`
- owner: research / backtest infrastructure
- cross-lane architecture guardrail; not the current execution lane

## Sources

- `AGENTS.md`
- `docs/development/github_issues_workflow.md` (legacy: `docs/todo/workflow_standard.md`)
- `docs/todo/historical_breath_regime_context_backlog.md`
- existing runners under `src/backtest/` and `src/research/`
- Freqtrade capability metadata as an architecture reference only; no code dependency or runtime integration

## Current state / facts

- Synth already has multiple backtest, replay, validation, and historical-context runners.
- Standing rules require point-in-time inputs and prohibit joining current or latest state onto historical timestamps.
- Individual runners contain local safety rules, but there is no common machine-readable capability declaration or composition preflight.
- A flat compatibility flag is insufficient: replay support, data scope, as-of policy, and side effects are separate dimensions.
- Existing runners remain valid until audited; this TODO does not authorize a broad rewrite.

## Contract direction

Each composable research, filter, regime, rotation, or protection component must eventually declare at least:

```text
component_id
component_version
owner_layer
replay_support
data_scope
asof_policy
side_effect_policy
output_namespace
```

Initial enums:

```text
replay_support =
  BACKTEST_SAFE
  LIVE_ONLY
  NO_ACTION_IN_BACKTEST
  LOOKAHEAD_RISK

data_scope =
  MARKET_ONLY
  ACCOUNT_STATE_DEPENDENT

asof_policy =
  POINT_IN_TIME_REQUIRED
  CURRENT_ONLY

side_effect_policy =
  READ_ONLY
  RESEARCH_NAMESPACE_WRITE
  OPERATIONAL_WRITE_FORBIDDEN
```

These fields are orthogonal. For example, an account-state-dependent protection is not automatically unsafe, but it is backtest-safe only when point-in-time account state is available and declared.

## Open tasks by priority

### P1 — Inventory and specification

- Inventory current backtest/replay entrypoints and the components they compose.
- Record each component's real data dependencies, as-of semantics, side effects, and output namespace.
- Identify current uses of latest-state joins, live-only inputs, account state, non-deterministic ordering, or future-aware fields.
- Define one canonical capability schema and validation contract before selecting a registry or implementation abstraction.
- Map existing local runner safeguards into the contract without duplicating rules across documents.

### P1 — Composition preflight

Design a runner preflight that:

- accepts `BACKTEST_SAFE` components only when all declared point-in-time prerequisites are satisfied;
- rejects `LIVE_ONLY` and `LOOKAHEAD_RISK` components in replay/backtest mode;
- permits `NO_ACTION_IN_BACKTEST` only when the omission is explicit in the run manifest and cannot change silently;
- rejects `ACCOUNT_STATE_DEPENDENT` components when no point-in-time account ledger/configuration exists;
- rejects operational-table writes and ambiguous output namespaces;
- emits the resolved component order and capabilities in the run manifest;
- fails closed before computation or writes when the composition is invalid.

### P2 — Minimal implementation

- Add the smallest reusable contract and preflight after the inventory identifies the actual common boundary.
- Avoid a plugin framework unless multiple current components genuinely require one.
- Add focused tests for valid market-only replay, live-only rejection, look-ahead rejection, account-state rejection without a historical ledger, and explicit no-action behavior.
- Migrate runners incrementally; do not perform a broad flag-only retrofit that claims safety without dependency validation.

## Acceptance

- Every migrated component has explicit capability metadata.
- Historical runs use point-in-time inputs only.
- Invalid compositions fail before computation or writes.
- Run outputs record component versions, order, capability decisions, and omitted no-action components.
- `latest` state cannot silently enter a historical run.
- Account-aware components cannot be replayed from current balances, positions, orders, or settings.
- Research/backtest outputs remain outside operational runtime truth.
- Existing accepted runners are not reclassified as safe without evidence.

## Boundary

```text
research/backtest infrastructure only
no selection_engine behavior change
no decision_gate behavior change
no execution_planner change
no executor change
no broker calls
no broker writes
no order submission
no operational runtime-table backfill
```

## Non-goals

- No Freqtrade dependency or code copy.
- No second trading runtime.
- No claim that capability metadata alone proves absence of leakage.
- No automatic promotion from research/backtest into live selection or permission.
- No account-performance ranking in `selection_engine`.
