# Context Qualified Symbol Reaction Profile Audit V1

## Purpose

`context_qualified_symbol_reaction_profile_audit_v1` audits profile usability by context-quality buckets instead of trying to force more non-`UNKNOWN` labels from the historical context source.

It is a research-only file audit over existing context-builder and symbol-profile outputs.

## Boundary

- research-only
- file-input / file-output only
- no DB writes
- no broker calls
- no broker writes
- no order submission
- no selection, decision, execution, or executor integration
- no trade recommendations

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

Optional supporting context:

- `data/research/historical_breath_regime_context_coverage_audit_v1/*`

## Bucket definitions

The runner reports these buckets:

- `ALL`
- `CONTEXT_QUALITY_HIGH`
- `CONTEXT_QUALITY_MEDIUM_OR_HIGH`
- `BREATH_PHASE_KNOWN`
- `BREATH_ALIGNMENT_KNOWN`
- `SYMBOL_REGIME_KNOWN`
- `MARKET_REGIME_KNOWN`
- `BTC_CONTEXT_KNOWN`
- `UNKNOWN_HEAVY`

Rules:

- `UNKNOWN` remains `UNKNOWN`
- no fake precision
- `UNKNOWN_HEAVY` means 4 or more of the core context fields are `UNKNOWN`
- context quality buckets are driven by exact symbol-plus-context matches back to context-builder rows

## Measures

Each bucket reports:

- `profile_row_count`
- `context_row_count`
- `symbols_covered`
- `event_count_sum`
- `eligible_event_count_sum`
- `profile_label_distribution`
- `sample_quality_distribution`
- `avg_mfe_pct_weighted`
- `avg_mae_pct_weighted`
- `avg_fakeout_rate_weighted`
- `avg_reaction_zone_touch_rate_weighted`
- `top_symbols_by_event_count`
- `skipped_reason`
- `research_only=true`

Weighted metrics use `event_count` as the weight.

## Output files

When `--write-files` is set:

```text
data/research/context_qualified_symbol_reaction_profile_audit_v1/
  context_qualified_profile_audit_rows_v1.csv
  context_qualified_profile_audit_rows_v1.jsonl
  manifest_v1.json
```

## CLI

```bash
python -m src.research.run_context_qualified_symbol_reaction_profile_audit_v1 \
  --write-files \
  --output summary
```

## Interpretation

This audit is for research quality only.

It helps answer:

- whether any subset of profiles with stronger context coverage looks more usable
- whether `UNKNOWN_HEAVY` profiles materially differ from known-context profiles
- whether more upstream context recompute work is still justified

It does not:

- promote strategies
- authorize selection/advice/execution changes
- reduce `UNKNOWN` labels by invention
