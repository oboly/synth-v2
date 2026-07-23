# Sector Rotation Initiative v1

## Status

Phase A is done / accepted and operationally activated from merged main
`794a03e014c44b5f01410a07bc5f24aa763715a8`. Its migration, first import,
post-write verification, and idempotent second import passed on 2026-07-16.
Phase B repository implementation is complete for review; its migration and
snapshot writes remain separate post-merge acceptance actions. Phase B2 is a
short, open research audit of a few market-filter ideas; it may run alongside
Phase C after persisted Phase B snapshots are accepted and must not reopen or
retune Phase B without evidence. Phase D has not started.

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

## Phase B2 — Market-filter candidate audit

Status: open / short research after accepted Phase B snapshots. This audit may
run alongside Phase C because it changes no dashboard or runtime behavior.

Purpose:

Determine whether a small set of market-only filter ideas adds genuine sector
rotation information or belongs elsewhere in Synth. Phase B remains the
accepted baseline; no v1 score, migration, or writer is changed by this audit.

Research questions:

- Test realized-volatility normalization as an explanatory sector feature, while
  avoiding duplicate information already present in dispersion and liquidity
  quality.
- Test member-level range compression/expansion as an aggregated participation
  or confirmation measure; do not blindly remove compressed assets before
  breakout analysis.
- Treat listing age and historical-data age as eligibility or confidence inputs,
  not as sector leadership.
- Keep spread, precision, and instrument tradability in market quality, asset
  profile, or selection eligibility unless evidence shows an aggregate sector
  metric adds independent value.
- Compare every candidate against the existing Phase B components and measure
  incremental stability, explanatory value, and replay-safe predictive value.
- Use point-in-time inputs and the future
  `backtest_capability_contract_v1.md`; no current/latest profile joins in
  historical evaluation.

Required output:

```text
candidate
source_inputs
point_in_time_availability
existing_metric_overlap
sector_level_hypothesis
validation_method
decision
```

Allowed decisions:

```text
ADOPT_AS_SECTOR_FEATURE
ADOPT_AS_ELIGIBILITY_OR_CONFIDENCE
KEEP_IN_OTHER_LAYER
REJECT
```

Explicit exclusions:

- Trade-performance ranking is account-aware and belongs only in a future
  decision-gate protection/permission design.
- Random shuffle is non-deterministic and is rejected.
- No Freqtrade code copy, plugin framework, dependency, or second runtime.
- No implementation starts until this short audit is reviewed.

## Completion rule

Each phase is a separate reviewed PR. Phase D must not start until A-C have produced stable, reproducible, and explainable research outputs.
