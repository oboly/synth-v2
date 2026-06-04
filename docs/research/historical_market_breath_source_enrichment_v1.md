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

## Implemented runner

Research-only runner:

`historical_market_breath_source_enrichment_v1`

Files:

- `src/research/run_historical_market_breath_source_enrichment_v1.py`
- `docs/research/historical_market_breath_source_enrichment_v1.md`
- `tests/test_historical_market_breath_source_enrichment_v1.py`

### Purpose

Normalize the current historical market-breath source into a canonical file-first source that downstream context builders can consume directly, without re-deriving the same labels each time.

V1 is file-only. It does not replay candles or query DB.

### Inputs

Primary:

- `data/research/market_breath_outcome_validation_v1/outcome_rows_v1.jsonl`

Optional path references for downstream audit context:

- `data/research/historical_breath_regime_context_builder_v1/historical_breath_regime_context_rows_v1.csv`
- `data/research/symbol_reaction_profile_by_context_v1/symbol_reaction_profile_by_context_rows_v1.csv`

### Outputs

File-output only, no DB writes:

```text
data/research/historical_market_breath_source_enrichment_v1/
  historical_market_breath_source_enriched_rows_v1.csv
  historical_market_breath_source_enriched_rows_v1.jsonl
  manifest_v1.json
```

### Output fields

- `symbol`
- `venue`
- `interval`
- `asof_ts_utc`
- `source_event_ts_utc`
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

### Derivation rules

- live/reporting consistency rule:
  - reuse the pure canonical mapping helpers already used by `historical_breath_regime_context_builder_v1`
  - do not create alternate label semantics in this runner
  - if a comparable live/reporting label is not explicitly supported, emit `UNKNOWN`
- `breath_phase` derives from `market_breath_phase_raw`
- `breath_alignment` derives from `market_breath_state_raw`
- `market_regime` reuses the score-band logic from `historical_breath_regime_context_builder_v1`
- `btc_context` reuses the score-band logic from `historical_breath_regime_context_builder_v1`
- `symbol_regime` derives from `relative_strength_score` and `momentum_score`
- `quality_state` is:
  - `HIGH` when `breath_phase` is known and at least one of `symbol_regime`, `market_regime`, or `btc_context` is known
  - `MEDIUM` when one of `symbol_regime`, `market_regime`, or `btc_context` is known but `breath_phase` is unknown
  - `LOW` otherwise
- `source_refs` preserves path/source/as-of provenance
- V1 does not invent alignment precision when the raw upstream state is `UNKNOWN`

Inspected consistency sources:

- `src/reporting/market_breath_context_bridge_v1.py`
- `src/reporting/run_breath_fibo_strategy_static_dashboard_v1.py`
- `src/reporting/rotation_destination_eligibility_v1.py`
- `src/research/run_market_breath_analysis_v1.py`
- `src/research/run_historical_breath_regime_context_builder_v1.py`

Result:

- live/reporting code does not expose a richer canonical `breath_phase`, `breath_alignment`, `market_regime`, `btc_context`, `symbol_regime`, or `fibo_context` mapping than the builder already uses
- therefore V1 enrichment remains intentionally conservative and emits `UNKNOWN` for unsupported or ambiguous raw values

### CLI

```bash
python -m src.research.run_historical_market_breath_source_enrichment_v1 \
  --symbols WLD,NEAR,HYPE,TAO,FET,ALGO,XLM \
  --max-rows 500 \
  --write-files \
  --output summary
```

### Measures

The runner reports:

- `input_rows`
- `output_rows`
- `raw_phase_known_before`
- `breath_phase_known_after`
- `raw_alignment_known_before`
- `breath_alignment_known_after`
- `symbol_regime_known_before`
- `symbol_regime_known_after`
- `breath_phase_unknown_after`
- `breath_alignment_unknown_after`
- `symbol_regime_unknown_after`
- `quality_state_distribution`
- `source_coverage`

## Why this runner is the right next step

The current chain is:

- sparse upstream market-breath outcome rows
- context builder remap
- densifier
- profile runner

That chain cannot recover coverage if the first historical source is already weak.

So the next correct batch after this source enrichment is:

- rebuild context rows from the enriched source
- rerun coverage audit
- rerun symbol reaction profile by context

Current downstream consumer:

- `historical_breath_regime_context_builder_v1` can optionally consume:
  - `historical_market_breath_source_enriched_rows_v1.csv`
  - `historical_market_breath_source_enriched_rows_v1.jsonl`

Consumption rule:

- enriched rows are preferred only for supported canonical fields
- enriched `UNKNOWN` values do not overwrite known fallback values from the legacy market-breath source

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
