# Forecast confluence point-in-time replay v1

This research-only runner persists a deterministic JSON result under
`data/research/forecast_confluence_pit_replay_v1/`. It does not alter
selection, decision, execution, broker, or production database state.

It selects the latest Rotation Pressure observation and sector snapshot no
later than each Fib-map forecast timestamp, with a four-hour freshness bound.
Rows without a valid feature are explicitly `UNAVAILABLE`; they are never
filled from a later row. Sector membership is joined using its historical
validity interval. The result includes availability, feature provenance,
baseline/enriched cohorts, negative results, interactions with at least 20
outcomes, and an explicit future-leakage assertion.

The confidence label is evaluated as an empirical cohort label. It is not
treated as a calibrated probability without supporting calibration evidence.

## 2026-07-31 through 2026-08-17 replay

Artifact: `data/research/forecast_confluence_pit_replay_v1/result_20260731_20260817_v1.json`.

The current database replay yielded 3,039 forecast rows and 8,130 evaluable
baseline outcomes (the supplied completed replay had 2,938 / 8,814, so this is
recorded as input/cohort drift, not claimed as a reproduction). Rotation
Pressure was available for 1,656 rows (54.49%); sector rotation for 1,595
rows (52.49%). Feature availability starts only on their persisted historical
dates, so older rows remain unavailable rather than receiving later values.

Baseline direction hit rate was 49.40%, mean return -1.5783%, median -0.0233%.
The enriched score gave 48.94%, -1.6387%, and -0.0399%, respectively. This is
not evidence of incremental aggregate value. Rotation-in was the least poor
pressure state (+0.1467% mean, n=540); sector `INSUFFICIENT_PARTICIPATION`
was strongly negative (-5.7881%, n=720). These are retained as observations,
not rule proposals, because the period is short and coverage is incomplete.

Confidence does not behave as directional probability: baseline HIGH had a
45.81% hit rate but +1.2258% mean return (n=227), while LOW had a 50.88% hit
rate but -2.3985% mean return (n=6,134). Within this replay it is more
defensible to describe HIGH as a return-quality / heuristic grouping than a
calibrated directional-probability label. No production label is renamed.
