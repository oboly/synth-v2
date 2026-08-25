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
and 168 hours. The committed canonical payload is
`data/research/forecast_confluence_pit_replay_v1/cohort_determinism_audit_v1.json`.
Its separately timestamped metadata is
`data/research/forecast_confluence_pit_replay_v1/cohort_determinism_audit_manifest_v1.json`.

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

Two independent read-only audit runs produced byte-identical identity ledgers
and canonical audit payload. The full digests are computed from the committed
bytes they describe:

```text
forecast identity ledger SHA256=862fb3a2df8611e1382447da5e3ecadfcda68de7086a98caa4b729e4ebb7692b
baseline outcome identity ledger SHA256=5b6d33cf399b78701623992ce2dbe58b12156aa3ba2d523bccb5f33079a88380
enriched outcome identity ledger SHA256=4d9ce9bb1ad19993b733bacd92f385ef5411526a37bb7465b2f5c5e76c58fbc6
canonical audit payload SHA256=96a5a91a44738c0e233d9c3ad7e922ddb3c96a5cc179ec7a70c7ccf39aaf8379
```

The prior `c3f9cb32ab97b13b33481870e8f78681a48c1b6796822191c2091e484a95c0d3`
claim cannot be tied to any recoverable committed payload, replay result, or
identity ledger. It is removed rather than retained as canonical evidence.
The prior abbreviated per-ledger values are also superseded by the committed,
full-byte ledgers above. `generated_at_utc` exists only in the metadata
manifest and is outside the deterministic audit payload.

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
- The prior `c3f9...` source payload is unavailable, so its semantics cannot
  be recovered beyond the fact that it was not a digest of the previously
  committed audit JSON.

Safety: `production_db_mutation=0`, `selection_engine_behavior_changes=0`,
`decision_gate_changes=0`, `execution_planner_changes=0`, `executor_changes=0`,
`broker_writes=0`, `orders=0`, `live_activation=0`, `future_leakage=0`.
