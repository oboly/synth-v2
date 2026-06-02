# Manual limit buy ladder v1

## Purpose

src/execution/limit_buy_ladder_v1.py provides a manual helper for building Bitvavo limit BUY orders from quote-notional amounts.

Example:

    BUY EUR 15 WLD @ 0.345
    amount = 15 / 0.345 = 43.47826086 WLD

Bitvavo order placement uses base-asset amount plus limit price, not quote notional.

## Boundary

This helper is broker-side manual order tooling.

It is not:

    selection_engine output
    decision_gate permission
    execution_planner intent
    executor automation
    strategy logic

Do not wire this helper into autonomous Synth execution without a separate decision-gate and execution-planner design.

## Safety

Real order placement remains fail-closed through BitvavoClient.place_order.

Required controls:

    confirm_real_orders=True
    SYNTH_BROKER_WRITE_PERMISSION=I_UNDERSTAND_THIS_PLACES_REAL_ORDERS

When using short-lived manual runner scripts, remember that bitvavo_client.py loads .env with override behavior. If needed, set the write permission after imports inside the temporary runner.

## Design

The helper converts quote notional to base amount:

    quote_notional / limit_price = base amount

It builds BitvavoOrderRequest objects with:

    side=buy
    order_type=limit
    time_in_force=GTC
    post_only configurable, default true

## Operational rule

Keep manual order scripts temporary unless promoted intentionally.

Do not commit one-off order placement files under /tmp or repo paths.
