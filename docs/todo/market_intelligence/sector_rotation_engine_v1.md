# Sector Rotation Engine v1

## Status

**Phase B accepted** — Phase A is accepted. The Phase B migration has been
applied and the accepted persisted cohort (venue `bitvavo`,
`model_version=sector-rotation-v1.0.0`, `asof_ts_utc=2026-07-16 18:00:00 UTC`,
116 rows, 29 sectors, windows 1h/4h/1d/7d) passed provenance/idempotence
audit. Phase C1 (`../sector_rotation_dashboard_v1.md`) now reads this cohort
through a bounded read-only Sector Overview publisher. Canonical
implementation contract:

```text
docs/research/sector_rotation_engine_v1.md
```

## Purpose

Build a research-only, explainable sector analytics engine that measures participation, relative strength, volume confirmation, and rotation state across canonical Synth sectors.

This phase depends on the taxonomy and database seed from `../completed/sector_taxonomy_database_seed_v1.md`.

## Inputs

- `asset_cluster_membership`;
- enabled/research-universe asset set;
- market candles;
- quote volume;
- BTC and ETH benchmark returns;
- liquidity/profile metadata where available;
- optional existing momentum features, kept read-only.

## Required timeframes

At minimum:

- 1h
- 4h
- 1d
- 7d

## Sector metrics

For each sector, venue, timeframe, and as-of timestamp compute:

- weighted return;
- median return;
- positive participation percentage;
- negative participation percentage;
- participation ratio;
- relative strength versus BTC;
- relative strength versus ETH;
- sector volume share;
- change in sector volume share;
- momentum-positive percentage;
- dispersion;
- member count;
- eligible member count;
- effective weighted member count;
- data coverage ratio;
- liquidity quality;
- persistence across prior snapshots.

## Rotation score v1

Use an explicit, versioned, explainable formula. Initial proposal:

```text
30% relative strength
25% participation
20% volume-share change
15% momentum persistence
10% liquidity quality
```

The exact weights must be constants tied to a model version and covered by tests.

## States and terminology

Allowed research states should include:

- `MARKET_ACTIVITY_RISING`
- `MARKET_ACTIVITY_COOLING`
- `ROTATION_INFLOW_PROXY`
- `ROTATION_OUTFLOW_PROXY`
- `LEADING`
- `IMPROVING`
- `NEUTRAL`
- `WEAKENING`
- `LAGGING`
- `NO_CONFIRMATION`
- `INSUFFICIENT_PARTICIPATION`
- `DATA_UNAVAILABLE`

Do not call price/volume-derived behavior measured inflow or outflow.

Measured external/public flows remain separately typed:

- `MEASURED_ONCHAIN_FLOW`
- `MEASURED_ETF_FLOW`
- `EXTERNAL_RESEARCH_FLOW`

## Proposed snapshot table

### `sector_rotation_snapshot`

```sql
sector_code              VARCHAR(...)
venue                    VARCHAR(...)
interval_code            VARCHAR(...)
asof_ts_utc              DATETIME
return_weighted          DECIMAL(...)
return_median            DECIMAL(...)
positive_participation_pct DECIMAL(...)
negative_participation_pct DECIMAL(...)
participation_ratio       DECIMAL(...)
rs_vs_btc                DECIMAL(...)
rs_vs_eth                DECIMAL(...)
volume_share             DECIMAL(...)
volume_share_change      DECIMAL(...)
momentum_positive_pct    DECIMAL(...)
dispersion               DECIMAL(...)
liquidity_quality        DECIMAL(...)
rotation_score           DECIMAL(...)
rotation_state           VARCHAR(...)
confidence               DECIMAL(...)
member_count             INT
eligible_member_count    INT
effective_member_count   DECIMAL(...)
coverage_ratio           DECIMAL(...)
model_version            VARCHAR(...)
notes                     TEXT NULL
```

Use a deterministic uniqueness key over sector, venue, interval, as-of timestamp, and model version.

## Guardrails

- Require a minimum eligible member count.
- Cap single-asset contribution.
- Cap liquidity weighting.
- A one-coin spike must not generate high sector participation.
- Missing benchmark data must fail closed.
- Low coverage must produce `DATA_UNAVAILABLE` or `INSUFFICIENT_PARTICIPATION`.
- Keep timeframes separate; do not silently average them.
- Preserve raw score components for auditability.
- No automatic selection or trading impact.

## Validation scenarios

Synthetic tests must cover:

1. Broad sector advance with rising volume.
2. One-coin spike while peers are flat or down.
3. Broad sector cooling after prior leadership.
4. BTC decline with alts declining harder.
5. ETH-led DeFi improvement.
6. Missing members and stale candles.
7. Dominant large-cap member with capped influence.
8. Conflicting 1h and 1d states.

## Backtest and research output

Provide a replay or backfill runner that can:

- generate historical snapshots;
- compare state transitions with subsequent returns;
- measure false-positive rotation signals;
- inspect persistence requirements;
- export audit-friendly research rows.

## Acceptance

- Reproducible snapshots exist for at least 1h, 4h, and 1d.
- Initial outputs cover DeFi, RWA, AI/Compute, L2, and Perp DEX.
- Score components are explainable and stored.
- One-coin spikes do not masquerade as broad sector rotation.
- Risk-off alt underperformance is classified correctly.
- Stale or insufficient data fails closed.
- Backfill/replay is deterministic.
- No changes to `selection_engine`, `decision_gate`, `execution_planner`, executor, or broker paths.

## Repository acceptance evidence

```text
model_version=sector-rotation-v1.0.0
windows=1h,4h,1d,7d
score weights=30/25/20/15/10
active sectors=29
point-in-time memberships=473
dry-run rows=116
dry-run reconciliation=inserts 116, updates 0, unchanged 0, stale 0
database writes=0
migration applied=0
```

At `2026-07-16T18:00:00Z`, BTC and ETH benchmark timestamps matched exactly
for all windows. Available / insufficient / unavailable counts were 17/11/1
for 1h, 13/12/4 for 4h, 10/10/9 for 1d, and 8/10/11 for 7d. Single-member and
dominant-member sectors failed closed. This is one current snapshot and makes
no predictive-quality claim.

## Remaining acceptance actions

Phase B acceptance actions (merge, migration apply, first write, invariant
checks, idempotent second write) are complete. Remaining work belongs to the
Phase C dashboard lanes in `../sector_rotation_dashboard_v1.md`.

## Layer and boundaries

```text
Owner: research / analytics
Depends on: Sector Taxonomy & Database Seed v1
DB writes: expected analytics snapshots only
Broker writes: 0
Order submissions: 0
Execution impact: none
```
