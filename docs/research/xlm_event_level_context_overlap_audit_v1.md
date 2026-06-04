# XLM Event Level Context Overlap Audit V1

## Purpose

`xlm_event_level_context_overlap_audit_v1` inspects XLM at lower event level to determine whether usable recomputed context exists but is lost by aggregate `symbol_reaction_profile_by_context_v1` output.

This is a research-only readout. It does not create or modify strategy/advice/execution behavior.

## Boundary

- research-only
- file-input / file-output only
- no DB writes
- no broker calls
- no broker writes
- no order submission
- no selection, decision, execution, or executor integration

Safety markers:

```text
research_only=true
broker_calls=0
broker_writes=0
order_submission=0
executor=none
db_writes=0
```

## Inputs

Primary inputs:

- `data/research/historical_market_breath_source_recompute_v1/historical_market_breath_source_recomputed_rows_v1.csv`
- `data/research/historical_breath_regime_context_builder_v1/historical_breath_regime_context_rows_v1.csv`
- `data/research/symbol_reaction_profile_by_context_v1/symbol_reaction_profile_by_context_rows_v1.csv`
- lower-level event rows from:
  - `data/research/position_lifecycle_outcome_validation_v1/outcome_rows_v1.jsonl`

The runner is XLM-only by default.

## Method

For each XLM event row:

1. find nearest recompute context at or before `event_ts_utc`
2. find nearest context-builder row at or before `event_ts_utc`
3. inspect recompute:
   - `breath_phase`
   - `breath_alignment`
   - `symbol_regime`
4. check whether the aggregate profile export contains the same symbol-plus-context bucket

Important:

- profile rows do not carry timestamps
- therefore aggregate preservation is checked at bucket level, not timestamp level
- this is deliberate and avoids inventing event timestamps in the profile export

## Output rows

Each row includes:

- `symbol`
- `event_ts_utc`
- `source_candle_ts_utc`
- `recompute_asof_ts_utc`
- `context_asof_ts_utc`
- `breath_phase`
- `breath_alignment`
- `market_regime`
- `btc_context`
- `symbol_regime`
- `event_has_known_context`
- `aggregate_profile_preserved_context`
- `max_favorable_excursion_pct`
- `max_adverse_excursion_pct`
- `drawdown_after_event_pct`
- `issue_classification`

## Issue classifications

- `EVENT_HAS_KNOWN_CONTEXT`
- `EVENT_CONTEXT_UNKNOWN`
- `AGGREGATE_PROFILE_LOST_CONTEXT`
- `NO_EVENT_OVERLAP`
- `SOURCE_MISSING`

## Output files

When `--write-files` is set:

```text
data/research/xlm_event_level_context_overlap_audit_v1/
  xlm_event_level_context_overlap_rows_v1.csv
  manifest_v1.json
```

## CLI

```bash
python -m src.research.run_xlm_event_level_context_overlap_audit_v1 \
  --write-files \
  --output summary
```

## Interpretation

This audit helps answer:

- whether XLM events actually have known recomputed context at event time
- whether aggregate profile output preserves or loses those buckets
- whether the problem is upstream unknown semantics or downstream aggregation loss
