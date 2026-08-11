# Multi-Horizon + A+ Breathline Strategy Contract v1

## Purpose

Canonical contract for:

- SHORT / MEDIUM / LONG strategy horizons and allowed inputs
- A+ / universal Breathline cycle-context fields
- Synth Confirmation sensor namespace, distinct from Breathline
- future `HorizonStrategyState` schema
- market-observer horizon evidence boundary
- forbidden flows across horizon, Breathline, selection, permission, and execution

It extends `breath_fibo_synth_framework_contract_v1.md` and `pipeline_contracts.md`.

## Horizon Definitions

### Canonical horizon set

```text
FIB_TRADING_HORIZONS = ("SHORT", "MEDIUM", "LONG")
```

This document is the current canonical definition of the horizon vocabulary.

`src/research/multi_horizon_fib_contract_v1.py::HORIZON_MATRIX` is a **research reference only**, not a runtime-wide contract source. No runtime module may import a shared horizon contract from `src.research`.

Before any runtime consumer is introduced, a bounded code PR must move the shared horizon constant and definition to a neutral contracts namespace, add a runtime-to-research import guard, and update this document with the new code source. This docs-only PR does not perform that migration.

Interval is candle granularity. Horizon is strategy classification and intended holding window. They must not be conflated.

### SHORT

- Primary timeframe: 4h
- Supporting timeframe: 1h
- Live data window: 60 days
- Fibo map type: swing retrace / intra-cycle
- Holding window: days to 2 weeks
- Allowed market inputs: fib map, local MA/ATR, impulse, RSI, ADX, volume, read-only Breathline context
- Forbidden: account state, balances, positions, open orders, broker calls

### MEDIUM

- Primary timeframe: 1d
- Supporting timeframe: 4h
- Live data window: 365 days
- Fibo map type: impulse / retrace
- Holding window: weeks to months
- Allowed market inputs: fib map, local MA/ATR, impulse, slope, EMA alignment, read-only Breathline context
- Forbidden: account state, balances, positions, open orders, broker calls

### LONG

- Primary timeframe: 1w
- Supporting timeframe: 1d
- Live data window: 4 years
- Fibo map type: macro wave
- Holding window: months to years
- Allowed market inputs: fib map, impulse health, macro regime, long-term MA context, read-only Breathline context
- Forbidden: account state, balances, positions, open orders, broker calls

## A+ / Universal Breathline Data Contract

A+ Breathline is market-cycle context originating from external symbolic research. It may be forwarded read-only into market context or selection context.

Allowed fields:

```text
universal_breath_phase: EXPANSION | COMPRESSION | ACCUMULATION | RESET | UNKNOWN
universal_breath_direction: BULLISH | BEARISH | NEUTRAL
universal_breath_confidence: HIGH | MEDIUM | LOW | NONE
cycle_window: WEEKLY | MONTHLY | MULTI_MONTH
risk_climate: RISK_ON | RISK_OFF | TRANSITIONING | UNKNOWN
asset_breath_sync: IN_SYNC | DIVERGING | LAGGING | LEADING | UNKNOWN
asset_relative_phase: narrative label
phase_offset: optional label
freshness_state: FRESH | AGING | STALE | VERY_STALE
```

Existing factor names `breathline_phase` and `breathline_direction` in `src/aplus/factor_extractor.py` are live representations and must not be renamed.

Breathline must not provide exact entries, exits, targets, invalidations, ladders, allocation, broker actions, or duplicated local technical sensors. EMA/MA alignment, ATR distance, slope, volume, RSI, ADX, and price-action sensing remain Synth Confirmation ownership.

`symbolic_target_price` remains research-only source vocabulary. It cannot flow into selection entry levels, decision gate, execution planner, executor, order, ladder, or allocation.

## Synth Confirmation Sensor Namespace

Canonical values live in `src/market_context/contracts_v1.py`.

- `local_ma_atr_state` (`LocalMaAtrState`)
- `impulse_health_state` (`ImpulseHealthState`)
- EMA/MA alignment
- RSI
- ADX
- volume context
- slope
- price-action pattern

They are measurable market states, not Breathline, and carry no order-action semantics.

## Market Observer Horizon Evidence

A future `MarketObserverSnapshot` may expose cross-market evidence at declared intervals and optional horizon tags: BTC range stability, ETH/BTC relative strength, sector breadth, or per-symbol reclaim/pullback context.

It does not choose an account horizon, own `HorizonStrategyState`, relabel an interval as a horizon, produce execution instruction, or bypass selection/decision/execution boundaries.

Every evidence item preserves source interval, as-of, freshness, and explicit horizon tag where applicable. A `15m` reading cannot silently become a MEDIUM or LONG conclusion.

## Future `HorizonStrategyState`

Status: documented only; not implemented.

This is the horizon-specific Strategy State emitted within `selection_engine`, not a layer between selection and decision gate.

Fields:

- `symbol`
- `fib_trading_horizon`: SHORT | MEDIUM | LONG
- `strategy_family`
- `setup_classification`
- `breathline_context`: forwarded read-only context
- `synth_confirmation`: summary of measurable sensors
- `fib_map_state`
- `timing_state`
- `validation_state`: VALID | PARTIAL | INVALID | NO_DATA
- `computed_at_utc`
- `horizon_end_ts_utc`

It must not contain balance, position, sleeve, order ID, execution intent, broker fields, entry/exit/stop price, or allocation.

## Canonical Data Flow

```text
A+ Breathline
  -> market_context / features
       -> Synth Confirmation sensors
       -> Fibo map state
       -> canonical regime context
       -> optional MarketObserverSnapshot
  -> selection_engine
       -> Strategy State / future HorizonStrategyState
  -> decision_gate
  -> execution_planner
  -> executor / broker
```

Observer stays inside market context. Strategy State stays inside selection. Decision Gate remains the only account-aware permission layer.

## Forbidden Shortcuts

```text
symbolic_target_price     -> selection entry level or execution price
breathline / A+ phase     -> direct entry / exit / order
breathline                -> duplicated local technical sensor
MarketObserverSnapshot    -> trade permission or execution intent
observer horizon evidence -> account horizon choice
runtime module            -> src.research shared-contract import
selection_engine          -> account state / balances / positions
decision_gate             -> Fibo, MA/ATR, impulse, breadth, or observer recomputation
execution_planner         -> market_context / features / selection / aplus
executor                  -> selection / aplus / market_context
```

## Guard Expectations

Existing/future guards must preserve:

1. selection engine has no account/balance/execution/broker imports
2. decision gate has no market-structure computation imports
3. execution planner has no market-context/selection/aplus imports
4. executor has no strategy/selection/aplus imports
5. `src.aplus` has no execution/broker imports
6. horizon set is exactly SHORT / MEDIUM / LONG
7. A+ factors contain no runtime execution-price terms
8. observer stays market-only
9. runtime modules cannot import shared contracts from `src.research`

## Related Documents

- `docs/architecture/multi_horizon_signal_timescale_contract_v1.md` — signal
  timescale (input interval / lookback / effective horizon / observed
  lifecycle duration) and horizon-composition semantics, orthogonal to the
  SHORT/MEDIUM/LONG strategy-horizon vocabulary defined here.
- `docs/architecture/breath_fibo_synth_framework_contract_v1.md`
- `docs/architecture/pipeline_contracts.md`
- `docs/architecture/market_observer_contract_v1.md`
- `docs/architecture/external_research_overlay_contract_v1.md`
- `src/market_context/contracts_v1.py`
- `src/aplus/factor_extractor.py`
