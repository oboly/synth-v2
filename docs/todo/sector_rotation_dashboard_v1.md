# Sector Rotation Dashboard v1

## Status

**Phase C1 implemented / ready for review** — Phase A taxonomy data and the
Phase B migration plus persisted analytics snapshots are accepted (venue
`bitvavo`, `model_version=sector-rotation-v1.0.0`,
`asof_ts_utc=2026-07-16 18:00:00 UTC`, 116 rows, 29 sectors, windows
1h/4h/1d/7d). Phase C1 delivers a bounded, read-only Sector Overview
publisher backed exclusively by that accepted cohort:

```text
src/reporting/sector_rotation_dashboard_v1.py
src/reporting/run_sector_rotation_dashboard_v1.py
tests/test_sector_rotation_dashboard_v1.py
```

Phase C1 selects one internally coherent cohort (one venue, one model
version, one as-of timestamp, all four required windows), renders static
JSON and HTML from a single assembled view model, and fails closed on a
missing cohort, missing sector/window evidence, or a stale cohort. It does
not recompute scores, states, confidence, participation, or evidence.

Asset cards, member/rank tables, sector drilldown, rotation history, filters,
and account-aware overlays remain open and are not implemented by Phase C1.

Runtime preparation for the publisher side of the writer→publisher chain is
tracked in `docs/ops/sector_rotation_runtime_activation_v1.md`:
**runtime artifacts prepared — not installed — not enabled — not
production-accepted.** No claim of live activation is made or implied.
No systemd timer or production deployment was added; this phase is a
runner-invoked publisher only.

Macro, composite-regime, catalyst, and narrative views are future read-only
extensions owned by separate TODO lanes. They do not expand the Phase C1
scope or unblock it.

## Purpose

Expose sector taxonomy, cluster membership, sector scores, participation, and rotation history in the Synth GUI without implying that price/volume proxies are measured capital flows.

This phase depends on:

- `sector_taxonomy_database_seed_v1.md`;
- `sector_rotation_engine_v1.md`.

Future extensions depend on:

- `macro_regime_engine_v1.md`;
- `composite_market_regime_v1.md`;
- `catalyst_engine_v1.md`;
- `narrative_engine_v1.md`.

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

## Future macro overview

Blocked until accepted Macro Regime Engine snapshots exist. Candidate display:

```text
DXY        USD_EXHAUSTION       confidence 0.71
SOX        SEMI_OVERHEATED      confidence 0.83
NASDAQ     EQUITY_CORRECTION    confidence 0.66
GOLD       METALS_BOTTOMING     confidence 0.58
OIL        OIL_INFLATION_PRESSURE confidence 0.79
BTC        CAPITULATION_RISK
ALTS       NARROW
```

Requirements:

- show exact series, provider, timeframe, as-of, and freshness;
- never display a forecast as measured current state;
- never substitute zero for unavailable data;
- distinguish public measured flows from price/volume proxies.

## Future composite market regime

Blocked until accepted macro, BTC structure, breadth, and sector snapshots exist.

Example presentation only:

```text
Composite market regime:
BTC_BOTTOMING / SECTOR_SELECTIVE_ROTATION
```

The dashboard displays an accepted persisted composite snapshot. It must not
calculate or override composite state in the browser or reporting controller.

## Future narrative and catalyst context

Blocked on their separate canonical lanes.

Asset cards may eventually show:

- point-in-time narrative badges;
- narrative strength and participation;
- confirmed upcoming catalyst badges;
- event status, source, scheduled time, and verification state;
- completed, cancelled, expired, disputed, and stale events.

The UI must distinguish:

```text
stable sector classification
current narrative membership
confirmed catalyst metadata
external research assertion
```

A price target is not a catalyst. An external briefing is not confirmation.

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

Future filters after separate acceptance:

- macro regime state;
- composite market regime;
- narrative membership and state;
- catalyst type, status, verification, and date window.

## Failure and stale behavior

- Missing sector metadata: `UNCLASSIFIED`.
- Missing analytics snapshot: `DATA_UNAVAILABLE`.
- Low participation: `INSUFFICIENT_PARTICIPATION`.
- Stale snapshot: show age and `STALE` prominently.
- Never fall back to a previous score without visibly marking it stale.
- Never show zero as a substitute for unavailable data.
- Missing catalyst data means `DATA_UNAVAILABLE`, not `NO_UPCOMING_EVENTS`.
- Browser-side or cached data may never become canonical authority.

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

Future-extension acceptance remains in the owning macro, composite, catalyst, and narrative lanes and is not implied by completion of this dashboard phase.

## Layer and boundaries

```text
Owner: reporting / GUI
Depends on: taxonomy seed + rotation engine
DB writes: none, except existing expected reporting cache behavior if separately approved
Broker writes: 0
Order submissions: 0
Execution impact: none
```

Read-only display or untrusted user input only. No direct broker access. No authority derived from HTML/JSON presentation.
