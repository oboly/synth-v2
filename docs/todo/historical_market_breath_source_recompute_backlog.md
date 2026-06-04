# TODO — Historical Market Breath Source Recompute

## Status

- `active`
- upstream recompute required

## Trigger condition

Confirmed after:

- enriched source publishing
- enriched source wired into context builder
- no field-level coverage improvement in rebuilt context rows

Observed unchanged coverage on the current sample:

- `breath_phase_unknown 377 -> 377`
- `breath_alignment_unknown 377 -> 377`
- `symbol_regime_unknown 157 -> 157`
- `quality_state` unchanged

## Sources inspected

- `src/research/run_market_breath_analysis_v1.py`
- `src/research/run_market_breath_outcome_validation_v1.py`
- `src/reporting/market_breath_context_bridge_v1.py`
- `src/research/run_historical_market_breath_source_enrichment_v1.py`
- `src/research/run_historical_breath_regime_context_builder_v1.py`
- `data/research/market_breath_outcome_validation_v1/outcome_rows_v1.jsonl`
- `data/research/historical_market_breath_source_enrichment_v1/historical_market_breath_source_enriched_rows_v1.csv`

## Available historical inputs

- historical market-breath outcome rows already store:
  - `market_breath_phase`
  - `market_breath_state`
  - `compression_score`
  - `expansion_score`
  - `momentum_score`
  - `reversal_pressure_score`
  - `relative_strength_score`
  - `btc_alignment_score`
  - `breadth_alignment_score`
- underlying replay source exists in `obs_market_candle`
- live/research pure classifier already exists in `run_market_breath_analysis_v1.py`

## Missing pieces

- event-aligned replay over missing timestamps
- denser as-of timestamp spine than the sparse validation sample set
- recomputed raw phase/state rows at those timestamps
- replay-produced canonical rows emitted directly from the candle-level classifier

## Next implementation batch

Implement:

- `src/research/run_historical_market_breath_source_recompute_v1.py`
- `tests/test_historical_market_breath_source_recompute_v1.py`

Output path:

- `data/research/historical_market_breath_source_recompute_v1/`

## Required design rules

- reuse `run_market_breath_analysis_v1.py` pure helpers
- reuse canonical mapping helpers from `historical_breath_regime_context_builder_v1.py`
- emit `UNKNOWN` for unsupported values
- no fake precision
- no DB writes
- no broker calls
- no strategy or execution semantics

## Required output fields

- `symbol`
- `venue`
- `interval`
- `asof_ts_utc`
- `market_breath_phase_raw`
- `market_breath_state_raw`
- `breath_phase`
- `breath_alignment`
- `market_regime`
- `btc_context`
- `symbol_regime`
- `relative_strength_score`
- `momentum_score`
- `relative_strength_bucket`
- `momentum_bucket`
- `quality_state`
- `confidence_bucket`
- `source_refs`
- `research_only=true`

## Follow-up after recompute

1. rerun `historical_market_breath_source_enrichment_v1` only if normalization/publishing still adds value
2. rebuild `historical_breath_regime_context_builder_v1`
3. rerun `historical_breath_regime_context_coverage_audit_v1`
4. rerun `symbol_reaction_profile_by_context_v1`
5. compare field-level unknown counts before/after

## Boundary

- research-only
- market-only
- no broker calls
- no broker writes
- no order submission
- no decision_gate changes
- no execution_planner changes
- no executor changes
