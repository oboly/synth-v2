# Synth v2.7 Broker Reserved Reconciliation Status — 2026-05-10

Status: read-only reconciliation report
Runtime impact: none
Decision impact: none
Execution impact: none
Broker write impact: none
Live trading: not enabled

## Purpose

The broker reserved reconciliation report compares:

- `trading_account_balance_snapshot.reserved_amount`
- `broker_order_snapshot.remaining_quantity_base`

For sell limit orders, Bitvavo reserves base asset quantity. Therefore the reserved balance per currency should match the summed remaining quantity of open sell limit orders for that symbol.

## Scope

Input tables:

- `trading_account_balance_snapshot`
- `broker_order_snapshot`
- `trading_account`

No broker API calls are made by this report.

## Boundary

Allowed:

- read local DB snapshots
- compare latest balance batch to latest order batch
- report mismatches

Forbidden:

- broker calls
- DB writes
- order placement
- order cancellation
- position mutation
- decision_gate override
- execution_planner override
- executor live activation

## Interpretation

A match means current Bitvavo reserved balances are explained by open sell limit orders.

A mismatch means one of the following may be true:

- snapshots were taken at different moments and broker state changed between reads
- unsupported order type exists
- schema mapping missed a field
- broker returned a partial/different state
- rounding tolerance is too strict

Mismatch does not automatically mean danger, but it blocks the next step until understood.
