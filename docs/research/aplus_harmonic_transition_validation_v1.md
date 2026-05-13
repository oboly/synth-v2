# A+ Harmonic Transition Validation v1

Status: research-only  
Layer: market-only / account-agnostic  
Broker calls: none  
Broker writes: none  
Orders: none  
DB writes: none  

## Purpose

Validate A+ harmonic phase movement across multiple snapshots.

This is designed to answer:

- Do tokens progress from early/forming phases into clean 0.618 recognition?
- Do clean 0.618 tokens progress into 0.786 overflow pressure?
- Do 0.786 overflow states progress into 1.000 / 1.272 extension?
- Does clean-to-dirty transition warn about exhaustion?
- Does drift or +7/+10.5 offset mark late/unstable phase behavior?

## Current behavior with one snapshot

With only one stored A+ harmonic snapshot, the runner reports:

- current phase bucket distribution
- current quality bucket distribution
- transition_count = 0
- ready_for_next_snapshot = true

This lets us test the harness now.  
Tomorrow, adding another snapshot enables true transition analysis.

## Inputs

Default snapshot glob:

    data/external/aplus_harmonic_phase_overlay/*.jsonl

Expected JSONL fields:

- snapshot_id
- snapshot_ts_local
- token
- phase_marker
- phase_offset_band
- phase_stability
- recognition_0618
- overflow_0786
- extension_1272
- regime_fit
- clean_or_dirty

## Transition types

Examples:

- EARLY_TO_FORMING
- FORMING_TO_RECOGNITION
- RECOGNITION_TO_OVERFLOW
- OVERFLOW_TO_EXTENSION
- CLEAN_TO_DIRTY
- DIRTY_TO_CLEAN
- OFFSET_CONVERGED
- OFFSET_DRIFTED
- LATE_EXTENSION
- UNCLEAR_TRANSITION

## Boundary

This is not a strategy.

Forbidden downstream use:

- selection_engine modifier
- decision_gate rule
- execution_planner instruction
- executor/order logic
- live or paper execution trigger
