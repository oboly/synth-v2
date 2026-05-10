# Synth v2.7 Broker Account Position Snapshot Status — 2026-05-10

Status: local DB snapshot writer
Runtime impact: operations only
Decision impact: none
Execution impact: none
Broker write impact: none
Live trading: not enabled

## Purpose

The broker account position snapshot writer converts the latest private broker balance snapshot into `account_position_snapshot` rows.

This gives account-aware layers a local position source without requiring a broker call during decision checks.

## Source

Input:

- `trading_account_balance_snapshot`
- `asset`
- `obs_market_candle`

Output:

- `account_position_snapshot`

## Boundary

Allowed:

- read latest balance snapshot
- read local candle price
- write account position snapshot rows

Forbidden:

- broker API calls
- broker writes
- order placement
- order cancellation
- account mutation outside append-only snapshot history
- decision_gate override
- execution_planner override
- executor live activation

## Timestamp rule

The writer uses the balance snapshot timestamp as the position snapshot timestamp.

This keeps balance and position snapshots aligned.

## Idempotence rule

If the same account / venue / source / timestamp / symbol already exists, the writer reuses the existing row instead of inserting a duplicate.
