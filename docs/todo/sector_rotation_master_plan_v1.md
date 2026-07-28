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

Separate future-design lanes now own macro regime, composite market regime,
catalyst, and narrative research. They do not expand Phase B authority and do
not change the current cross-lane execution order.

## Goal

Build a research-only sector intelligence layer above individual asset analysis so Synth can distinguish isolated coin moves from broader sector participation and rotation.

## Roadmap

A. Sector Taxonomy & Database Seed v1

B. Sector Rotation Engine v1

C. Sector Rotation Dashboard v1

D. Sector Context Integration v1 (future, research-only until separately accepted)

Adjacent future-design lanes:

```text
Macro Regime Engine v1
Composite Market Regime v1
Catalyst Engine v1
Narrative Engine v1
```

Canonical TODO owners:

```text
docs/todo/macro_regime_engine_v1.md
docs/todo/composite_market_regime_v1.md
docs/todo/catalyst_engine_v1.md
docs/todo/narrative_engine_v1.md
```

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

Adjacent research sequence:

```text
accepted macro inputs + classifiers
              \
accepted BTC structure + breadth
                \
accepted sector rotation snapshots ---> composite market regime research
                /
accepted measured-flow overlays

catalyst metadata --------> read-only context
narrative taxonomy -------> read-only analytics
```

Catalyst and narrative lanes remain separate from macro and sector state. The
composite regime may consume only accepted market evidence; it must not consume
external conviction or unverified catalyst claims as market truth.

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
- Narrative membership must not overwrite primary sector ownership.
- Catalyst state must not become a hidden trade trigger.
- External research remains separately typed and cannot assign canonical market state.

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

## Financial Infrastructure audit

The existing taxonomy must be audited before adding another broad sector.
Candidate distinctions:

```text
Tokenization
Settlement
Stable Assets
Treasury Infrastructure
Yield Markets
Governance / risk coordination
```

Candidate assets for classification review, not predetermined membership:

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

RSR must be evaluated from its actual protocol roles, including governance,
risk coordination, DTF infrastructure, first-loss staking, and RWA/stable-asset
adjacency. Project ambition to become reserve-currency infrastructure is not a
classification fact.

## Initial tracked examples

- AAVE, PENDLE, ENA
- ONDO, PLUME, LINK
- TAO, AKT, RENDER, CHIP
- POL
- HYPE, LIT
- NEAR, VET, DEEP
- RSR as a taxonomy and research-universe candidate pending canonical asset and membership review

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
- Macro state, catalyst status, and narrative popularity are not Phase B score
  components.

## Completion rule

Each phase is a separate reviewed PR. Phase D must not start until A-C have produced stable, reproducible, and explainable research outputs. Adjacent future-design lanes require their own reviewed contracts and acceptance; this master plan grants none of them runtime or downstream authority.
