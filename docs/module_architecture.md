# Synth Module Architecture

This document defines how Synth modules are structured and how they interact.

The goal is to keep the system:

- modular
- explainable
- schedulable
- easy to extend
- safe to refactor

Each module belongs to a specific **architecture layer** and must only perform responsibilities belonging to that layer.

---

# Architecture Layers

Synth is structured as a layered pipeline:

Observation Layer  
→ Feature Layer  
→ Interpretation Layer  
→ Strategy Layer  
→ Decision Layer  
→ Execution Layer (future)

Modules must not skip layers.

Example rule:

- a strategy module must never read raw market candles directly
- it should use features or interpretation states

---

# Observation Modules

Purpose: ingest and store raw external observations.

Observation modules are the only components allowed to read external data sources.

Examples:

Market observations

- market candles
- ticker snapshots
- market cap data
- exchange metadata

Structural observations

- asset metadata
- sector mappings

Context observations

- breathline observations
- astro / cycle calendar events
- macro cycle windows

Observation modules must **not interpret the data**.

They only normalize and store it.

Typical tables:
candle_feat
context_feat


Feature modules should be deterministic transformations of observations.

---

# Interpretation Modules

Purpose: convert features into **market state descriptions**.

Interpretation modules answer the question:

"What environment are we in?"

Examples:

Market interpretation

- trend regime
- volatility regime
- consolidation state

Sector interpretation

- sector regime
- sector rotation

Context interpretation

- breathline alignment
- macro cycle phase
- calendar influence state

Typical tables:

Feature modules should be deterministic transformations of observations.

---

# Interpretation Modules

Purpose: convert features into **market state descriptions**.

Interpretation modules answer the question:

"What environment are we in?"

Examples:

Market interpretation

- trend regime
- volatility regime
- consolidation state

Sector interpretation

- sector regime
- sector rotation

Context interpretation

- breathline alignment
- macro cycle phase
- calendar influence state

Typical tables:



Interpretation modules should remain explainable.

They produce **states**, not trades.

---

# Strategy Modules

Purpose: generate strategy opportunities based on interpreted market states.

Strategies combine:

- feature signals
- interpretation states
- sector context
- contextual compass signals

Strategies generate **candidate trade ideas**.

Examples:

Breakout strategies

- trend breakout
- volatility expansion

Rotation strategies

- sector rotation
- leadership rotation

Mean reversion strategies

- range bounce
- volatility contraction

Example output table:

Interpretation modules should remain explainable.

They produce **states**, not trades.

---

# Strategy Modules

Purpose: generate strategy opportunities based on interpreted market states.

Strategies combine:

- feature signals
- interpretation states
- sector context
- contextual compass signals

Strategies generate **candidate trade ideas**.

Examples:

Breakout strategies

- trend breakout
- volatility expansion

Rotation strategies

- sector rotation
- leadership rotation

Mean reversion strategies

- range bounce
- volatility contraction

Example output table:
strategy_signal


A strategy module should never place trades directly.

It proposes opportunities.

---

# Decision Modules

Purpose: combine strategy signals and determine final actions.

Responsibilities include:

- ranking strategy opportunities
- filtering weak setups
- resolving conflicting signals
- applying risk rules
- applying patience rules
- incorporating contextual bias

Example table:

A strategy module should never place trades directly.

It proposes opportunities.

---

# Decision Modules

Purpose: combine strategy signals and determine final actions.

Responsibilities include:

- ranking strategy opportunities
- filtering weak setups
- resolving conflicting signals
- applying risk rules
- applying patience rules
- incorporating contextual bias

Example table:
decision_log


Decision modules produce **final system decisions**.

They do not interact with exchanges.

---

# Execution Modules (Future)

Execution modules will manage live trading.

Responsibilities will include:

- exchange connectivity
- order placement
- order management
- capital allocation
- position tracking
- risk enforcement

Execution will be isolated from analysis logic.

---

# Context / Compass Modules

Certain modules provide **contextual bias** rather than direct signals.

Examples:

Breathline observations

- convergence
- compression
- expansion
- integration

Astro / cycle calendar events

- moon phases
- planetary cycles
- macro timing windows

These inputs influence:

- patience
- ranking
- tolerance
- strategy weighting

They do **not trigger trades directly**.

---

# Sector Modules

Sector modules allow Synth to reason about market structure.

Assets may belong to multiple sectors.

Sector analysis includes:

- sector strength
- breadth
- leadership behavior
- sector rotation

Core tables:
sector
asset_sector_map
sector_snapshot
sector_regime


Sector regimes influence strategy weighting and asset ranking.

---

# Thesis Bias Overlay

Synth supports discretionary bias overlays.

Example table:
thesis_bias


Possible sources:

- macro thesis
- breathline interpretation
- remote viewing
- discretionary strategic views

Rules:

- thesis bias never overrides market confirmation
- thesis bias influences tolerance and patience
- thesis bias acts as an overlay

---

# Module Design Rules

Every module should follow these rules:

1. Modules should depend only on the previous layer.
2. Modules should be schedulable independently.
3. Modules must produce deterministic outputs.
4. Modules should not perform multiple layer responsibilities.
5. Modules must remain explainable.
6. Modules should write results only to their own layer tables.
7. Cross-layer writes should be avoided.
8. Modules must not depend on dashboard logic.

---

# Module Independence

Each module should be runnable independently.

Examples:

Feature modules can run whenever new candles arrive.

Interpretation modules can run:

- periodically
- after feature updates
- after sector updates

Strategy modules can run:

- after interpretation updates
- on schedule

Decision modules run after strategy updates.

---

# Design Goal

The architecture allows Synth to evolve into a **transparent reasoning engine** that:

- observes markets
- derives features
- interprets environments
- generates strategies
- makes explainable decisions
