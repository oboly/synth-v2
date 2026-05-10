# Synth v2.7 Broker Account Valuation Status — 2026-05-10

Status: read-only valuation report
Runtime impact: none
Decision impact: none
Execution impact: none
Broker write impact: none
Live trading: not enabled

## Purpose

The broker account valuation report values the latest private broker balance snapshot in EUR using local market candles.

It combines:

- `trading_account_balance_snapshot`
- `broker_order_snapshot`
- `obs_market_candle`
- `asset`

## Boundary

Allowed:

- read local DB snapshots
- use local market candle close price
- report available / reserved / total value in EUR
- report open sell-limit order notional

Forbidden:

- broker API calls
- DB writes
- order placement
- order cancellation
- position mutation
- decision_gate override
- execution_planner override
- executor live activation

## Interpretation

`total_value_eur` is current mark-value based on local latest candle close.

`open_order_limit_notional_eur` is not current value. It is the future notional if current open sell limit orders fill at their limit prices.

This report is portfolio visibility only. It is not permission to trade.
