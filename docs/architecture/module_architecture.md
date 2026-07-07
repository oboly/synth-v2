# Synth — Module Architecture

## Purpose

Module inventory, ownership, and implementation posture for Synth v2.

Modules may be unimplemented, but they must never be undefined. `pipeline_contracts.md` remains authoritative for import direction and execution boundaries.

Every module declares purpose, inputs, outputs, layer, dependencies, forbidden dependencies, status, canonical documentation, and validation path before runtime promotion.

## Canonical Module Statuses

| Status | Meaning |
|---|---|
| `IMPLEMENTED` | Exists in maintained runtime/research code with an owned contract. |
| `IMPLEMENTED_EVOLVING` | Exists, but its bounded contract or implementation is still under active revision. |
| `DOCS_ONLY` | A contract/design exists; no implementation is implied. |
| `PLANNED` | Required next-stage module; no implementation exists yet. |
| `RESEARCH_ONLY` | May exist only in research/shadow context and cannot affect selection, permission, planning, or execution. |
| `PLANNED_FUTURE` | Recognized architecture component, deliberately not scheduled for the next implementation stage. |
| `DEPRECATED` | Retained only for migration/history; no new use permitted. |

No alternate status strings may be introduced without updating this table.

## Module Layers

| Layer | Meaning |
|---|---|
| OBSERVATION | Raw, timestamped market or external-source facts with provenance. |
| FEATURE | Deterministic narrow measurements from observation. |
| INTERPRETATION | Market-only descriptive states from features and canonical context. |
| PROJECTION | Bounded research hypotheses/scenario context; never execution instruction. |
| SELECTION | Market-only candidate ranking and strategy-state interpretation after validated promotion. |
| PERMISSION | Account-aware constraints in `decision_gate`. |
| EXECUTION | Execution-plan and order handling only. |

## Required and Planned Modules

| Module | Layer | Status | Responsibility |
|---|---|---|---|
| `market_data` | OBSERVATION | `IMPLEMENTED` | Candles, ticker price, volume, normalization, freshness. |
| `local_ma_atr_context` | FEATURE | `IMPLEMENTED_EVOLVING` | Per-symbol MA position measured in ATR context. |
| `impulse_health_state` | INTERPRETATION | `IMPLEMENTED_EVOLVING` | Per-symbol impulse/cooling/distribution condition. |
| `fib_navigation_map` | INTERPRETATION | `IMPLEMENTED_EVOLVING` | Structural zones, map lifecycle, confidence. |
| `active_regime_observation` | INTERPRETATION | `IMPLEMENTED` | Canonical market-wide/asset-class regime source. |
| `market_observer_v1` | INTERPRETATION | `DOCS_ONLY` | Cross-market aggregate of measured context and provenance-tagged overlays. |
| `sector_snapshot_v1` | FEATURE | `PLANNED` | Sector return, breadth, volume, persistence, leader/laggard measurement. |
| `sector_rotation_state_v1` | INTERPRETATION | `PLANNED` | Descriptive sector leadership/rotation from measured snapshots. |
| `alt_market_phase_detector` | INTERPRETATION | `PLANNED_FUTURE` | Participation/phase classifier that reuses canonical regime. |
| `wave_rotation_classifier` | INTERPRETATION | `PLANNED_FUTURE` | Descriptive sequence/rotation classifier, not an order engine. |
| `universal_breathline_context` | PROJECTION | `RESEARCH_ONLY` | Market-cycle context, separate from local technical sensors. |
| `breathline_feat` | — | `DEPRECATED` | Legacy planning name. Do not use for a context/projection module; it falsely implies a measurable local feature. |
| `thesis_bias` | PROJECTION | `RESEARCH_ONLY` | Inspectable scenario hypothesis, never hidden selection weight. |
| `trend_volume_classifier` | INTERPRETATION | `PLANNED_FUTURE` | Market-only trend and participation classifier. |

## Market Observer Ownership

`market_observer_v1` belongs under `src/market_context/` when implemented.

It may read deterministic features, `MarketNavigationState`, canonical regime observations, future sector/breadth snapshots, and registered external overlays.

It may emit `MarketObserverSnapshot`, descriptive BTC/ETH/breadth/sector/symbol context, freshness, confidence, warnings, and evidence references.

It may not emit permission, account allocation, execution intent/plans, broker actions, or unproven scoring bonuses.

`agent` is not the ownership name: executor/agent namespaces remain reserved for order handling.

## External Research Overlay Ownership

External research is an OBSERVATION/PROJECTION overlay, not a market-data replacement. A future adapter preserves original source/time, venue/pair/timeframe when known, source currency and FX conversion, source-confidence prior, independent verification, freshness/expiry, and map/anchor provenance.

It does not belong in selection, decision gate, execution planner, executor, or broker modules.

## Sector and Breadth Ownership

```text
asset returns and volume
  -> sector snapshot
  -> sector breadth / leader / persistence features
  -> sector rotation state
  -> market observer context
  -> shadow outcome validation
  -> possible future selection promotion
```

No direct score weight enters `selection_engine` before documented definition, baseline, horizon, sample policy, and out-of-sample outcome evidence.

## Dependency Rules

```text
market_data
  -> observation / features
  -> interpretation / market_context
  -> selection_engine
       -> Strategy State
  -> decision_gate
  -> execution_planner
  -> executor / broker
```

Forbidden shortcuts:

```text
market_observer      -> account state, decision permission, execution intent
external overlay     -> direct selection bonus
sector rotation      -> direct order
thesis_bias          -> account allocation
executor / agent     -> market-context calculation
runtime module       -> src.research import for shared contracts
```

## Implementation Model

### Phase 1 — deterministic foundations

- market data
- base technical features
- navigation state
- canonical regime observations

### Phase 2 — structural market context

- fib map lifecycle
- zones/invalidation state
- local trend/impulse context
- observer contract and deterministic inputs

### Phase 3 — breadth and cross-market interpretation

- sector snapshots
- BTC/ETH relative context
- breadth/participation measurements
- research-only observer writer
- shadow validation

### Phase 4 — evidence-led promotion

- preregistered validation studies
- explicit promotion proposals
- limited selection integration only where evidence survives review

### Phase 5 — optimization / ML

Only after deterministic feature inventory and validation data mature. No hidden-state replacement for transparent market context.

## Related Documents

- `docs/architecture/pipeline_contracts.md`
- `docs/architecture/market_observer_contract_v1.md`
- `docs/architecture/external_research_overlay_contract_v1.md`
- `docs/architecture/breath_fibo_synth_framework_contract_v1.md`
- `docs/research/canonical_regime_context_source_v1.md`
- `docs/research/sector_module_design.md`
