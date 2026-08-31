# Multi-Horizon Rotation Dataset Builder v1

Issue: #593
Status: research-only dataset construction contract

Depends on:
- `docs/research/multi_horizon_rotation_preregistration_v1.md`
- `docs/research/multi_horizon_rotation_candidate_definition_v1.md`
- `docs/research/multi_horizon_rotation_replay_v1.md`
- `docs/research/multi_horizon_rotation_validation_v1.md`
- `docs/architecture/multi_horizon_signal_contract_v1.md`

## Scope

This slice builds point-in-time-safe discovery or validation artifacts for the frozen C1/C2/C3 evaluator.

It does not promote a candidate, inspect final-holdout outcomes, write database state, change Rotation V1, change production ranking, use account state, or create execution intent.

## Source-span derivation

The split is derived from persisted source availability only. No candidate score, forward return, performance statistic, regime result, CQ value, reporting output, or holdout outcome participates in boundary selection.

For one venue:

1. read each asset's first and last persisted canonical `15m` candle;
2. add the maximum frozen candidate lookback, 36h, to each first-candle timestamp;
3. floor every asset interval start by the first canonical Rotation Pressure V1 PIT timestamp for `model_version=1.0`;
4. treat each asset as potentially replayable on the exact 15m grid from that eligible start through its last persisted candle;
5. sweep those intervals and identify contiguous regions where at least 20 assets are simultaneously eligible at the coverage-envelope level;
6. choose the longest such contiguous region, with the earliest region as deterministic tie-break;
7. represent the selected end as the exclusive 15m boundary immediately after the last included as-of;
8. the existing frozen `derive_chronological_split()` produces exactly 60% discovery, 20% validation, 20% final holdout on that discrete 15m grid.

This prevents two disconnected asset groups from being combined into a synthetic common span.

The coverage envelope is intentionally not a substitute for candle continuity. Exact window boundaries and contiguous candles remain validated independently by `multi_horizon_rotation_replay_v1.py` for every candidate observation. Missing evidence remains missing.

## Point-in-time asset universe

Artifact missingness must not improve merely because an asset has no candle in the current 36h source window.

For each observation as-of, the builder therefore passes to the candidate replay owner every asset whose first canonical 15m candle is at or before that as-of. Assets not yet observed are excluded, so there is no future-listing or current-universe backfill.

A previously observed asset with missing recent candles remains in the observation universe with an empty replay window. The replay owner then emits `INSUFFICIENT_DATA` for that asset instead of silently dropping it from the coverage denominator.

The observation-universe rule does not use an asset's eventual last candle to decide whether it belongs at a historical as-of. Future delisting knowledge therefore does not remove historical rows.

## Holdout isolation

The runner CLI exposes only:

```text
discovery
validation
```

There is no `final_holdout` mode.

One invocation writes one phase artifact. Validation reads canonical candles only through the last 15m boundary strictly before the validation phase end. It never requests candles at or beyond holdout start.

The bulk Rotation V1 read is also phase-scoped and uses an exclusive phase-end cutoff. PIT lookup then selects only source rows at or before each candidate as-of.

Forward labels are purged at every phase boundary:

```text
asof + forward_horizon >= phase_end -> null
```

Therefore:

- discovery cannot consume validation outcomes;
- validation cannot consume final-holdout outcomes.

The split manifest records `final_holdout_inspected=false`.

## Candidate construction

C1/C2/C3 are not recomputed independently here. The builder calls the already-frozen replay owner:

`src/research/multi_horizon_rotation_replay_v1.py`

That owner remains responsible for candidate formula, cohort rules, normalization, model/version identity, horizon metadata, freshness and data-quality semantics.

## B0 canonical Rotation V1

B0 is attached point-in-time from the existing authoritative tables:

```text
market_rotation_pressure_observation_v1
JOIN market_rotation_pressure_snapshot_v1
venue = requested venue
observation.model_version = 1.0
snapshot.model_version = 1.0
source asof <= candidate asof
latest source row only
```

Fields:

```text
score_total
pressure_state
```

If multiple canonical observations share the same timestamp, the bulk query order preserves `pressure_obs_id` ordering and the PIT index deterministically selects the last row at that timestamp, matching the canonical latest-row tie principle.

No duplicate Rotation V1 history is created.

## B1 comparable momentum

B1 is the frozen exact-boundary log return over the candidate's own horizon:

```text
C1 -> 15m
C2 -> 1h
C3 -> 4h
```

Both exact canonical 15m boundaries must exist. No nearest-candle fallback is permitted.

## B2

B2 remains:

```text
UNAVAILABLE_NO_REPLAY_SAFE_CANONICAL_SOURCE
```

No RSI or alternate momentum implementation is introduced in #593.

## Forward response

Exact-boundary log returns are produced for:

```text
15m
1h
4h
24h
```

Only endpoints strictly before the requested phase end are populated.

## Artifact identity

Each validation row contains at minimum:

```text
venue
asset_id
asof_ts
candidate_id
candidate_model_id
candidate_model_version
candidate_effective_horizon
candidate_score
candidate_data_quality
candidate_reason
candidate_cohort_size
b0_score
b0_pressure_state
b0_model_version
b1_return
b2_status
forward_15m
forward_1h
forward_4h
forward_24h
```

The evaluator's deterministic identity remains:

```text
venue + asset_id + candidate_id + asof_ts
```

Artifacts are research evidence, not production truth.

## Runtime characteristics

The v1 runner favors explicitness over query cleverness. It processes one as-of grid point at a time and queries only the bounded lookback/forward window required for that observation.

This is deliberately simple for the first full validation run. Performance optimization may later batch source reads, but must preserve identical PIT, missingness and phase-isolation semantics.

## Safety

```text
research_only=1
market_only=1
database_reads=1
database_writes=0
account_awareness=0
selection_engine_production_changes=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
production_runtime_activation=0
final_holdout_access=DENY
```
