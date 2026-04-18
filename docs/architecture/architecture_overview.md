# Synth v2 — Architecture Overview

## 🎯 Doel
Modulaire trading engine met:

- duidelijke lagen
- explainable decisions
- uitbreidbaarheid
- scheiding analyse vs execution

---

## 🧱 Core Layers

Observation Layer
    ↓
Feature Layer
    ↓
Interpretation Layer
    ↓
Strategy Layer
    ↓
Decision Layer
    ↓
Execution Layer (in ontwikkeling)

---

## 🔍 Observation Layer

Brondata:

- obs_market_candle
- volume data
- exchange data

---

## ⚙️ Feature Layer

Afgeleide data:

- technische indicatoren
- volume metrics
- prijsstructuren

---

## 🧠 Interpretation Layer

Interpretaties zoals:

- trend
- volume regime
- phase / structure

## Measurement Layer v1

A new timeframe-aware measurement layer has been added via `structure_state`.

Purpose:
- keep objective market-state measurements separate from advice, ranking, and human presentation
- provide reusable state inputs for both future entry and exit logic

Current measurement modules:
- `trend_state`
- `pullback_state`
- `reclaim_state`

Design rules:
- measurement states are stored per `asset_id + venue + interval_code + asof_ts_utc`
- measurement layer contains no action labels such as BUY / SELL / PREPARE / AVOID
- interpretation remains downstream in advice / ranking / selection / future final advice

Current storage:
- table: `structure_state`
- latest view: `vw_structure_state_latest`

Current structure state outputs:
- `trend_state`: `UPTREND_STRONG`, `UPTREND_WEAK`, `RANGE`, `DOWNTREND_WEAK`, `DOWNTREND_STRONG`
- `pullback_state`: `NO_PULLBACK`, `HEALTHY_PULLBACK`, `DEEP_PULLBACK`, `POTENTIAL_REVERSAL`
- `reclaim_state`: `NO_RECLAIM_ATTEMPT`, `RECLAIM_ATTEMPT`, `RECLAIM_CONFIRMED`, `FAILED_RECLAIM`

Notes:
- `reclaim_state` is currently a lightweight transition-aware v1 and should later evolve into a more explicit multi-candle / prior-state state machine
- `1h` reclaim currently contributes less than `1h` pullback; `4h/1d` reclaim is more useful as a structural recovery signal

Pipeline now:
`obs_market_candle -> feat_candle -> signal_engine_state -> advice_state -> ranking_state -> selection_state`

Selection integration:
- `selection_engine` now consumes structure-state context in addition to ranking/advice
- especially relevant inputs:
  - `4h trend_state`
  - `1h pullback_state`
  - `4h reclaim_state`
  - `1d reclaim_state`

Architectural boundary:
- human-readable final advice is intentionally not yet implemented here
- targets / zones / invalidation are intentionally deferred to a later dedicated layer

---

## 🧩 Market Structure Layer

### Zones
- support / resistance detectie
- zone strength

### Fibonacci
- retracements + extensions

### Volume context
- ratio
- z-score
- alignment

---

## 📊 Context Layer

### Tabel: strategy_signal_context

Bevat:

- zone_state
- distance_to_support/resistance (bps)
- fib_level
- fib_state
- fib_distance_bps
- zone_confluence_score
- fib_confluence_score
- volume_alignment_score
- context_score

---

## 🧠 Context Score

- zones (40%)
- fib (40%)
- volume (20%)

---

## 📈 Strategy Layer

Interpreteert context → mogelijke acties

---

## 🧾 Decision Layer

Maakt:

- BUY / SELL / HOLD
- position sizing
- sleeve allocation

---

## ⚙️ Execution Layer (next)

- order placement
- order management
- reprice logic

---

## 🧠 Filosofie

Analyse ≠ Execution

- Analyse bepaalt WAT
- Execution bepaalt HOE

---

## 🔮 Toekomst

- Elliott Wave
- multi-timeframe bias
- ML op context features

