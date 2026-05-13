# Breath Curve Calibrated Policy Findings — 2026-05-13

Status: research-only  
Layer: market-only / account-agnostic  
Broker calls: none  
Broker writes: none  
Orders: none  
Runtime impact: none  

## Source

Input CSV:

    data/research/breath_curve_template_matcher_v1/breath_curve_partial_to_full_v1_20260513T022333Z.csv

Runner:

    python -m src.research.run_breath_curve_calibrated_policy_backtest_v1

Input rows:

    48

Annotated rows:

    48

Policy rows:

    24

## Core correction

Exact offset-match is no longer a primary quality filter.

The calibrated model separates:

    early recognition
    ignition coherence
    extension outcome

This matters because some fields are available at checkpoint time, while others are only known after the full cycle resolves.

## Policy classification

### 0618_selected_early_band_v1

Classification:

    early-recognition research candidate

This is the primary candidate because it uses the selected partial offset at the 0.618 checkpoint.

Summary:

| metric | value |
|---|---:|
| rows | 12 |
| avg partial score | 0.8926 |
| avg offset distance | 6.75 |
| avg return to 1.000 | 7.8456 |
| positive to 1.000 | 100.00% |
| avg return to 1.272 | 5.4711 |
| positive to 1.272 | 75.00% |
| best return to 1.000 | 26.6212 |
| worst return to 1.000 | 2.2444 |
| best return to 1.272 | 29.5296 |
| worst return to 1.272 | -3.7737 |

Interpretation:

0.618 selected early band is currently the cleanest early measured recognition candidate.

### Selected -8 vs -7

The selected -8 band outperformed selected -7 in this run.

| selected band | rows | avg return to 1.000 | positive to 1.000 | avg return to 1.272 | positive to 1.272 |
|---|---:|---:|---:|---:|---:|
| -8 | 8 | 9.2598 | 100.00% | 7.2601 | 87.50% |
| -7 | 4 | 5.0171 | 100.00% | 1.8931 | 50.00% |

Interpretation:

The next random-anchor baseline should test selected -8 and selected -7 separately, not only as a combined early band.

### 0786_ignition_band_match_v1

Classification:

    post-hoc ignition coherence label

Summary:

| metric | value |
|---|---:|
| rows | 8 |
| avg partial score | 0.9041 |
| avg offset distance | 0.25 |
| avg return to 1.000 | 6.3182 |
| positive to 1.000 | 100.00% |
| avg return to 1.272 | 14.6662 |
| positive to 1.272 | 100.00% |
| best return to 1.272 | 38.4358 |
| worst return to 1.272 | 3.3784 |

Interpretation:

0.786 band coherence is strong as an ignition / overflow confirmation label.

Important limitation:

This policy uses best-full band information through band_match. That is full-cycle information and is not available at checkpoint time.

Therefore it must not be treated as an entry filter.

Correct use:

    post-hoc label
    future target class
    training/validation label for finding pre-confirmation predictors

### extension_best_full_plus7_v1

Classification:

    post-hoc extension / overflow outcome label

Summary:

| metric | value |
|---|---:|
| rows | 4 |
| avg partial score | 0.9183 |
| avg offset distance | 9.00 |
| avg return to 1.000 | 2.9512 |
| positive to 1.000 | 75.00% |
| avg return to 1.272 | 26.5163 |
| positive to 1.272 | 100.00% |
| best return to 1.272 | 43.1473 |
| worst return to 1.272 | 6.6034 |

Symbol concentration:

| symbol | rows | avg return to 1.272 |
|---|---:|---:|
| FIL | 2 | 41.0442 |
| PEPE | 2 | 11.9885 |

Interpretation:

Best-full +7 appears to describe an extension / overflow path, but it is not known at checkpoint time.

Correct use:

    outcome class
    extension target label
    later training label

Incorrect use:

    live filter
    selection_engine modifier
    decision_gate rule

## Phase drift read

For 0.618 selected early band:

| drift bucket | rows | avg return to 1.000 | avg return to 1.272 |
|---|---:|---:|---:|
| DRIFT_BACKWARD_0_3D | 3 | 7.8566 | 2.5269 |
| DRIFT_BACKWARD_3D_PLUS | 1 | 3.8336 | 3.4020 |
| DRIFT_FLAT_0_5D | 1 | 9.8042 | -0.7086 |
| DRIFT_FORWARD_3_7D | 3 | 10.8740 | 14.5109 |
| DRIFT_FORWARD_7D_PLUS | 4 | 6.0792 | 2.9616 |

Interpretation:

Constructive forward drift from 0.618 may be useful, especially DRIFT_FORWARD_3_7D.

However, drift itself relies on best-full information and is currently post-hoc unless a partial-time proxy is built later.

## Current working model

Primary early-recognition candidate:

    0618_selected_early_band_v1

More precise candidates for next validation:

    0618_selected_minus8_v1
    0618_selected_minus7_v1

Secondary post-hoc coherence label:

    0786_ignition_band_match_v1

Extension outcome label:

    extension_best_full_plus7_v1

## Next validation

Run same-symbol random-anchor baseline using early-available filters first:

    0618_selected_minus8_v1
    0618_selected_minus7_v1
    0618_selected_early_band_v1

Then use post-hoc labels as outcome classes:

    0786_ignition_band_match_v1
    extension_best_full_plus7_v1

Critical rule:

Random-anchor comparison must separate early-available filters from post-hoc labels.

## Boundary

These findings are not strategy rules.

Forbidden downstream use:

    selection_engine modifier
    decision_gate rule
    execution_planner instruction
    executor/order logic
    live or paper execution trigger

Correct path:

    calibrated research policy
    -> same-symbol random-anchor baseline
    -> regime bucket validation
    -> optional market-only feature proposal after validation
