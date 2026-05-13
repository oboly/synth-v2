# Breath Curve Regime-Gated Policy Preview v1

Status: research-only  
Layer: market-only / account-agnostic  
Broker calls: none  
Broker writes: none  
Orders: none  
Runtime impact: none  

## Purpose

Test explicit pre-measurable regime gates for the Breath Curve selected -8 candidate.

This is not a live policy.

The previous diagnostic showed:

    ungated selected -8 is not generally robust
    selected -8 may have strong edge inside an alt-core rotation regime

This runner tests candidate gates across clean winning and failing broader-history runs.

## Core idea

Most strategies are regime-dependent.

Therefore strategy scoring should evolve from:

    score(strategy)

to:

    score(strategy, regime_context)

## Inputs

Reads clean broader-history run outputs under:

    data/research/breath_curve_broader_history_v1/

A clean run requires:

    random_window_end == latest anchor in cohort

Duplicate manifest runs are deduped by default.

The runner reads per-cohort symbol-regime policy rows.

## Default target

    minus8_core_symbols_v1

Default core symbols:

    BTC, ETH, FIL, TAO

Default alt-core proxy symbols:

    ETH, FIL, TAO

## Gates

Gate v1 tests:

    gate_01_minus8_core_symbols
    gate_02_minus8_core_btc_eth_bear
    gate_03_minus8_core_volume_expansion
    gate_04_minus8_core_rsi_mid_high
    gate_05_minus8_core_bear_volume
    gate_06_minus8_alt_core_participation_proxy
    gate_07_minus8_alt_core_bear_volume_or_rsi
    gate_08_early_band_core_bear_or_volume

## Interpretation

A useful gate should show:

    positive edge in winning regime
    weak or negative edge in failing regime
    positive winning worst-case
    enough real/random samples
    clear edge separation

## Output

Generated files:

    run_meta.csv
    policy_rows.csv
    source_summary.csv
    comparison.csv
    symbol_summary.csv

Output directory:

    data/research/breath_curve_regime_gated_policy_preview_v1/

This directory is ignored by git.

## Boundary

Allowed:

    research-only gate preview
    market-only validation
    candidate scoring evidence

Forbidden:

    selection_engine modifier
    decision_gate rule
    execution_planner instruction
    executor/order logic
    broker call
    broker write
    paper or live trigger

## Correct path

    regime-gated policy preview
    -> validation
    -> strategy scoring board per regime
    -> optional paper-candidate contract
    -> decision_gate
    -> execution_planner
    -> paper executor

## Wrong path

    regime gate looks good
    -> live

No.
