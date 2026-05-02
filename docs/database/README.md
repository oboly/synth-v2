# Synth Database Schema Reference

This document is the database reference for Synth v2.5.

It defines:

- canonical table families
- canonical column names
- join contracts
- time alignment rules
- profile/state boundaries
- research/live separation

If something is unclear:

    update this document
    do not solve it only in code or chat

---

## 1. Architecture

Canonical live/research pipeline:

    OBS
    → FEAT
    → MEASUREMENT / EVENT
    → SIGNAL
    → RANKING
    → SELECTION
    → DECISION
    → EXECUTION

Research lanes:

    REPLAY / BACKTEST / PAPER / ORACLE

Research lanes may read live-safe upstream data, but must not write into live decision or execution layers.

---

## 2. Table Families

### Observation Layer

Prefix:

    obs_*

Purpose:

- raw external observations
- exchange candles
- market data
- orderbook snapshots later

Primary table:

    obs_market_candle

---

### Feature Layer

Prefix:

    feat_*

Purpose:

- derived indicators
- context features
- non-decision feature calculations

Primary table:

    feat_candle

---

### Measurement / Event Layer

Prefixes:

    structure_*
    feat_*_event
    measurement_*

Purpose:

- objective market measurements
- liquidity events
- rejection events
- structure state
- no buy/sell decisions

Examples:

    structure_state
    feat_rejection_event
    feat_liquidity_event

---

### Signal Layer

Tables/prefixes:

    signal_engine_state
    signal_*

Purpose:

- interpretation of features and measurements
- categorical signal dimensions
- no account logic
- no execution logic

---

### Ranking Layer

Prefix:

    ranking_*

Purpose:

- relative ranking
- rotation state
- market-only prioritization

---

### Selection Layer

Tables/prefixes:

    selection_state
    selection_*

Purpose:

- market-only candidate selection
- account-agnostic state
- no balance checks
- no order checks
- no execution planning

---

### Decision Layer

Tables/prefixes:

    decision_log
    decision_*

Purpose:

- account-aware permission layer
- balance/capacity/position/order gating
- no order placement

---

### Execution Layer

Prefix:

    execution_*

Purpose:

- execution plans
- execution events
- order handling metadata
- executor/agent state

---

### Research / Backtest Layer

Prefixes:

    research_*
    bt_*

Purpose:

- replay outputs
- forward-return evaluation
- paper candidates
- oracle research
- future-aware labels where explicitly documented

Research outputs must never be consumed by live inference unless transformed into a live-safe strategy and validated separately.
