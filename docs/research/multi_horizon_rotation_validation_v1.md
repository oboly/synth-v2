# Multi-Horizon Rotation Validation v1

Issue: #593
Status: research-only evaluator contract
Depends on:
- `docs/research/multi_horizon_rotation_preregistration_v1.md`
- `docs/research/multi_horizon_rotation_candidate_definition_v1.md`
- `docs/research/multi_horizon_rotation_replay_v1.md`
- `docs/architecture/multi_horizon_signal_contract_v1.md`

## Scope

This slice freezes the evaluation semantics before any final-holdout result is inspected.

It does not change C1/C2/C3 formulas, Rotation V1, production ranking, reporting authority, CQ, account logic, decision permission, execution planning, broker behavior, or order handling.

## Baselines

### B0

Reuse the existing canonical persisted Rotation Pressure V1 truth:

```text
market_rotation_pressure_observation_v1
JOIN market_rotation_pressure_snapshot_v1
model_version = 1.0
same asset
same venue
source as_of_ts_utc <= candidate observation asof
latest PIT row only
```

Value:

```text
score_total
```

State context:

```text
pressure_state
```

No duplicate V1 storage is authorized.

### B1

Comparable-horizon price-only baseline:

```text
ln(close(asof) / close(asof - candidate_horizon))
```

Both boundaries must exist exactly on the canonical 15m grid. Missing boundaries remain missing.

### B2

Current audit status:

```text
UNAVAILABLE_NO_REPLAY_SAFE_CANONICAL_SOURCE
```

No canonical persisted replay-safe RSI/momentum history was found in the repository audit. The evaluator therefore reports B2 unavailable rather than substituting reporting-layer, current-only, or synthetic values.

## Chronological split

The split method is frozen before outcome inspection:

```text
common replay-safe span
-> 60% discovery
-> 20% validation
-> 20% final holdout
```

Boundaries are snapped deterministically to the 15m grid.

The exact timestamps are not guessed in code or docs. They must be derived from the broadest common replay-safe source span and persisted in a split manifest before validation is run.

The validation runner accepts only:

```text
discovery
validation
```

It has no final-holdout phase option. A manifest must assert:

```text
final_holdout_inspected = false
```

and discovery/validation must end no later than the recorded holdout start.

## Forward response

Exact-boundary log returns are frozen at:

```text
15m
1h
4h
24h
```

Missing exact future boundaries are `INSUFFICIENT_DATA`; there is no nearest-candle fallback.

## Metrics

Per candidate C1/C2/C3:

```text
sample_count
coverage
Pearson correlation versus B0
Pearson correlation versus B1
forward information coefficient at 15m/1h/4h/24h
Fisher-z 95% confidence interval
partial correlation versus forward return residualized on B0
partial correlation versus forward return residualized on B1
state persistence
sign-flip count
chop reversion rate
```

Cross-horizon:

```text
C1:C2 paired correlation
C1:C3 paired correlation
C2:C3 paired correlation
```

Pairs are matched only on:

```text
venue + asset_id + asof_ts
```

## Directional state and chop

No learned threshold is introduced.

Frozen state:

```text
score > 0 -> POSITIVE
score = 0 -> ZERO
score < 0 -> NEGATIVE
```

Persistence is consecutive sample count within candidate + asset.

A chop reversion is a sign/state flip that returns to the previous state within the next four 15m samples.

This definition is intentionally simple and fixed before validation. It does not claim trading significance by itself.

## Multiple comparisons

The inference family is frozen as exactly:

```text
3 candidates x 4 forward horizons = 12 forward-IC tests
```

Holm-Bonferroni at alpha 0.05 is applied across all twelve tests together, not separately per candidate.

The implementation uses an approximate two-sided normal p-value derived from the Fisher-z transform. Effect size, confidence interval, paired sample count, and raw metric remain primary; a corrected boolean is not sufficient for promotion.

## Incremental utility

Incremental utility is represented by partial correlation after linear residualization on the baseline.

This is reported separately for B0 and B1. A candidate must not be called incremental merely because its raw forward correlation is non-zero.

B2 remains unavailable until a separately audited replay-safe canonical source exists.

## Artifact boundary

`src/research/multi_horizon_rotation_validation_v1.py` is a pure evaluator over point-in-time-safe rows.

`src/research/run_multi_horizon_rotation_validation_v1.py` consumes JSONL research artifacts plus a frozen split manifest. It performs no database or network access.

A separate bounded dataset-builder slice must still:

1. derive and persist the exact common replay-safe date span and split manifest without reading outcome statistics;
2. replay C1/C2/C3 at 15m as-of steps;
3. attach B0 using the canonical PIT join;
4. compute exact-boundary B1;
5. attach exact-boundary 15m/1h/4h/24h forward responses;
6. keep final-holdout rows inaccessible to this validation runner.

## Safety

```text
research_only=1
market_only=1
account_awareness=0
selection_engine_production_changes=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
database_writes=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
production_runtime_activation=0
```
