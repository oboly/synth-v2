# Multi-Horizon + A+ Breathline Strategy Contract v1

## Purpose

This document defines the canonical contract for:

- SHORT / MEDIUM / LONG strategy horizons and their allowed inputs
- A+ / universal Breathline cycle-context field contract
- Synth Confirmation sensor namespace (distinct from Breathline)
- Future `HorizonStrategyState` schema (documented, not yet implemented)
- Forbidden flows across all layers for horizon and Breathline data

Extends `breath_fibo_synth_framework_contract_v1.md` (concept boundaries)
and `pipeline_contracts.md` (layer responsibilities). Does not replace them.

No PR may add new Breathline fields, rename horizon labels, or introduce
`HorizonStrategyState` fields without updating this document.

---

## Horizon Definitions

### Canonical horizon set

```
FIB_TRADING_HORIZONS = ("SHORT", "MEDIUM", "LONG")
```

Canonical code source:
`src/research/multi_horizon_fib_contract_v1.py::HORIZON_MATRIX`

Do not duplicate the raw matrix here; reference the module as authoritative.

### SHORT

- Primary timeframe: 4h
- Supporting timeframe: 1h
- Live data window: 60 days
- Fibo map type: swing retrace (intra-cycle)
- Holding window: days to 2 weeks
- Breathline input: allowed read-only as cycle context
- Synth sensors: LocalMaAtrState, ImpulseHealthState, RSI, ADX, volume
- Forbidden: account state, balances, positions, open orders, broker calls

### MEDIUM

- Primary timeframe: 1d
- Supporting timeframe: 4h
- Live data window: 365 days
- Fibo map type: impulse / retrace
- Holding window: weeks to months
- Breathline input: allowed read-only as cycle context
- Synth sensors: LocalMaAtrState, ImpulseHealthState, slope, EMA alignment
- Forbidden: account state, balances, positions, open orders, broker calls

### LONG

- Primary timeframe: 1w
- Supporting timeframe: 1d
- Live data window: 4 years
- Fibo map type: macro wave
- Holding window: months to years
- Breathline input: allowed read-only as cycle context
- Synth sensors: ImpulseHealthState, macro regime, long-term MA context
- Forbidden: account state, balances, positions, open orders, broker calls

### Horizon vs interval

Interval (4h, 1d, 1w) is the measurement tool — candle granularity
used to build Fibo maps and sensor readings.

Horizon (SHORT, MEDIUM, LONG) is the strategy classification — which
swing type and holding window a setup targets.

They must not be conflated. A 4h candle used in a MEDIUM scaffold is
a supporting interval for MEDIUM, not a SHORT horizon strategy.

Guard: `test_interval_role_is_separate_from_trading_horizon` in
`tests/test_multi_horizon_fib_contract_v1.py`.

---

## A+ / Universal Breathline Data Contract

### Layer identity

A+ Breathline is a market-cycle context layer originating from external
symbolic research (A+ model runs). It feeds into `src/aplus/` and may
be forwarded read-only into selection context.

### Allowed cycle-context fields

Market-only. No price levels, entries, exits, or order actions.

- `universal_breath_phase`
  Values: EXPANSION | COMPRESSION | ACCUMULATION | RESET | UNKNOWN

- `universal_breath_direction`
  Values: BULLISH | BEARISH | NEUTRAL

- `universal_breath_confidence`
  Values: HIGH | MEDIUM | LOW | NONE

- `cycle_window`
  Values: WEEKLY | MONTHLY | MULTI_MONTH

- `risk_climate`
  Values: RISK_ON | RISK_OFF | TRANSITIONING | UNKNOWN

- `asset_breath_sync`
  Values: IN_SYNC | DIVERGING | LAGGING | LEADING | UNKNOWN

- `asset_relative_phase`
  Type: str — narrative phase label for asset vs market breath

- `phase_offset`
  Type: str | None — offset label when asset leads or lags the cycle

- `freshness_state`
  Values: FRESH | AGING | STALE | VERY_STALE

Existing factor names `breathline_phase` and `breathline_direction`
in `src/aplus/factor_extractor.py` are the live representations of
`universal_breath_phase` and `universal_breath_direction`.
They must not be renamed.

### `symbolic_target_price` — research-only

`symbolic_target_price` is produced by `src/aplus/factor_extractor.py`
and represents the symbolic price target from an A+ model run.

It is research-only / A+ source vocabulary:
- may appear in research and reporting display context only
- must not flow into `selection_engine` as an executable price target
- must not be used in `decision_gate`, `execution_planner`, or `executor`
- must not be the basis for any order, ladder, or execution intent
- not renamed or removed in this PR

### Forbidden from Breathline contract

These belong to Fibo / Strategy / Execution layers, not Breathline:

- exact buy entry prices
- exact sell / exit prices
- invalidation price levels
- ladder definitions
- order size or capital allocation
- broker / executor actions

---

## Synth Confirmation Sensor Namespace

Synth Confirmation sensors are measurable indicator states.
They are not Breathline.

Canonical values live in `src/market_context/contracts_v1.py`.

Sensors:

- `local_ma_atr_state` (LocalMaAtrState)
  Price position relative to EMA/MA measured in ATR units.
  Values: ABOVE_MA, TESTING_MA, BELOW_MA, RECLAIMING_MA,
          EXTENDED_ABOVE_MA, SPIKE_COOLING

