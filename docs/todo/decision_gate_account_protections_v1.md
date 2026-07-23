# TODO — Decision Gate Account Protections v1

## Status

- `future design`
- priority: `P2`
- owner: `decision_gate`
- existing permission model partially covers the boundary; typed protections and locks are still missing

## Sources

- `docs/core/decision_gate_v1.md`
- `docs/ops/multi_user_strategy_account_scope_v1.md`
- `docs/todo/profit_plan_live_ladder.md`
- `docs/todo/backtest_capability_contract_v1.md`
- Freqtrade protections as an architecture reference only; no code dependency or runtime integration

## Current state / facts

The existing Synth decision-gate direction already owns:

- duplicate position, order, and active-plan prevention;
- account and sleeve status;
- balance and available-equity checks;
- exposure, allocation, and account risk limits;
- account-scoped permission before execution planning.

The missing part is an explicit, typed protection contract for temporary account-, sleeve-, or asset-scoped permission blocks based on account outcome history.

These protections are not market regimes, sector rotation, ranking, or execution logic.

## Candidate capabilities

Research and specify at least:

- `MAX_ACCOUNT_DRAWDOWN_BLOCK`;
- `DAILY_REALIZED_LOSS_BLOCK`;
- `REPEATED_STOPLOSS_BLOCK`;
- `LOW_PROFIT_ASSET_COOLDOWN`;
- `POST_CLOSE_REENTRY_COOLDOWN`;
- `MANUAL_ACCOUNT_LOCK`.

A protection may reduce or block permission. It may never raise market rank, create a candidate, force an entry or exit, size an order, or submit an order.

## Required lock contract

Each triggered protection should eventually produce an immutable decision-gate fact with at least:

```text
protection_code
protection_version
trading_account_id
scope_type
scope_id
observed_from_ts_utc
observed_to_ts_utc
triggered_ts_utc
expires_ts_utc
reason_code
evidence_refs
configuration_version
decision_state
```

Initial scope types:

```text
ACCOUNT
SLEEVE
ASSET
```

The contract must define idempotency, overlapping-lock precedence, expiry, explicit manual lock/unlock authority, audit history, and fail-closed behavior for missing or stale account inputs.

## Open tasks by priority

### P1 — Research and contract design

- Inventory existing account, equity, fill, realized-PnL, stoploss, position, order, and risk-configuration sources.
- Define a point-in-time equity curve that separates trading PnL from deposits, withdrawals, transfers, and configuration changes.
- Define precise event semantics for stoplosses, partial exits, manual closes, reopened positions, and repeated losses.
- Decide thresholds, lookback windows, scope, lock duration, and recovery conditions per capability.
- Define how simultaneous account, sleeve, and asset locks compose.
- Define stable reason codes and human-readable reporting without action-sounding labels.
- Keep configuration account-scoped and versioned.

### P1 — Replay and validation design

Declare these protections as:

```text
data_scope=ACCOUNT_STATE_DEPENDENT
asof_policy=POINT_IN_TIME_REQUIRED
```

A protection is `BACKTEST_SAFE` only when the replay has a complete point-in-time account ledger, historical risk configuration, and deterministic clock. Otherwise it is `LIVE_ONLY` or `NO_ACTION_IN_BACKTEST` and must be handled by the backtest capability preflight.

Required validation includes:

- deterministic replay of trigger and expiry;
- deposits/withdrawals not misclassified as strategy drawdown;
- partial fills and partial exits;
- overlapping asset and account locks;
- restart/idempotency behavior;
- stale or missing account state;
- multi-account isolation;
- no cross-account evidence leakage.

### P2 — Minimal implementation

- Add protections inside `decision_gate` after the contract and replay design are accepted.
- Reuse existing account/risk facts where correct; do not create a second portfolio ledger.
- Persist typed lock facts only if required for deterministic restart and audit.
- Add read-only reporting of active and expired protections.
- Keep execution planning and order handling downstream and unchanged.

## Acceptance

- Protection evaluation is account-scoped and deterministic.
- Market-only layers import no account protection code or state.
- A triggered protection produces a typed permission block with evidence and expiry.
- Restart cannot silently clear or duplicate an active lock.
- Backtests cannot substitute current account state for historical account state.
- Reporting is read-only and cannot unlock or mutate protection state.
- No protection creates execution intent or broker activity.
- Multi-account tests prove strict isolation.

## Boundary

```text
selection_engine = unchanged, market-only
sector rotation = unchanged, market-only
decision_gate = account-aware protection owner
execution_planner = unchanged
executor = unchanged
broker_private_calls = 0
broker_writes = 0
order_submission = 0
```

## Non-goals

- No Freqtrade code copy or dependency.
- No market-regime classification.
- No account-performance sorting in `selection_engine`.
- No automatic sell or liquidation path.
- No dashboard-owned risk logic or unlock authority.
- No live activation in this TODO.
