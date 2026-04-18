# SYNTH – Start Context for New Chat

This document provides the minimal authoritative context required to resume development of the **Synth trading/analysis engine** in a new chat session.

It summarizes the current architecture, core design rules, repository structure, and current development state.

---

# Project Identity

**Synth** is a modular crypto market analysis and strategy engine.

The system is designed to be:

- explainable
- modular
- research-friendly
- extensible
- safe for incremental development

Execution is **not the current focus**.  
The system is primarily an **analysis and strategy synthesis engine**.

Execution will be integrated later.

---

# Core Architecture

The system follows a strict layered architecture.

Observation Layer  
→ Feature Layer  
→ Interpretation Layer  
→ Strategy Layer  
→ Decision Layer  
→ Execution Layer

Each layer has strict responsibilities and should not leak responsibilities to other layers.

---

# Layer Responsibilities

## Observation Layer

Purpose: ingest raw observations from the world.

Examples:

- market candles
- market tickers
- market cap data
- FX rates
- sector mappings
- breathline observations
- astro / cycle calendar events

Observations may have different time semantics:

- interval based (candles)
- rolling snapshot (tickers)
- point-in-time snapshots
- event based observations (astro / breathline)

Observation modules must **never perform interpretation**.

---

## Feature Layer

Purpose: derive measurable features from raw observations.

Examples:

- SMA / EMA / RSI
- ATR
- volume ratios
- OBV
- volatility regime metrics
- sector strength metrics
- context features

Feature modules transform observations into **structured quantitative signals**.

---

## Interpretation Layer

Purpose: convert features into **state interpretations**.

Examples:

- market regime
- sector regime
- breathline alignment state
- volatility regime
- trend strength
- cluster phase

Interpretations describe **what the system believes the current state is**.

They do not generate trades.

---

## Strategy Layer

Purpose: generate **strategy intentions** based on interpreted states.

Examples:

- breakout strategies
- swing rotation strategies
- parking rotation strategies
- mean reversion strategies

Strategies may combine:

- market features
- interpretation states
- sector regimes
- contextual compass inputs

Strategies output **intent**, not execution.

---

## Decision Layer

Purpose: combine multiple strategy intents and produce **final decisions**.

Responsibilities:

- conflict resolution
- ranking
- weighting
- risk filters
- patience logic

The decision layer determines **what the system would do**.

---

## Execution Layer

Execution is intentionally postponed.

Future responsibilities:

- exchange integration
- order management
- risk limits
- capital allocation
- position tracking

---

# Time System Rules

Internal time rules are strict.

Internal storage:  
**UTC**

Display / UI:  
**Europe/Amsterdam**

Market values:

- default currency: **EUR**

FX data will be derived where necessary.

---

# Context / Compass Inputs

Certain inputs act as **contextual compass signals**, not direct triggers.

Examples:

- breathline observations
- astro / cycle calendar
- macro cycle windows

These inputs:

- influence patience
- influence ranking
- influence tolerance
- influence sector focus

They do **not directly trigger trades**.

---

# Thesis Bias

The system supports discretionary overlays.

Example:

`thesis_bias`

Sources may include:

- remote viewing
- macro thesis
- breathline interpretation
- discretionary strategic views

Rules:

- thesis bias never overrides market confirmation
- thesis bias influences tolerance and patience
- thesis bias acts as an **overlay**

---

# Sector System

The system includes a sector awareness module.

Core ideas:

Assets may belong to **multiple sectors**.

Sector state is derived from:

- sector asset performance
- breadth
- leader / laggard behavior

Components:

- sector table
- asset_sector_map
- sector_snapshot
- sector_regime

Sector regime influences:

- ranking
- rotation
- strategy weighting

---

# Breathline / Compass System

Breathline is treated as a **compass**, not a timing clock.

Core phases:

- Convergence
- Compression
- Expansion
- Integration

Breathline observations enter the system as:

`breathline_input`

They may be transformed into:

`context_feat`

Interpretation modules may derive states such as:

- breathline alignment
- expansion quality
- cluster pressure

---

# Repository Structure (current)

Typical structure:
# SYNTH – Start Context for New Chat

This document provides the minimal authoritative context required to resume development of the **Synth trading/analysis engine** in a new chat session.

It summarizes the current architecture, core design rules, repository structure, and current development state.

---

# Project Identity

**Synth** is a modular crypto market analysis and strategy engine.

The system is designed to be:

- explainable
- modular
- research-friendly
- extensible
- safe for incremental development

Execution is **not the current focus**.  
The system is primarily an **analysis and strategy synthesis engine**.

Execution will be integrated later.

---

# Core Architecture

