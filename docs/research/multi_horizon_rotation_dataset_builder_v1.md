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

## Frozen source span and split

The first invocation derives one source manifest from persisted availability only. No candidate score, forward return, validation result, regime result, CQ value, reporting output, or holdout outcome participates in boundary selection.

For one venue:

1. read each asset's first and last persisted canonical `15m` candle;
2. add the maximum frozen candidate lookback, 36h, to each first-candle timestamp;
3. floor every asset interval start by the first canonical Rotation Pressure V1 PIT timestamp for `model_version=1.0`;
4. identify contiguous 15m-grid regions where at least 20 assets are simultaneously eligible at the coverage-envelope level;
5. choose the longest region, earliest on an exact-duration tie;
6. represent its end as the exclusive 15m boundary after the last included as-of;
7. derive exactly 60% discovery, 20% validation and 20% final holdout using the frozen validation contract.

The selected source end is then used as a historical cutoff to recompute first/last candle coverage. The manifest persists a deterministic SHA-256 over that frozen coverage plus the resulting span/splits.

`split_manifest_v1.json` is write-once for the research run. Later discovery/validation invocations must reuse it. They re-read source availability only through the frozen source end and fail closed if the resulting coverage hash, venue, span or split differs. New candles after the frozen source end cannot move the split.

The coverage envelope does not replace per-observation continuity checks. `multi_horizon_rotation_replay_v1.py` still validates exact window boundaries and contiguous candles for every candidate observation.

## Point-in-time asset universe

For each observation as-of, the builder includes every asset whose first canonical 15m candle is at or before that as-of.

Consequences:

- no future-listing backfill;
- no current-universe backfill;
- future delisting knowledge does not remove historical observations;
- a previously observed asset with missing recent candles remains present and is emitted as `INSUFFICIENT_DATA` by the replay owner rather than disappearing from coverage.

## Phase and holdout isolation

The CLI exposes only:

```text
discovery
validation
```

There is no final-holdout mode.

Candle reads are capped at the last 15m close strictly before the requested phase end. Rotation V1 bulk reads also use an exclusive phase-end cutoff.

Forward labels obey:

```text
asof + forward_horizon >= phase_end -> null
```

Therefore discovery cannot consume validation outcomes and validation cannot consume final-holdout outcomes. The frozen manifest always asserts `final_holdout_inspected=false`.

## Candidate construction

C1/C2/C3 are delegated to the frozen owner:

`src/research/multi_horizon_rotation_replay_v1.py`

The dataset builder does not duplicate or reinterpret candidate formulas, normalization, cohort rules, horizon metadata, model/version identity, freshness or data-quality semantics.

## Baselines

### B0: Rotation Pressure V1

Canonical PIT source:

```text
market_rotation_pressure_observation_v1
JOIN market_rotation_pressure_snapshot_v1
venue = requested venue
observation.model_version = 1.0
snapshot.model_version = 1.0
source asof <= candidate asof
latest source row only
```

Fields: `score_total`, `pressure_state`.

Multiple rows at the same timestamp retain `pressure_obs_id` ordering; the PIT index selects the last row at that timestamp. No duplicate V1 history is created.

### B1: comparable price momentum

Exact-boundary log return matching the candidate horizon:

```text
C1 -> 15m
C2 -> 1h
C3 -> 4h
```

Missing exact boundaries remain missing. No nearest-candle fallback.

### B2

```text
UNAVAILABLE_NO_REPLAY_SAFE_CANONICAL_SOURCE
```

No substitute RSI/current-only/reporting-layer source is introduced.

## Forward response

Exact-boundary log returns are produced for `15m`, `1h`, `4h`, and `24h`, subject to the phase-end purge above.

## Artifact identity

Each validation row includes at minimum:

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

Evaluator identity remains:

```text
venue + asset_id + candidate_id + asof_ts
```

Artifacts are research evidence, not production truth.

## Runtime and resume contract

Source reads are batched by UTC as-of day. Each batch covers only the 36h lookback and allowed forward window needed by that day's observations. Per-as-of replay still receives only candles at or before that as-of.

Rows stream to:

```text
.<phase>_rows_v1.jsonl.partial
```

After every fully completed as-of:

1. the partial artifact is flushed and fsynced;
2. an atomic checkpoint records the frozen manifest SHA-256, venue, phase, last completed as-of, completed count, committed row count and exact partial byte offset.

`--resume` requires a compatible checkpoint. It truncates any uncheckpointed mid-as-of bytes to the committed byte offset and verifies the committed newline/row count before appending. Changed venue, phase, runner version or frozen manifest fails closed.

An interrupt or failure changes only the checkpoint terminal status while preserving the last committed counts. After all as-ofs finish, the partial artifact is atomically renamed to the final JSONL and the checkpoint becomes `FINISHED`.

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
