# CQ v1 Temporal Source Audit v1

Issue: #629
Parent: #568

## Purpose

This research-only audit determines whether the already-frozen CQ v1 candidate family can be reconstructed over multiple historical observation timestamps without leaking current/latest truth into past observations.

It does not inspect forward outcomes, change the frozen model, create historical shadow rows, or modify production ranking.

## Frozen boundary

The CQ v1 family remains unchanged:

```text
model_family_version=1.0.0
coverage_artifact_sha256=f09a515535dd72c5422cbfea7ad449163132b298d1759f32701f0152c78aff2d
cq_v1_mrp_balanced_v1
cq_v1_mrp_anchor_v1
```

The current accepted comparison (#623 / PR #624) contains 419 observations from one as-of timestamp and therefore remains bounded cross-sectional evidence only.

## Sources audited

The runner checks bounded history and index metadata for:

```text
asset_interval_quality
signal_engine_state
market_rotation_pressure_snapshot_v1
market_rotation_pressure_observation_v1
sector_rotation_snapshot
obs_market_candle (15m)
```

The audit records row count, distinct timestamp count, first/last timestamp within a bounded lookback, PIT rule and available indexes.

A required source is considered historically replayable only when at least two distinct timestamps exist in the bounded window. This is a feasibility gate, not proof that the final temporal sampling design is acceptable.

## Important existing limitation

`run_entry_quality_shadow_bounded_v1.py` selects current/latest quality and signal rows using `MAX(...)` without a candidate historical as-of cutoff. It is therefore explicitly denied for historical reconstruction as-is.

A temporal population builder must instead perform deterministic `latest <= candidate_asof` lookups for every historical source.

The existing CQ v1 PIT extractor already uses this form for aggregate MRP, per-asset MRP, sector membership and sector rotation.

## PPP

The current shadow lane can receive PPP through an external CSV/artifact. This audit does not assume such a file is historically canonical. Temporal PPP remains unavailable unless a historical artifact with point-in-time provenance is explicitly supplied. Non-PPP CQ comparisons may continue without fabricating PPP.

## Runner

```text
python3 -m src.research.run_cq_v1_temporal_source_audit_v1 \
  --venue bitvavo \
  --lookback-days 45 \
  --output-json data/research/cq_v1_temporal_source_audit_v1/<timestamp>/source_audit.json
```

The lookback is bounded to `1..366` days. The output path must not already exist.

Possible terminal states:

```text
READY_TO_FREEZE_TEMPORAL_SAMPLING
BLOCKED_SOURCE_HISTORY
```

A ready state only authorizes the next research step: freeze a deterministic multi-date sampling contract before any temporal outcome inspection.

## Safety

```text
research_only=1
market_only=1
db_reads=1
db_writes=0
outcomes_read=0
model_retuning=0
production_ranking_changes=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
runtime_activation=0
```
