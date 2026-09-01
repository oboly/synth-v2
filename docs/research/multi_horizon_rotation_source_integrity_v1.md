# Multi-Horizon Rotation Source Integrity v1

Issue: #593
Status: research-only pre-holdout integrity gate

## Purpose

Freeze deterministic content fingerprints for the canonical market sources that a later final-holdout builder is allowed to read.

This gate exists because `multi_horizon_rotation_dataset_builder_v1` deliberately freezes only the coverage envelope. That is sufficient for discovery/validation split stability, but not sufficient to detect later edits to interior candle content or historical Rotation Pressure V1 rows.

This slice resolves that gap **before final-holdout outcomes are inspected**.

## Scope

The runner fingerprints source content only. It does not:

- build final-holdout candidate rows;
- read or evaluate final-holdout forward outcomes;
- change C1/C2/C3 formulas;
- reopen C2 or C3 after the frozen pre-holdout selection gate;
- alter Rotation Pressure V1;
- write database state;
- touch selection, decision, execution, broker, order or account layers.

Pre-holdout selection remains:

```text
C1 -> ADVANCE_TO_FINAL_HOLDOUT
C2 -> REJECT_BEFORE_FINAL_HOLDOUT
C3 -> INSUFFICIENT_DATA
```

## Frozen source union

### Canonical 15m candles

The candidate replay owner may require up to 36h of lookback before the first frozen source as-of. Across discovery, validation and a future holdout-only build, the full candle source union is therefore:

```text
venue = frozen venue
interval_code = 15m
close_ts_utc >= source_span.start - 36h
close_ts_utc < source_span.end
```

Fingerprinted fields, in deterministic order:

```text
asset_id
close_ts_utc
close_price
volume_base
```

Ordering:

```text
asset_id, close_ts_utc
```

### Rotation Pressure V1 PIT source

The existing dataset builder loads historical Rotation V1 PIT evidence up to each phase end so that `latest_at_or_before(asof)` can resolve the canonical B0 row.

The full source union needed before a future holdout build is therefore:

```text
venue = frozen venue
observation.model_version = 1.0
snapshot.model_version = 1.0
observation.as_of_ts_utc < source_span.end
snapshot.as_of_ts_utc < source_span.end
```

Fingerprinted fields:

```text
pressure_obs_id
pressure_snapshot_id
asset_id
as_of_ts_utc
score_total
pressure_state
observation_model_version
snapshot_as_of_ts_utc
snapshot_model_version
```

Ordering matches the PIT owner:

```text
asset_id, as_of_ts_utc, pressure_obs_id
```

## Canonical serialization

Each source row is serialized as one JSON array in the frozen field order followed by `\n`.

Rules:

- timestamps -> UTC ISO-8601 with `Z`;
- decimals -> fixed decimal text, preserving database decimal scale as exposed by the driver;
- integers -> JSON integers;
- null -> JSON null;
- strings -> JSON strings;
- no locale-dependent formatting.

SHA-256 is updated incrementally per row. Full source rows are never materialized in memory.

## Artifact

Default recommended artifact name:

```text
source_integrity_v1.json
```

The artifact contains:

- frozen split-manifest SHA-256;
- candle source bounds, row count and SHA-256;
- Rotation V1 source bound, row count and SHA-256;
- composite SHA-256 over those three identities;
- explicit `final_holdout_outcomes_inspected=false`;
- research safety markers.

The artifact is write-once. A second `--freeze` with identical content returns `VERIFIED_EXISTING`; changed content fails closed.

`--verify` requires the frozen artifact to exist and recomputes all fingerprints. Any source-content drift fails closed.

## Execution

Freeze after discovery/validation selection is fixed and before any holdout-only builder exists or runs:

```text
python -m src.research.run_multi_horizon_rotation_source_integrity_v1 \
  --venue bitvavo \
  --split-manifest <run>/split_manifest_v1.json \
  --output-json <run>/source_integrity_v1.json \
  --freeze
```

Immediately before a later holdout-only build:

```text
python -m src.research.run_multi_horizon_rotation_source_integrity_v1 \
  --venue bitvavo \
  --split-manifest <run>/split_manifest_v1.json \
  --output-json <run>/source_integrity_v1.json \
  --verify
```

A future holdout-only runner must require successful verification before it reads/builds any holdout rows. It must not weaken this gate by silently refreezing changed sources.

## Bounded I/O

Both source queries use `fetchmany(5000)`. Memory scales with one fetch batch plus SHA state, not historical row count.

No broad `fetchall()` is allowed.

## Safety

```text
research_only=1
market_only=1
database_reads=1
database_writes=0
account_awareness=0
decision_gate=none
execution_planner=none
executor=none
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
final_holdout_outcomes_inspected=0
```
