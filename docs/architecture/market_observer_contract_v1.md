# Market Observer Contract v1

## Status

Design contract only. No runtime module, schema, dashboard output, selection behavior, decision-gate behavior, execution-plan behavior, broker call, or order behavior is introduced here.

## Purpose

`market_observer` is the market-only aggregation layer that turns already-owned observations into one explainable cross-market snapshot.

It aggregates context currently read manually:

- BTC structure and range stability
- ETH relative strength and ETH/BTC
- BTC-dominance context
- alt breadth and participation
- sector leadership and rotation
- per-symbol structural context
- external overlays with explicit provenance

It does not decide whether an account may trade, create an order plan, or submit/cancel orders.

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
       -> Strategy State / future HorizonStrategyState
  -> decision_gate
  -> execution_planner
  -> executor / broker
```

`executor / agents` remains reserved for order handling. Market observation must never be implemented in `src/executor/`, `src/execution/`, or an order-handling agent namespace.

## Hard Boundaries

`market_observer` may:

- read public market data and deterministic market-context features
- forward canonical regime observations without redefining them
- read symbol-level `MarketNavigationState`
- read future sector/breadth observations
- attach external research as explicitly non-canonical overlays
- emit descriptive state, freshness, confidence, warnings, and evidence references
- write research-only artifacts in a future shadow implementation

It must not:

- read balances, positions, sleeves, open orders, or account tables
- combine market context with account state
- grant or deny trade permission
- produce `BUY`, `SELL`, sizing, allocation, stop, target, or order labels
- create execution intent or an execution plan
- import decision-gate, execution-planner, executor, broker, or account modules
- silently convert an external claim into measured market truth
- replace `active_regime_observation`
- apply hidden score weights or policy thresholds

## Input Channels

### Measured Market Context

Deterministic, market-only, timestamped inputs from canonical or versioned feature builders:

- canonical global and asset-class regime observations
- BTC range, breakout, breakdown-risk, and volatility observations
- ETH relative strength
- breadth and participation
- future sector snapshots/leadership
- symbol-level `MarketNavigationState`
- fib-map state/confidence and explicitly registered map references
- local MA/ATR, impulse, timing, freshness, and warnings

### External Research Overlay

May include FFG flow snapshots, source charts/external fib maps, catalyst/news events, manually extracted zones, and source-specific narrative classifications.

Every overlay carries provenance, source as-of, venue/pair/timeframe when known, verification, freshness, and expiry. It never substitutes for measured context.

See `external_research_overlay_contract_v1.md`.

## Future Output Contract

`MarketObserverSnapshot` requires:

- `schema_version`, `computed_at_utc`, `venue`, `quote_currency`, `freshness_state`
- `canonical_global_regime`, `canonical_asset_class_regimes`
- `rotation_observation_state`, `btc_structure_state`, `eth_relative_strength_state`, `alt_breadth_state`, `sector_rotation_states`
- `symbol_contexts`, `external_overlay_state`, `warnings`, `evidence_refs`

Every nontrivial state requires evidence references. Insufficient evidence must downgrade freshness/confidence rather than imply certainty.

## State Names

Observer labels are descriptive and distinct from canonical regime and A+ vocabulary.

### `rotation_observation_state`

```text
UNKNOWN
NO_ROTATION
SELECTIVE_ROTATION
ROTATION_BROADENING
BROAD_PARTICIPATION
FRAGILE_ROTATION
STALE
```

`BROAD_PARTICIPATION` describes breadth only. It is not `GLOBAL_RISK_ON` and not A+ `risk_climate=RISK_ON`.

### `btc_structure_state`

```text
UNKNOWN
RANGE_STABLE
RANGE_UNRESOLVED
BREAKOUT_UP
BREAKDOWN_RISK
BREAKDOWN_CONFIRMED
STALE
```

### `eth_relative_strength_state`

```text
UNKNOWN
OUTPERFORMING_BTC
NEUTRAL_TO_BTC
UNDERPERFORMING_BTC
STALE
```

### `alt_breadth_state`

```text
UNKNOWN
NARROW
EXPANDING_SELECTIVELY
BROADENING
CONTRACTING
STALE
```

### Per-symbol descriptive context

```text
UPTREND_CONTINUATION
PULLBACK_AFTER_EXTENSION
TARGET_BREAK_ACCEPTANCE_PENDING
RECLAIM_PENDING
RECLAIM_CONFIRMED
INVALIDATION_RISK
```

None means purchase, sale, allocation, or order permission.

## Canonical Regime Rule

Observer forwards existing canonical global/asset-class regimes. It may add `rotation_observation_state`; it must not rename, overwrite, synthesize, or visually substitute canonical regime values.

`GLOBAL_ROTATION_WINDOW` and `GLOBAL_RISK_ON` remain owned by the canonical regime source. A+ `risk_climate` remains A+ context. UI must render these fields as separate provenance-tagged concepts.

## Fibo and External-Level Rule

Fibo ownership remains with its navigation/builder layer. Observer may read `FibMapState`, confidence, lifecycle, and registered map references.

It must not rebuild a map without a dedicated builder, merge incompatible external maps because their visual zoom differs, or turn a target/zone into an execution instruction.

External and internal maps remain separate with declared provenance.

## Horizon Rule

Observer may display evidence across SHORT, MEDIUM, and LONG contexts. It does not choose a holding horizon, own `HorizonStrategyState`, or replace a horizon scorer.

Per-symbol context preserves source interval, as-of, freshness, and explicit horizon tag when applicable. A `15m` observation cannot silently become a MEDIUM or LONG conclusion.

## Shadow-First Validation

First implementation is shadow-only.

```text
MarketObserverSnapshot
  -> market-only StrategyCandidate
  -> DecisionPreview
  -> ExecutionPlanPreview
  -> ShadowEvent
  -> forward outcome validation
```

Test incremental value against baselines, including:

- `SELECTIVE_ROTATION` vs `NO_ROTATION`
- `EXPANDING_SELECTIVELY` vs `NARROW`
- `RANGE_STABLE` vs `BREAKDOWN_RISK`
- symbol setup with/without matching sector breadth
- external-map reaction with/without measured confirmation

No observer field reaches `selection_engine` without documented definition, sample rules, expected horizon, baseline, and out-of-sample evidence.

## Implementation Sequence

1. Docs-only contract alignment.
2. Deterministic measured inputs.
3. Research-only snapshot writer.
4. Shadow-chain attachment without downstream behavior change.
5. Outcome validation/cohort reports.
6. Explicit evidence-led promotion proposal.

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
