# Sector Rotation Dashboard Acceptance v1

## Status

Repository acceptance evidence for GitHub Issue #204. This records the
bounded Phase C1 Sector Overview publisher only; it does not authorize a
runtime installation, activation, or production deployment.

## Boundary

```text
market data / research owners
    -> persisted canonical sector rotation truth
    -> read-only reporting
```

The publisher is market-only and account-agnostic. It has no
`selection_engine`, `decision_gate`, `execution_planner`, executor, broker,
order, or account authority.

## Canonical inputs

The runner reads only these persisted inputs for the requested venue and
model version:

- `sector_definition`: active `sector_code` and `display_name`, ordered by
  canonical `sort_order, sector_code`.
- `sector_rotation_snapshot`: the newest `asof_ts_utc`, then that exact
  timestamp's `sector_code`, `window_code`, `rotation_score`,
  `rotation_state`, `confidence`, `participation_ratio`,
  `supporting_flags_json`, and `generated_ts_utc`.

The accepted model and windows are `sector-rotation-v1.0.0` and exactly
`1h`, `4h`, `1d`, `7d`. The publisher never queries an older timestamp as a
fallback, and it never reads source candles, memberships, balances,
positions, orders, preferences, or broker state.

## Freshness and availability contract

- `FRESH`: newest coherent cohort is at most three hours old.
- `STALE`: newest coherent cohort is more than three hours old; it is
  published as `DEGRADED` with age shown.
- `FUTURE_TIMESTAMP`: newest coherent cohort is over five minutes ahead of
  render time; it is published as `DEGRADED`.
- Missing: a newest cohort with anything other than the exact window set, or
  without every active sector/window cell, is `DATA_UNAVAILABLE` with
  `INCOMPLETE_LATEST_COHORT`.
- Unavailable: no candidate cohort is `NO_COHORT_CANDIDATES`; no active
  sector definition is `NO_ACTIVE_SECTORS`.

Missing and unavailable outputs atomically replace prior HTML/JSON output;
the runner exits nonzero after publishing the unavailable state. This avoids
silently retaining an older complete view.

## Display-field source map

| Display field | Source or pure presentation derivation |
| --- | --- |
| Sector name/code | `sector_definition.display_name` / `sector_definition.sector_code` |
| Window columns | Fixed canonical contract: `1h`, `4h`, `1d`, `7d` |
| Score | `sector_rotation_snapshot.rotation_score`, formatting only |
| State | `sector_rotation_snapshot.rotation_state`, underscore-to-space label only |
| Confidence | `sector_rotation_snapshot.confidence`, percentage formatting only |
| Participation | `sector_rotation_snapshot.participation_ratio`, percentage formatting only |
| Volume confirmation | Pure label selection from persisted `supporting_flags_json` |
| Venue/model/as-of | Requested venue/model and newest persisted `asof_ts_utc` |
| Age/freshness | Pure comparison of persisted as-of against render time |
| Availability reason | Cohort completeness and source-presence checks only |
| Safety markers | Static reporting boundary declaration, verified by focused tests |

No HTML or JavaScript is used for sector aggregation, scoring, taxonomy
classification, ranking, or state calculation. The static HTML has no
JavaScript execution path.

## Repository acceptance evidence

```text
canonical_inputs=sector_definition(active code/display name/order); sector_rotation_snapshot(newest exact venue/model cohort)
freshness_contract=FRESH<=3h; STALE>3h; FUTURE_TIMESTAMP>5m ahead; incomplete/no-candidate/no-active-sector fail closed
display_field_source_map=this document, Display-field source map
market_only_check=passed; persisted market/research truth only
account_inputs=0
writer_calls=0
broker_calls=0
local_sector_recompute=0
local_rank_recompute=0
focused_tests=tests/test_sector_rotation_dashboard_v1.py
deployment_required=no
activation_gate=separate; docs/ops/sector_rotation_runtime_activation_v1.md remains not installed, not enabled, and not production-accepted
```
