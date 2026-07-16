# Sector Rotation Engine v1

## Status

Repository implementation is complete for review. The migration has not been
applied and no `sector_rotation_snapshot` rows have been written. Phase C is the
next separate lane after Phase B review, migration, and snapshot acceptance.

## Boundary

Owner: research / analytics. The engine is market-only, account-agnostic, and
has no selection, permission, planning, execution, order, broker, reporting,
GUI, systemd, or timer behavior.

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
selection_engine=none
decision_gate=none
execution_planner=none
executor=none
```

Price and quote-volume observations support proxy rotation only. They are not
measurements of capital inflow or outflow and do not establish predictive
quality from one snapshot.

## Source contract

The engine reads:

- active `sector_definition` rows;
- point-in-time `asset_cluster_membership` rows joined to
  `asset_taxonomy_profile`;
- enabled or research-universe identities with a venue market-data mapping;
- canonical `obs_market_candle` 1h closes and quote volume;
- BTC and ETH candles at the same explicit as-of anchor;
- the reviewed `liquidity_market_cap_code` dimension;
- earlier persisted `sector_rotation_snapshot` rows for persistence only.

`asset.sector` is not a membership or score input. Membership validity is
start-inclusive and end-exclusive. A replay query may read only memberships
valid at its as-of timestamp and candles whose close timestamp is not later
than that timestamp.

## Grain and schema

Migration:

```text
db/migrations/20260716_sector_rotation_engine_v1.sql
```

The `sector_rotation_snapshot` deterministic key is:

```text
(sector_code, venue, window_code, asof_ts_utc, model_version)
```

`source_interval_code` is `1h`; independent `window_code` values are `1h`,
`4h`, `1d`, and `7d`. The table stores all required measured fields, member and
coverage diagnostics, persistence status, canonical state, confidence,
component JSON, supporting flags, taxonomy versions, an input hash, model
version, and generation timestamp. The component JSON includes per-member
eligibility and effective-weight evidence so the score can be reconstructed.

## Model v1.0.0

```text
model_version=sector-rotation-v1.0.0

rotation_score =
    0.30 * relative_strength_component
  + 0.25 * participation_component
  + 0.20 * volume_share_change_component
  + 0.15 * persistence_component
  + 0.10 * liquidity_quality_component
```

All five components are bounded to `[-100, 100]`. Relative strength combines
BTC at 60% and ETH at 40% after window-specific hyperbolic-tangent scaling.
The participation component is the signed positive-minus-negative percentage
multiplied by the participation ratio. Volume-share change uses a versioned
0.25 percentage-point scale. Liquidity quality is a bounded reviewed tier
weight. First-snapshot persistence is zero evidence with explicit
`INSUFFICIENT_HISTORY`, not implied neutral history.

Measured-field definitions are deterministic:

- weighted return uses capped sector weights; median return remains unweighted;
- positive and negative participation use window-specific absolute-move
  thresholds of 0.10%, 0.25%, 0.50%, and 1.50%;
- participation ratio is `(positive members + negative members) / eligible members`;
- benchmark outperformance is the eligible-member percentage above BTC;
- relative strength subtracts the same-window BTC or ETH return;
- sector volume share allocates each asset's quote volume by its normalized
  cross-cluster membership and divides by eligible-universe quote volume;
- sector volume-share change subtracts the preceding comparable-window share;
- momentum-positive percentage counts current returns above the asset's
  preceding comparable-window return;
- dispersion is the capped-weight population standard deviation;
- effective weighted member count is `1 / sum(weight^2)`;
- coverage ratio is `eligible members / point-in-time taxonomy members`.

## Weighting and fail-closed rules

- An asset's membership weights are divided by `max(1, sum(weights))`, so its
  aggregate cross-cluster allocation cannot exceed one.
- Liquidity multipliers are capped at `1.25`.
- Classifiable sectors cap an asset's normalized sector contribution at 35%.
- At least three eligible and 2.5 effective weighted members are required.
- Coverage and participation ratios must each be at least 0.50.
- Current and comparable baseline candle coverage must each be at least 0.90.
- Candles more than two hours behind the explicit as-of anchor are stale.
- Missing or stale BTC or ETH data produces `DATA_UNAVAILABLE`.
- `UNCLASSIFIED` cannot receive a leading or tradable interpretation.
- Small, single-member, dominant-member, or low-participation sectors report
  `INSUFFICIENT_PARTICIPATION` rather than manufactured confidence.

The canonical state is one of `LEADING`, `IMPROVING`, `NEUTRAL`, `WEAKENING`,
`LAGGING`, `INSUFFICIENT_PARTICIPATION`, or `DATA_UNAVAILABLE`. Independent
proxy-rotation, market-activity, confirmation, dominance, and persistence facts
remain explicit supporting flags rather than contradictory canonical states.

## Persistence and reconciliation

Persistence uses only up to three earlier rows with the same sector, venue,
window, and model version. No process-local history is accepted. In replay
write mode, earlier rows in the same database transaction become the only
source for later persistence.

Writes require a named zero-wait database lock and one transaction. The runner
compares deterministic input hashes and reports inserts, updates, unchanged,
and stale counts separately. Unchanged rows are not updated. A rerun of the
same key and inputs is a no-op.

## Runner contract

Current/as-of computation:

```bash
python -m src.research.run_sector_rotation_engine_v1 --validate-only
python -m src.research.run_sector_rotation_engine_v1 --dry-run
python -m src.research.run_sector_rotation_engine_v1 --write-db
python -m src.research.run_sector_rotation_engine_v1 --dry-run \
  --as-of-ts 2026-07-16T18:00:00Z
