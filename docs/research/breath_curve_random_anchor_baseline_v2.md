# Breath Curve Random-Anchor Baseline v2

Status: research-only  
Layer: market-only / account-agnostic  
Broker calls: none  
Broker writes: none  
Orders: none  
Runtime impact: none  

## Purpose

Test whether calibrated 0.618 Breath Curve early-recognition filters outperform same-symbol random anchors.

This is the first hard edge test after phase calibration showed that exact offset-match is too brittle for 0.618.

## Critical correction

This runner tests only early-available filters.

It does not use these post-hoc labels as entry filters:

    0786_ignition_band_match_v1
    extension_best_full_plus7_v1
    best_full_band
    selected-to-best phase drift

Those can be used later as outcome classes, not checkpoint-time filters.

## Tested policies

### 0618_selected_minus8_v1

Gate:

    checkpoint = 0.618
    selected_band_w1_0 = -8

Purpose:

    primary early-recognition candidate

### 0618_selected_minus7_v1

Gate:

    checkpoint = 0.618
    selected_band_w1_0 = -7

Purpose:

    secondary early-recognition candidate

### 0618_selected_early_band_v1

Gate:

    checkpoint = 0.618
    selected_band_w1_0 in [-8, -7]

Purpose:

    combined early-recognition candidate

## Method

For each symbol:

1. Use the real Breath Curve anchors.
2. Generate random anchors inside the same date window.
3. Exclude random anchors close to real anchors.
4. Recompute partial matching at 0.618.
5. Recompute full-cycle outcomes.
6. Apply the same early-available calibrated filters.
7. Compare real anchors against same-symbol random anchors.

## Metrics

The report includes:

    evaluated rows
    eligible rows
    selection rate
    average return to 1.000
    median return to 1.000
    positive rate to 1.000
    best/worst return to 1.000
    average return to 1.272
    positive rate to 1.272
    by-symbol summaries

Important:

    selection_rate is measured against all evaluated anchors,
    not only against selected rows.

## Runner

Default:

    python -m src.research.run_breath_curve_random_anchor_baseline_v2 --output table

Recommended smoke:

    python -m src.research.run_breath_curve_random_anchor_baseline_v2 \
      --random-count-per-symbol 10 \
      --output table

Recommended fuller run:

    python -m src.research.run_breath_curve_random_anchor_baseline_v2 \
      --random-count-per-symbol 100 \
      --output table

## Output

Generated CSV files are written under:

    data/research/breath_curve_random_anchor_baseline_v2/

This path is ignored by git.

## Boundary

Allowed:

    research-only matching
    same-symbol random-anchor comparison
    market-only validation
    generated research CSV output

Forbidden:

    selection_engine modifier
    decision_gate rule
    execution_planner instruction
    executor/order logic
    broker API call
    broker write
    live or paper execution trigger

## Interpretation rule

A calibrated filter becomes interesting only if it beats same-symbol random anchors on:

    average return
    positive rate
    worst-case profile
    selection quality

Passing this test does not make it a live strategy.

Correct path:

    random-anchor baseline
    -> regime bucket validation
    -> broader history
    -> optional market-only feature proposal

Incorrect path:

    random-anchor win
    -> BUY_READY

That would bypass the architecture.
