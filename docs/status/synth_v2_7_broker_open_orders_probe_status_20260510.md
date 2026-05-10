# Synth v2.7 Broker Open Orders Probe Status — 2026-05-10

Status: read-only probe
Runtime impact: none
Decision impact: none
Execution impact: none
Broker write impact: none
Live trading: not enabled

## Purpose

The broker open orders probe reads private Bitvavo open orders using the fail-closed private-read guard.

This is needed because `trading_account_balance_snapshot` can show reserved balances while Synth has no `broker_order_snapshot` rows yet.

The probe helps reconcile:

- reserved balances
- open broker orders
- future broker order snapshot ingestion

## Boundary

Allowed:

- private read from Bitvavo
- local terminal report
- no database writes

Forbidden:

- order placement
- order cancellation
- broker write calls
- position mutation
- decision_gate override
- execution_planner override
- executor live activation

## Current source

Module:

- `src.operations.run_broker_open_orders_readonly_probe_v1`

Bitvavo client method:

- `BitvavoClient.get_open_orders`

The method is protected by:

- `SYNTH_BROKER_PRIVATE_READ_PERMISSION`

It is not protected by broker write permission because it does not place or cancel orders.

## Next step after probe

If read-only output is correct, the next controlled step is a broker order snapshot writer.

That writer should map broker open orders into `broker_order_snapshot` without creating, changing, or canceling orders.
