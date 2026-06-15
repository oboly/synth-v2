# Synth v2 Development Roadmap v1

## Current live status

- main/live: `d7c57af`
- FibNavigationMap emergency/candle-driven rebuild deployed
- `NAVIGATION_ONLY` visible in live Profit Plan JSON
- `fib_nav_context` visible in live Profit Plan JSON
- Odroid venv has pytest installed

## Completed

- FibNavigationMap builder
- candle-driven primary rebuild path
- anchor fallback secondary
- Profit Plan integration
- SXT exhausted-map case no longer collapses to no navigation

## Core architecture rule

Navigation availability is not trade permission.

Pipeline separation:

1. `market_data`
   - candles, ticker/current price, volume, freshness, symbol normalization only

2. `market_context / selection_engine features`
   - market-only deterministic feature objects
   - owns MarketNavigationState, FibNavigationMap, BreathlineState, ImpulseHealthState, TimingState

3. `selection_engine scoring`
   - market-only ranking/classification

4. `decision_gate`
   - account-aware permission only
   - balances, exposure, open orders, risk, broker_writes, manual review

5. `execution_planner`
   - execution intent only
   - creates proposed LadderIntent

6. `executor / agents`
   - only broker/order handling layer

7. `UI / dashboard`
   - display payload and explicit manual actions only

## Forbidden coupling

- market_context must not import account, balances, orders, decision_gate, execution_planner, executor, agents, dashboard
- dashboard must not calculate fibs, breathline, impulse, timing, or permissions
- executor is the only broker-write layer

## Roadmap bundles

### Bundle 1 — Pipeline contracts + guard tests

Goal:
- canonical architecture doc
- executable market-context contracts/enums
- architecture guard tests

No new trading logic.

### Bundle 2 — BreathlineState

Goal:
- market-only breathline/equilibrium state
- states like ABOVE_MA, TESTING_MA, RECLAIMING_MA, SPIKE_COOLING

### Bundle 3 — ImpulseHealthState

Goal:
- classify impulse health
- healthy impulse vs blow-off spike vs cooling pullback vs second bump possible

### Bundle 4 — TimingState

Goal:
- replace vague WAIT / REENTRY_WAIT labels with explicit market-only timing states
- no order intent

### Bundle 5 — Backtest matrix / golden fixtures

Goal:
- SXT, CRV, HOT, ONDO, VET, NEAR, CC regression fixtures
- historical scenario checks and metrics

### Bundle 6 — Manual ladder preview dry-run

Goal:
- LadderIntent preview only
- decision_gate snapshot
- no executor/broker calls

### Bundle 7 — Manual ladder submit safety

Only after Bundle 6 is green.

Goal:
- explicit user click
- broker_writes check
- TTL/freshness
- decision_gate re-check
- idempotency
- audit
- executor boundary

## Process rule

Use small bundles.

Each bundle must report:
- branch name
- files changed
- tests added
- tests run
- docs updated
- architecture boundaries respected
- no deploy/restart/webroot/broker-write confirmation

## Live safety

Do not:
- deploy to Odroid
- restart services
- write to `/var/www/html`
- overwrite live dashboard
- enable broker writes
- submit orders

Use:
- feature branch
- local tests
- docs update
- preview page / feature flag
- dry-run first
