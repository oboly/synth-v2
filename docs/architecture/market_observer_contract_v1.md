# Market Observer Contract v1

## Status

Design contract only. No runtime module, database schema, dashboard output, selection behavior, decision-gate behavior, execution-plan behavior, broker call, or order behavior is introduced by this document.

## Purpose

`market_observer` is the market-only aggregation layer that turns already-owned observations into one explainable market snapshot.

It is the place for the cross-market reasoning that is currently done manually:

- BTC structure and range stability
- ETH relative strength
- ETH/BTC and BTC-dominance context
- alt breadth and participation
- sector leadership and rotation
- per-symbol structural context
- external research overlays with explicit provenance

It does not decide whether an account may trade. It does not create an order plan. It does not submit or cancel orders.

## Placement

`market_observer` belongs inside `market_context` as a market-only aggregate/read model.

```text
market_data
  -> market_context / features
       -> MarketNavigationState
       -> canonical active-regime observation
       -> future sector/breadth observations
       -> market_observer
  -> selection_engine
  -> decision_gate
  -> execution_planner
  -> executor / broker
```

`executor / agents` remains reserved for order handling. A market observer must never be implemented under `src/executor/`, `src/execution/`, or an order-handling agent namespace.

## Hard Boundaries

`market_observer` may:

- read public market data and deterministic market-context features
- read canonical regime observations without redefining them
- read symbol-level `MarketNavigationState` values
- read future sector and breadth observations
- attach external research as explicitly non-canonical overlays
- emit descriptive state, freshness, confidence, warnings, and evidence references
- write research-only artifacts in a future shadow implementation

`market_observer` must not:

- read account balances, positions, sleeves, open orders, or account tables
- grant or deny trade permission
- produce `BUY`, `SELL`, allocation, sizing, stop, target, or order labels
- create execution intent or an execution plan
- import decision-gate, execution-planner, executor, broker, or account modules
- silently convert an external source claim into measured market truth
- replace the canonical `active_regime_observation` source
- apply hidden score weights or hidden policy thresholds

## Input Channels

### 1. Measured Market Context

Measured context is deterministic, market-only, timestamped, and sourced from canonical or explicitly versioned feature builders.

Expected inputs include:

- canonical global and asset-class regime observations
- BTC range, breakout, breakdown-risk, and volatility observations
- ETH relative-strength observations
- breadth and participation observations
- sector snapshots and sector-leadership observations when implemented
- symbol-level `MarketNavigationState`
- fib-map state and confidence, not undocumented manually inferred levels
- local MA/ATR, impulse-health, timing, freshness, and warning states

### 2. External Research Overlay

External overlay inputs may include:

- FFG money-flow snapshots
- source charts and externally supplied fib maps
- catalyst/news events
- manually extracted support, retest, target, and invalidation zones
- source-specific narrative classifications

Every overlay item must carry source provenance, source as-of time, venue/pair/timeframe when known, verification status, freshness, and expiry policy. External overlay is never a substitute for measured context.

The detailed overlay boundary is defined in `external_research_overlay_contract_v1.md`.

## Future Output Contract

The future aggregate object is `MarketObserverSnapshot`.

Required fields:

- `schema_version`
- `computed_at_utc`
- `venue`
- `quote_currency`
- `freshness_state`
- `canonical_global_regime`
- `canonical_asset_class_regimes`
- `rotation_observation_state`
- `btc_structure_state`
- `eth_relative_strength_state`
- `alt_breadth_state`
- `sector_rotation_states`
- `symbol_contexts`
- `external_overlay_state`
- `warnings`
- `evidence_refs`

`evidence_refs` must identify the input artifact or canonical observation used for every nontrivial state. A snapshot without enough evidence must downgrade its confidence/freshness rather than imply certainty.

## State Names

These are observer descriptions, not execution labels.

### `rotation_observation_state`

- `UNKNOWN`
- `NO_ROTATION`
- `SELECTIVE_ROTATION`
- `ROTATION_BROADENING`
- `BROAD_RISK_ON`
- `FRAGILE_ROTATION`
- `STALE`

