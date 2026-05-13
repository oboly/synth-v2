# A+ Harmonic Snapshot Validation v1

Status: research-only  
Layer: market-only / account-agnostic  
Broker calls: none  
Broker writes: none  
Orders: none  
DB writes: none  

## Purpose

Validate whether A+ harmonic phase snapshot buckets add useful structure to Breath Curve research outcomes.

This compares:

- A+ clean 0.618 recognition basket
- A+ dirty / late overflow basket
- A+ forming / early basket
- other / unclear bucket

against:

- real Breath Curve policy DB rows
- same-symbol random-anchor baseline samples

## Inputs

A+ snapshot:

    data/external/aplus_harmonic_phase_overlay/aplus_breathline_harmonic_snapshot_20260513_0358.jsonl

Real Breath Curve policy rows:

    research_breath_curve_policy_run
    research_breath_curve_policy_result

Random-anchor baseline samples:

    data/research/breath_curve_random_anchor_baseline_v2/*samples*.csv

## Buckets

Clean 0.618 recognition:

    phase_marker = 0.618
    recognition_0618 = confirmed
    regime_fit = high
    clean_or_dirty = clean

Dirty / late overflow:

    phase_marker in 1.000 / 1.272
    extension_1272 = exceeded

Forming / early:

    phase_marker in 0.236 / 0.382 / 0.500
    recognition_0618 = forming

Other:

    all remaining labels

## Boundary

This is not a strategy.

Forbidden downstream use:

- selection_engine modifier
- decision_gate rule
- execution_planner instruction
- executor/order logic
- live or paper execution trigger
