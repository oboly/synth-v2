# Breath / Fibo / Synth Framework Contract v1

## Purpose

Canonical concept boundaries for Synth v2. No concept may be renamed, reused, or extended without updating this document.

## Layers

### Breathline / Market Breath

Breathline is probabilistic market-cycle and timing context from external symbolic research or validated market-breath models.

It may provide cycle phase, directional bias, timing confidence, and inhale/exhale/spike/distribution labels.

It must not provide price levels, entries, exits, targets, ladders, invalidations, account permission, execution intent, or broker actions. It must not replace or duplicate moving averages, EMA alignment, ATR distance, slope, volume, RSI, ADX, or price-action sensors.

### Fibo Framework

Fibo is the structural map: reload, breakout, target, invalidation zones, extension levels, and structural lifecycle.

It must not provide market-cycle timing, local momentum/EMA/ATR sensing, account permission, or broker actions.

### Synth Confirmation / Local Market Context

Measurable, per-symbol indicator state: EMA alignment/slope, ATR distance, RSI, ADX, volume, price action, and local trend strength.

Canonical sensors are `local_ma_atr_context` (`LocalMaAtrState`) and `impulse_health_state` (`ImpulseHealthState`). They are not Breathline and carry no order semantics.

### Market Observer

Market-only aggregation/read model inside `market_context`. It may aggregate canonical regime forwarding, BTC structure, ETH relative strength, breadth, sector rotation, per-symbol structure, and provenance-tagged external overlays.

It may emit descriptive states only. It must not read account state, replace canonical regime, rebuild fib maps outside their builder, convert an external map into measured truth, grant permission, create execution intent, or emit allocation/order labels.

Canonical contract: `docs/architecture/market_observer_contract_v1.md`.

### External Research Overlay

Traceable source overlay, not market truth. It preserves source time, venue/pair/timeframe when known, source currency/conversion, verification, freshness, expiry, and provenance.

Source confidence prior is distinct from Synth validation status.

Canonical contract: `docs/architecture/external_research_overlay_contract_v1.md`.

### Strategy State

Market-only interpretation produced inside `selection_engine`. It converts market context and confirmation signals into setup classification, event state, and display/manual-support labels. `HorizonStrategyState` is its future horizon-specific schema.

Strategy State is not an independent pipeline layer between `selection_engine` and `decision_gate`.

### Decision Gate

`decision_gate` is the account-aware permission layer and the **only** layer allowed to combine market-only upstream context with balances, sleeves, positions, active plans, open orders, or duplicate exposure.

It may allow or block a proposal. It must not recalculate regime, fib, MA/ATR, impulse, breadth, or observer context; create an execution plan; or call a broker.

No observer, selection, planner, executor, reporting, or external-overlay module may become account-aware by combining market context with account state.

### Execution Planner

Converts an approved decision into a proposed execution plan. It may not call a broker, apply account permission, or bypass Decision Gate.

### Executor / Broker

Handles order submission/cancel/monitoring, idempotency, and failures only. It must not contain strategy, allocation, fib/profile interpretation, or market observation.

## Fibo Map Provenance

Map references must be `INTERNAL_REBUILT`, `EXTERNAL`, or `UNVERIFIED`. Source/conversion data remain separate from internal map data.

A screenshot zoom change does not create a new map. Similar maps must not be merged without matching pair, venue, timeframe, anchors, and construction. External ABC/reclaim/extension annotations remain source claims until reconstructed or outcome-validated.

## Naming and UI Rules

`LocalMaAtrState` uses MA-centric names:

```text
ABOVE_MA
TESTING_MA
BELOW_MA
RECLAIMING_MA
EXTENDED_ABOVE_MA
SPIKE_COOLING
```

A+ factor names `breathline_phase` and `breathline_direction` remain correct and must not be renamed. `model_variant="8.5D_breathline"` remains an A+ model identifier.

Correct labels:

| Content | Label |
|---|---|
| A+ phase / market breath | `A+ Phase / Market Breath` |
| EMA/ATR state | `Local MA Context` or `Trend Sensor` |
| Fibo zones | `Fibo / Zone Map` |
| Canonical regime | `Regime` |
| BTC/ETH/breadth/sector aggregate | `Market Overview / Rotation Context` |
| Source charts, catalysts, flow, external levels | `External Research Overlay` |

## Prevention Rules

1. Concepts require an entry in this document or `pipeline_contracts.md` before use.
2. Sensors must be named after what they measure.
3. Working indicator logic must not hide behind higher-level terminology; Breathline must not duplicate local technical sensors.
4. UI labels must reflect the producing layer.
5. `market_observer` must not become a shadow decision gate or executor.
6. Only `decision_gate` may combine market context with account state.
7. Implementation bundles touching local sensors, Breathline research, fib maps, observer, breadth, or external overlays must cite this document and the relevant specific contract.

## Canonical Data Flow

```text
Market observation
-> features and local market context
-> fib structure and canonical regime
-> optional provenance-tagged external overlay
-> optional MarketObserverSnapshot
-> selection_engine
     -> Strategy State / future HorizonStrategyState
-> decision_gate
-> execution_planner
-> executor
-> broker
```

Forbidden shortcuts:

```text
breathline              -> direct execution or duplicate local sensor
fibo zone               -> account permission
external overlay        -> direct execution or hidden selection bonus
market observer         -> account state, permission, or execution intent
selection_engine        -> account state
execution_planner       -> permission or market-feature recomputation
executor                -> strategy decision
```

See `docs/architecture/multi_horizon_aplus_breathline_strategy_contract_v1.md` for horizon and A+ field rules.
