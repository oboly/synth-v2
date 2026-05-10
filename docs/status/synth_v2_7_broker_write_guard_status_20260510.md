# Synth v2.7 Broker Write Guard Status — 2026-05-10

Status: active safety guard
Runtime impact: broker write calls fail-closed by default
Decision impact: none
Execution planner impact: none
Market-chain impact: none
Live trading: not enabled

## Purpose

The repository still contains legacy execution paths capable of calling Bitvavo private order endpoints.

The sell-only preview lane is separate and remains broker-disabled, but the legacy adapter now has a hard fail-closed write guard to prevent accidental broker writes.

## Guard

Broker write methods now require the exact environment value:

`SYNTH_BROKER_WRITE_PERMISSION=I_UNDERSTAND_THIS_PLACES_REAL_ORDERS`

Without this exact value, these methods raise `PermissionError` before signing or making a network request:

- `BitvavoClient.place_order`
- `BitvavoClient.cancel_order`

Read-only/public methods are not affected:

- `get_ticker_price`
- `get_book`

Authenticated read-only order status remains separate:

- `get_order`

## Boundary

This guard is not a trading permission system.

It is a lower-level emergency brake inside the broker adapter.

Real trading still requires the normal architecture:

- decision_gate approval
- execution_planner plan
- executor order handling
- explicit live permission
- broker write guard
- account safety checks
- duplicate/open-order checks

## Current state

The sell-only lifecycle preview remains paper-only:

- no broker submission
- no live order submission
- no position mutation
- no broker_order_snapshot rows

Legacy execution paths must not be used as the canonical sell-only runtime without separate audit and approval.

