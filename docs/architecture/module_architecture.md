# Synth — Module Architecture

## Purpose

This document records the module inventory, ownership, and implementation posture for Synth v2.

Modules may be unimplemented, but they must never be undefined. Design establishes boundaries first; implementation follows in bounded phases.

`docs/architecture/pipeline_contracts.md` remains authoritative for import direction and execution boundaries.

## Core Principle

Design for the complete system without letting a future module bypass the current architecture.

Every module must declare:

- purpose
- inputs
- outputs
- layer
- dependencies
- forbidden dependencies
- status
- canonical documentation
- validation path before runtime promotion

## Module Layers

| Layer | Meaning |
|---|---|
| OBSERVATION | Captures raw, timestamped market or external-source facts with provenance. |
| FEATURE | Produces deterministic, narrow measurements from observation data. |
| INTERPRETATION | Produces market-only descriptive states from features and canonical context. |
| PROJECTION | Holds bounded research hypotheses or scenario context; never execution instruction. |
| SELECTION | Ranks/classifies market-only candidates after validated feature promotion. |
| PERMISSION | Applies account-aware constraints in `decision_gate`. |
| EXECUTION | Produces and handles execution intent/orders only. |

## Required and Planned Modules

| Module | Layer | Status | Responsibility |
|---|---|---|---|
| `market_data` | OBSERVATION | implemented | Candles, ticker price, volume, symbol normalization, freshness. |
| `local_ma_atr_context` | FEATURE | implemented / evolving | Per-symbol EMA/MA position measured in ATR context. |
| `impulse_health_state` | INTERPRETATION | implemented / evolving | Per-symbol impulse phase and cooling/distribution risk. |
| `fib_navigation_map` | INTERPRETATION | implemented / evolving | Structural zones, map lifecycle, and confidence. |
| `active_regime_observation` | INTERPRETATION | implemented | Canonical market-wide and asset-class regime source. |
| `market_observer_v1` | INTERPRETATION | planned_docs_only | Market-wide aggregate of measured context, symbol context, sector/breadth context, and external-overlay references. |
| `sector_snapshot_v1` | FEATURE | planned | Sector return, breadth, volume, persistence, leader/laggard measurement. |
| `sector_rotation_state_v1` | INTERPRETATION | planned | Descriptive sector leadership and rotation state from measured sector snapshots. |
| `alt_market_phase_detector` | INTERPRETATION | planned_future | Market participation/phase classifier; must reuse canonical regime rather than replace it. |
| `wave_rotation_classifier` | INTERPRETATION | planned_future | Descriptive sequence/rotation classifier, not an order engine. |
| `breathline_feat` | PROJECTION / context | research-only | Universal market-cycle context; separate from local technical sensors. |
| `thesis_bias` | PROJECTION | research-only | Explicit, inspectable scenario hypothesis; never a hidden selection weight. |
| `trend_volume_classifier` | INTERPRETATION | planned_future | Market-only trend and participation classification. |

## Market Observer Ownership

`market_observer_v1` belongs under `src/market_context/` when implemented.

It may read:

- deterministic market features
- `MarketNavigationState`
- canonical active-regime observations
- future sector/breadth snapshots
- registered external research overlays

It may emit:

- `MarketObserverSnapshot`
- descriptive rotation, BTC-structure, ETH-relative-strength, breadth, sector, and per-symbol context
- explicit freshness, confidence, warnings, and evidence references

It may not emit:

- trade permission
- account allocation
- order intent
- execution plans
- broker actions
- unproven scoring bonuses

`agent` is not the correct ownership name. In Synth, executor/agent namespaces are reserved for order handling and must not contain market-observation logic.

## External Research Overlay Ownership

External research is an OBSERVATION/PROJECTION overlay, not a market-data replacement.

A future overlay adapter may ingest structured records into a research-only store. It must preserve:

- original source content and time
- venue/pair/timeframe when known
- source currency and separate FX conversion
- source-confidence prior
- independent verification status
- expiry/freshness
- map and anchor provenance

External overlay belongs adjacent to market observation. It does not belong in `selection_engine`, `decision_gate`, `execution_planner`, or executor modules.

## Sector and Breadth Ownership

Sector/breadth work is measurement first.

```text
asset returns and volume
  -> sector snapshot
  -> sector breadth / leader / persistence features
  -> sector rotation state
  -> market observer context
  -> shadow outcome validation
  -> possible future selection promotion
```

No direct score weight may be added to `selection_engine` before the feature has a documented definition, baseline, horizon, sample policy, and out-of-sample outcome evidence.

## Dependency Rules

Allowed high-level dependency direction:

```text
market_data
  -> observation / features
  -> interpretation / market_context
  -> selection_engine
  -> decision_gate
  -> execution_planner
  -> executor / broker
```

Forbidden shortcuts:

```text
market_observer      -> decision_gate permission
market_observer      -> execution intent
external overlay     -> direct selection bonus
sector rotation      -> direct order
thesis_bias          -> account allocation
executor / agent     -> market-context calculation
```

## Implementation Model

### Phase 1 — deterministic foundations

- market data
- base technical features
- navigation state
- canonical regime observations

### Phase 2 — structural market context

- fib map lifecycle
- zones and invalidation state
- local trend/impulse context
- market observer contract and deterministic snapshot inputs

### Phase 3 — breadth and cross-market interpretation

- sector snapshots
- BTC/ETH relative context
- breadth and participation measurements
- research-only observer snapshot writer
- shadow validation

### Phase 4 — evidence-led promotion

- preregistered validation studies
- explicit feature promotion proposals
- limited selection-engine integration only where evidence survives review

### Phase 5 — optimization / ML

- only after the deterministic feature inventory and validation dataset are mature
- no hidden-state replacement for transparent market context

## Related Documents

- `docs/architecture/pipeline_contracts.md`
- `docs/architecture/market_observer_contract_v1.md`
- `docs/architecture/external_research_overlay_contract_v1.md`
- `docs/architecture/breath_fibo_synth_framework_contract_v1.md`
- `docs/research/canonical_regime_context_source_v1.md`
- `docs/research/sector_module_design.md`