```

Historical replay:

```bash
python -m src.research.run_sector_rotation_replay_v1 --validate-only
python -m src.research.run_sector_rotation_replay_v1 --dry-run \
  --start-as-of 2026-07-15T18:00:00Z \
  --end-as-of 2026-07-16T18:00:00Z
```

`--validate-only` opens no database connection. `--dry-run` reads the database,
computes the reconciliation plan, and rolls back. `--write-db` fails unless the
reviewed migration exists, obtains the single-writer lock, and commits or rolls
back atomically.

## Real-data no-write evidence

Read-only acceptance ran against `synth` on `gurkdb` at
`2026-07-16T18:00:00Z` with 29 active sectors, 473 point-in-time memberships,
428 venue-mapped identities, and 107,615 bounded candle rows. BTC and ETH both
resolved exactly to the as-of timestamp for all four windows. The missing
target table was reported with the migration path; the transaction rolled back
and database writes were zero.

```text
window  sectors  available  insufficient  unavailable
1h      29       17         11            1
4h      29       13         12            4
1d      29       10         10            9
7d      29        8         10           11

planned inserts=116 updates=0 unchanged=0 stale=0
```

A bounded one-timestamp replay of the same anchor also produced 116 planned
rows, 43 insufficient and 25 unavailable sector-window states, rolled back,
and performed zero writes.

Requested component evidence was emitted for every window for `DEFI_LENDING`,
`RWA`, `AI_COMPUTE`, `PERP_DEX`, and
`INSTITUTIONAL_FINANCE_INFRA`. Examples of honest failure include the
single-member DeFi Lending and Institutional Finance Infrastructure sectors,
which remain `INSUFFICIENT_PARTICIPATION` even when their raw score is large.
AI Compute had two eligible members and also remained insufficient. RWA and
Perp DEX changed state across windows, demonstrating that windows are not
silently averaged.

Dominance diagnostics identified 50 sector-window rows above the 35% threshold;
all such classifiable-cap violations were small or low-coverage rows already
failed closed. The complete deterministic lists are printed by the dry-run.

## Validation and next lane

Synthetic tests cover broad advance, isolated spike, cooling, risk-off
underperformance, ETH-led improvement, stale inputs, capped dominance,
conflicting windows, cross-cluster normalization, missing benchmarks,
first-snapshot persistence, idempotency, taxonomy validity, `UNCLASSIFIED`,
future-candle exclusion, replay ordering, migration contract, and forbidden
imports.

Phase C dashboard work is next only after this migration and initial snapshots
are separately reviewed and accepted. Reporting must read persisted truth and
must not recompute it.
