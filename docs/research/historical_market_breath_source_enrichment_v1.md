# Historical Market Breath Source Enrichment V1

## Purpose

Define why `market_breath_outcome_validation_v1` is too sparse for downstream historical context use, and specify the research-only upstream enrichment runner that should fix that gap before any more context-joined profile work.

This document does not authorize strategy changes, decision changes, execution changes, broker calls, DB writes, or runtime integration.

## Current finding

`historical_market_breath_densifier_v1` produced `enriched_rows=0` because the nearest-row join logic was not the real blocker.

The blocker is upstream source sparsity in:

- `breath_phase`
- `breath_alignment`
- `symbol_regime`

Specifically:

- `data/research/market_breath_outcome_validation_v1/outcome_rows_v1.jsonl` contains `market_breath_phase` and `market_breath_state`, not the canonical fields used downstream.
- `market_breath_phase` is present for all rows, but most rows are `NEUTRAL_TRANSITION`, which maps to canonical `breath_phase=UNKNOWN`.
- `market_breath_state` is present for all rows, but most rows are `UNKNOWN`, which maps to canonical `breath_alignment=UNKNOWN`.
- `symbol_regime` is not stored explicitly upstream, but can already be derived from `relative_strength_score` and `momentum_score`.

Observed sample from the current source:

- rows sampled: `2460`
- `market_breath_phase=NEUTRAL_TRANSITION`: `2157`
- `market_breath_state=UNKNOWN`: `2157`
- derived canonical `breath_phase=UNKNOWN`: `2157`
- derived canonical `breath_alignment=UNKNOWN`: `2157`
- derived canonical `symbol_regime=UNKNOWN`: `1066`

Conclusion:

- `breath_phase` is partially derivable now, but its usefulness is capped by the dominance of `NEUTRAL_TRANSITION`.
- `breath_alignment` is mostly unusable as-is because upstream state classification rarely leaves `UNKNOWN`.
- `symbol_regime` can be materially improved now from existing score fields without new raw inputs.

## Source inventory relevant to enrichment

### `src/research/run_market_breath_analysis_v1.py`

This is the real upstream classifier.

It already computes per-symbol historical-style observation fields:

- `compression_score`
- `expansion_score`
- `momentum_score`
- `reversal_pressure_score`
- `relative_strength_score`
- `btc_alignment_score`
- `breadth_alignment_score`
- `market_breath_phase`
- `market_breath_state`
- `market_breath_score`
- `market_breath_confidence`

The core phase/state classifier is already explicit:

- `COLLAPSE_RESET` / `RESET`
- `OVERBREATH_EXTENSION` / `LATE`
- `EXHALE_EXPANSION` / `FORMING|CONFIRMED`
- `HOLD_COMPRESSION` / `FORMING|CONFIRMED`
- `INHALE_ACCUMULATION` / `FORMING|CONFIRMED`
- fallback `NEUTRAL_TRANSITION` / `UNKNOWN`

This means the next enrichment step should be built around replaying this classifier over historical as-of timestamps, not inventing new downstream heuristics.

### `src/research/run_market_breath_outcome_validation_v1.py`

This runner persists the historical research rows currently used by the context builder.

It preserves:

- `market_breath_phase`
- `market_breath_state`
- `relative_strength_score`
- `momentum_score`
- `btc_alignment_score`
- `breadth_alignment_score`
- `compression_score`
- `expansion_score`
- `reversal_pressure_score`
- outcome fields

It does not persist:

- canonical `breath_phase`
- canonical `breath_alignment`
- canonical `market_regime`
- canonical `btc_context`
- canonical `symbol_regime`

That omission is acceptable if downstream remapping is strong enough. Right now it is not strong enough for `breath_alignment`, because upstream state itself is too often `UNKNOWN`.

### `src/research/run_historical_breath_regime_context_builder_v1.py`

The builder already proves that the following fields are derivable from the current market-breath source:

- `breath_phase` from `market_breath_phase`
- `breath_alignment` from `market_breath_state`
- `market_regime` from score bands
- `btc_context` from score bands
- `symbol_regime` from `relative_strength_score` and `momentum_score`
- `relative_strength_bucket`
- `momentum_bucket`
- `confidence_bucket`

So the builder is not the root problem. Its remapping logic is mostly adequate for V1.

## Which missing fields can be derived now

### Derivable from existing market-breath rows

- `breath_phase`
  - already derivable from `market_breath_phase`
  - current canonical mapping is valid
- `market_regime`
  - derivable from `momentum_score`, `relative_strength_score`, `btc_alignment_score`, `breadth_alignment_score`
- `btc_context`
  - derivable from `btc_alignment_score`
- `symbol_regime`
  - derivable from `relative_strength_score` and `momentum_score`
- `relative_strength_bucket`
  - derivable from `relative_strength_score`
- `momentum_bucket`
  - derivable from `momentum_score`
- `confidence_bucket`
  - derivable from `market_breath_confidence`

### Derivable only partially from existing market-breath rows

- `breath_alignment`
  - technically derivable from `market_breath_state`
  - practically weak because upstream `market_breath_state` is overwhelmingly `UNKNOWN`

## Which fields require new upstream calculations

### `breath_alignment`

This is the main enrichment target.

Reason:

- upstream already emits `market_breath_state`
- but most historical rows land in fallback `UNKNOWN`
- downstream cannot improve that without stronger upstream classification

