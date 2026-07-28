# Sector Rotation Initiative v1

## Status

Phase A is accepted and operationally activated from merged main `794a03e014c44b5f01410a07bc5f24aa763715a8`.

Phase B repository implementation is complete for review. Migration application and persisted snapshot acceptance remain separate post-merge actions.

Phase B2 is a short research audit that may run after accepted Phase B snapshots. Phase C is the reporting lane. Phase D has not started.

Macro regime, composite market regime, catalyst, and narrative research are separate future-design lanes. They do not expand Phase B authority or change the current cross-lane execution order.

## Goal

Build a research-only sector intelligence layer above individual asset analysis so Synth can distinguish isolated asset moves from broader sector participation and rotation.

## Roadmap

```text
A. Sector Taxonomy & Database Seed v1
        ↓
B. Sector Rotation Engine v1
        ↓
C. Sector Rotation Dashboard v1
        ↓
D. Optional Sector Context Integration v1
```

Adjacent market-intelligence owners:

```text
docs/todo/market_intelligence/macro_regime_engine_v1.md
docs/todo/market_intelligence/composite_market_regime_v1.md
docs/todo/market_intelligence/catalyst_engine_v1.md
docs/todo/market_intelligence/narrative_engine_v1.md
```

## Dependency boundaries

- The composite regime may consume only accepted macro, BTC structure, breadth, sector-rotation, and separately typed measured-flow snapshots.
- Catalyst metadata and narrative analytics remain separate from macro and sector state.
- External research may create candidates but cannot assign canonical market state.
- Narrative membership must not overwrite primary sector ownership.
- Catalyst state must not become a hidden trade trigger.

## Existing hooks

- `asset.sector` exists as global asset metadata.
- `asset_profile_snapshot.sector_group_code` and `sector_confidence` exist.
- Asset Profile v1 intentionally leaves sector clustering unresolved; this initiative owns that deferred work.

## Hard boundaries

- Research/reporting only through phases A–C.
- No `selection_engine`, `decision_gate`, `execution_planner`, executor, agent, broker, or order-path behavior changes.
- Database writes are limited to deterministic taxonomy imports and accepted analytics snapshots.
- Proxy flow labels must never be presented as measured capital flow.

## Initial sector coverage

At minimum:

```text
DeFi Lending
DeFi Yield
RWA
RWA Infrastructure
AI / Decentralized Intelligence
AI Compute / DePIN
L1
L2
Perpetual DEX
Oracle / Interoperability
Payments
Gaming
Stablecoin Infrastructure
```

## Financial Infrastructure audit

Audit whether the existing taxonomy adequately represents:

```text
Tokenization
Settlement
Stable Assets
Treasury Infrastructure
Yield Markets
Governance / risk coordination
```

Candidate assets for classification review, without predetermined membership:

```text
ONDO
RSR
PENDLE
XRP
XLM
HBAR
QNT
XDC
ALGO
```

RSR must be evaluated from actual protocol roles such as governance, risk coordination, DTF infrastructure, first-loss staking, and RWA/stable-asset adjacency. Project ambition is not classification evidence.

## Phase B2 — Market-filter candidate audit

Status: open after accepted Phase B snapshots.

Evaluate only whether these market-only candidates add independent sector information:

- realized-volatility normalization;
- member-level range compression or expansion;
- listing age and historical-data age as eligibility/confidence inputs;
- spread, precision, and tradability only where aggregate sector value is demonstrated.

Every candidate must record:

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

Random shuffle is rejected. Trade-performance ranking remains account-aware and outside this lane. No Freqtrade runtime, plugin framework, or copied implementation is introduced.

## Completion rule

Each phase requires separate review and acceptance. Phase D must not start until phases A–C produce stable, reproducible, explainable outputs. Adjacent market-intelligence lanes require their own contracts and acceptance; this master plan grants none of them downstream authority.
