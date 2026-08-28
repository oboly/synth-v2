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
model/version provenance exists
point-in-time row can be resolved at or before CQ observation as-of
source venue equals CQ observation venue
future/current-truth fallback is unnecessary
```

If any item is missing, the candidate remains unavailable rather than being recomputed ad hoc inside CQ.

Cross-venue fallback is forbidden. Source identity must remain pinned to the same venue as the CQ shadow observation.

## Eligible family 1: Market Rotation Pressure

Canonical persisted tables:

```text
market_rotation_pressure_snapshot_v1
market_rotation_pressure_observation_v1
```

Both use `as_of_ts_utc`, `venue`, and `model_version`. The aggregate snapshot exposes breadth and market-direction context, while the per-asset observation exposes asset-level rotation pressure.

Frozen source identities are:

```text
aggregate: venue + as_of_ts_utc + model_version
per asset: venue + asset_id + as_of_ts_utc + model_version
```

The extractor must match `venue` to the CQ observation before selecting the latest eligible row at or before the observation timestamp.

Eligible aggregate fields are frozen in the registry and include market score, positive/negative breadth ratios, acceleration/concentration/confirmation states, market direction, evidence-light count and eligible-asset count.

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

Replay identity/provenance includes:

```text
venue
window_code
asof_ts_utc
model_version
input_hash
taxonomy_versions_json
```

### Frozen sector window

Registry v1.0.0 fixes sector context to:

```text
window_code = 4h
```

This matches the canonical 4h setup context used by local CQ/selection quality and prevents Phase 2C from selecting whichever sector window happens to look best. Arbitrary window selection or cross-window fallback is forbidden.

The source `venue` must equal the CQ observation venue. Cross-venue fallback is forbidden.

The table exposes deterministic sector-level rotation, participation, confidence, persistence, volume-share and BTC/ETH benchmark-relative fields.

### Symbol-to-sector point-in-time requirement

Sector context may be attached to a CQ observation only through canonical membership history:

```text
asset_cluster_membership.valid_from_ts_utc <= observation_asof
AND
(
  valid_to_ts_utc IS NULL
  OR observation_asof < valid_to_ts_utc
)
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
feature_row.venue = cq_observation.venue
sector_rotation.window_code = 4h
```

The extractor must select the latest eligible canonical row at or before the observation timestamp after applying the frozen identity constraints. It must never use:

```text
future rows
cross-venue fallback
arbitrary sector-window selection
latest-now rows as historical fallback
later taxonomy membership
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
same-venue matching
sector window = 4h
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

Phase 2C should build a replay-safe extractor over the frozen eligible inputs, enforce same-venue matching and the fixed 4h sector window, measure feature availability/missingness on the CQ-shadow population, and only then preregister a small deterministic CQ v1 candidate formula.

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
