# Breath / Fibo / Synth Framework Contract v1

## Purpose

This document defines the canonical concept boundaries for the Synth v2 framework layers.
It is the reference for naming decisions, PR reviews, Claude/agent implementation bundles,
and UI/label policy.

No PR may rename, reuse, or extend a concept defined here without updating this document.

---

## Canonical Layer Definitions

### Breathline / Market Breath

Breathline is a **market-cycle context layer**.

Breathline describes **probabilistic cycle phase and timing context** derived from external
symbolic research (A+, Codex-style output) or validated market-breath models.

Breathline provides:
- cycle phase (e.g. compression, expansion, peak, reversion)
- macro rhythm / directional bias
- timing confidence
- inhale / exhale / spike / distribution phase labels

Breathline does **NOT**:
- produce exact price levels, entries, exits, targets, ladders, or invalidations
- replace or duplicate moving averages, EMA alignment, ATR distance, or slope sensors
- act as a decision gate
- place orders
- create execution intent

### Fibo Framework

Fibo defines the **structural map**.

Fibo provides:
- zone boundaries (reload / breakout / target / invalidation)
- extension levels (1.272, 1.618, 2.0, etc.)
- structural lifecycle (UPCOMING / NEAR / PASSED / COMPLETED)
- navigation map and invalidation levels

Fibo does **NOT**:
- provide market-cycle timing context
- assess momentum, ATR distance, or EMA alignment
- produce account-aware permission

### Synth Confirmation Signals / Local Market Context

Synth Confirmation describes **measurable indicator state**.

This includes:
- EMA alignment (price vs EMA20, EMA50, spread)
- EMA slope
- ATR distance (`distance_atr`)
- RSI, ADX, volume context
- price action patterns
- local trend strength

These live in `src/market_context/` and `src/features/` as bounded sensor modules.

The canonical local MA/ATR sensor is `local_ma_atr_context` (`LocalMaAtrState`).
The canonical impulse health sensor is `impulse_health_state` (`ImpulseHealthState`).

Synth Confirmation Signals **confirm or reject** a framework setup. They are not Breathline.

### Strategy State

Strategy State **interprets** framework context + confirmation signals into an action state.

Strategy State provides:
- setup classification (BREAKOUT_RETEST, REENTRY_WAIT, EXTENSION_SWING, etc.)
- event state (TAKE_PROFIT_WAITING, RELOAD_ZONE_APPROACHING, etc.)
- action label (for display and manual decision support)

Strategy State does **NOT**:
- place orders
- bypass Decision Gate
- apply account-level permission

### Decision Gate

Decision Gate is the **account-aware permission layer**.

Decision Gate:
- checks balance, sleeve, position, active plan, open order, duplicate exposure
- produces allowed/blocked decision state or execution intent
- is the only layer that combines market context with account state

Decision Gate does **NOT**:
- apply market-regime logic
- place orders directly

### Execution Planner

Execution Planner converts **approved execution intent** into an execution plan.

Execution Planner decides:
- passive vs urgent limit
- laddering, tick placement, repricing controls, urgency, spread capture

Execution Planner does **NOT**:
- place orders
- call broker/exchange
- apply account-level permission
- bypass Decision Gate

### Executor / Broker

Executor and broker layers handle **order execution only**.

They:
- place, cancel, and monitor orders
- write execution events and order state
- handle idempotency and failure

They do **NOT**:
- contain strategy logic
- perform account allocation logic
- apply target selection or fib/profile interpretation

---

## Naming Rules

### Local MA/ATR state values

`LocalMaAtrState` enum values describe **price position relative to the EMA/MA line**.
They must use MA-centric terminology, not breathline terminology.

Canonical values:

    ABOVE_MA
    TESTING_MA
    BELOW_MA
    RECLAIMING_MA
    EXTENDED_ABOVE_MA
    SPIKE_COOLING

These describe where price sits relative to the local moving average, measured in ATR units.
They are **not** breathline states. They are **not** cycle phase labels.

### A+ / Breathline phase factors

A+ output factors use `breathline_phase` and `breathline_direction` as factor names.
These are correct — they describe A+ model output, which is a genuine breathline concept.

`model_variant="8.5D_breathline"` in the A+ parser is the A+ model identifier. Keep as-is.

### UI and report labels

UI sections and labels must reflect the **layer that produces them**:

| Section content | Correct label |
|---|---|
| A+ phase, breath cycle, market breath | `A+ Phase / Market Breath` |
| EMA/ATR sensor state | `Local MA Context` or `Trend Sensor` |
| Fibo zone map | `Fibo / Zone Map` |
| Regime interpretation | `Regime` |

Labels must not imply that an MA sensor is a breathline, or that a breathline produces zones.

---

## Prevention Rules

1. Concept terms must have entries in this doc or `docs/architecture/pipeline_contracts.md`
   before being used in code or reports.

2. No PR may silently reuse a concept name for a different sensor without updating this doc.

3. `LocalMaAtrState` enum values must not embed higher-level concept names
   (breathline, regime, fibo, etc.). Name values after what the sensor measures.

4. UI/report labels must align with the layer that produces them, not with a higher-level concept.

5. Claude/agent implementation bundles must include a reference to this contract doc before
   implementing any work that touches `local_ma_atr_context`, `impulse_health_state`,
   breathline research, or market breath labels.

6. Useful sensors must be named after what they measure (EMA/MA position),
   not after the concept they support (breathline, cycle phase).

7. Working indicator logic must not be hidden behind higher-level concept names.
   If a sensor computes EMA distance, name it EMA distance — not breathline distance.

---

## Correct Data Flow

```
Market observation
→ Feature (EMA, ATR, volume, price action)
→ Synth Confirmation Signal / Local Market Context
  (local_ma_atr_context, impulse_health_state, price_vs_ema*)
→ Market-only candidate/ranking (selection_engine)
→ Optional: A+ / Breathline phase context (research/symbolic lane)
→ Optional: Fibo structural map (FibNavigationMap, FibExtContext)
→ Strategy State (interprets context + confirmation)
→ Decision Gate (account-aware permission)
→ Execution Planner (execution intent)
→ Executor (order handling)
→ Broker (exchange API)
```

Forbidden shortcuts:

```
breathline / A+ phase  →  direct entry/exit/order
local_ma_atr_context   →  order placement
fibo zone              →  account permission
reporting/dashboard    →  broker call or execution intent
executor               →  strategy decision
```
