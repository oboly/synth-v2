# Historical Market Breath Source Recompute V1

## Purpose

Define the next research-only runner needed to recompute richer historical market-breath source rows from underlying historical market inputs, after proving that:

- downstream context wiring works
- downstream densification works
- canonical enrichment wiring works
- coverage still does not improve

This document is design-only. It does not authorize DB writes, broker calls, strategy changes, decision changes, execution changes, or runtime integration.

## Current conclusion

The coverage bottleneck is upstream.

Current chain:

- `market_breath_outcome_validation_v1`
- `historical_market_breath_source_enrichment_v1`
- `historical_breath_regime_context_builder_v1`
- `historical_breath_regime_context_coverage_audit_v1`
- `historical_market_breath_densifier_v1`

Observed result:

- `breath_phase_unknown` unchanged
- `breath_alignment_unknown` unchanged
- `symbol_regime_unknown` unchanged in rebuilt context rows
- `quality_state` unchanged

This means:

- downstream mapping is not the blocker
- downstream joining is not the blocker
- the historical source itself does not contain enough non-`UNKNOWN` phase/state coverage on the timestamps we care about

## Direct answers

### 1. Which raw inputs are available historically to recompute `market_breath_phase`?

Two levels of historical inputs exist.

#### A. Stored historical research rows

From `data/research/market_breath_outcome_validation_v1/outcome_rows_v1.jsonl`:

- `compression_score`
- `expansion_score`
- `momentum_score`
- `reversal_pressure_score`
- `relative_strength_score`
- `btc_alignment_score`
- `breadth_alignment_score`
- `market_breath_phase`
- `market_breath_state`
- `market_breath_confidence`
- `asof_ts_utc`
- `symbol`
- `venue`
- `interval_code`

These are enough to inspect and reuse already-computed phase/state classifications where rows exist.

#### B. Underlying historical market inputs

From `src/research/run_market_breath_analysis_v1.py`, historical replay can recompute phase from:

- `obs_market_candle.close_price`
- `obs_market_candle.high_price`
- `obs_market_candle.low_price`
- `obs_market_candle.open_price`
- historical candle timestamps
- BTC reference returns via BTC candle history

Derived features already implemented in live/research logic:

- `return_1`
- `return_3`
- `return_6`
- `return_12`
- `range_pct`
- `atr_pct_proxy`
- `compression_score`
- `expansion_score`
- `momentum_score`
- `reversal_pressure_score`
- `relative_strength_score`
- `btc_alignment_score`
- `breadth_alignment_score`

Conclusion:

- yes, `market_breath_phase` can be recomputed historically
- but to improve coverage on missing timestamps, the runner must replay the candle-driven logic, not just remap existing sparse rows

### 2. Which raw inputs are available historically to recompute `market_breath_state` / `breath_alignment`?

Historically available from stored rows:

- `market_breath_state`
- `compression_score`
- `expansion_score`
- `momentum_score`
- `reversal_pressure_score`
- `relative_strength_score`

Historically available from underlying replay inputs:

- same candle-derived score set used by `phase_and_state()` in `run_market_breath_analysis_v1.py`

Current live/research phase/state classifier:

- `COLLAPSE_RESET` / `RESET`
- `OVERBREATH_EXTENSION` / `LATE`
- `EXHALE_EXPANSION` / `FORMING|CONFIRMED`
- `HOLD_COMPRESSION` / `FORMING|CONFIRMED`
- `INHALE_ACCUMULATION` / `FORMING|CONFIRMED`
- fallback `NEUTRAL_TRANSITION` / `UNKNOWN`

Canonical historical alignment mapping already used downstream:

- `CONFIRMED -> ALIGNED`
- `FORMING -> EARLY`
- `EARLY -> EARLY`
- `LATE -> LATE`
- `RESET -> INCOHERENT`
- otherwise `UNKNOWN`

Conclusion:

- yes, `market_breath_state` and canonical `breath_alignment` can be recomputed historically
- the correct path is to reuse `phase_and_state()` over historical candle windows
- if recomputed raw state is still `UNKNOWN`, canonical `breath_alignment` must remain `UNKNOWN`

### 3. Can `symbol_regime` be recomputed from existing `relative_strength_score` and `momentum_score` consistently with current builder helpers?

Yes.

Current helper already used by:

- `historical_breath_regime_context_builder_v1`
- `historical_market_breath_source_enrichment_v1`

Current thresholds:

- `relative_strength_score >= 20 -> REL_STRENGTH`
- `relative_strength_score <= -20 -> LAGGARD`
- `abs(momentum_score) >= 45 -> HIGH_BETA`
- `abs(momentum_score) <= 10 -> LOW_BETA`
- otherwise `UNKNOWN`

Conclusion:

- `symbol_regime` does not require new semantics
- it should be recomputed using the exact same pure helper, not a new threshold set

### 4. Which current live/reporting logic can be reused as pure helpers?

The canonical reusable logic is already in research/runtime-adjacent pure functions, not in the dashboards themselves.

#### Reuse directly

From `src/research/run_market_breath_analysis_v1.py`:

- `safe_return()`
- `range_pct()`
- `true_range_pct()`
- `score_low_vs_baseline()`
- `score_high_vs_baseline()`
- `momentum_score()`
- `reversal_pressure_score()`
- `relative_strength_score()`
- `btc_alignment_score()`
- `phase_and_state()`
- `breath_score()`
- `confidence()`
- `build_base_observation()`
- `add_breadth_and_scores()`

From `src/research/run_historical_breath_regime_context_builder_v1.py`:

