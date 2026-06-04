# Historical Market Breath Densifier V1

## Purpose

`historical_market_breath_densifier_v1` improves historical context coverage by creating event-aligned context rows near lifecycle timestamps when nearby market-breath evidence exists.

It is a research-only densifier for:

- `historical_breath_regime_context_builder_v1`
- later context-joined profile and replay research

## Boundary

- research-only
- market-only
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

- `data/research/historical_breath_regime_context_builder_v1/historical_breath_regime_context_rows_v1.csv`
- `data/research/symbol_reaction_profile_by_context_v1/symbol_reaction_profile_by_context_rows_v1.csv`
- `data/research/market_breath_outcome_validation_v1/outcome_rows_v1.jsonl`
- `data/research/position_lifecycle_outcome_validation_v1/outcome_rows_v1.jsonl` when present

## Densification behavior

V1:

- identifies lifecycle event timestamps per symbol
- looks for nearby market-breath rows for the same symbol
- creates event-aligned context rows at `event_ts_utc` when the nearest existing context row is missing or unknown-heavy
- fills only missing fields
- preserves symbol identity
- preserves or extends `source_refs`
- never fabricates high-confidence context without source support
- keeps `UNKNOWN` where no evidence exists

## Output files

When `--write-files` is set:

```text
data/research/historical_market_breath_densifier_v1/
  historical_market_breath_densified_rows_v1.csv
  historical_market_breath_densified_rows_v1.jsonl
  manifest_v1.json
```

## CLI

```bash
python -m src.research.run_historical_market_breath_densifier_v1 \
  --symbols WLD,NEAR,HYPE,TAO,FET,ALGO,XLM \
  --max-rows 500 \
  --write-files \
  --output summary
```

## Measures

The runner reports:

- `input_context_rows`
- `input_profile_rows`
- `output_rows`
- `enriched_rows`
- `unknown_heavy_before`
- `unknown_heavy_after`
- `breath_phase_unknown_before/after`
- `breath_alignment_unknown_before/after`
- `market_regime_unknown_before/after`
- `symbol_regime_unknown_before/after`
- `quality_state` distribution
- `source_coverage` by `source_refs`

## Recommended use

Run this after context-builder and before rerunning profile research when context coverage is partial because lifecycle dates are underrepresented.
