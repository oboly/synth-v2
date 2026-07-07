# Multi-Horizon + A+ Breathline Strategy Contract v1

## Purpose

This document defines the canonical contract for:

- SHORT / MEDIUM / LONG strategy horizons and their allowed inputs
- A+ / universal Breathline cycle-context field contract
- Synth Confirmation sensor namespace, distinct from Breathline
- future `HorizonStrategyState` schema
- future market-observer horizon evidence boundary
- forbidden flows across all layers for horizon and Breathline data

It extends `breath_fibo_synth_framework_contract_v1.md` and `pipeline_contracts.md`. It does not replace them.

No PR may add Breathline fields, rename horizon labels, introduce `HorizonStrategyState` fields, or treat observer context as horizon ownership without updating this document.

---

## Horizon Definitions

### Canonical horizon set

```text
FIB_TRADING_HORIZONS = ("SHORT", "MEDIUM", "LONG")
```

Canonical code source: `src/research/multi_horizon_fib_contract_v1.py::HORIZON_MATRIX`.

Interval is the candle granularity used to measure a condition. Horizon is the strategy classification and intended holding window. They must not be conflated.

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

Guard: `test_interval_role_is_separate_from_trading_horizon` in `tests/test_multi_horizon_fib_contract_v1.py`.

---

## A+ / Universal Breathline Data Contract

### Layer identity

A+ Breathline is a market-cycle context layer originating from external symbolic research. It feeds into `src/aplus/` and may be forwarded read-only into market context or selection context.

Allowed market-only fields:

- `universal_breath_phase`: EXPANSION | COMPRESSION | ACCUMULATION | RESET | UNKNOWN
- `universal_breath_direction`: BULLISH | BEARISH | NEUTRAL
- `universal_breath_confidence`: HIGH | MEDIUM | LOW | NONE
- `cycle_window`: WEEKLY | MONTHLY | MULTI_MONTH
- `risk_climate`: RISK_ON | RISK_OFF | TRANSITIONING | UNKNOWN
- `asset_breath_sync`: IN_SYNC | DIVERGING | LAGGING | LEADING | UNKNOWN
- `asset_relative_phase`: narrative phase label
- `phase_offset`: optional offset label
- `freshness_state`: FRESH | AGING | STALE | VERY_STALE

Existing factor names `breathline_phase` and `breathline_direction` in `src/aplus/factor_extractor.py` are the live representations and must not be renamed.

### `symbolic_target_price` — research-only

`symbolic_target_price` is A+ source vocabulary only.

It may appear in research/reporting context but must not flow into an executable target, decision gate, execution planner, executor, order, ladder, or allocation.

### Forbidden from Breathline contract

The following belong to Fibo, strategy, or execution layers, not Breathline:

- exact entries, exits, targets, invalidations, or ladders
- order size or capital allocation
- broker/executor actions

---

## Synth Confirmation Sensor Namespace

Synth Confirmation sensors are measurable indicator states. They are not Breathline.

Canonical values live in `src/market_context/contracts_v1.py`.

- `local_ma_atr_state` (`LocalMaAtrState`): ABOVE_MA, TESTING_MA, BELOW_MA, RECLAIMING_MA, EXTENDED_ABOVE_MA, SPIKE_COOLING
- `impulse_health_state` (`ImpulseHealthState`): HEALTHY_IMPULSE, EARLY_IMPULSE, EXTENDED_IMPULSE, BLOW_OFF_SPIKE, DISTRIBUTION_RISK, COOLING_PULLBACK, SECOND_BUMP_POSSIBLE, FAILED_RECLAIM
- EMA/MA alignment
- RSI
- ADX
- volume context
- slope
- price-action pattern

None may carry order-action semantics.

---

## Market Observer Horizon Evidence

A future `MarketObserverSnapshot` may expose cross-market evidence at one or more horizons, for example:

- BTC range stability measured on an intraday interval
- ETH/BTC relative strength measured on a daily interval
- sector breadth measured on a declared interval
- per-symbol pullback/reclaim state linked to its source interval

It does not:

- select SHORT, MEDIUM, or LONG for an account
- own `HorizonStrategyState`
- relabel an interval as a strategy horizon
- turn a horizon observation into a buy/sell instruction
- bypass selection, decision gate, or execution planner

Any observer evidence item must preserve its source interval, observation as-of, freshness, and, when applicable, explicit horizon tag. A `15m` reading cannot silently become a MEDIUM or LONG conclusion.

The observer may forward canonical regime and Breathline context as opaque read-only evidence. It must not redefine their labels.

---

## Future `HorizonStrategyState` Schema

Status: documented only; not implemented.

Future output of a market-only selection-engine horizon scorer:

- `symbol`
- `fib_trading_horizon`: SHORT | MEDIUM | LONG
- `strategy_family`
- `setup_classification`
- `breathline_context`: forwarded read-only context
- `synth_confirmation`: summary of measurable confirmation signals
- `fib_map_state`
- `timing_state`
- `validation_state`: VALID | PARTIAL | INVALID | NO_DATA
- `computed_at_utc`
- `horizon_end_ts_utc`

It must not contain balance, position, sleeve, order ID, execution intent, broker fields, entry price, exit price, stop price, or allocation.

`fib_trading_horizon` belongs to this future schema. It is not added to `MarketNavigationState` or a future observer snapshot as an inferred execution instruction.

---

## Data Flow

```text
A+ Breathline
  -> market_context / features
       -> Synth Confirmation sensors
       -> Fibo map state
       -> canonical regime context
       -> optional future MarketObserverSnapshot
  -> selection_engine
       -> future HorizonStrategyState
  -> decision_gate
  -> execution_planner
  -> executor / broker
```

The observer is inside market context. It is not a new authority between selection and decision gate.

---

## Forbidden Shortcuts

```text
symbolic_target_price     -> selection entry level or execution price
breathline / A+ phase     -> direct entry / exit / order
MarketObserverSnapshot    -> trade permission or execution intent
observer horizon evidence -> account horizon choice
selection_engine          -> account state / balances / positions
decision_gate             -> Fibo zone or MA/ATR recomputation
execution_planner         -> market_context / features / selection / aplus
executor                  -> selection / aplus / market_context
src.aplus                 -> decision_gate / execution_planner / executor
```

---

## Guard Expectations

Guard test file: `tests/test_multi_horizon_aplus_breathline_contract_v1.py`.

Existing and future guards must preserve:

1. selection engine has no account/balance/execution/broker imports
2. decision gate has no market-structure computation imports
3. execution planner has no market-context/selection/aplus imports
4. executor has no strategy/selection/aplus imports
5. `src.aplus` has no execution/broker imports
6. horizon set is exactly SHORT / MEDIUM / LONG
7. A+ factor names contain no runtime execution-price terms
8. any future observer implementation stays market-only and does not import decision, planning, execution, broker, or account modules

---

## Related Documents

- `docs/architecture/breath_fibo_synth_framework_contract_v1.md`
- `docs/architecture/pipeline_contracts.md`
- `docs/architecture/market_observer_contract_v1.md`
- `docs/architecture/external_research_overlay_contract_v1.md`
- `src/research/multi_horizon_fib_contract_v1.py`
- `src/market_context/contracts_v1.py`
- `src/aplus/factor_extractor.py`