Required change:

- rerun or extend historical market-breath generation with a richer state classifier
- specifically around lifecycle/reaction event dates, not just sparse sample dates
- keep replay-safe as-of construction

### `breath_phase`

Not missing in a schema sense, but under-informative in a coverage sense.

Reason:

- upstream emits `market_breath_phase`
- but most rows are `NEUTRAL_TRANSITION`
- downstream canonical mapping intentionally treats that as `UNKNOWN`

Required change:

- not a downstream remap tweak
- a stronger upstream historical market-breath sampling and/or classification pass
- possibly event-aligned as-of generation instead of sparse validation-only samples

### `symbol_regime`

This does not require new raw market inputs.

Reason:

- upstream already stores `relative_strength_score` and `momentum_score`
- current thresholds already generate non-`UNKNOWN` `symbol_regime` in many rows

Required change:

- upstream enrichment runner should persist `symbol_regime` explicitly
- this is a normalization/publishing gap, not a raw data gap

## Direct answers

### Can `breath_phase` be inferred from existing market-breath rows?

Yes, partially.

- `market_breath_phase` already exists upstream.
- Canonical mapping is straightforward:
  - `EXHALE_EXPANSION -> EXPANSION`
  - `HOLD_COMPRESSION -> CONTRACTION`
  - `INHALE_ACCUMULATION -> RELOAD`
  - `OVERBREATH_EXTENSION -> POST_SPIKE`
  - `COLLAPSE_RESET -> IGNITION`
  - `NEUTRAL_TRANSITION -> UNKNOWN`
- The real problem is not inference availability.
- The real problem is that too many rows are upstream `NEUTRAL_TRANSITION`.

### Can `breath_alignment` be inferred per symbol?

Partially, but not well enough from the current stored source.

- `market_breath_state` is symbol-scoped and already stored.
- Canonical mapping is straightforward:
  - `CONFIRMED -> ALIGNED`
  - `FORMING -> EARLY`
  - `LATE -> LATE`
  - `RESET -> INCOHERENT`
  - `UNKNOWN -> UNKNOWN`
- Coverage is poor because upstream state itself is mostly `UNKNOWN`.
- Therefore improvement requires new upstream calculations or denser historical recomputation, not another downstream remap layer.

### Can `symbol_regime` be improved from relative strength and momentum?

Yes.

This is the clearest short-term win.

- existing source has `relative_strength_score`
- existing source has `momentum_score`
- current builder thresholds already derive:
  - `REL_STRENGTH`
  - `LAGGARD`
  - `HIGH_BETA`
  - `LOW_BETA`
  - `UNKNOWN`

Recommended V1 upstream change:

- persist explicit `symbol_regime`
- persist `relative_strength_bucket`
- persist `momentum_bucket`

## Recommended implementation batch

Implement a new research-only runner:

`historical_market_breath_source_enrichment_v1`

Proposed future files:

- `src/research/run_historical_market_breath_source_enrichment_v1.py`
- `docs/research/historical_market_breath_source_enrichment_v1.md`
- `tests/test_historical_market_breath_source_enrichment_v1.py`

### Proposed purpose

Replay historical market-breath observations at denser, event-relevant as-of timestamps and emit an enriched file-first source that downstream context builders can trust more than the current validation-only rows.

### Proposed inputs

- `data/research/market_breath_outcome_validation_v1/outcome_rows_v1.jsonl`
- lifecycle/reaction event timestamps used by reload/reaction research
- `obs_market_candle` via existing research DB helper patterns
- optional `signal_engine_state` / `selection_state` timestamps as extra anchor candidates

### Proposed outputs

File-output only, no DB writes:

```text
data/research/historical_market_breath_source_enrichment_v1/
  historical_market_breath_source_rows_v1.csv
  historical_market_breath_source_rows_v1.jsonl
  manifest_v1.json
```

### Required output fields

- `symbol`
- `venue`
- `interval`
- `asof_ts_utc`
- `market_breath_phase`
- `market_breath_state`
- `breath_phase`
- `breath_alignment`
- `market_regime`
- `btc_context`
- `symbol_regime`
- `relative_strength_score`
- `momentum_score`
- `btc_alignment_score`
- `breadth_alignment_score`
- `compression_score`
- `expansion_score`
- `reversal_pressure_score`
- `relative_strength_bucket`
- `momentum_bucket`
- `market_breath_confidence`
- `confidence_bucket`
- `quality_state`
- `source_refs`
- `research_only=true`

### V1 rules

- build event-aligned historical rows, not just sparse audit samples
- preserve symbol identity
- preserve as-of timestamps
- keep replay-safe point-in-time construction
- explicitly persist normalized canonical fields, not only raw market-breath labels
- do not invent `ALIGNED` or non-`UNKNOWN` phase/state without classifier support
- prefer `UNKNOWN` over guessed context

## Why this runner is the right next step

The current chain is:

- sparse upstream market-breath outcome rows
- context builder remap
- densifier
- profile runner

That chain cannot recover coverage if the first historical source is already weak.

So the next correct batch is:

- strengthen the upstream historical market-breath source itself
- then rebuild context rows
- then rerun coverage audit
- then rerun symbol reaction profile by context

## Safety boundary

```text
research_only=true
broker_calls=0
broker_writes=0
order_submission=0
executor=none
db_writes=0
```

No selection, decision, execution, broker, or runtime changes are authorized by this design.
