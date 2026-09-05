# MA / Volume Incremental Validation v1

Issue: #310
Status: research-only historical validation harness

## Purpose

Evaluate whether frozen point-in-time MA/volume candidate features add monotonic
information beyond an explicitly supplied existing baseline, without defining
production thresholds or fitting a trading model.

This contract follows the candidate feature preparation merged via PR #754.

## Input contract

The evaluator consumes a frozen tabular dataset containing:

```text
split                  # DISCOVERY | VALIDATION | HOLDOUT
future outcome label   # explicit caller-owned future label
candidate columns      # #310 MA/volume PIT features
baseline columns       # existing baseline features supplied explicitly
```

The evaluator does not fetch candles, create outcome labels, infer split
boundaries, or choose the baseline. Those identities must be frozen by the
calling research artifact/run.

Split, outcome, candidate and baseline column roles must be mutually disjoint.
A feature may not alias the outcome or split column, and a candidate may not
also be a baseline. This prevents trivial self-association and ambiguous
selection semantics.

Unknown split labels fail closed. All three split labels are mandatory; an
incomplete frozen split set is rejected rather than producing a partial-looking
report.

## Metrics

For each candidate feature and each split independently:

- `sample_count`: rows complete for candidate + future outcome, used for raw
  Spearman;
- `partial_sample_count`: rows additionally complete for every supplied baseline
  column, used for partial Spearman;
- raw Spearman rank correlation with the future outcome;
- partial Spearman rank correlation after controlling for the supplied baseline
  columns.

Baseline missingness therefore cannot silently change the documented raw
candidate/outcome association.

Partial Spearman is implemented as rank-transforming candidate, outcome and
baseline columns, then residualizing candidate and outcome ranks against the
baseline ranks within the same split. No fit crosses split boundaries. The
partial metric is undefined (`None`) when residual degrees of freedom are
insufficient or either residual series has only numerical-noise variance after
control residualization.

This is a descriptive incremental-information measure. It is not a trading
score, probability, classifier, or promotion decision.

## Discovery / validation / holdout discipline

The harness requires and reports all three frozen split labels but does not tune
anything. Any future threshold or feature-selection rule must be chosen using
discovery only, frozen, and then evaluated unchanged on validation/holdout.

The holdout must not be repeatedly inspected to retune feature definitions,
slope windows, thresholds or baseline composition.

## Non-goals

This module does not:

- define `TREND_ALIGNED`, `TREND_RECOVERY`, `MA_RECLAIM_PENDING`, or any volume
  lifecycle state;
- select a slope window;
- create `volume_zscore`;
- define a baseline score;
- combine features into a production ranking;
- modify `selection_engine`, `decision_gate`, `execution_planner`, executor, or
  reporting;
- write any database or production artifact.

## Next evidence step

Run this harness on a frozen, reproducible historical dataset that binds:

```text
universe/cohort identity
market + interval
as-of timestamps
candidate model/version
baseline feature identities/versions
future label definition + horizon
split boundaries
source dataset hash
```

The resulting report should determine `RETAIN`, `REJECT`, or
`RESEARCH_FURTHER` per candidate family. No production promotion is implied by
positive research metrics alone.

## Safety

```text
research_only=1
market_only=1
production_db_writes=0
selection_engine_change=0
decision_gate_change=0
execution_planner_change=0
executor_change=0
reporting_change=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_activation=0
```