The system follows a strict layered architecture.

Observation Layer  
→ Feature Layer  
→ Interpretation Layer  
→ Strategy Layer  
→ Decision Layer  
→ Execution Layer

Each layer has strict responsibilities and should not leak responsibilities to other layers.

---

# Layer Responsibilities

## Observation Layer

Purpose: ingest raw observations from the world.

Examples:

- market candles
- market tickers
- market cap data
- FX rates
- sector mappings
- breathline observations
- astro / cycle calendar events

Observations may have different time semantics:

- interval based (candles)
- rolling snapshot (tickers)
- point-in-time snapshots
- event based observations (astro / breathline)

Observation modules must **never perform interpretation**.

---

## Feature Layer

Purpose: derive measurable features from raw observations.

Examples:

- SMA / EMA / RSI
- ATR
- volume ratios
- OBV
- volatility regime metrics
- sector strength metrics
- context features

Feature modules transform observations into **structured quantitative signals**.

---

## Interpretation Layer

Purpose: convert features into **state interpretations**.

Examples:

- market regime
- sector regime
- breathline alignment state
- volatility regime
- trend strength
- cluster phase

Interpretations describe **what the system believes the current state is**.

They do not generate trades.

---

## Strategy Layer

Purpose: generate **strategy intentions** based on interpreted states.

Examples:

- breakout strategies
- swing rotation strategies
- parking rotation strategies
- mean reversion strategies

Strategies may combine:

- market features
- interpretation states
- sector regimes
- contextual compass inputs

Strategies output **intent**, not execution.

---

## Decision Layer

Purpose: combine multiple strategy intents and produce **final decisions**.

Responsibilities:

- conflict resolution
- ranking
- weighting
- risk filters
- patience logic

The decision layer determines **what the system would do**.

---

## Execution Layer

Execution is intentionally postponed.

Future responsibilities:

- exchange integration
- order management
- risk limits
- capital allocation
- position tracking

---

# Time System Rules

Internal time rules are strict.

Internal storage:  
**UTC**

Display / UI:  
**Europe/Amsterdam**

Market values:

- default currency: **EUR**

FX data will be derived where necessary.

---

# Context / Compass Inputs

Certain inputs act as **contextual compass signals**, not direct triggers.

Examples:

- breathline observations
- astro / cycle calendar
- macro cycle windows

These inputs:

- influence patience
- influence ranking
- influence tolerance
- influence sector focus

They do **not directly trigger trades**.

---

# Thesis Bias

The system supports discretionary overlays.

Example:

`thesis_bias`

Sources may include:

- remote viewing
- macro thesis
- breathline interpretation
- discretionary strategic views

Rules:

- thesis bias never overrides market confirmation
- thesis bias influences tolerance and patience
- thesis bias acts as an **overlay**

---

# Sector System

The system includes a sector awareness module.

Core ideas:

Assets may belong to **multiple sectors**.

Sector state is derived from:

- sector asset performance
- breadth
- leader / laggard behavior

Components:

- sector table
- asset_sector_map
- sector_snapshot
- sector_regime

Sector regime influences:

- ranking
- rotation
- strategy weighting

---

# Breathline / Compass System

Breathline is treated as a **compass**, not a timing clock.

Core phases:

- Convergence
- Compression
- Expansion
- Integration

Breathline observations enter the system as:

`breathline_input`

They may be transformed into:

`context_feat`

Interpretation modules may derive states such as:

- breathline alignment
- expansion quality
- cluster pressure

---

# Repository Structure (current)

Typical structure:
repo/

src/
db/
ingestion/
compute/
features/
interpretation/
strategies/
decision/

docs/

config/

scripts/

tests/


---

# Configuration Rules

Secrets are stored in:

`.env`

Runtime configuration:

`config.yaml`

Database helpers:

`src/db/db.py`

Python environment:

`venv`

---

# Current Development State

Current work has focused on:

- database schema design
- modular architecture definition
- sector module design
- contextual compass inputs
- breathline integration
- astro/cycle calendar integration
- thesis overlay system

Execution layer has not yet been implemented.

---

# Current Priority

Short-term priorities:

1. stabilize schema
2. integrate sector modules
3. integrate context/compass modules
4. implement feature generation
5. implement interpretation modules
6. build strategy modules
7. build decision engine
8. postpone execution

---

# Key Design Principles

1. Modules must remain independent.
2. Interpretation must not occur in ingestion.
3. Strategies produce intent, not trades.
4. Decision layer resolves conflicts.
5. Context inputs influence bias but do not trigger trades.
6. Internal time must always remain UTC.
7. System must remain explainable.

---

# End of Start Context
