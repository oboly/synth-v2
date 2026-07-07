# Breath / Fibo / Synth Framework Contract v1

## Purpose

This document defines the canonical concept boundaries for the Synth v2 framework layers.

It is the reference for naming decisions, PR reviews, Claude implementation bundles, and UI/label policy.

No PR may rename, reuse, or extend a concept defined here without updating this document.

---

## Canonical Layer Definitions

### Breathline / Market Breath

Breathline is a market-cycle context layer.

It describes probabilistic cycle phase and timing context derived from external symbolic research or validated market-breath models.

Breathline may provide:

- cycle phase
- macro rhythm / directional bias
- timing confidence
- inhale / exhale / spike / distribution phase labels

Breathline must not provide exact price levels, entries, exits, targets, ladders, invalidations, account permission, execution intent, or broker action.

### Fibo Framework

Fibo defines the structural map.

It may provide:

- reload, breakout, target, and invalidation zone boundaries
- extension levels
- structural lifecycle: UPCOMING / NEAR / PASSED / COMPLETED
- navigation map and invalidation state

Fibo must not provide market-cycle timing context, local momentum/ATR/EMA readings, account-aware permission, or broker action.

### Synth Confirmation Signals / Local Market Context

Synth Confirmation describes measurable per-symbol indicator state.

This includes:

- EMA alignment and slope
- ATR distance
- RSI, ADX, and volume context
- price-action patterns
- local trend strength

These live in `src/market_context/` and `src/features/` as bounded sensor modules.

The canonical local MA/ATR sensor is `local_ma_atr_context` (`LocalMaAtrState`).

The canonical impulse-health sensor is `impulse_health_state` (`ImpulseHealthState`).

Synth Confirmation signals confirm or reject a framework setup. They are not Breathline and do not carry order semantics.

### Market Observer

Market Observer is a market-only aggregation/read-model layer inside `market_context`.

It combines already-owned observations into explainable cross-market context, for example:

- canonical regime forwarding
- BTC structure/range context
- ETH relative strength
- alt breadth and participation
- sector leadership/rotation
- per-symbol structural state
- explicit external-research overlay references

It may describe conditions such as `SELECTIVE_ROTATION`, `RANGE_STABLE`, `EXPANDING_SELECTIVELY`, or `PULLBACK_AFTER_EXTENSION`.

It must not:

- replace canonical regime ownership
- rebuild fib levels outside the fib-map builder
- turn an external map into measured truth
- produce buy/sell, allocation, sizing, stop, target, or order labels
- grant decision permission or create execution intent

The canonical observer contract is `docs/architecture/market_observer_contract_v1.md`.

### External Research Overlay

External research is a traceable source overlay, not a market-data source of truth.

It may contain charts, fib maps, flow snapshots, catalysts, and narrative hypotheses. It must preserve source as-of time, venue/pair/timeframe when known, source currency, conversion, verification status, freshness, expiry, and provenance.

Source confidence prior is distinct from Synth validation status.

The canonical overlay contract is `docs/architecture/external_research_overlay_contract_v1.md`.

### Strategy State

Strategy State interprets framework context and confirmation signals into a market-only action state for display/manual decision support.

It may provide setup classification, event state, and action label. It must not place orders, bypass Decision Gate, or apply account permission.

### Decision Gate

Decision Gate is the account-aware permission layer.

It checks balances, sleeves, positions, active plans, open orders, and duplicate exposure. It may allow or block a proposal, but it must not recalculate market-regime, fib, MA/ATR, impulse, breadth, or observer context.

### Execution Planner

Execution Planner converts approved execution intent into a proposed execution plan.

It may decide passive/urgent limit behavior, laddering, tick placement, repricing controls, urgency, and spread capture. It must not call a broker, apply account permission, or bypass Decision Gate.

### Executor / Broker

Executor and broker layers handle order execution only: order submission/cancel/monitoring, execution events, idempotency, and failure handling.

They must not contain strategy logic, account allocation logic, fib/profile interpretation, or market observation.

---

## Fibo Map Provenance

Every map reference must state whether it is:

- `INTERNAL_REBUILT`
- `EXTERNAL`
- `UNVERIFIED`

Source and conversion data must remain separate from internally rebuilt map data.

Rules:

- a screenshot zoom change does not create a new map by itself
- visually similar maps must not be merged unless their pair, venue, timeframe, anchors, and construction are known to match
- externally annotated ABC/reclaim/extension claims remain source claims until independently rebuilt or outcome-validated
- target lifecycle completion does not make market navigation disappear

---

## Naming Rules

### Local MA/ATR state values

`LocalMaAtrState` values describe price position relative to an EMA/MA line and must use MA-centric terminology:

```text
ABOVE_MA
TESTING_MA
BELOW_MA
RECLAIMING_MA
EXTENDED_ABOVE_MA
SPIKE_COOLING
```

They describe local price position measured in ATR units. They are not Breathline, regime, fib, sector, or observer states.

### A+ / Breathline phase factors

A+ output factors use `breathline_phase` and `breathline_direction`. These names correctly describe A+ model output and must remain unchanged.

`model_variant="8.5D_breathline"` is an A+ model identifier and remains unchanged.

### UI and report labels

| Section content | Correct label |
|---|---|
| A+ phase, breath cycle, market breath | `A+ Phase / Market Breath` |
| EMA/ATR sensor state | `Local MA Context` or `Trend Sensor` |
| Fibo zone map | `Fibo / Zone Map` |
| Canonical regime | `Regime` |
| Cross-market BTC/ETH/breadth/sector context | `Market Overview / Rotation Context` |
| Source chart, catalyst, flow snapshot, external levels | `External Research Overlay` |

Labels must not imply that an MA sensor is a breathline, that a breathline produces zones, or that external research is verified market data.

---

## Prevention Rules

1. Concept terms must have entries in this document or `docs/architecture/pipeline_contracts.md` before use in code or reports.
2. No PR may silently reuse a concept name for a different sensor without updating this document.
3. `LocalMaAtrState` values must not embed higher-level concept names.
4. UI/report labels must align with the layer that produces them.
5. Implementation bundles touching local sensors, breathline research, fib maps, market observer, breadth, or external overlays must cite the relevant contract.
6. Sensors must be named after what they measure, not the concept they support.
7. Working indicator logic must not be hidden behind higher-level concept names.
8. `market_observer` may aggregate market context but must not become a shadow decision gate or executor.

---

## Correct Data Flow

```text
Market observation
-> Feature (EMA, ATR, volume, price action, returns, breadth)
-> Local Market Context / Synth Confirmation
-> Fibo structural map
-> Canonical regime context
-> optional external research overlay, separately provenance-tagged
-> optional future MarketObserverSnapshot
-> market-only candidate/ranking (selection_engine)
-> Decision Gate (account-aware permission)
-> Execution Planner (execution intent)
-> Executor (order handling)
-> Broker (exchange API)
```

Forbidden shortcuts:

```text
breathline / A+ phase  -> direct entry/exit/order
local_ma_atr_context   -> order placement
fibo zone              -> account permission
external overlay       -> direct order or hidden selection bonus
market observer        -> decision permission or execution intent
reporting/dashboard    -> broker call or execution intent
executor               -> strategy decision
```

For expanded A+ / universal Breathline field rules and per-horizon inputs, see `docs/architecture/multi_horizon_aplus_breathline_strategy_contract_v1.md`.
