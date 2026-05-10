# Sell-Only Limit Execution Lane V1

Status: design-only  
Runtime impact: none  
Decision/execution impact: none  
Live trading: not enabled  
Broker calls: not enabled  

## Purpose

This document defines the first minimal execution lane for Synth after the market-only chains.

The first broker-capable path should be:

- sell-only
- limit-order only
- position-reducing only
- no buys
- no market orders
- no orderbook dependency
- no automatic live trading

The goal is to safely test account-aware and broker-aware infrastructure without introducing new exposure.

## Current runtime boundary

Current active cron chains are market-only:

- observation
- feature
- signal
- advice
- ranking
- measurement
- selection
- trade setup filter
- trade setup policy preview
- strategy runtime snapshot

The current chains explicitly do not activate:

- decision_gate
- execution_planner
- executor
- broker adapter
- live trading

## Architectural boundary

Layer responsibilities remain strict.

| Layer | Responsibility |
|---|---|
| selection_engine | Market-only ranking/state. No account, position, balance, order, or broker logic. |
| trade_setup_filter | Market-only setup filter. No account, position, balance, order, or broker logic. |
| policy_preview | Research/policy visibility. No permission to trade. |
| decision_gate | Account-aware permission layer. Not started. |
| execution_planner | Converts approved intent into execution plan. Not started. |
| executor/broker | Places/cancels/reads orders. Not started. |

The broker must not contain strategy logic.

## Sell-only V1 scope

Allowed future action type:

- LIMIT_SELL

Explicitly not allowed:

- BUY
- MARKET_BUY
- MARKET_SELL
- STOP_LOSS_MARKET
- TRAILING_STOP
- margin/futures/leverage
- automatic reinvestment
- orderbook-driven placement
- uncontrolled repricing

## Required preconditions before any sell-only order

A sell-only order may only be planned after all of the following exist:

1. Account model exists.
2. Position table exists.
3. Position quantity is known.
4. Decision gate confirms sell permission.
5. Execution planner creates a sell-only execution intent.
6. Executor verifies live/paper mode.
7. Broker adapter is explicitly configured.
8. Live trading flag remains false unless manually enabled later.

## Minimal sell-only intent shape

A future execution intent may contain:

- account_id
- asset_id
- symbol
- venue
- side = SELL
- order_type = LIMIT
- quantity_base
- limit_price_eur
- reduce_only = true
- reason_code
- source_signal_ts_utc
- created_ts_utc

This belongs after decision_gate approval.

## Price source for V1

V1 does not require orderbook input.

Acceptable initial price sources:

- latest candle close
- latest ticker price
- exit profile target
- fixed passive limit offset

Example concept:

- if target_exit_price exists, use it as floor
- otherwise use latest reference price
- optional passive offset may be applied by execution_planner

The broker adapter should only receive the final price. It should not decide strategy, timing, or target price.

## Broker adapter minimal interface

The broker adapter should remain intentionally dumb:

- place_limit_sell(symbol, quantity_base, limit_price)
- cancel_order(order_id)
- get_order(order_id)
- get_open_orders(symbol=None)

No strategy scoring.  
No selection reads.  
No decision reads.  
No account policy decisions.  

## Why sell-only first

Sell-only is safer because it can only reduce existing exposure.

This allows testing:

- broker authentication
- order placement plumbing
- order status reads
- cancel behavior
- DB event logging
- paper/live parity

without allowing the system to open new positions.

## Future extension

Orderbook-aware execution can be added later, but only inside execution_planner or a dedicated execution microstructure module.

Future optional inputs:

- spread
- top-of-book depth
- orderbook imbalance
- queue priority
- passive/aggressive execution mode
- reprice limits

These must not be introduced in the broker adapter itself.

## Hard rule

No live broker order path may be activated until decision_gate exists and blocks:

- no position
- unknown position
- open order already exists
- active execution plan already exists
- insufficient balance/asset quantity
- disabled account
- disabled sleeve
- live trading disabled
