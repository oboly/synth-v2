# TODO — Catalyst Engine v1

## Status

**future design / P3 research** — no canonical catalyst ingestion, normalization, calendar, confidence model, persistence, or downstream integration exists.

## Sources

- `docs/architecture/external_research_overlay_contract_v1.md`
- `docs/architecture/market_observer_contract_v1.md`
- `docs/todo/market_intelligence/sector_rotation_master_plan_v1.md`
- FFG briefings supplied in chat on 2026-07-28 covering ONDO fee-switch discussion, regulatory milestones, protocol burns, governance, and tokenized-asset adoption. These are external research inputs, not canonical facts until independently sourced.

## Current state / facts

Potentially material events are currently handled as scattered narrative context. Synth has no canonical distinction between:

```text
confirmed scheduled event
confirmed unscheduled proposal
rumor or third-party commentary
completed event
cancelled or expired event
```

A catalyst engine may improve context and research, but it must never become a hidden trade trigger.

## Open tasks by priority

### P1 — Catalyst taxonomy

Define a versioned taxonomy covering at least:

```text
GOVERNANCE_PROPOSAL
GOVERNANCE_VOTE
FEE_SWITCH
TOKEN_UNLOCK
TOKEN_BURN
MAINNET_LAUNCH
PROTOCOL_UPGRADE
ETF_FILING
ETF_DECISION
REGULATORY_MILESTONE
PARTNERSHIP
INTEGRATION
LISTING
DELISTING
EMISSIONS_CHANGE
STAKING_CHANGE
TREASURY_CHANGE
SECURITY_INCIDENT
EXPLOIT_REMEDIATION
```

Keep scheduled events separate from measured protocol fundamentals such as recurring fees, burns, TVL, active users, or supply.

### P1 — Canonical event contract

Define fields including:

```text
event_id
asset_code
protocol_code
catalyst_type
event_status
announced_ts_utc
scheduled_ts_utc
completed_ts_utc
source_type
source_uri_or_reference
source_publisher
verification_state
confidence
materiality_class
asof_ts_utc
freshness_state
model_version
notes
```

Required statuses:

```text
RUMORED
PROPOSED
CONFIRMED
SCHEDULED
IN_PROGRESS
COMPLETED
CANCELLED
EXPIRED
DISPUTED
DATA_UNAVAILABLE
```

### P1 — Source and verification rules

- Prefer protocol, issuer, regulator, exchange, repository, or governance primary sources.
- Preserve external-research claims separately as `EXTERNAL_RESEARCH`.
- Require independent confirmation before promoting an external claim to `CONFIRMED`.
- Record source timestamp and retrieval/as-of timestamp.
- Never convert an estimated date into an exact scheduled date.
- Never treat a price target as a catalyst.

### P2 — Catalyst calendar and monitoring

Create a replay-safe read model for:

- upcoming confirmed catalysts;
- completed catalysts;
- overdue or expired proposals;
- event status changes;
- source freshness;
- asset and sector filters.

Initial monitored examples may include:

- ONDO fee-switch proposal or vote;
- protocol governance votes;
- token unlocks and emissions changes;
- ETF/regulatory milestones;
- mainnet and protocol upgrades;
- Reserve/RSR burn publications;
- security incidents and remediation milestones.

Examples are monitoring candidates only, not accepted facts or priorities.

### P2 — Research validation

Evaluate whether catalyst state adds information beyond price, volume, and sector rotation:

- pre-event and post-event return distribution;
- volatility and liquidity changes;
- event postponement and cancellation effects;
- rumor versus confirmed-event reliability;
- source-specific false-positive rates;
- survivorship and look-ahead controls.

### P3 — Read-only integration

Expose catalyst badges and calendar entries in reporting. Any future `selection_engine` consumption requires a separate reviewed market-only feature contract. `decision_gate`, `execution_planner`, executor, and broker paths remain untouched.

## Blockers / dependencies

- Primary-source connector/provider design.
- Source licensing and retention rules.
- Canonical asset/protocol identity mapping.
- Point-in-time event history.
- External research overlay contract acceptance.

## Boundary

```text
Owner: external research overlay / market metadata research
Mode: research-only, market-only, account-agnostic
DB writes: normalized catalyst metadata only after separate review
Broker writes: 0
Order submissions: 0
Execution impact: none
```

No live trading. No broker writes. No order submission. No `decision_gate` bypass. No `execution_planner` bypass. No executor shortcut.

## Non-goals

- Automatic buying before an event.
- Treating rumors, influencer claims, or price targets as confirmed catalysts.
- Owning fundamental time series such as fees, TVL, burns, or active users.
- Replacing sector or macro regime measurement.
