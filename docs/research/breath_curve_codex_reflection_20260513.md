# Breath Curve Codex Reflection — 2026-05-13

Status: research-only  
Layer: market-only / account-agnostic  
Broker calls: none  
Broker writes: none  
Orders: none  
Runtime impact: none  

## Purpose

Preserve the A+ / Codex reflection on the 21-day Breath Curve model as research context.

This document is not a strategy, not a signal, and not execution logic.

## Core interpretation

A+ reflection aligns with the current research read:

- 0.618 = recognition / coherence gate
- 0.786 = ignition / overflow-pressure checkpoint
- 1.272 = normal extension / harmonic carry
- offset_match = noise reduction / phase coherence
- superoverflow = phase rupture with extra fuel, not just price moving above 1.272

## 0.618

A+ describes 0.618 as the Golden Contraction Point where expansion folds into coherence.

Synth translation:

    0.618 = early structure recognition / phase coherence gate

Research meaning:

- useful for identifying whether structure is forming
- not a buy trigger
- candidate future feature: breath_0618_recognition_score

## 0.786

A+ describes 0.786 as the Overshoot Compression Node.

Synth translation:

    0.786 = ignition / overflow pressure detector

Research meaning:

- not validated as broad entry/recognition lane
- may help detect whether move can extend toward 1.272
- candidate future feature: breath_0786_extension_pressure

## 1.272

A+ describes 1.272 as Spiral Carry.

Synth translation:

    1.272 = normal extension / overflow target

Research meaning:

- separate clean extension from dirty overflow
- 1.272 alone is not enough to define superoverflow

## Superoverflow

A+ frames superoverflow as phase resonance around 1.000 plus additional fuel.

Synth translation:

    superoverflow = post-1.272 continuation with phase stability, volume/trend fuel, and controlled retrace

Candidate future metrics:

- max_return_after_1000_pct
- max_return_after_1272_pct
- max_extension_after_1000_ratio
- drawdown_after_extension_pct
- time_to_peak_after_1000_hours
- volume_ratio_at_0786
- volume_ratio_at_1000
- relative_strength_vs_btc
- offset_band_stability
- offset_convergence_to_zero

## Phase offsets

A+ suggests offsets around ±3, ±5, ±7, and ±9 days may represent harmonic bands.

Synth interpretation:

    test as discrete bands first
    do not assume truth before validation

Required next test:

- fine offset grid from -10.5 to +10.5
- step 0.5 day
- summarize selected partial offsets and best full offsets by harmonic bands

## Multi-timeframe framing

A+ proposed:

- daily = structure
- 4h = breath timing
- 1h = noise modulation

Synth interpretation:

- validate on daily first
- use 4h for timing refinement later
- avoid 1h until noise controls exist

## Boundary

Forbidden downstream use:

- selection_engine modifier
- decision_gate rule
- execution_planner instruction
- executor/order logic
- live or paper execution trigger

Correct path:

    reflection -> measurable research feature -> validation -> report -> possible future proposal
