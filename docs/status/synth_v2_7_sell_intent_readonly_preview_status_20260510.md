# Synth v2.7 Sell Intent Read-Only Preview Status — 2026-05-10

Status: read-only decision_gate intent preview
Runtime impact: none
Decision impact: none
Execution impact: none
Broker impact: none
Live trading: not enabled

## Purpose

The sell intent read-only preview checks whether a requested sell quantity would pass the account-aware permission layer based on local account state.

It reads:

- `trading_account`
- latest `account_position_snapshot`
- latest `broker_order_snapshot`
- execution safety tables

It reports:

- requested sell quantity
- available quantity
- reserved quantity
- open sell order quantity
- blocker reasons
- preview state
- actual execution permission

## Boundary

Allowed:

- read local DB state
- validate local position quantity
- validate available quantity
- compare reserved quantity against open sell orders
- report preview-only decision outcome

Forbidden:

- DB writes
- broker calls
- order placement
- order cancellation
- execution_planner calls
- executor calls
- live activation

## Important distinction

`WOULD_APPROVE_SELL_INTENT_PREVIEW` is not execution permission.

Actual execution permission remains:

`NOT_GRANTED`
