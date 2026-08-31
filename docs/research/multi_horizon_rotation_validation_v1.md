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

Value: `score_total`.
State context: `pressure_state`.
No duplicate V1 storage is authorized.

### B1

Comparable-horizon price-only baseline:

```text
ln(close(asof) / close(asof - candidate_horizon))
```

Both boundaries must exist exactly on the canonical 15m grid. Missing boundaries remain missing.

### B2

```text
UNAVAILABLE_NO_REPLAY_SAFE_CANONICAL_SOURCE
```

No canonical persisted replay-safe RSI/momentum history was found in the repository audit. The evaluator reports B2 unavailable rather than substituting reporting-layer, current-only, or synthetic values.

## Chronological split and holdout isolation

The split method is frozen before outcome inspection:

```text
common replay-safe span
-> 60% discovery
-> 20% validation
-> 20% final holdout
```

All boundaries must be exact 15m-grid timestamps. Exact timestamps are derived from the broadest common replay-safe source span and persisted before validation.

The validation runner accepts only `discovery` or `validation`. It has no final-holdout phase and requires:

```text
final_holdout_inspected = false
```

Input JSONL is also required to be phase-scoped. Every row must fall inside the requested discovery or validation interval. A mixed artifact containing any row from another phase, including holdout, fails closed before metric evaluation.

Forward labels are purged at every phase boundary: a non-null 15m/1h/4h/24h forward response is allowed only when its exact outcome endpoint is strictly before the requested phase end. Discovery therefore cannot consume validation outcomes, and validation cannot consume final-holdout outcomes.

## Forward response

Exact-boundary log returns are frozen at:

```text
15m
1h
4h
24h
```

Missing exact future boundaries remain `INSUFFICIENT_DATA`; there is no nearest-candle fallback.

## Core metrics

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
lead/lag versus B1 turns
regime stability by B0 pressure_state
```

Raw correlations require at least 4 paired rows. Partial correlations with one controlled baseline require at least 5 paired rows; Fisher-z uncertainty therefore uses `n - 4` for that case.

Cross-horizon correlations pair only exact `venue + asset_id + asof_ts` observations.

## Directional state, persistence and chop

No learned threshold is introduced:

```text
score > 0 -> POSITIVE
score = 0 -> ZERO
score < 0 -> NEGATIVE
```

Persistence is consecutive 15m sample count within candidate + asset. Missing scores and timestamp gaps break a run and cannot create a synthetic transition.

A chop reversion is a valid consecutive state flip that returns to the previous state within the next four contiguous 15m samples. Missing samples or timestamp gaps terminate the reversion search.

## Lead/lag around turns

The preregistered lead/lag requirement is frozen using observable sign-state changes, with B1 as the price-only reference.

Per asset and candidate:

```text
turn event = valid state differs from previous valid state on the next exact 15m sample
reference = B1 comparable-horizon log-return state
pair = nearest unmatched B1 turn within +/-16 samples
16 samples = 4 hours
tie = earlier B1 turn
delta = candidate_turn_ts - B1_turn_ts
negative delta = candidate leads
positive delta = candidate lags
```

Missing values and timestamp gaps break turn continuity. Report turn counts, paired/unpaired counts and mean/median/min/max delta in 15m samples.

## Regime stability

Rows are grouped by canonical PIT `B0.pressure_state` separately for each candidate. A group requires at least 30 rows before its coverage and four forward-IC metrics are marked `MEASURED`; smaller groups remain `INSUFFICIENT_DATA`.

This is descriptive stability evidence, not a regime-based selection rule.

## Multiple comparisons

The inference family is frozen as exactly:

```text
3 candidates x 4 forward horizons = 12 forward-IC tests
```

Holm-Bonferroni at alpha 0.05 is applied across all twelve tests together. A hypothesis with insufficient data remains part of the frozen family size and is reported as unavailable rather than shrinking the family after seeing coverage.

Effect size, confidence interval, paired sample count, and raw metric remain primary; a corrected boolean alone is not a promotion decision.

## Incremental utility

Incremental utility is partial correlation after linear residualization on one baseline, separately for B0 and B1. A candidate is not incremental merely because its raw forward correlation is non-zero.

B2 remains unavailable until a separately audited replay-safe canonical source exists.

## Artifact boundary

- `src/research/multi_horizon_rotation_validation_v1.py`: core paired statistics, persistence/chop, split semantics.
- `src/research/multi_horizon_rotation_validation_temporal_v1.py`: frozen lead/lag and regime-stability metrics.
- `src/research/run_multi_horizon_rotation_validation_v1.py`: phase-scoped local-artifact evaluator with no DB/network access.

A separate bounded dataset-builder slice must still:

1. derive and persist the exact common replay-safe date span and split manifest without reading outcome statistics;
2. replay C1/C2/C3 at 15m as-of steps;
3. attach B0 using the canonical PIT join;
4. compute exact-boundary B1;
5. attach exact-boundary 15m/1h/4h/24h forward responses;
6. emit separate discovery and validation artifacts with forward labels purged at each phase end;
7. keep final-holdout rows in a separate inaccessible artifact/path until the final-holdout gate is explicitly opened.

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
final_holdout_access=DENY
```