- `impulse_health_state` (ImpulseHealthState)
  Impulse quality and phase.
  Values: HEALTHY_IMPULSE, EARLY_IMPULSE, EXTENDED_IMPULSE,
          BLOW_OFF_SPIKE, DISTRIBUTION_RISK, COOLING_PULLBACK,
          SECOND_BUMP_POSSIBLE, FAILED_RECLAIM

- EMA / MA alignment
  Type: bool or enum — price vs EMA20, EMA50 alignment

- RSI
  Type: numeric / zone label — momentum reading

- ADX
  Type: numeric / strength label — trend strength

- volume context
  Type: label — above/below average volume state

- slope
  Type: numeric / label — price or EMA slope direction

- price action pattern
  Type: label — candle/pattern label (e.g. DOJI, ENGULF)

None of these are Breathline. None may carry order-action semantics.

---

## Future `HorizonStrategyState` Schema

Status: documented only — not yet implemented.

This schema is the intended future output of a selection_engine
horizon scorer. A later implementation PR will create the dataclass
and wire it into the pipeline. No code in this PR creates this class.

Fields:

- `symbol` — str
- `fib_trading_horizon` — str: SHORT | MEDIUM | LONG
- `strategy_family` — str: e.g. SWING_RETRACE, IMPULSE_FOLLOW
- `setup_classification` — str: e.g. RELOAD_ZONE, BREAKOUT_WATCH
- `breathline_context` — str: forwarded universal_breath_phase,
  read-only, not reinterpreted by selection or downstream layers
- `synth_confirmation` — str: summary label from
  LocalMaAtrState + ImpulseHealthState
- `fib_map_state` — str: forwarded FibMapState value
- `timing_state` — str: forwarded TimingState value
- `validation_state` — str: VALID | PARTIAL | INVALID | NO_DATA
- `computed_at_utc` — str: ISO-8601 UTC
- `horizon_end_ts_utc` — str | None: expected end of holding window

Must not contain: balance, position, order_id, sleeve,
execution_intent, broker fields, entry price, exit price, stop price.

Note: `fib_trading_horizon` belongs to this future schema only.
It is not added to `MarketNavigationState` in this PR.

---

## Data Flow

```
A+ Breathline  (cycle context — research origin)
  |  universal_breath_phase, risk_climate, asset_breath_sync, ...
  |  read-only; no price levels; no order actions
  |
  v
market_context / features  (src/market_context/, src/features/)
  |  Synth Confirmation sensors (LocalMaAtrState, ImpulseHealthState)
  |  Fibo map state (FibMapState, zones, targets -- structural only)
  |  Breathline forwarded as opaque context label
  |
  v
selection_engine  (src/selection/)
  |  market-only, account-agnostic
  |  future: emits HorizonStrategyState per horizon
  |
  v
decision_gate  (src/decision_gate/)
  |  account-aware permission only
  |  does not recalculate Fibo, MA/ATR, or Breathline
  |  target_horizon is an opaque string -- not reinterpreted
  |
  v
execution_planner  (src/execution_planner/)
  |  order intent only
  |  does not import market_context, features, selection, or aplus
  |
  v
executor / broker  (src/executor/, src/execution/)
     order handling only
     does not import selection, aplus, or market_context
```

---

## Forbidden Shortcuts

```
symbolic_target_price     ->  selection entry level or execution price
breathline / A+ phase     ->  direct entry / exit / order
selection_engine          ->  account state / balances / positions
decision_gate             ->  Fibo zone or MA/ATR recomputation
execution_planner         ->  market_context / features / selection / aplus
executor                  ->  selection / aplus / market_context
src.aplus                 ->  decision_gate / execution_planner / executor
SHORT/MEDIUM/LONG output  ->  untagged schema (must carry fib_trading_horizon)
```

---

## Guard Tests

Guard test file:
`tests/test_multi_horizon_aplus_breathline_contract_v1.py`

Guards enforced:

1. selection_engine has no account / balance / execution / broker imports
2. decision_gate has no market-structure computation imports
3. execution_planner has no market-context / selection / aplus imports
4. executor has no strategy / selection / aplus imports
5. src.aplus has no execution / broker imports
6. FIB_TRADING_HORIZONS is exactly ("SHORT", "MEDIUM", "LONG")
7. A+ factor names contain no runtime execution price terms
8. HorizonStrategyState guard (stub -- pending implementation PR)

---

## Related Documents

- `docs/architecture/breath_fibo_synth_framework_contract_v1.md`
  Canonical concept boundaries for Breathline, Fibo, Synth Confirmation,
  Strategy State, Decision Gate, and Executor layers.

- `docs/architecture/pipeline_contracts.md`
  Layer responsibilities, MarketNavigationState contract,
  allowed import directions.

- `src/research/multi_horizon_fib_contract_v1.py`
  Canonical HORIZON_MATRIX and HorizonDefinition dataclass.

- `src/market_context/contracts_v1.py`
  LocalMaAtrState, ImpulseHealthState, TimingState,
  MarketNavigationState enums and dataclass.

- `src/aplus/factor_extractor.py`
  breathline_phase, breathline_direction, symbolic_target_price
  factor names and PredictionFactorSeed.
