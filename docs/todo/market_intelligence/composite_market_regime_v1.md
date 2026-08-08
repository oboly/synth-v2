# TODO — Composite Market Regime v1

## GitHub Issue migration

Status: migrated

Operational status/priority is owned by GitHub Issues.

Section ownership:
- composite contract, state vocabulary, combination rules, replay validation -> Issue #301

Unmigrated executable scope:
- none

## Status

**future design / P3 research** — no composite classifier, persistence, runtime owner, dashboard authority, or downstream selection integration is implemented.

## Sources

- `docs/architecture/market_observer_contract_v1.md`
- `docs/todo/market_intelligence/macro_regime_engine_v1.md`
- `docs/todo/market_intelligence/sector_rotation_master_plan_v1.md`
- `docs/todo/market_intelligence/sector_rotation_engine_v1.md`
- `docs/todo/backtest_capability_contract_v1.md`

## Current state / facts

Synth has or is building independent market-only evidence layers, but no accepted owner currently combines them into one canonical cross-market state.

Candidate upstream evidence owners:

```text
Macro Regime Engine
BTC structure
ETH/BTC leadership
alt breadth
Sector Rotation Engine
measured ETF/on-chain flow overlays
```

The composite layer must consume accepted upstream snapshots. It must not duplicate their calculations or reach into account, portfolio, decision, planning, or execution state.

## Open tasks by priority

### P1 — Contract and ownership

Define a frozen, versioned, account-agnostic composite contract containing:

```text
asof_ts_utc
venue_scope
macro_regime_ref
btc_structure_ref
breadth_ref
sector_rotation_ref
measured_flow_refs
composite_state
confidence
freshness_state
component_explanations
model_version
```

Specify exact join and temporal-consistency rules. Never join a current macro row to a historical crypto row or silently reuse an older component.

### P1 — State vocabulary

Preregister a minimal vocabulary, initially considering:

```text
RISK_OFF_CAPITULATION
RISK_OFF_STABILIZING
BTC_BOTTOMING
BTC_LED_RECOVERY
ETH_ROTATION
SECTOR_SELECTIVE_ROTATION
BROAD_ALT_EXPANSION
LATE_CYCLE_EXHAUSTION
NO_CONFIRMATION
DATA_UNAVAILABLE
```

Names are candidates until reviewed. Every state must have deterministic evidence requirements and explicit conflicting-signal behavior.

### P1 — Combination rules

- Preserve each upstream component and its confidence.
- Define minimum coverage and freshness requirements.
- Fail closed when required inputs disagree in time or are unavailable.
- Prevent a single sector or asset spike from producing broad-alt expansion.
- Keep price/volume rotation proxies separate from measured ETF or on-chain flows.
- Do not use narrative or catalyst assertions as substitutes for market evidence.
- Store the exact rule path that produced each state.

### P2 — Replay and validation

Validate against historical scenarios including:

1. Equity and semiconductor correction while crypto remains weak.
2. BTC capitulation followed by stabilization without alt participation.
3. BTC-led recovery with ETH/BTC still weak.
4. ETH leadership followed by sector-selective rotation.
5. Broad alt expansion with rising participation and volume confirmation.
6. One-sector spike without broad market confirmation.
7. Conflicting macro and crypto signals.
8. Stale or unavailable cross-asset inputs.

Measure:

- transition persistence;
- false state changes;
- subsequent market behavior for research only;
- incremental value over upstream components;
- whether the composite merely restates BTC returns.

### P3 — Optional downstream context research

Only after upstream acceptance and replay validation, investigate whether `selection_engine` may consume the composite as one market-only context input.

Required architecture:

```text
market data / observers
        ↓
composite market regime
        ↓
selection_engine
        ↓
decision_gate
        ↓
execution_planner
        ↓
executor / agents
```

The composite layer must never grant account permission, determine quantity, create execution intent, or submit orders.

## Blockers / dependencies

- Accepted Macro Regime Engine inputs and states.
- Accepted persisted Sector Rotation Engine snapshots.
- Canonical BTC structure and alt breadth primitives.
- Temporal join and freshness contract.
- Replay-capability preflight.

## Boundary

```text
Owner: market observer / research analytics
Mode: research-only, market-only, account-agnostic
DB writes: deterministic composite analytics snapshots only after review
Broker writes: 0
Order submissions: 0
Execution impact: none
```

No live trading. No broker writes. No order submission. No `decision_gate` bypass. No `execution_planner` bypass. No executor shortcut.

## Non-goals

- A direct trade signal.
- Account-aware risk permission.
- Position sizing.
- Recomputing sector, macro, breadth, or flow evidence inside the composite layer.
- Presenting external research conviction as a canonical regime state.
