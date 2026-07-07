# Pipeline Contracts — Synth v2

## Purpose

This document defines the canonical layer responsibilities, allowed dependencies, forbidden dependencies, and contract rules for the Synth v2 pipeline.

It is the reference for architecture guard tests and Claude implementation bundles.

## Core rule

Navigation availability is not trade permission.

Market-context modules describe market structure only. Account permission, execution intent, and broker actions belong to separate layers.

A `MarketObserverSnapshot` is market observation, not trade permission.

## Layer responsibilities

| Layer | Modules | Responsibility | Must not do |
|---|---|---|---|
| market_data | `src/market_data/` | Candles, ticker/current price, volume, freshness, symbol normalization | Account logic, scoring, ladders, orders |
| market_context / features | `src/market_context/`, `src/features/`, `src/measurement/` | Market-only deterministic feature objects, market navigation, canonical regime forwarding, future market-observer aggregation | Account state, orders, decision_gate, execution planning, broker calls |
| selection_engine | `src/selection/` | Market-only ranking and setup classification | Balances, exposure, open orders, broker calls |
| decision_gate | `src/decision_gate/` | Account-aware permission checks | Fibs, local MA/ATR context, impulse, timing, order placement |
| execution_planner | `src/execution_planner/` | Execution intent and proposed plans only | Broker calls, market feature calculation, permission bypass |
| executor / agents | `src/executor/`, `src/execution/` | Broker/order handling, idempotency, audit, failure handling | Market scoring, feature calculation, strategy selection |
| UI / dashboard | `apps/`, `src/reporting/` | Display payload and explicit manual user actions | Hidden order logic, market feature calculation, permission inference |

## Module ownership rule

Each market-context feature must have a clear contract and must be developed through its own bounded bundle.

Allowed market-context module group pattern:

    contracts/model file
    pure builder file
    serializer/adapter file if required
    matching unit test file
    one canonical docs section

Claude implementation bundles must explicitly list allowed modified files. All other files are inspect-only.

Bundle 1 may only modify:

    docs/architecture/pipeline_contracts.md
    src/market_context/__init__.py
    src/market_context/contracts_v1.py
    tests/test_pipeline_contract_boundaries_v1.py

## Allowed import direction

Pipeline dependencies must flow one way:

    market_data
      -> market_context / features
      -> selection_engine
      -> decision_gate
      -> execution_planner
      -> executor / agents / execution
      -> broker / exchange

`market_observer` is an aggregate inside `market_context / features`; it is not an additional execution layer.

UI/reporting may read prepared payloads, but must not calculate market features or create hidden order behavior.

## Forbidden imports

| Layer | Forbidden imports |
|---|---|
| market_data | decision_gate, execution_planner, executor, agents, execution, broker, account, balance, orders, dashboard, view, apps |
| market_context / features | decision_gate, execution_planner, executor, agents, execution, broker, account, balance, orders, dashboard, view, apps |
| selection_engine | decision_gate, execution_planner, executor, agents, execution, broker, account, balance, orders |
| decision_gate | execution_planner, executor, agents, execution, broker |
| execution_planner | executor, agents, execution, broker, market feature builders |
| executor / agents | selection_engine, market_context feature builders, strategy scoring |
| UI / reporting | broker write APIs, executor submit/cancel calls, decision_gate mutation, execution_planner mutation |

## MarketNavigationState contract

`MarketNavigationState` is the top-level symbol-level market-context aggregate object.

It must be account-agnostic and market-only.

It aggregates:

    symbol
    navigation_regime
    fib_map_state
    fib_map_confidence
    local_ma_atr_state
    impulse_health_state
    timing_state
    freshness_state
    warnings
    computed_at_utc

`computed_at_utc` must be an ISO-8601 UTC string so the object is JSON-safe without a custom serializer.

## MarketObserverSnapshot contract

`MarketObserverSnapshot` is the future market-wide / cross-symbol aggregate object. It belongs inside `market_context`; it does not replace `MarketNavigationState`.

