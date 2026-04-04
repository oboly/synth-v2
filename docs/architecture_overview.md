# SYNTH Architecture Overview

This document describes the high-level architecture of the Synth analysis engine.

Synth is a modular system designed to transform raw market observations into structured strategy decisions.

Execution is intentionally separated and will be integrated later.

---

# System Philosophy

Synth is designed to be:

- modular
- explainable
- extensible
- research-friendly
- safe for incremental development

The system emphasizes **clarity of responsibility between layers**.

---

# Core Architecture Flow

Synth follows a strict layered architecture.

Observation Layer  
→ Feature Layer  
→ Interpretation Layer  
→ Strategy Layer  
→ Decision Layer  
→ Execution Layer

This pipeline allows Synth to transform raw market observations into explainable strategy decisions.

Each layer has a specific role and should not perform responsibilities belonging to other layers.

---


## Future Modules

- Execution Planner (order optimization layer)
  → see: docs/architecture/execution_planner.md




# Observation Layer

The observation layer collects raw signals from the outside world.

Examples include:

Market Data

- candles
- tickers
- market cap
- volume data

Structural Data

- asset metadata
- sector mappings
- exchange listings

Contextual Inputs

- breathline observations
- astro / cycle calendar
- macro cycle windows

Observation modules store data **without interpretation**.

---

# Feature Layer

The feature layer transforms observations into structured numerical features.

Examples:

Technical Indicators

- SMA
- EMA
- RSI
- ATR

Volume Metrics

- volume ratios
- OBV
- dollar volume

Structural Metrics

- sector strength
- breadth metrics
- volatility measurements

Features are **quantitative transformations** of observations.

---

# Interpretation Layer

The interpretation layer converts features into **market state descriptions**.

Examples:

- market regime
- trend strength
- sector regime
- volatility regime
- breathline alignment state

Interpretations describe the **current environment**.

They do not produce trading decisions.

---

# Strategy Layer

Strategies generate **intentions** based on interpreted states.

Strategies may combine:

- technical features
- sector regimes
- volatility states
- contextual compass inputs

Example strategies:

- breakout strategy
- swing rotation strategy
- parking rotation strategy
- mean reversion strategy

Strategies produce **candidate actions**.

---

# Decision Layer

The decision layer combines strategy outputs and determines the system's final position.

Responsibilities include:

- ranking opportunities
- resolving strategy conflicts
- filtering low-quality setups
- applying risk rules
- managing patience and tolerance

The decision layer produces **final decisions**.

---

# Execution Layer

Execution will be implemented later.

Future responsibilities include:

- exchange connectivity
- order placement
- portfolio management
- position tracking
- risk enforcement

Execution will remain **separate from analysis logic**.

---

# Contextual Compass System

Certain inputs influence system bias without directly triggering trades.

Examples:

- breathline observations
- astro / cycle calendar
- macro cycle signals

These signals influence:

- patience
- ranking
- tolerance
- sector focus

They function as a **contextual compass**.

---

# Sector Awareness

Synth includes sector-aware analysis.

Assets may belong to multiple sectors.

Sector analysis includes:

- sector strength
- sector breadth
- leader / laggard behavior

Sector regimes influence strategy weighting and asset ranking.

---

# Time System

Internal system time:

**UTC**

User display time:

**Europe/Amsterdam**

Market data is processed using **UTC timestamps**.

---

# Currency System

The system uses **EUR as the default reference currency**.

Derived views may provide USD equivalents where necessary.

---

# Modularity Principle

Each module must be:

- independently testable
- independently schedulable
- independent of execution logic

Modules must communicate through **structured data layers**.

---

# Design Goal

The goal of Synth is to create a **transparent market reasoning engine** that can:

- analyze markets
- synthesize strategies
- explain decisions
- evolve safely over time
