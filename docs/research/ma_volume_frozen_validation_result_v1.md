# MA / Volume Frozen Historical Validation Result v1

Issue: #310

Status: final frozen empirical result

## Runtime identity

```text
runner=ma_volume_frozen_validation_run_v1
runner_merge_commit=1c31fa532ca352fa400a124db733f2499af5120b
population_rows=19520
unique_asofs=45
population_sha256=61bab264b2921b93a25a22ec0d12cbc031ad0ef234fa989b2ea43c894bc263b4
outcomes_rows=58560
outcomes_sha256=2c1b3b9e17e6e06eec3831ac47b48bfd91944730cf9c6e75929979a795727500
candidate_rows_sha256=01eca1ec56adaa9d4e10599b2e210dd0628c33d7d3ff8c0dbeb273b90f429c4b
manifest_sha256=650bbd82dff6762c3c77f88fd131cb4f1ac4462eaf1d4fc7088ad6fc29087c99
db_writes=0
full_frozen_run=1
```

Focused tests passed 15/15 before the run. The bounded candle query used
`ix_market_candle_lookup`. One-observation, 25-observation, and signal
interrupt/resume smokes passed before the full frozen run.

## Feature availability

```text
AVAILABLE=6636
INSUFFICIENT_CANDLE_HISTORY=3061
MISSING_EXACT_ASOF_CANDLE=533
NONCONTIGUOUS_CANDLE_HISTORY=9290
```

Missing or non-contiguous history was not imputed. The evaluator therefore uses
only observations with valid candidate values for each split/horizon metric.

## Baseline-controlled evidence

Values below are partial Spearman correlations after controlling for the frozen
baseline fields `selection_score` and `trade_quality_score`.

| Feature | 1h D / V / H | 4h D / V / H | 24h D / V / H | Disposition |
|---|---:|---:|---:|---|
| `close_vs_sma50_pct` | +0.009 / +0.199 / -0.069 | -0.088 / +0.292 / -0.232 | -0.078 / +0.071 / -0.048 | REJECT |
| `close_vs_sma150_pct` | -0.017 / +0.199 / -0.089 | -0.080 / +0.279 / -0.189 | -0.057 / +0.045 / -0.087 | REJECT |
| `close_vs_sma200_pct` | -0.035 / +0.178 / -0.085 | -0.088 / +0.269 / -0.139 | -0.051 / +0.038 / -0.093 | REJECT |
| `sma50_slope_pct_6b` | +0.023 / +0.208 / -0.037 | -0.041 / +0.315 / -0.212 | -0.056 / -0.026 / -0.000 | REJECT |
| `sma150_slope_pct_6b` | -0.035 / +0.122 / +0.006 | -0.063 / +0.211 / -0.021 | -0.013 / -0.018 / +0.008 | REJECT |
| `sma200_slope_pct_6b` | -0.047 / +0.130 / +0.030 | -0.062 / +0.226 / -0.009 | -0.041 / +0.017 / +0.046 | REJECT |
| `bullish_ma_stack` | -0.026 / +0.051 / -0.009 | -0.034 / +0.026 / +0.116 | -0.042 / -0.028 / -0.020 | REJECT |
| `volume_ratio_20` | -0.031 / +0.089 / +0.042 | -0.007 / +0.072 / +0.086 | -0.031 / +0.084 / +0.292 | RESEARCH_FURTHER |

D = Discovery, V = Validation, H = Holdout.

## Decision

The MA-distance and MA-slope family is rejected as a general predictive ranking
addition. Validation-period correlations looked attractive, especially at 4h,
but most of those signals reversed sign in holdout. This is not robust enough to
support selection authority or evidence-backed dashboard thresholds.

`bullish_ma_stack` is also rejected as a general predictive feature. It shows one
positive 4h holdout result but does not reproduce consistently across horizons or
splits.

`volume_ratio_20` remains the only candidate worth further research. Validation
and holdout are positive on all three horizons, with the strongest holdout result
at 24h, but Discovery remains slightly negative. The existing primitive is
retained unchanged; no new volume lifecycle class, threshold, or production
weight is authorized by this result.

## Breadth implication

This result does not justify new SMA150/SMA200/bullish-stack predictive breadth
bands or stoplight thresholds. Existing MA50 breadth may remain descriptive
market context under its own canonical owner, but this study does not promote it
into selection authority.

## Architecture boundary

```text
research_only=1
selection_engine_promotion=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
broker_writes=0
live_activation=0
```

Any future work on `volume_ratio_20` must be a new bounded research issue with a
new preregistered hypothesis. It must not reopen or mutate this frozen result.
