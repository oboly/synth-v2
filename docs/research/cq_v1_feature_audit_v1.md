# CQ v1 canonical feature audit v1

Issue: #568
Phase: 2B
Status: research-only, market-only, no production ranking change

## Purpose

Freeze which cross-market feature families are currently allowed to enter a future CQ v1 candidate before any CQ v1 formula or weights are chosen.

This slice does **not** score CQ v1. It audits canonical ownership, point-in-time replayability, timestamp/version provenance and the exact fields that may later be extracted.

Frozen registry:

```text
config/research/cq_v1_feature_audit_v1.yaml
```

## Eligibility rule

A candidate family is eligible only when all of the following are true:

```text
market-only
account-agnostic
canonical persisted owner exists
observation timestamp exists
exact source model version is frozen
same-venue identity is enforceable
point-in-time row can be resolved at or before CQ observation as-of
future/current-truth fallback is unnecessary
```

If any item is missing, the candidate remains unavailable rather than being recomputed ad hoc inside CQ.

## Eligible family 1: Market Rotation Pressure

Canonical persisted tables:

```text
market_rotation_pressure_snapshot_v1
market_rotation_pressure_observation_v1
```

Frozen source model version:

```text
model_version = 1.0
```

Both sources use `as_of_ts_utc` and `model_version`. The aggregate snapshot exposes breadth and market-direction context, while the per-asset observation exposes asset-level rotation pressure.

### Venue identity

The aggregate row has its own `venue`. The per-asset table does **not** have a venue column, so its venue is resolved only through its parent snapshot:

```text
market_rotation_pressure_observation_v1.pressure_snapshot_id
  -> market_rotation_pressure_snapshot_v1.pressure_snapshot_id
  -> market_rotation_pressure_snapshot_v1.venue
```

That resolved venue must equal the CQ observation venue. Cross-venue fallback is forbidden.

Eligible aggregate fields include market score, positive/negative breadth ratios, acceleration/concentration/confirmation states, market direction, evidence-light count and eligible-asset count.

Eligible per-asset fields are `score_total`, `pressure_state`, `phase_state`, and `raw_market_relative_pct`.

Important semantic boundary:

```text
raw_market_relative_pct != BTC-relative strength
```

It is a market-relative field and must not be relabeled as BTC-specific evidence.

## Eligible family 2: Sector Rotation

Canonical persisted table:

```text
sector_rotation_snapshot
```

Frozen source identity:

```text
model_version = sector-rotation-v1.0.0
window_code = 4h
venue = CQ observation venue
```

Replay identity/provenance includes:

```text
sector_code
venue
window_code
asof_ts_utc
model_version
input_hash
taxonomy_versions_json
```

Arbitrary window selection and cross-venue fallback are forbidden in registry v1.0.0.

### Symbol-to-sector point-in-time requirement

Sector context may be attached to a CQ observation only through canonical membership history satisfying:

```text
asset_cluster_membership.valid_from_ts_utc <= observation_asof
AND
(
  valid_to_ts_utc IS NULL
  OR observation_asof < valid_to_ts_utc
)
AND
membership_type = PRIMARY
```

If multiple valid PRIMARY rows exist, selection is deterministic:

```text
ORDER BY membership_weight DESC, sector_code ASC
LIMIT 1
```

No current sector label may be backfilled into historical observations.

`relative_strength_vs_btc` and `relative_strength_vs_eth` are **sector-level** measurements. They must not be presented as symbol-level BTC/ETH relative strength.

## Explicitly unavailable / excluded

The following candidate families are not allowed in CQ v1 registry version 1.0.0:

```text
BTC structure/regime
symbol-vs-BTC relative strength
ETH/BTC relative context
Breathline context
Rotation Flip research findings
```

For the first three, the audit did not identify a separate canonical replayable owner with the required timestamp/version contract. Breathline and Rotation Flip remain research inputs/hypotheses rather than promoted canonical CQ inputs.

A later implementation may add one of these only through a new registry version after its canonical producer has independently satisfied replay and ownership requirements.

## Point-in-time extraction rule

For every CQ shadow observation:

```text
feature_row.asof <= cq_observation.asof
feature_source.venue = cq_observation.venue
feature_source.model_version = frozen registry version
```

The extractor must select the latest eligible canonical row at or before the observation timestamp. It must never use:

```text
future rows
latest-now rows as historical fallback
later taxonomy membership
a different venue
a later/backfilled model version
an arbitrary sector window
future outcome labels
later market regime/breadth state
```

Missing context remains explicit and contributes to coverage/unavailable reporting.

## Freeze boundary

Version 1.0.0 freezes only:

```text
eligible feature families
canonical source tables
allowed source fields
same-venue source identity
source model versions
sector window = 4h
PRIMARY membership selection and tie-break
point-in-time source rules
explicit exclusions
```

It does **not** freeze:

```text
feature normalization/transforms
weights
CQ v1 formula
bucket thresholds
promotion decision
```

Those belong in the next preregistered slice and must be frozen before final holdout inspection.

## Next slice

Phase 2C should build a replay-safe extractor over the frozen eligible inputs, measure feature availability/missingness on the CQ-shadow population, and only then preregister a small deterministic CQ v1 candidate formula.

The same eligible observation set must ultimately be used when comparing CQ v0 vs CQ v1 so missingness cannot manufacture an apparent improvement.

## Safety

```text
research_only=1
market_only=1
account_awareness=0
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
