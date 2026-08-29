# CQ v1 point-in-time extractor v1

Issue: #568
Phase: 2C
Status: research-only, market-only, read-only

## Purpose

Measure how often the frozen Phase 2B cross-market inputs are actually available for the immutable `research_entry_quality_shadow` population before any CQ v1 transform, weight, formula or score is chosen.

This slice emits raw canonical context plus availability flags only.

## Population

```text
research_entry_quality_shadow
ORDER BY shadow_id ASC
```

Identity is preserved from Phase 1:

```text
shadow_id
asset_id
venue
asof_ts_utc
evidence_key
cq_model_version
```

The runner reads in bounded batches (default 100, maximum 1000). It does not fetch unbounded history into memory.

## Point-in-time Market Rotation Pressure

Aggregate lookup:

```text
venue = CQ observation venue
model_version = 1.0
as_of_ts_utc <= CQ observation asof
latest eligible row only
```

Per-asset lookup:

```text
asset_id = CQ asset
venue inherited through pressure_snapshot_id -> parent snapshot.venue
observation model_version = 1.0
parent snapshot model_version = 1.0
as_of_ts_utc <= CQ observation asof
latest eligible row only
```

No cross-venue or later-version fallback is allowed.

## Point-in-time Sector Rotation

Historical sector membership is resolved first:

```text
asset_id = CQ asset
membership_type = PRIMARY
valid_from_ts_utc <= CQ observation asof
valid_to_ts_utc IS NULL OR CQ observation asof < valid_to_ts_utc
ORDER BY membership_weight DESC, sector_code ASC
LIMIT 1
```

Then the canonical sector snapshot is resolved with:

```text
sector_code = resolved PIT PRIMARY sector
venue = CQ observation venue
window_code = 4h
model_version = sector-rotation-v1.0.0
asof_ts_utc <= CQ observation asof
latest eligible row only
```

Current taxonomy labels are never backfilled into historical observations.

## Availability and coverage

Each observation records explicit family states. The report uses the same CQ-shadow population denominator for:

```text
MRP coverage
Sector Rotation coverage
joint MRP + Sector coverage
```

Missing context stays missing. There is no imputation or current-truth fallback.

A low coverage result is a valid negative research result. Phase 2C must not compensate by adding new features after seeing coverage or forward outcomes.

## Resume and crash safety

`features.jsonl` is append-only during a run. After each complete row, a checkpoint records:

```text
last_shadow_id
processed
mrp_available_count
sector_available_count
joint_available_count
venue
batch_size
```

On `--resume`, the runner validates scope and reconciles JSONL to the last committed checkpoint. Extra rows, including a malformed partial tail written after the checkpoint boundary, are discarded. Missing or malformed checkpointed rows fail closed.

Coverage counters are cumulative across resumed invocations.

## Deliberately not implemented

```text
feature normalization
feature transforms
weights
CQ v1 score
Entry Strength v1
forward-outcome reads
production ranking
```

Those remain frozen out until coverage/missingness has been measured and a later preregistered model slice is created.

## Safety

```text
research_only=1
market_only=1
db_writes=0
production_ranking_changes=0
decision_gate=none
execution_planner=none
executor=none
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
```
