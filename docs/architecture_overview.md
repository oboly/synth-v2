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

