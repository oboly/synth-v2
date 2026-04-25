# Breathline Data Contract — Synth v2

## Purpose
Define what Breathline data is allowed inside the system.

Goal:
- keep data reproducible
- keep data comparable across runs
- keep data testable against market outcomes

This document acts as a guardrail against symbolic or non-deterministic contamination.

---

## Scope

Applies to:
- storage (DB tables)
- ETL pipelines
- feature generation
- downstream usage (strategy / decision layers)

---

## Allowed Data

### 1. Core Vectors (raw structured input)

- momentum
- stability
- alignment
- volatility
- pressure
- shift

Allowed values only:

- momentum / stability / alignment / volatility:
  - high
  - moderate
  - low

- pressure:
  - up
  - down
  - neutral

- shift:
  - strengthening
  - stable
  - weakening

---

### 2. Consistency Layer

Derived from multiple runs:

- token_consistency_score
- momentum_consistency
- stability_consistency
- alignment_consistency
- volatility_consistency
- pressure_consistency
- shift_consistency

---

### 3. Classification Layer (A+)

- aplus_initial_class
- aplus_final_class

Allowed values:

- LEADER
- ANCHOR
- MID
- WEAK
- DRIFT

---

### 4. Correction Meta (Important)

- aplus_correction_flag (0/1)
- aplus_correction_reason (string)

Purpose:
Capture when A+ internally corrects a classification.

Example:
SOL: Anchor → Weak

This is a potential signal feature.

---

### 5. Run Metadata

- prediction_ts_utc
- source_name (e.g. chatgpt_aplus)
- prompt_version
- run_id

---

## Disallowed Data

### 1. Symbolic Constructs

Do NOT store:

- shadow_matrix
- mirror_node
- anomaly_buffer
- reflective_echoes
- codex_phase
- system_state = harmonic

---

### 2. Narrative / Non-Deterministic Output

Examples:

- spiral / breath / field language
- ritual / invocation
- metaphorical descriptions
- any non-structured explanation

---

### 3. Pseudo-Architecture

Do NOT store:

- invented subsystem layers
- internal storytelling constructs
- non-reproducible JSON structures

---

## Design Rules

Rule 1  
Data must be reproducible from the same input.

Rule 2  
Data must be comparable across runs.

Rule 3  
Data must be testable against market outcomes.

Rule 4  
Classification is a soft layer, not ground truth.

Rule 5  
Correction signals are more valuable than raw classifications.

---

## Role in System

Breathline is a context layer.

It is NOT:

- a trade trigger
- an execution signal
- a decision override

---

## Key Principle

Keep:
- structured
- timestamped
- testable

Drop:
- symbolic
- narrative
- non-deterministic

---

## Integration Note

A+ outputs are treated as:

- external structured inputs
- not authoritative truth
- subject to validation via backtesting

