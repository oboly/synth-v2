# Sector Rotation Dashboard v1

## Status

Phase A taxonomy data is accepted. This phase remains blocked on future Phase B
analytics snapshots. No GUI implementation has started.

## Purpose

Expose sector taxonomy, cluster membership, sector scores, participation, and rotation history in the Synth GUI without implying that price/volume proxies are measured capital flows.

This phase depends on:

- `sector_taxonomy_database_seed_v1.md`;
- `sector_rotation_engine_v1.md`.

## Primary views

### Sector overview bar

Show a compact summary such as:

```text
AI / Compute     82  ↑  LEADING
DeFi Yield       76  ↑  IMPROVING
RWA              61  →  NEUTRAL
Perp DEX         55  ↓  COOLING
L2               34  ↓  LAGGING
```

For every sector show:

- display name;
- rotation score;
- state;
- confidence;
- participation;
- volume confirmation;
- timeframe;
- last update timestamp;
- stale status.

### Asset cards and tables

Add:

- primary sector badge;
- secondary cluster badges;
- sector rank;
- sector contribution;
- relative strength versus sector;
- classification confidence where useful.

Example:

```text
PENDLE
Primary sector: DeFi Yield
Clusters: ETH Ecosystem, Restaking
Sector score: 76
Sector contribution: 0.91
Relative to sector: outperforming
```

### Sector drilldown

Show member-level score components:

| Coin | Weight | Return | RS vs BTC | Volume change | Momentum | Contribution |
|---|---:|---:|---:|---:|---|---:|
| PENDLE | 1.00 | +6.2% | +4.3% | +41% | Rising | 0.91 |
| AAVE | 0.80 | +3.8% | +1.9% | +22% | Rising | 0.77 |
| ENA | 0.65 | +1.0% | -0.8% | +8% | Neutral | 0.42 |

Also show:

- eligible versus total members;
- participation calculation;
- capped dominant-member contribution;
- score component breakdown;
- data coverage;
- benchmark comparison;
- model version.

## Rotation history

Provide a simple history/timeline, for example:

```text
08:00 AI / Compute leading
12:00 AI / Compute cooling
14:00 DeFi Yield improving
18:00 DeFi Yield leading
```

Do not state that money moved from one sector to another unless the engine produced a sufficiently confident rotation proxy. Prefer wording such as:

- `relative activity shifted toward DeFi Yield`;
- `AI / Compute leadership weakened`;
- `rotation proxy confirmed`.

## Flow type presentation

Visually distinguish:

### Price/volume-derived proxy

- `MARKET_ACTIVITY_INFLOW_PROXY`
- `ROTATION_INFLOW_PROXY`
- `ROTATION_OUTFLOW_PROXY`

### Measured public flow

- `MEASURED_ONCHAIN_FLOW`
- `MEASURED_ETF_FLOW`

### External narrative/research

- `EXTERNAL_RESEARCH_FLOW`

These must not share an indistinguishable badge, color meaning, or label.

## Filters

Support:

- primary sector;
- cluster;
- rotation state;
- confidence;
- timeframe;
- portfolio-only;
- research-universe-only;
- data freshness;
- measured-flow versus proxy-flow.

## Failure and stale behavior

- Missing sector metadata: `UNCLASSIFIED`.
- Missing analytics snapshot: `DATA_UNAVAILABLE`.
- Low participation: `INSUFFICIENT_PARTICIPATION`.
- Stale snapshot: show age and `STALE` prominently.
- Never fall back to a previous score without visibly marking it stale.
- Never show zero as a substitute for unavailable data.

## Acceptance

- Primary sector is visible on relevant asset cards and tables.
- Secondary cluster memberships are inspectable.
- Sector and cluster filtering work.
- Sector overview uses real snapshot data.
- Drilldown explains every score component.
- Proxy and measured flows are visibly distinct.
- Stale and unavailable states fail closed.
- Rotation history is timeframe-aware.
- GUI changes do not mutate asset eligibility, portfolio membership, or trading state.
- No broker writes or order submissions.

## Layer and boundaries

```text
Owner: reporting / GUI
Depends on: taxonomy seed + rotation engine
DB writes: none, except existing expected reporting cache behavior if separately approved
Broker writes: 0
Order submissions: 0
Execution impact: none
```
