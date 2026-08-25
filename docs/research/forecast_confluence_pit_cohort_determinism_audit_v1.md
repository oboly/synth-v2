# Forecast confluence PIT cohort determinism audit v1

## Canonical finding

The historical **2938 forecasts / 8814 outcomes** cohort is not canonical
because its identity ledger and source snapshot are unavailable.

The current **3039 forecast** cohort is the reproducible canonical research
cohort for `forecast_confluence_pit_replay/v1` as of the persisted source
state. This does **not** mean historical DB state is immutable. It records a
deterministic replay result against the persisted source state observed for
this audit only.

Scope: `bitvavo`, `[2026-07-31T00:00:00Z, 2026-08-18T00:00:00Z)`.

This audit establishes forecast-cohort determinism. It does not establish
underlying persisted-data immutability, and it makes no claim about Rotation
Pressure or sector effectiveness.

## Identity contracts

Forecast identity is:

```text
(venue, market, forecast_as_of UTC, map_id)
```

Outcome identity is:

```text
(forecast identity, mode, horizon_hours, endpoint_close_ts UTC)
```

The expected outcome slots are `3039 * 3 = 9117` per mode for horizons 4, 24,
and 168 hours. The identity artifact is
`data/research/forecast_confluence_pit_replay_v1/cohort_determinism_audit_v1.json`.

## Current replay cohort

| measure | value |
| --- | ---: |
| forecast count | 3039 |
| baseline outcomes | 8175 |
| enriched outcomes | 7938 |

Pipeline stage counts:

```text
raw=3825
venue=3825
interval=3825
Fib-status=3039
asset=3039
same-ts-signal=3039
dedup=3039
final=3039
```

Current Fib eligibility is unchanged: a forecast is a `bitvavo` canonical
Fib-zone map in the requested time window at interval `4h`, with map status
`FRESH`, `FALLBACK`, or `EMERGENCY_REBUILT`; it must resolve to an asset and a
same-timestamp `signal_engine_state` row at interval `4h`. The audit does not
change replay filtering, neutral-direction semantics, outcome generation,
Fib eligibility, or confidence semantics.

## Exclusions

All non-neutral exclusion reasons are zero. The only exclusions are neutral
directions, across all three horizons:

```text
baseline neutral_direction=942  (314 forecasts * 3 horizons)
enriched neutral_direction=1179 (393 forecasts * 3 horizons)
all other exclusion reasons=0
```

Thus baseline has `9117 - 942 = 8175` outcomes and enriched has
`9117 - 1179 = 7938` outcomes.

## Determinism evidence

Independent full-audit JSON reruns were byte-identical:

```text
full audit SHA256=c3f9cb32ab97b13b33481870e8f78681a48c1b6796822191c2091e484a95c0d3
forecast identity SHA256=83704f...45ad3
baseline outcome SHA256=e76d55...54513
enriched outcome SHA256=ec47cd...11f0a
```

The supplied identity-ledger evidence retains the abbreviated SHA256 values
above. Its full per-ledger digests and ledger bytes were not supplied with the
historical artifacts; the full audit JSON digest is retained in the canonical
machine-readable record.

## Historical comparison and drift

The original historical cohort was 2938 forecasts and 8814 outcomes. Its
command, code/data snapshot, and identity artifact are unavailable, so it
cannot be reproduced or promoted to canonical status.

The older checked-in aggregate was `3039 / 8130 / 7895`
(forecasts / baseline outcomes / enriched outcomes). The current persisted
data produces `3039 / 8175 / 7938`. This is observed data drift, not a replay
semantic change.

## Unresolved uncertainty

- The historical 2938/8814 cohort's source snapshot, command, code revision,
  and identity ledger are unavailable.
- The audit proves deterministic cohort construction for the observed source
  state, not that historical tables cannot change later.
- The accepted evidence includes only abbreviated per-ledger SHA256 values;
  a future source-state audit should retain full identity ledgers and full
  per-ledger digests alongside the full audit JSON.

Safety: `production_db_mutation=0`, `selection_engine_behavior_changes=0`,
`decision_gate_changes=0`, `execution_planner_changes=0`, `executor_changes=0`,
`broker_writes=0`, `orders=0`, `live_activation=0`, `future_leakage=0`.