### `btc_structure_state`

- `UNKNOWN`
- `RANGE_STABLE`
- `RANGE_UNRESOLVED`
- `BREAKOUT_UP`
- `BREAKDOWN_RISK`
- `BREAKDOWN_CONFIRMED`
- `STALE`

### `eth_relative_strength_state`

- `UNKNOWN`
- `OUTPERFORMING_BTC`
- `NEUTRAL_TO_BTC`
- `UNDERPERFORMING_BTC`
- `STALE`

### `alt_breadth_state`

- `UNKNOWN`
- `NARROW`
- `EXPANDING_SELECTIVELY`
- `BROADENING`
- `CONTRACTING`
- `STALE`

### Per-symbol descriptive context

A symbol context may describe states such as:

- `UPTREND_CONTINUATION`
- `PULLBACK_AFTER_EXTENSION`
- `TARGET_BREAK_ACCEPTANCE_PENDING`
- `RECLAIM_PENDING`
- `RECLAIM_CONFIRMED`
- `INVALIDATION_RISK`

These labels remain descriptive. They do not mean that a purchase, sale, allocation, or order is allowed.

## Canonical Regime Rule

The observer must forward the existing canonical global and asset-class regimes. It may add a separate `rotation_observation_state`, but it must not rename, overwrite, or synthesize replacements for canonical regime values.

`GLOBAL_ROTATION_WINDOW` and `GLOBAL_RISK_ON` remain owned by the canonical regime source, not by the observer.

## Fibo and External-Level Rule

Fibo map ownership remains with the fib/navigation layer.

The observer may read:

- `FibMapState`
- map confidence
- structural lifecycle
- explicitly registered level-map references

The observer must not:

- rebuild a fib map without a dedicated fib builder
- merge incompatible external maps because their visual zoom differs
- turn a target or extension level into a direct sell instruction
- turn an external zone into a direct buy instruction

External level maps must remain separate from internally rebuilt maps and must declare their provenance.

## Horizon Rule

The observer may display evidence across SHORT, MEDIUM, and LONG contexts. It does not own `HorizonStrategyState`, choose a holding horizon, or replace a horizon scorer.

A per-symbol observer context must preserve the source interval and any relevant horizon tag so a 15m observation is never silently represented as a MEDIUM or LONG conclusion.

## Shadow-First Validation

The first implementation must be shadow-only.

Required sequence:

```text
MarketObserverSnapshot
  -> market-only StrategyCandidate
  -> DecisionPreview
  -> ExecutionPlanPreview
  -> ShadowEvent
  -> forward outcome validation
```

The observer must first prove incremental value against baseline cohorts. Suggested comparisons include:

- `SELECTIVE_ROTATION` versus `NO_ROTATION`
- `EXPANDING_SELECTIVELY` versus `NARROW`
- `RANGE_STABLE` versus `BREAKDOWN_RISK`
- symbol setup with and without matching sector breadth
- external-map reaction state with and without measured confirmation

No observer field may be promoted into `selection_engine` until its definition, sample rules, expected horizon, baseline, and out-of-sample outcome are documented.

## Implementation Sequence

1. Docs-only contract and architecture alignment.
2. Deterministic measured inputs only.
3. Research-only snapshot writer.
4. Shadow-chain attachment with no behavior change downstream.
5. Outcome validation and cohort reports.
6. Explicit feature-promotion proposal, only after evidence.

## Related Documents

- `docs/architecture/pipeline_contracts.md`
- `docs/architecture/module_architecture.md`
- `docs/architecture/external_research_overlay_contract_v1.md`
- `docs/architecture/breath_fibo_synth_framework_contract_v1.md`
- `docs/architecture/multi_horizon_aplus_breathline_strategy_contract_v1.md`
- `docs/research/canonical_regime_context_source_v1.md`
- `docs/research/sector_module_design.md`
- `docs/research/live_like_shadow_chain_v1.md`
- `docs/research/shadow_heartbeat_outcome_validation_v1.md`
