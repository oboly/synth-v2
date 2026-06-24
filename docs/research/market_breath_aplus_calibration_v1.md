# Market Breath A+ Calibration V1

## Purpose

`run_market_breath_aplus_calibration_v1.py` is a research-only supervised calibration harness for the deterministic Market Breath classifier.

This lane treats A+ Table 1 snapshots as offline teacher labels only.

It does not:

- add an A+ runtime dependency
- add A+ overlay fields to runtime market-breath output
- change selection, decision, execution, broker, UI, account, or order code
- write DB state

## Architecture

The classifier precedence and threshold profile live in the shared pure helper:

- `src/research/market_breath_classifier_v1.py`

The existing runner:

- `src/research/run_market_breath_analysis_v1.py`

and the calibration harness:

- `src/research/run_market_breath_aplus_calibration_v1.py`

both import and call the same pure function:

- `classify_market_breath_phase_state_v1(...)`

This is required so any calibrated profile is evaluated against exactly the same precedence logic that runtime uses with the default profile.

## Runtime boundary

Runtime Market Breath remains candle/BTC/breadth-derived only.

Runtime inputs remain:

- symbol candles
- BTC reference candles
- cross-symbol breadth
- one explicit fixed threshold profile chosen offline

No A+ report is required at runtime.

## Teacher labels

V1 uses only the five full canonical Table 1 report timestamps:

- `2026-05-13T19:15:00Z`
- `2026-05-14T13:15:00Z`
- `2026-05-15T12:44:48Z`
- `2026-05-16T01:15:11Z`
- `2026-05-16T12:09:00Z`

Partial, subset, and Prime17 reports are explicitly excluded from V1 training and recorded in the manifest with exclusion reasons.

## Provisional teacher mapping

The V1 teacher mapping is intentionally explicit and reviewable:

- `phase=reset` -> `COLLAPSE_RESET`
- `field=expansion` and `phase in {late, exhaustion}` -> `OVERBREATH_EXTENSION`
- `field=expansion` otherwise -> `EXHALE_EXPANSION`
- `field=compression` and `strategic_bias=accumulation` -> `INHALE_ACCUMULATION`
- `field=compression` otherwise -> `HOLD_COMPRESSION`
- `field in {transition, neutral}` -> `NEUTRAL_TRANSITION`
- any other combination -> `UNMAPPED`

Every teacher row keeps the original A+ values and the mapping reason.

## Interpretation boundary

A+ Table 1 mapping in this V1 harness is provisional teacher-label normalization.

The current low-score result is not evidence that A+ and Market Breath fail to match.

It also does not validate A+ threshold tuning.

The previously observed exact-match comparison has not yet been recovered as a versioned comparator.

This harness establishes reproducible calibration plumbing only.

Any future calibration claim requires recovery or reconstruction of that prior comparator plus a larger snapshot set.

## Calibration search

V1 search mode is:

- `SINGLE_AXIS`

This means:

- baseline profile plus one changed threshold axis at a time
- no Cartesian search
- no hidden optimization
- no random search
- no ML model fitting

## Validation

Validation uses leave-one-report-out by report timestamp, never random token splits.

For every candidate profile the harness reports:

- labeled-row coverage
- exact raw-phase match rate
- macro F1
- per-phase precision/recall
- confusion matrix
- mean fold score
- worst-report score
- deltas versus the unchanged baseline

Result statuses:

- `BASELINE_RETAINED`
- `CALIBRATION_CANDIDATE`
- `INSUFFICIENT_TRAINING_DATA`

Warnings:

- `TRAINING_SAMPLE_SMALL` whenever fewer than 10 teacher reports are available

## Runtime promotion boundary

Any profile marked `CALIBRATION_CANDIDATE` is still research-only.

It is not:

- a selected runtime profile
- a runtime default
- a live decision input
- a permission to change trading behavior

Any future runtime promotion requires:

1. separate validation
2. separate review
3. separate PR
