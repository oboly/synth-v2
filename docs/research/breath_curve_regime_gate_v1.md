# Breath Curve Regime Gate v1

Status: research-only  
Layer: market-only / account-agnostic  
Broker calls: none  
Broker writes: none  
Orders: none  
Runtime impact: none  

## Purpose

Diagnose whether the Breath Curve 0.618 selected -8 edge is regime-gated rather than generally robust.

The previous non-overlap / older-history validation rejected the ungated candidate as a general strategy.

This runner does not attempt to rescue the strategy by tuning thresholds. It compares winning and failing regimes to identify whether a pre-measurable regime gate may exist.

## Primary question

Not:

    Is selected -8 always good?

But:

    When is selected -8 allowed to matter?

## Default target

    minus8_core_symbols_v1

Meaning:

    0.618 selected -8
    + symbol in [BTC, ETH, FIL, TAO]
    -> early pulse-to-1.000 candidate

## Inputs

Reads generated broader-history validation runs under:

    data/research/breath_curve_broader_history_v1/

For each run it reads:

    aggregate_comparison_summary.csv
    all_cohort_comparison_rows.csv
    per-cohort composite preview summaries

## Duplicate run handling

By default, runs with non-zero post-pad random windows are excluded.

A clean run requires each cohort row to have:

    random_window_end == latest anchor in cohort

This avoids comparing clean real anchors against random anchors with different forward-data availability.

By default, runs with identical `cohort_manifest.csv` signatures are also deduplicated.

When duplicate manifests exist, the newest run is retained.

This prevents repeated reruns of the same cohort set from being counted multiple times.

Use these only for debugging:

    --include-duplicate-manifests
    --include-non-zero-post-pad-runs

## Classification

A run is classified as:

    WINNING_REGIME
        target edge > 0
        target real eligible >= min-winning-real-eligible

    FAILING_REGIME
        target edge <= 0

    NEUTRAL_OR_SAMPLE_THIN
        all other cases

Default min-winning-real-eligible:

    10

## Outputs

Generated CSV files are written under:

    data/research/breath_curve_regime_gate_v1/

Outputs:

    run classification
    composite separation summary
    target cohort details
    cohort class summary
    target real bucket rows
    target real bucket summary

## Intended interpretation

A useful regime-gate candidate should show:

    positive edge in winning regimes
    weak or negative edge in failing regimes
    clear separation between winning and failing regimes
    preferably pre-measurable context differences

Candidate dimensions:

    BTC/ETH context
    symbol trend bucket
    volume bucket
    RSI bucket
    symbol distribution

## Boundary

Allowed:

    research-only diagnostics
    market-only analysis
    generated CSV outputs
    regime hypothesis generation

Forbidden:

    selection_engine modifier
    decision_gate rule
    execution_planner instruction
    executor/order logic
    broker API call
    broker write
    live or paper execution trigger

## Correct path

    regime-gate diagnostic
    -> pre-measurable gate hypothesis
    -> validation
    -> scoring board
    -> optional paper-candidate proposal

## Incorrect path

    winning window found
    -> tune until green
    -> paper/live

That would be curve fitting.
