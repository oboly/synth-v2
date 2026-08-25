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

The current database replay yielded 3,039 forecast rows, 8,081 evaluable
baseline outcomes, and 7,844 evaluable enriched outcomes (the supplied
completed replay had 2,938 / 8,814, so this is recorded as input/cohort drift,
not claimed as a reproduction). Rotation
Pressure was available for 1,656 rows (54.49%); sector rotation for 1,595
rows (52.49%). Feature availability starts only on their persisted historical
dates, so older rows remain unavailable rather than receiving later values.

Endpoint evaluation now requires the exact canonical `4h` close at each
requested horizon. A missing exact endpoint is excluded as
`missing_endpoint_candle`; there were 94 such exclusions in each mode. The
MFE/MAE window ends at that same exact endpoint and never advances to a later
candle.

Baseline direction hit rate was 49.31%, mean return -1.6349%, median -0.0267%,
mean MFE 3.4450%, and mean MAE 5.7613%. The enriched score gave 48.84%,
-1.6983%, -0.0432%, 3.4356%, and 5.8442%, respectively. These aggregate
results are not evidence of incremental feature value and do not propose a
production rule.

Confidence remains an empirical cohort label, not a calibrated directional
probability. No production label is renamed.
