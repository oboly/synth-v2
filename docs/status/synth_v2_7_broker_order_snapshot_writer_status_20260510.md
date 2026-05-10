# Synth v2.7 Broker Order Snapshot Writer Status — 2026-05-10

Status: controlled private-read snapshot writer
Runtime impact: operations only
Decision impact: none
Execution impact: none
Broker write impact: none
Live trading: not enabled

## Purpose

The broker order snapshot writer reads open Bitvavo orders and writes them to `broker_order_snapshot`.

This reconciles Bitvavo reserved balances with actual open broker orders.

## Boundary

Allowed:

- Bitvavo private read: open orders
- DB writes to `broker_order_snapshot`
- one coherent batch timestamp per snapshot run

Forbidden:

- order placement
- order cancellation
- broker write calls
- position mutation
- decision_gate override
- execution_planner override
- executor live activation

## Important safety change

`broker_order_snapshot` rows are now expected once this writer runs.

A nonzero `broker_order_snapshot` count is not evidence of Synth placing orders.

It means Synth has read external broker state.

Hard safety checks remain:

- no broker submission enabled plan
- no live trading enabled plan
- no live trading enabled sell intent
- no execution enabled sell intent
- no broker write permission

## Current limitation

The current broker order snapshot schema accepts sell limit orders only.

The writer therefore stores only EUR-market SELL LIMIT orders and skips anything outside that schema.
