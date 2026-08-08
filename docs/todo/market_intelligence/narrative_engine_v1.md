# TODO — Narrative Engine v1

## GitHub Issue migration

Status: migrated

Operational status/priority is owned by GitHub Issues.

Section ownership:
- narrative taxonomy, Financial Infrastructure audit, narrative analytics, lifecycle -> Issue #307

Unmigrated executable scope:
- none

## Status

**future design / P3 research** — Synth has sector taxonomy and rotation analytics, but no separately owned, versioned narrative taxonomy or narrative-strength engine.

## Sources

- `docs/todo/market_intelligence/sector_rotation_master_plan_v1.md`
- `docs/archive/completed/sector_taxonomy_database_seed_v1.md`
- `docs/todo/market_intelligence/sector_rotation_engine_v1.md`
- `docs/architecture/external_research_overlay_contract_v1.md`
- FFG briefings supplied in chat on 2026-07-28 discussing RWA, tokenized equities, settlement rails, programmable collateral, ONDO, PENDLE, and RSR. These are narrative inputs, not canonical classifications by themselves.

## Current state / facts

Sector and narrative are related but not identical:

- a sector is a relatively stable functional classification;
- a narrative is a time-varying market theme that may span multiple sectors;
- one asset may participate in several narratives;
- narrative membership must not overwrite primary sector ownership.

Examples requiring separation include:

```text
RWA
Financial Infrastructure
Tokenization
Stablecoin Infrastructure
Institutional DeFi
AI
DePIN
Privacy
Gaming
Payments
```

## Open tasks by priority

### P1 — Narrative taxonomy contract

Define a versioned taxonomy with point-in-time memberships and explicit relationships to canonical sectors and clusters.

Candidate initial narratives:

```text
RWA
TOKENIZED_EQUITIES
FINANCIAL_INFRASTRUCTURE
SETTLEMENT_RAILS
PROGRAMMABLE_COLLATERAL
STABLECOIN_INFRASTRUCTURE
INSTITUTIONAL_DEFI
YIELD_MARKETS
AI
AI_COMPUTE
DEPIN
L1_ROTATION
L2_ROTATION
PAYMENTS
PRIVACY
GAMING
MEMES
```

Names and scope remain candidates until reviewed against existing taxonomy to prevent duplication.

### P1 — Financial Infrastructure classification audit

Audit whether the existing sector/cluster taxonomy already represents the following distinctions adequately:

```text
Tokenization
Settlement
Stable Assets
Treasury Infrastructure
Yield Markets
Governance / risk coordination
```

Review candidate assets without precommitting classification:

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

For each candidate, record:

```text
primary_sector
secondary_clusters
narrative_memberships
membership_confidence
valid_from_utc
source_evidence
review_decision
```

RSR should be evaluated for governance/risk coordination, DTF infrastructure, RWA adjacency, and stable-asset infrastructure. Do not classify it as a world currency based on project ambition or external commentary.

### P1 — Narrative analytics

Measure narrative strength using accepted market-only inputs:

- weighted and median return;
- positive/negative participation;
- relative strength versus BTC and ETH;
- volume share and change;
- member dispersion;
- persistence;
- coverage and liquidity quality;
- leader concentration and capped contribution.

Reuse shared primitives where appropriate, but do not silently duplicate or fork Sector Rotation Engine logic. Determine whether narrative analytics should be a parameterized consumer of common analytics primitives or a separate snapshot owner.

### P2 — Narrative lifecycle and evidence

Define states such as:

```text
EMERGING
BROADENING
LEADING
MATURE
COOLING
FADING
NO_CONFIRMATION
INSUFFICIENT_PARTICIPATION
DATA_UNAVAILABLE
```

Require evidence for state transitions and preserve point-in-time membership. External articles may create a research candidate but cannot by themselves assign `EMERGING` or `LEADING`.

### P2 — Fundamental monitoring references

For thesis monitoring, define references to separately owned fundamental time series rather than embedding them in narrative scoring. Candidate examples:

- DTF adoption and protocol fees;
- RSR burn activity and staking participation;
- ONDO tokenized-asset adoption and fee-switch status;
- PENDLE protocol revenue and integration growth;
- tokenized-equity holder counts;
- stablecoin and RWA market growth.

Each metric requires a primary source, provenance, timestamp, and point-in-time history. No unsourced briefing number becomes canonical data.

### P3 — Reporting and optional selection research

Expose narrative badges, participation, confidence, history, and member contribution as read-only reporting.

Any future `selection_engine` use must consume a reviewed market-only snapshot. Narratives may influence candidate ranking only after replay validation and must never bypass `decision_gate`.

## Blockers / dependencies

- Taxonomy overlap audit.
- Accepted sector snapshots and shared analytics primitives.
- Point-in-time membership model.
- Primary-source fundamental data design.
- Clear ownership split between sector, narrative, catalyst, macro, and external research overlays.

## Boundary

```text
Owner: research analytics / taxonomy
Mode: research-only, market-only, account-agnostic
DB writes: deterministic taxonomy and analytics snapshots only after review
Broker writes: 0
Order submissions: 0
Execution impact: none
```

No live trading. No broker writes. No order submission. No `decision_gate` bypass. No `execution_planner` bypass. No executor shortcut.

## Non-goals

- Rebranding sectors based on current social-media attention.
- Treating FFG or other external conviction as measured market participation.
- Storing catalyst status in narrative memberships.
- Direct account allocation, sizing, planning, or execution.
