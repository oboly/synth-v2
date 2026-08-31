# CQ v1 Temporal Sampling Contract v1

Issue: #646
Parent: #568

## Purpose

This contract freezes the multi-date CQ v1 temporal sampling plan before any temporal forward-outcome statistics are inspected.

It follows the successful Phase A replayability audit from #629 / PR #630:

```text
state=READY_TO_FREEZE_TEMPORAL_SAMPLING
blockers=none
asset_interval_quality distinct_ts=138
signal_engine_state distinct_ts=131
mrp_aggregate distinct_ts=461
mrp_asset distinct_ts=461
canonical_candles_15m distinct_ts=4134
```

Historical sector membership was unavailable in that audit. Sector context therefore remains unavailable for this lane and must not be reconstructed from current membership. Frozen CQ v1 does not score Sector Rotation.

## Frozen sampling

```text
timezone=UTC
cadence=1d
first_asof_ts_utc=2026-07-18T00:00:00Z
last_asof_ts_utc=2026-08-31T00:00:00Z
expected_unique_asofs=45
```

Daily cadence is deliberately conservative relative to the limiting quality/signal history and is chosen from source availability, not outcome performance. It avoids treating multiple same-day source updates as independent temporal validation windows.

The first sample is the first full UTC midnight after the audited history cutoff. The final sample is the last full UTC midnight at or before the audit as-of.

## Frozen chronological split

```text
discovery  2026-07-18 .. 2026-08-13  27 as-ofs
validation 2026-08-14 .. 2026-08-22   9 as-ofs
holdout    2026-08-23 .. 2026-08-31   9 as-ofs
```

This is a fixed 60/20/20 chronological allocation over the 45 daily timestamps. Split assignment is based only on `asof_ts_utc`. Asset ordering is never chronology.

The holdout is untouched until the final temporal evaluation slice.

## Point-in-time rules

At each frozen as-of, historical feature sources use the latest canonical row whose source timestamp is `<= asof_ts_utc`, under the source's canonical identity constraints.

Current/latest fallback is forbidden. Future feature truth is forbidden. Missing inputs remain missing. No imputation or weight renormalization is permitted.

Canonical candles at or before as-of may support feature reconstruction. Candles after as-of are labels only.

Sector context is explicitly `UNAVAILABLE_HISTORICAL_MEMBERSHIP`; current `asset_cluster_membership` may not substitute for missing history.

PPP remains unavailable unless a canonical historical PPP artifact with explicit point-in-time provenance is supplied.

## Observation identity

Each reconstructed temporal observation must include at least:

```text
asset_id
venue
asof_ts_utc
evidence_key
cq_model_version
model_family_version
coverage_artifact_sha256
```

Prefer immutable research file artifacts. Do not backfill reconstructed historical observations into `research_entry_quality_shadow`.

## Frozen CQ model family

Unchanged:

```text
model_family_version=1.0.0
coverage_artifact_sha256=f09a515535dd72c5422cbfea7ad449163132b298d1759f32701f0152c78aff2d
cq_v1_mrp_balanced_v1
cq_v1_mrp_anchor_v1
```

## Machine-readable authority

The canonical machine-readable contract is:

```text
config/research/cq_v1_temporal_sampling_v1.json
```

`src/research/cq_v1_temporal_sampling_v1.py` derives the exact as-of sequence and split membership from that contract. Tests lock the endpoints, count, cadence, split boundaries, fail-closed PIT semantics and frozen model identity.

## Safety

This slice reads no outcomes and performs no production or execution mutation.
