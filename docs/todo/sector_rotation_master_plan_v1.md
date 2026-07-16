# Sector Rotation Initiative v1

## Status

Phase A repository implementation is complete for review. Migration and
transactional taxonomy import remain explicit post-merge actions. Phases B-D
have not started.

## Goal

Build a research-only sector intelligence layer above individual asset analysis so Synth can distinguish isolated coin moves from broader sector participation and rotation.

## Roadmap

A. Sector Taxonomy & Database Seed v1

B. Sector Rotation Engine v1

C. Sector Rotation Dashboard v1

D. Sector Context Integration v1 (future, research-only until separately accepted)

## Dependency order

```text
A. taxonomy + DB seed
        ↓
B. sector snapshots + rotation algorithm
        ↓
C. GUI + drilldown
        ↓
D. optional downstream context integration
```

## Existing hooks

- `asset.sector` already exists as global asset metadata.
- `asset_profile_snapshot.sector_group_code` and `sector_confidence` already exist.
- Asset Profile v1 intentionally leaves sector clustering null; this initiative completes that deferred line.

## Hard boundaries

- Research/reporting only through phases A-C.
- No `selection_engine` behavior changes.
- No `decision_gate` behavior changes.
- No `execution_planner` behavior changes.
- No executor or agent behavior changes.
- No broker writes or order submissions.
- Database writes are limited to deterministic taxonomy imports and expected analytics snapshots.
- Proxy flow labels must never be presented as measured capital flow.

## Flow terminology

Synth must distinguish:

- `MARKET_ACTIVITY_INFLOW_PROXY`
- `ROTATION_INFLOW_PROXY`
- `ROTATION_OUTFLOW_PROXY`
- `MEASURED_ONCHAIN_FLOW`
- `MEASURED_ETF_FLOW`
- `EXTERNAL_RESEARCH_FLOW`

Price/volume-derived proxies must remain visibly separate from measured public flows.

## Initial sector coverage

At minimum:

- DeFi Lending
- DeFi Yield
- RWA
- RWA Infrastructure
- AI / Decentralized Intelligence
- AI Compute / DePIN
- L1
- L2
- Perpetual DEX
- Oracle / Interoperability
- Payments
- Gaming
- Stablecoin Infrastructure

## Initial tracked examples

- AAVE, PENDLE, ENA
- ONDO, PLUME, LINK
- TAO, AKT, RENDER, CHIP
- POL
- HYPE, LIT
- NEAR, VET, DEEP

## Completion rule

Each phase is a separate reviewed PR. Phase D must not start until A-C have produced stable, reproducible, and explainable research outputs.
