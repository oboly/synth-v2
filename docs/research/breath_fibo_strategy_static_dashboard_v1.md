# Breath Fibo Strategy Static Dashboard V1

## Purpose

`breath_fibo_strategy_static_dashboard_v1` is the first Synth v2.14
strategy-oriented market-only dashboard.

It is not:

- an advice dashboard
- a decision surface
- an execution surface
- an account-aware cockpit

It exists to show research strategy hypotheses built from:

- Breath/Fibo frame
- canonical regime context
- public market price and level position
- canonical fib/zone map context first

Core principle:

```text
Breath/Fibo gives the frame.
Regime gives the first Synth layer.
Fibo/zone levels give TP/reload/invalidation map.
Primitive market context gives evidence.
Strategy candidate gives a research hypothesis.
Nothing executes.
```

## Architecture Boundary

This dashboard is:

- reporting-only
- market-only
- account-agnostic
- static HTML

It must not:

- emit `BUY_READY`
- emit `SELL_NOW`
- emit final `AVOID` advice
- emit final `WATCH_ONLY` advice
- hide HTF/LTF conflicts
- create decision permission
- create execution intent

Hard boundaries:

```text
No selection_engine changes
No decision_gate changes
No execution_planner changes
No executor changes
No broker calls
No broker writes
No orders
No account-aware logic
```

## Data Sources Used

V1 uses only persisted public/reporting-safe sources:

- `obs_market_candle`
  - latest per-symbol price
  - latest per-symbol candle timestamp
  - candle freshness state
- `active_regime_observation`
  - canonical regime layer by asset class
- `canonical_fib_zone_map_latest_v1`
  - atomic production cohort from the existing `FibNavigationMap` builder
  - current leg, anchors, retracement/support, extensions, invalidation,
    freshness, and provenance

Allowed primary strategy-map sources in V1:

- canonical fib/zone map rows
- public candle/price data
- `active_regime_observation`
- future primitive signal matrix attachments when added later

If a source is missing, the dashboard shows `MISSING_SOURCE` or `UNKNOWN`
explicitly.

Direction is descriptive and comes only from the persisted map. `UP` selects
the next extension above current price and labels the retracement reaction as
support. `DOWN` selects the next extension below current price and labels the
reaction as resistance. `RANGE` and `UNKNOWN` suppress directional zones,
targets, and invalidation rather than applying long-only semantics.

## Required Row Fields

Each row shows:

- `asset`
- `current_price`
- `interval`
- `latest_candle_ts_utc`
- `candle_freshness_state`
- `regime_context`
- `fibo_map_state`
- `current_leg`
- `nearest_support_or_reaction_zone`
- `nearest_target_or_t1`
- `entry_zone`
- `invalidation_zone`
- `invalidation_source`
- `invalidation_method`
- `distance_to_target_pct`
- `distance_to_entry_zone_pct`
- `distance_to_invalidation_pct`
- `manual_ladder_context`
- `primitive_signal_context`
- `strategy_candidate_state`
- `strategy_candidate_reason`
- `source_status`

## Candidate States

V1 uses research/dashboard candidate states only:

- `NO_STRATEGY_CONTEXT`
- `MAP_INCOMPLETE`
- `SUPPORT_REACTION_CANDIDATE`
- `FIB_RETEST_CONTINUATION_CANDIDATE`
- `TARGET_TOUCHED_TP_REVIEW`
- `ENTRY_ZONE_NEAR`
- `INVALIDATION_NEAR`
- `FAILED_RECLAIM_FADE_RISK`
- `WAIT_RETEST`
- `CONTEXT_ONLY`

These are not orders.
They are not permission.
They are not hidden advice.

## Missing-Source Handling

V1 fails open for display and fails closed for meaning:

- if `obs_market_candle` is missing:
  - show missing price / missing freshness
- if the persisted canonical map is missing for a symbol:
  - show `FIB_MAP_UNKNOWN`
- if the persisted map is stale or unavailable:
  - show `MAP_UNAVAILABLE` and the exact map/freshness state
- if canonical regime row is missing:
  - show `UNKNOWN`
- if no reusable primitive/legacy context exists:
  - show `primitive_signal_context=unavailable`

The dashboard must not invent unavailable data.

## Invalidation Level

Invalidation Level:

The price level below or above which the current market-only strategy
hypothesis is considered invalid.

V1 resolves invalidation provenance explicitly with this priority:

1. `canonical_fib_zone_map_latest_v1.invalidation_level`
   - method from the persisted `invalidation_method`
2. missing:
   - method=`MISSING_INVALIDATION`
   - source=`UNKNOWN`

## Invalidation Source

Invalidation Source:

The table/file/field that supplied the invalidation level.

V1 shows both:

- source module / field
- invalidation method

This keeps `INVALIDATION_NEAR` explainable as a map fact rather than a hidden
label.

## Entry Zone

Entry Zone:

The directional retracement zone where reaction structure is inspected.

The zone may represent:

- support reaction for an `UP` map
- resistance reaction for a `DOWN` map
- retest
- reload-after-TP
- fib pullback
- reclaim area

It is not a buy command.

## Legacy Paper Context Rule

The dashboard does not query `paper_advice_observation` and has no legacy CSV
fallback. Missing canonical map truth stays missing.

Forbidden as active gates:

- `AVOID`
- `WATCH_ONLY`
- `BUY_READY`
- `SELL_NOW`

## Relationship To Manual Ladder Dashboard V1

Correct relationship:

```text
breath_fibo_strategy_static_dashboard_v1
-> strategy-oriented market-only hypothesis surface

manual_ladder_dashboard_v1
-> downstream manual level-reading surface
```

Interpretation:

- strategy dashboard = strategy frame first
- manual ladder dashboard = manual level review first
- neither surface executes

## Why This Is Not Advice / Execution

This dashboard does not resolve strategy context into:

- buy permission
- sell permission
- position sizing
- account-aware rotation
- broker intent

It only shows:

- frame
- map
- regime
- reusable context
- explicit missing sources
- explicit conflicts

The user or later research still has to validate whether a visible hypothesis
has any edge.
