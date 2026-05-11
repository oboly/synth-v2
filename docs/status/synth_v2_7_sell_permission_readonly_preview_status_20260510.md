# Synth v2.7 Sell Permission Read-Only Preview Status — 2026-05-10

Status: read-only decision_gate preview
Runtime impact: none
Decision impact: none
Execution impact: none
Broker impact: none
Live trading: not enabled

## Purpose

The sell permission read-only preview shows what the account-aware layer can infer from local account state.

It reads:

- `trading_account`
- latest `account_position_snapshot`
- latest `broker_order_snapshot`
- execution safety tables

It reports, per symbol:

- whether a local position exists
- available quantity
- reserved quantity
- open sell order quantity
- whether a read-only sell preview is possible
- actual execution permission

## Boundary

Allowed:

- read local DB state
- compare reserved quantity against open sell orders
- report preview-only sell availability

Forbidden:

- broker calls
- DB writes
- order placement
- order cancellation
- selection_engine overrides
- execution_planner instructions
- executor activation

## Important distinction

`may_sell_readonly_preview=YES` means only that local account data indicates available quantity exists.

It does not grant execution permission.

Actual execution permission remains:

`NOT_GRANTED`
