# CQ v2 fresh temporal cohort contract v1

Issue: #777 Phase C
Status: specification only; fresh data still accumulating

## Purpose

Freeze the temporal observation cohort required before any CQ v2 candidate family can be evaluated. The consumed #684 cohort remains diagnostic evidence only and is never reused as CQ v2 discovery, validation, or holdout.

This contract follows the #777 Phase A rejection post-mortem and Phase B upstream readiness audit. It does not define CQ v2 features, weights, thresholds, or candidate formulas.

## Fresh cohort boundary

```text
timezone=UTC
cadence=1d
first_asof_ts_utc=2026-09-01T00:00:00Z
last_asof_ts_utc=2026-10-15T00:00:00Z
expected_unique_asofs=45
prior_consumed_terminal_asof=2026-08-31T00:00:00Z
max_forward_horizon=24h
final_label_maturity_ts_utc=2026-10-16T00:00:00Z
```

Every fresh as-of is strictly later than the terminal #684 cohort. Daily cadence is retained for comparability with #646 and to avoid treating multiple same-day source updates as independent temporal windows.
## Frozen chronological split

```text
discovery  2026-09-01 .. 2026-09-27  27 as-ofs
validation 2026-09-28 .. 2026-10-06   9 as-ofs
holdout    2026-10-07 .. 2026-10-15   9 as-ofs
```

The allocation remains 60/20/20 over 45 daily timestamps. Split assignment is determined only by `asof_ts_utc`.

Asset ordering, score ordering, coverage state, or later outcomes may never alter split membership.

## Observation population

The fresh population must preserve immutable observation identity at minimum:

```text
asset_id
venue
asof_ts_utc
evidence_key
baseline/CQ-v0 source identity
feature-registry version
population-contract version
observation_id
```

Population materialization is market-only and outcome-blind. It may inspect only canonical source rows whose source timestamp is `<= asof_ts_utc`.
Current/latest fallback, future source rows, later taxonomy truth, or ad-hoc historical recomputation inside the CQ evaluator are forbidden. Missing canonical evidence remains missing.

## Feature-registry boundary

Phase B currently identifies CQ v0, broad/regime Market Rotation Pressure V1, and Sector Rotation 4h with PIT membership as canonical replayable contexts. This Phase C contract does **not** automatically freeze them into a CQ v2 formula.

Before score materialization, a separate preregistration must freeze a small feature registry and candidate family. Any additional feature may enter only if its canonical owner independently proves replayability across the complete fresh cohort under explicit version/provenance rules.

A feature that becomes available later may not be backfilled from current truth merely to increase coverage. If it cannot be reproduced canonically at every required historical as-of, it is unavailable for that registry version.

## Label opening sequence

Forward outcomes are not part of population materialization. Required sequence:

```text
1. complete all 45 observation as-ofs
2. freeze population artifact + SHA256
3. freeze feature registry + small deterministic CQ v2 candidate family
4. only then derive forward labels
5. open discovery outcomes
6. apply the preregistered discovery rule
7. open validation outcomes
8. freeze any advance/reject decision and final-holdout evaluator
9. wait until every final-holdout label is mature through the maximum 24h horizon
10. only then open final holdout, never before 2026-10-16T00:00:00Z
```

No discovery/validation result may be used to change the frozen family and then continue under the same cohort identity. Any changed family requires a new preregistration and an untouched later final test.
## Outcome contract

For comparability, the default forward horizons remain `1h`, `4h`, and `24h`, using canonical 15m candles and identical-eligible-sample comparisons. Exact outcome definitions must be frozen before labels are derived and may not change after any outcome inspection.

The terminal observation at `2026-10-15T00:00:00Z` is not fully label-mature until its maximum 24h horizon ends at `2026-10-16T00:00:00Z`. Population completion on October 15 therefore does **not** authorize final-holdout evaluation. The machine-readable contract requires `final_holdout_evaluation_not_before=2026-10-16T00:00:00Z`; any evaluator must fail closed before that instant.

Negative results are retained. The consumed #684 rows are never relabeled as fresh evidence.

## Current availability and next state

At the time this contract was written, only the first few September dates can exist. The full 45-as-of observation cohort cannot be complete before `2026-10-15T00:00:00Z`. Its final 24h labels cannot all be mature before `2026-10-16T00:00:00Z`, so final-holdout evaluation remains blocked until that later maturity boundary.

Therefore the current #777 state is:

```text
FRESH_DATA_REQUIRED
```

A bounded follow-up should materialize the observation-only population once the terminal as-of exists and all required canonical sources have been audited for PIT availability.

## Safety

```text
research_only=1
market_only=1
account_awareness=0
outcomes_opened=0
model_retuning=0
candidate_selection=0
production_ranking_changes=0
db_writes=0
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
runtime_activation=0
```

Machine-readable authority: `config/research/cq_v2_fresh_temporal_cohort_v1.json`.