- `canonical_breath_phase()`
- `canonical_breath_alignment()`
- `market_regime_from_scores()`
- `btc_context_from_scores()`
- `symbol_regime_from_scores()`
- `relative_strength_bucket()`
- `momentum_bucket()`
- `confidence_bucket()`

#### Reporting logic to inspect but not use as canonical derivation source

From `src/reporting/market_breath_context_bridge_v1.py`:

- `market_breath_context_state()`

This is a display/readout helper, not the canonical historical derivation for:

- `breath_phase`
- `breath_alignment`
- `market_regime`
- `btc_context`
- `symbol_regime`

It may remain a reporting-only context badge layer.

From `src/reporting/run_breath_fibo_strategy_static_dashboard_v1.py`:

- no stronger canonical breath/regime derivation helper was found

Conclusion:

- the recompute runner should reuse pure helpers from `run_market_breath_analysis_v1.py`
- canonical market/btc/symbol mappings should continue to reuse pure helpers from `historical_breath_regime_context_builder_v1.py`
- no new label semantics should be introduced in reporting or recompute code

### 5. Which fields must remain `UNKNOWN` because live logic has no supported derivation?

Must remain `UNKNOWN` in V1 recompute unless a separately validated source is wired:

- `fibo_context`
- `aplus_context_state`
- `martee_context_state`

Reason:

- live/reporting logic does not expose a canonical replay-safe derivation for these inside market-breath classification
- adding them here would invent semantics outside the market-breath source lane

Also must remain `UNKNOWN` when raw replay yields no supported label:

- `breath_phase` when raw phase is unsupported or falls to `NEUTRAL_TRANSITION` / `INSUFFICIENT_DATA`
- `breath_alignment` when raw state is unsupported or `UNKNOWN`
- `market_regime`, `btc_context`, `symbol_regime` when required score inputs are missing or do not meet existing helper rules

## Implemented runner

Files:

- `src/research/run_historical_market_breath_source_recompute_v1.py`
- `tests/test_historical_market_breath_source_recompute_v1.py`
- `docs/research/historical_market_breath_source_recompute_v1.md`

Output dir:

`data/research/historical_market_breath_source_recompute_v1/`

Output files:

- `historical_market_breath_source_recomputed_rows_v1.csv`
- `historical_market_breath_source_recomputed_rows_v1.jsonl`
- `manifest_v1.json`

## Runner design

### Purpose

Replay the live market-breath classifier over historical as-of timestamps chosen to improve coverage for downstream context and profile research.

### Input classes

#### Primary replay inputs

- historical `obs_market_candle` rows
- `asset` universe from `fetch_assets()`
- BTC historical candle rows as the reference series

#### Timestamp spine inputs

The runner should not depend only on sparse validation sample dates.

Preferred timestamp source in V1:

- available `obs_market_candle.close_ts_utc` values for the requested symbols
- optional bounded `--start-ts` / `--end-ts`

This keeps the replay deterministic and aligned to available market data.

### Replay flow

1. Resolve requested symbol set plus BTC anchor.
2. Resolve available as-of timestamps from `obs_market_candle`.
3. For each as-of timestamp:
   - fetch candle windows with `fetch_candles()`
   - compute BTC reference returns with `safe_return()`
   - call `build_base_observation()` for each selected symbol
   - call `add_breadth_and_scores()`
4. Convert raw phase/state to canonical labels using existing pure helpers.
5. Derive:
   - `market_regime`
   - `btc_context`
   - `symbol_regime`
   - `relative_strength_bucket`
   - `momentum_bucket`
   - `confidence_bucket`
6. Assign conservative `quality_state`.
7. Emit provenance in `source_refs`.

### Required output fields

- `symbol`
- `venue`
- `interval`
- `asof_ts_utc`
- `compression_score`
- `expansion_score`
- `momentum_score`
- `reversal_pressure_score`
- `relative_strength_score`
- `btc_alignment_score`
- `breadth_alignment_score`
- `market_breath_phase_raw`
- `market_breath_state_raw`
- `market_breath_confidence`
- `breath_phase`
- `breath_alignment`
- `market_regime`
- `btc_context`
- `symbol_regime`
- `relative_strength_bucket`
- `momentum_bucket`
- `quality_state`
- `confidence_bucket`
- `source_refs`
- `research_only=true`

### Quality rules

- `HIGH` only when raw replay yields supported non-`UNKNOWN` breath plus at least one supported regime field
- `MEDIUM` when regime fields exist but breath remains unknown
- `LOW` when mostly unknown
- never synthesize unsupported labels

### Source refs

Each row shows:

- replay source runner name
- as-of timestamp
- interval
- `obs_market_candle` provenance

## Why this runner is the correct next batch

The repo already proved:

- downstream mapping works
- enriched-source publishing works
- context-builder integration works

The remaining deficiency is timestamp coverage and raw phase/state richness at those timestamps.

Only a replay runner that uses the original candle-level market-breath classifier can change that.

## CLI

```bash
python -m src.research.run_historical_market_breath_source_recompute_v1 \
  --symbols WLD,NEAR,HYPE,TAO,FET,ALGO,XLM \
  --venue bitvavo \
  --interval 4h \
  --max-rows 500 \
  --write-files \
  --output summary
```

## Non-goals

- no DB writes
- no broker calls
- no selection integration
- no decision integration
- no execution integration
- no trade recommendations
- no executable permissions
- no new label semantics

## Safety boundary

```text
research_only=true
broker_calls=0
broker_writes=0
order_submission=0
executor=none
db_writes=0
```
