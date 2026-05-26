# Position Lifecycle Spike Harvest Preview V1

## Status

Canonical read-only preview note for the account-aware rotation lane.

No executor.
No simulated fills.
No order submission.
No live trading.

## Purpose

Define a small read-only position-lifecycle preview for existing holdings so the
manual cockpit can surface:

- `TRIM_REVIEW`
- `RELOAD_REVIEW`
- `HOLD`
- `REDUCE_REVIEW`

This preview is meant to help the user review spike-harvest and pullback/reload
context for positions they already hold manually.

## Where It Belongs

This preview belongs in the account-aware review/dashboard lane:

```text
account_position_snapshot
+ market_price_snapshot
+ paper_advice_observation
+ zone / target / invalidation context
+ optional lower-timeframe intrabar context
-> position rotation preview / dashboard
-> manual human review
```

It does not belong in:

- `selection_engine`
- `paper_advice` market-only candidate inbox
- `decision_gate`
- `execution_planner`
- `executor`

## Why This Is Separate From Paper Advice

The paper advice cockpit remains market-only and account-agnostic.

It may say:

- `BUY_REVIEW`
- `WAIT`
- `AVOID`
- `INVALIDATED`

for market/setup candidates.

The position lifecycle preview is different:

- it is account-aware
- it starts from an existing held position
- it is only for manual review of lifecycle management

This keeps the architecture boundary explicit:

```text
paper advice cockpit = candidate inbox / market-only co-pilot
rotation preview     = existing-position lifecycle review / account-aware readout
```

## Inputs

Minimum read-only inputs:

- latest `account_position_snapshot`
- latest `market_price_snapshot`
- latest `paper_advice_observation`
- latest available target / reaction / invalidation context

Optional overlay when already available in the current dashboard path:

- recent intrabar lifecycle context from lower-timeframe candles

Missing inputs must be shown explicitly as missing, not silently treated as
neutral.

## Output Shape

Each held-position row may surface:

- `position_lifecycle_action`
- `position_lifecycle_reason`
- current quantity
- current position value
- price vs entry
- price vs target/reaction zone
- price vs invalidation
- freshness
- `source_modules`
- `missing_inputs`

Required fallback states:

- `NO_POSITION_LIFECYCLE_EDGE`
- `STALE_POSITION_SOURCE`
- `MISSING_PRICE`
- `MISSING_POSITION`

## Conservative Heuristic V1

This preview is intentionally simple.

### `TRIM_REVIEW`

Use when:

- position is in profit and price is near or inside mapped target/reaction or
  extension context
- or a recent fast move looks extended from current intrabar context

### `RELOAD_REVIEW`

Use when:

- price pulls back toward the mapped entry/reaction/reload area after a prior
  target touch or harvest-style move
- and current context is not blocked/invalidated

Important limitation:

- the system does not know whether the user actually trimmed manually
- therefore `RELOAD_REVIEW` is only a market/position review hint, not proof of
  prior realized trim intent

### `HOLD`

Use when:

- a position exists
- current data is fresh enough
- no stronger trim/reload/reduce edge is visible

### `REDUCE_REVIEW`

Use when:

- paper-advice/risk context is defensive, avoid, or invalidated
- and position-risk context is poor enough that holding full size deserves
  manual review

## Non-Goals

This preview is not:

- paper execution
- simulated fills
- order generation
- allocation logic
- capital sizing
- a decision-gate replacement
- a broker-facing workflow

Forbidden:

- broker writes
- order submission
- fill creation
- live trading activation
- bypassing `decision_gate`

## Safety Boundary

Required safety markers remain:

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
```

This preview is manual review only.

## Relationship To Later Work

What belongs later, not now:

- manual trade journal integration
- explicit partial-trim history
- simulated fill tracking
- account-aware paper execution
- live execution permission

If those are added later, they should be separate lanes with explicit state and
permission boundaries, not hidden inside the read-only lifecycle preview.
