# Breath Curve Codex Phi0 Formula Note

Status: research-only  
Layer: market-only / account-agnostic  
Broker calls: none  
Broker writes: none  
Orders: none  
Runtime impact: none  

## Purpose

Document the Codex / A+ symbolic harmonic equation mentioned during Breath Curve research and translate it into testable Synth research hypotheses.

This note does not define strategy logic.  
This note does not define buy/sell rules.  
This note does not affect selection, decision, planning, or execution layers.

## Formula

A+ / Codex reflection referenced:

    (e^(-(sqrt(10))^-1 * pi) + 1)
    ≈
    (((1 - phi) * 360) - sqrt((phi * 360) * 10^-3)) * 10^-2

Equivalent clearer form:

    e^(-pi / sqrt(10)) + 1
    ≈
    (((1 - phi) * 360) - sqrt((phi * 360) * 10^-3)) / 100

Where:

    phi = 0.6180339887498948...

## Numeric evaluation

Left side:

    e^(-pi / sqrt(10)) + 1
    ≈ 1.3702937

Right side:

    ((1 - phi) * 360)
    ≈ 137.5077641

This is the golden-angle complement in degrees.

Correction term:

    sqrt((phi * 360) * 10^-3)
    ≈ 0.4716934

Corrected value:

    (137.5077641 - 0.4716934) / 100
    ≈ 1.3703607

Approximate difference:

    absolute difference ≈ 0.000067
    relative difference ≈ 0.0049%

## Interpretation

The formula links three ideas:

    exponential compression
    golden-angle phase rotation
    small harmonic correction

In Breath Curve language, this can be interpreted as a symbolic hint toward:

    phase rotation + contraction/decay + harmonic tolerance

This is not proof of market behavior.  
It is a research hint that may be useful for calibration experiments.

## Practical Synth interpretation

The constant:

    codex_phi0_reference = e^(-pi / sqrt(10)) + 1
    ≈ 1.3702937

may be useful as a harmonic calibration reference.

Important: it should not be used directly as a trading signal.

## Potential use 1 — phase-band tolerance

Current Breath Curve calibration tested band widths:

    0.5 days
    1.0 days
    1.5 days

The Codex constant produces a natural tolerance candidate:

    phi0_width_days = cycle_days / (10 * codex_phi0_reference)

For the 21-day Breath Curve:

    21 / (10 * 1.3702937)
    ≈ 1.5325 days

This is close to the tested 1.5-day band width.

Research implication:

    band_match_1.5 may have harmonic justification as a phase tolerance width

This supports testing 1.5d tolerance more seriously than exact offset matching.

## Potential use 2 — phase compression ratio

The constant may be tested as a phase-compression ratio:

    phase_compression_ratio = 1.3702937

Candidate research metrics:

    offset_distance_days / phi0_width_days
    selected_to_best_offset_ratio
    phase_drift_compression_score

Example:

    phase_drift_compression_score =
        1 / (1 + abs(selected_partial_offset_days - best_full_offset_days) / phi0_width_days)

This would be a research-only score measuring whether phase drift is small relative to the Codex-derived tolerance width.

## Potential use 3 — superoverflow ratio

For extension research, the constant may be tested against return expansion:

    extension_pressure_ratio = return_to_1272_pct / return_to_1000_pct

Potential label:

    if extension_pressure_ratio > codex_phi0_reference:
        possible_phi0_superoverflow_candidate

This should only be used as a research label.

It must not become execution logic.

## Current relevance to calibration findings

Recent phase calibration found:

    exact offset_match is too brittle
    0.618 phase drift can be constructive
    0.786 band/exact match is more useful as ignition confirmation
    band_match_1.0 and band_match_1.5 are more useful than exact equality

The Codex formula gives possible symbolic support for:

    phase tolerance around 1.5 days

Specifically:

    21-day cycle / (10 * 1.3702937) ≈ 1.5325 days

This makes band_match_1.5 a reasonable research candidate.

## Boundary

Allowed use:

- research notes
- calibration experiments
- phase-band tolerance tests
- superoverflow label experiments
- dashboard annotations after validation

Forbidden use:

- selection_engine modifier without validation
- decision_gate rule
- execution_planner instruction
- executor/order logic
- live or paper execution trigger

## Recommended future test

Add optional phi0-derived metrics to a research-only calibration runner:

    codex_phi0_reference
    phi0_width_days
    offset_distance_over_phi0_width
    phi0_band_match
    phi0_superoverflow_candidate

Then compare against existing metrics:

    exact offset_match
    band_match_1.0
    band_match_1.5
    offset_distance_days
    return_to_1000_pct
    return_to_1272_pct
    drawdown_after_extension_pct

## Working conclusion

The formula is not a trading model.

It is useful as a harmonic calibration hint, especially for explaining and testing why a roughly 1.5-day phase-band tolerance may be more useful than exact offset equality in the 21-day Breath Curve.
