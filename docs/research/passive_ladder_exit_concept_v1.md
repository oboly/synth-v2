# Passive Ladder Exit Concept v1

## Status

Research/design note only.

This document defines a future execution-planner capability for passive exit execution quality.

No implementation is active from this document.

## Scope

PASSIVE_LADDER_EXIT is a future execution-planner concept for improving the exit price of an already-approved sell intent.

It does not create sell intent.

It does not decide whether a position should be sold.

It does not select assets.

It does not submit orders.

## Core idea

When a real sell intent already exists, and the exit is not urgent, Synth may eventually choose to place small passive sell slices inside the bid/ask spread instead of immediately crossing the spread.

The goal is execution quality:

    sell better than immediate bid
    avoid unnecessary taker spread loss
    capture available spread when liquidity allows

This is only useful when the system is already allowed to sell and can afford patience.

## Architecture boundary

Correct layer ownership:

    selection_engine
      - market-only
      - account-agnostic
      - no exit execution behavior
      - no passive ladder logic

    decision_gate
      - account-aware permission layer
      - may approve or block exit intent
      - does not design ladder prices
      - does not place orders

    execution_planner
      - future owner of PASSIVE_LADDER_EXIT intent
      - converts approved exit permission into an execution plan
      - determines whether passive ladder is suitable

    executor / agents
      - future owner of actual order handling
      - may place, monitor, cancel, or replace orders only from approved execution plans

Hard rule:

    PASSIVE_LADDER_EXIT may only exist after decision_gate grants exit permission.

## Non-goals

This concept is not:

    a trading signal
    a selection modifier
    a decision gate rule
    a market-making bot
    a spoofing system
    a liquidity manipulation method
    a way to lure buyers
    a direct-sell emergency path

## Use cases

Valid future use cases:

    take-profit slicing
    position trim
    manual de-risk exit
    patient exit
    low-urgency sell
    thin-book exit optimization

Invalid or poor-fit use cases:

    urgent stop-loss
    hard thesis invalidation
    liquidity collapse
    risk-off dump
    emergency exit
    decision_gate hard block
    no-position context
    entry logic

## Urgency model

PASSIVE_LADDER_EXIT is only suitable for low or medium urgency.

    URGENT_EXIT
      - sell must happen now
      - passive ladder is usually wrong
      - use urgent limit / market-like execution path

    PATIENT_EXIT
      - sell is desired but not time-critical
      - passive ladder may be useful

    TAKE_PROFIT_EXIT
      - partial profit-taking
      - passive ladder may be highly suitable

    MANUAL_DE_RISK_EXIT
      - controlled position reduction
      - passive ladder may be suitable

Initial eligibility rule:

    exit_permission = APPROVED
    position_exists = true
    sell_urgency in [LOW, MEDIUM]
    spread_edge_available = true

## Anti-manipulation guardrails

All orders must represent genuine sell intent.

Required guardrails:

    1. Only use for an existing position.
    2. Only use after exit permission exists.
    3. Every order must be a real sell order that may fill.
    4. Never place fake liquidity.
    5. Never place orders only to influence buyers.
    6. Never use opposite-side orders to shape the book.
    7. Never create sell pressure illusions.
    8. Never cancel solely because the market reacted.
    9. Cancel/replace only for deterministic execution reasons.
    10. Preserve full auditability in execution events.

Valid deterministic cancel/replace reasons may include:

    price moved away
    spread disappeared
    order became stale
    volatility exceeded guardrail
    decision_gate revoked permission
    execution plan expired
    risk state changed
    better urgent path became necessary

Invalid cancel/replace reasons:

    buyer noticed the order
    order achieved visual pressure
    book moved because of our displayed order
    we only wanted to tease liquidity

## Passive sell ladder concept

Example market:

    last_close = 10.00
    best_bid   =  9.00
    best_ask   = 11.00

Immediate market-like sell likely fills near:

    9.00

Passive ladder may propose real sell slices inside the spread:

    10.99
    10.70
    10.40
    10.10
    9.90
    9.60

These levels are only valid if the system is genuinely willing to sell at those prices.

## Execution quality metric

Gross passive edge versus immediate bid:

    passive_edge_pct =
      (expected_passive_avg_fill_price - best_bid)
      / best_bid
      * 100

Net passive edge:

    net_passive_edge_pct =
      passive_edge_pct
      - maker_fee_pct
      - adverse_selection_buffer_pct
      - timeout_penalty_pct

Future planner should require:

    net_passive_edge_pct >= minimum_required_edge_pct

If not:

    execution_plan_type = NO_PASSIVE_EDGE

## Suitability checks

Future execution planner should check:

    spread_pct >= minimum_spread_pct
    book_depth_is_sufficient = true
    tick_size_allows_ladder = true
    sell_urgency != HIGH
    position_size_can_be_sliced = true
    expected_net_edge_positive = true

Potential rejection reasons:

    SPREAD_TOO_SMALL
    INSUFFICIENT_EDGE
    URGENCY_TOO_HIGH
    POSITION_TOO_SMALL
    BOOK_TOO_THIN
    VOLATILITY_TOO_HIGH
    NO_EXIT_PERMISSION
    NO_POSITION

## Research preview option

A future research-only preview may measure whether passive exits would have improved execution quality.

Allowed research preview inputs:

    symbol
    venue
    asof_ts_utc
    best_bid
    best_ask
    last_close
    tick_size
    fee assumptions
    spread
    public orderbook snapshot

Forbidden research preview inputs:

    account balance
    actual position size
    private orders
    private fills
    private API calls
    broker writes
    order ids
    portfolio state

Potential preview output:

    symbol
    venue
    asof_ts_utc
    best_bid
    best_ask
    last_close
    spread_pct
    ladder_levels_json
    estimated_passive_avg_price
    gross_passive_edge_pct
    net_passive_edge_pct
    preview_status
    rejection_reason
    created_at

This preview must remain market-data-only and account-agnostic.

## Future integration path

Correct path:

    research/design note
      -> optional read-only preview
      -> validation report
      -> execution_planner intent design
      -> decision_gate permission integration
      -> executor implementation

Forbidden path:

    research/design note
      -> selection_engine modifier
      -> direct order placement

## Architectural decision

PASSIVE_LADDER_EXIT should not be implemented now as active execution behavior.

The concept is worth preserving because it may improve exits during patient take-profit or controlled de-risk scenarios.

The use case is narrower than direct sell execution.

Final boundary:

    Spread capture is allowed as execution quality improvement.
    Spread creation or buyer manipulation is not allowed.