It may aggregate:

    canonical global and asset-class regime context
    BTC structure and range state
    ETH relative-strength state
    alt breadth and participation state
    sector leadership and rotation state
    per-symbol descriptive setup context
    external research overlay references
    freshness, warnings, and evidence references

It must remain account-agnostic, market-only, evidence-linked, and descriptive.

It must not:

    grant permission
    emit BUY or SELL commands
    emit allocation or sizing
    create execution intent
    call a broker
    overwrite canonical regime observations
    silently treat external research as measured market truth

The canonical contract is `docs/architecture/market_observer_contract_v1.md`.

## Always-emitted rule

Every candidate/card must be able to emit a `MarketNavigationState`.

If data is unavailable, stale, or unreliable, emit explicit sentinel states:

    NO_DATA
    STALE
    LOW_CONFIDENCE

Do not return `None` in place of market navigation.

A future market observer must follow the same explicit-state rule. It must emit an evidence/freshness downgrade rather than silently invent a market-wide conclusion.

## Navigation vs permission

These are market observations:

    navigation_regime = BULLISH
    timing_state = PULLBACK_ENTRY_ZONE
    timing_state = RECLAIM_CONFIRMED
    rotation_observation_state = SELECTIVE_ROTATION
    alt_breadth_state = EXPANDING_SELECTIVELY

They do not mean:

    allowed to buy
    submit a buy order
    permission granted

Trade permission belongs only to `decision_gate`.

Execution intent belongs only to `execution_planner`.

Broker writes belong only to `executor / agents`.

## Target lifecycle vs fib-map lifecycle

Target lifecycle and fib-map lifecycle are separate.

Completed or exhausted targets mean the old target lifecycle is complete. They do not mean market navigation disappears.

A stale or exhausted fib map should trigger a refresh attempt when market data allows it.

A map rebuild must not automatically cancel, replace, or submit orders. It may emit warnings for human review.

External level maps remain external overlays until a dedicated builder or validation lane establishes their relation to an internal map. A chart zoom change does not create a new map by itself.

## Canonical market-context states

Market-context contracts must use explicit states aligned with the golden cases.

Required sentinel states:

    NO_DATA
    STALE
    LOW_CONFIDENCE

`local_ma_atr_context` is local per-symbol MA/ATR trend context. It is not the future universal breathline model.

`breathline` is reserved for a future universal market breathline / A+ phase model and must not be used for per-symbol MA/ATR context naming.

Local MA/ATR examples:

    ABOVE_MA
    TESTING_MA
    BELOW_MA
    RECLAIMING_MA
    EXTENDED_ABOVE_MA
    SPIKE_COOLING

Impulse health examples:

    HEALTHY_IMPULSE
    EARLY_IMPULSE
    EXTENDED_IMPULSE
    BLOW_OFF_SPIKE
    DISTRIBUTION_RISK
    COOLING_PULLBACK
    SECOND_BUMP_POSSIBLE
    FAILED_RECLAIM

Timing examples:

    WAIT_FOR_PULLBACK
    WAIT_FOR_BREAKOUT
    WAIT_FOR_RECLAIM
    RECLAIM_CONFIRMED
    BREAKOUT_CONFIRMED
    PULLBACK_ENTRY_ZONE
    NO_CHASE_EXTENDED
    TOO_LATE
    FAILED_RECLAIM

## Live safety

Do not do these from market-context, docs, tests, or rendering work:

    deploy to Odroid
    restart services
    write to /var/www/html
    enable broker writes
    submit orders
    cancel orders
    bypass decision_gate
    call broker APIs

All live execution requires explicit user action, broker write permission, decision_gate re-check, idempotency, and executor boundary.

For SHORT / MEDIUM / LONG horizon ownership and the A+ / universal Breathline strategy contract, see `docs/architecture/multi_horizon_aplus_breathline_strategy_contract_v1.md`.

For future cross-market observation ownership, see `docs/architecture/market_observer_contract_v1.md`.
