# Historical Breath Regime Context Coverage Audit V1

## Purpose

`historical_breath_regime_context_coverage_audit_v1` measures how usable the current historical context builder output is for downstream symbol/profile research.

It audits two existing file outputs:

- `historical_breath_regime_context_builder_v1`
- `symbol_reaction_profile_by_context_v1`

This runner is file-only and research-only.

## Boundary

- no DB writes
- no broker calls
- no broker writes
- no order submission
- no selection, decision, execution, or executor integration
- no generated research outputs committed by default

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

Default input files:

```text
data/research/historical_breath_regime_context_builder_v1/historical_breath_regime_context_rows_v1.csv
data/research/symbol_reaction_profile_by_context_v1/symbol_reaction_profile_by_context_rows_v1.csv
```

## Measured outputs

The audit reports:

- total context rows
- total profile rows
- per-symbol context row counts
- per-symbol profile row counts
- unknown-rate for:
  - `breath_phase`
  - `breath_alignment`
  - `market_regime`
  - `btc_context`
  - `symbol_regime`
  - `fibo_context`
  - `aplus_context_state`
  - `martee_context_state`
- `quality_state` distribution
- `confidence_bucket` distribution
- `profile_label` distribution
- `sample_quality` distribution
- context-enriched profile rows vs unknown-heavy rows
- top missing context fields
- recommended next enrichment target

## Coverage status

V1 emits one of:

- `USABLE`
- `PARTIAL`
- `UNKNOWN_HEAVY`
- `UNUSABLE_NO_PROFILE_ROWS`

Interpretation:

- `USABLE`: most profile rows already resolve to non-unknown breath/regime context
- `PARTIAL`: profiler works, but context coverage still has notable gaps
- `UNKNOWN_HEAVY`: current historical context is too sparse for strong downstream conclusions
- `UNUSABLE_NO_PROFILE_ROWS`: no profile rows exist to audit

## CLI

```bash
python -m src.research.run_historical_breath_regime_context_coverage_audit_v1 \
  --output summary
```

Optional file output:

```bash
python -m src.research.run_historical_breath_regime_context_coverage_audit_v1 \
  --write-files \
  --output json \
  --output-dir data/research/historical_breath_regime_context_coverage_audit_v1
```

## Output files

When `--write-files` is set:

```text
data/research/historical_breath_regime_context_coverage_audit_v1/
  context_coverage_summary_v1.csv
  symbol_context_coverage_rows_v1.csv
  manifest_v1.json
```

## Recommended use

Run this audit after:

1. rebuilding historical context rows
2. rerunning `symbol_reaction_profile_by_context_v1`

Use the result to decide whether the next batch should:

- densify historical market-breath rows
- improve historical regime timestamp alignment
- add fibo context enrichment
- expand A+ historical coverage
