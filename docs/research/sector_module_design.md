# Sector Observation and Rotation Module — Design v1

## Status

Design only. No sector table, builder, runtime ranking weight, decision-gate rule, execution behavior, or broker action is introduced by this document.

## Purpose

The sector module adds a market-only observation layer above individual asset features.

It must answer measurable questions:

- is a sector moving broadly or because of one leader?
- which sectors are leading, improving, weakening, or lagging?
- is participation rotating across sectors?
- does a symbol perform differently when its sector has breadth and persistence?

It does not define an automatic trade rule.

## Architecture Position

```text
candles / ticker / volume
  -> asset returns and volume features
  -> asset-to-sector map
  -> sector snapshots
  -> sector breadth / persistence / leadership features
  -> sector rotation state
  -> future MarketObserverSnapshot
  -> shadow outcome validation
  -> possible future feature-promotion proposal
```

Sector observation belongs in market context/research. It is account-agnostic and must not be implemented in decision-gate, execution-planner, executor, or broker layers.

## Data Model

### `sector`

Defines sector taxonomy.

Examples:

```text
AI
DEFI
L1
L2
DATA
DEX
PERPS
RWA
PAYMENTS
PRIVACY
ORACLE
GAMING
MEME
BTC_ECOSYSTEM
```

Suggested fields:

- `sector_id`
- `sector_code`
- `sector_name`
- `taxonomy_version`
- `created_at`

### `asset_sector_map`

Maps an asset to one or more sectors.

Suggested fields:

- `asset_id`
- `sector_id`
- `weight`
- `classification_type`: PRIMARY | SECONDARY
- `taxonomy_version`
- `effective_from_utc`
- `effective_to_utc`

Classification starts manually and versioned. Dynamic narrative clustering is a later research overlay, not a silent replacement for taxonomy.

### `sector_snapshot`

One row per `(venue, interval, asof_ts_utc, sector, taxonomy_version)`.

Suggested measured fields:

- `coin_count`
- `active_coin_count`
- `breadth_ratio`
- `weighted_return_pct`
- `median_return_pct`
- `volume_ratio`
- `persistence_bars`
- `market_relative_return_pct`
- `leader_asset_id`
- `laggard_asset_id`
- `leader_contribution_pct`
- `freshness_state`
- `coverage_state`

Breadth definition:

```text
breadth_ratio = coins_up / coins_active
```

`leader_contribution_pct` is required so a single-asset pump cannot masquerade as sector rotation.

### `sector_rotation_state`

A descriptive, market-only interpretation of measured snapshots.

Allowed labels:

```text
UNKNOWN
LEADING
IMPROVING
NEUTRAL
WEAKENING
LAGGING
BREAKOUT
EXHAUSTION
STALE
```

Suggested fields:

- `sector_id`
- `asof_ts_utc`
- `interval`
- `regime_label`
- `confidence_score`
- `persistence_bars`
- `rank_in_market`
- `evidence_refs`

## Measurement Rules

A sector state must state its inputs and coverage. No hidden score formula is allowed.

A transparent research score may be calculated for ranking snapshots, but it is not a selection-engine score:

```text
sector_observation_score =
  documented_return_component
+ documented_breadth_component
+ documented_volume_component
+ documented_persistence_component
```

Any component, normalization method, missing-data treatment, and threshold must be versioned and visible in research output.

Market-relative context is required so a broad market pump does not label every sector `LEADING`:

```text
market_relative_return = sector_return - comparable_market_baseline
```

## Rotation Interpretation

Capital-rotation sequences are hypotheses to measure, not predefined market laws.

Examples worth measuring:

```text
L1 / infrastructure -> DeFi -> RWA -> small-cap beta
AI -> data -> compute -> privacy
BTC stability -> ETH relative strength -> broadening alt breadth
```

The module may observe these sequences only after the underlying sector snapshots exist. It must not encode a preferred narrative sequence as runtime policy.

## Relation to Market Observer

A future `MarketObserverSnapshot` may read sector states and report:

- which sectors are leading or improving
- whether breadth is narrow, selective, or broadening
- whether sector signals agree with BTC/ETH context
- whether a symbol's local setup aligns with its sector

It must not use sector labels as automatic buy/sell, allocation, or trade-permission instructions.

## Validation Plan

Before any use in `selection_engine`, test whether sector features add value beyond individual symbol context.

Minimum studies:

- symbol setup outcomes with matching versus non-matching sector state
- high breadth versus leader-dominated sector moves
- sector `LEADING` persistence across intervals
- sector state interaction with canonical global regime
- incremental outcome value against a no-sector baseline
- out-of-sample validation with explicit overlap control

Expected outcome measurements include return, MFE, MAE, invalidation-before-target rate, and horizon-aligned completeness.

## Forbidden Shortcuts

```text
sector state          -> direct order
sector score          -> hidden selection weight
sector rotation       -> account allocation
sector narrative      -> decision-gate permission
external flow snapshot -> sector truth without provenance
```

## Future Implementation Order

1. Canonical taxonomy and versioned asset-sector map.
2. Deterministic sector snapshots from existing market data.
3. Coverage, leader-contribution, and freshness diagnostics.
4. Descriptive sector-rotation state.
5. Research-only market-observer integration.
6. Shadow outcome validation.
7. Explicit feature-promotion proposal only after evidence.

## Related Documents

- `docs/architecture/pipeline_contracts.md`
- `docs/architecture/module_architecture.md`
- `docs/architecture/market_observer_contract_v1.md`
- `docs/research/canonical_regime_context_source_v1.md`
- `docs/research/shadow_heartbeat_outcome_validation_v1.md`
