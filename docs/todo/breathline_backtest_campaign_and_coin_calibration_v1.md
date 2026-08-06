# Breathline Backtest Campaign and Coin Calibration v1

> **Migration pointer.** Current execution status, priority, blockers,
> acceptance criteria, next action, and closure for this lane are owned by
> GitHub Issue
> [#225 — Run per-coin Breathline calibration campaign](https://github.com/oboly/synth-v2/issues/225).
> This file is retained as frozen historical/design context; the status and
> task text below is preserved but superseded operationally by Issue #225.
> Do not update status, priority, blockers, next action, or execution order
> here. See `docs/development/github_issues_workflow.md`,
> `docs/todo/MIGRATION_FREEZE.md`, and
> `docs/development/github_issues_batch_2b_migration_v1.md`.

## Status

Todo / research campaign specification.

## Purpose

Run the Breathline historical campaign needed to measure per-coin timing relative to the canonical A+ baseline without changing runtime behavior.

This campaign is for research output only.

## Baseline Contract

Canonical baseline:

* A+ Prime-17 / 21d average
* BTC-led reference
* canonical A+ baseline route for the active epoch

Definitions:

* offset = the coin template timing offset in days relative to the BTC-led Breathline reference
* A+ baseline phase window = the supplied model-average duration window for a baseline phase
* coin calibration window = the per-coin historical refinement measured from campaign artifacts

The campaign must measure coin behavior relative to this baseline.

It must not overwrite, replace, or silently mutate the A+ baseline.

## Existing Runner Chain

Use the current research-only runner chain:

* `src/research/backtest_breath_curve_partial_to_full_v1.py`
* `src/research/run_breath_curve_phase_calibration_v2.py`

Current chain responsibilities:

* run the historical partial-to-full Breathline backtest per symbol / anchor cohort
* derive per-symbol offset distance and band-calibration summaries
* retain immutable versioned output files for later comparison

## Required Artifacts

Campaign output must stay immutable and versioned.

Expected artifact pattern from the existing runner chain:

* `data/research/breath_curve_template_matcher_v1/breath_curve_partial_to_full_v1_<UTCSTAMP>.csv`
* `data/research/breath_curve_template_matcher_v1/breath_curve_partial_to_full_v1_<UTCSTAMP>.jsonl`
* `data/research/breath_curve_phase_calibration_v2/*_phase_calibration_annotated.csv`
* `data/research/breath_curve_phase_calibration_v2/*_phase_calibration_distance_summary.csv`
* `data/research/breath_curve_phase_calibration_v2/*_phase_calibration_selected_band_summary.csv`
* `data/research/breath_curve_phase_calibration_v2/*_phase_calibration_best_band_summary.csv`
* `data/research/breath_curve_phase_calibration_v2/*_phase_calibration_band_match_summary.csv`
* `data/research/breath_curve_phase_calibration_v2/*_phase_calibration_selected_to_best_cross.csv`

## Required Output

For each coin under campaign review, produce research output covering:

* per-coin calibration record
* best-fit offset
* A+ baseline phase window when supplied
* coin calibration window from historical results
* phase-duration distribution
* stability over the sampled campaign set
* confidence and sample size
* observed shifts
* observed reversals
* observed re-anchors

## Boundaries

This campaign is:

* research-only
* market-only
* account-agnostic

This campaign must not change:

* the A+ baseline
* `selection_engine`
* `decision_gate`
* `execution_planner`
* executors
* UI behavior
* DB behavior
* broker behavior

This campaign PR must not introduce:

* runtime writes that overwrite baseline truth
* selection or allocation logic
* decision permission logic
* execution intent
* order handling
* account-aware policy

## Interpretation Rule

Campaign outputs are calibration evidence only.

Correct path:

    historical campaign
    -> immutable versioned artifacts
    -> per-coin calibration review
    -> optional later read-model use after separate approval

Incorrect path:

    historical campaign
    -> selection or execution behavior change

That would bypass the architecture and the scope of this PR.
