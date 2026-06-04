# Event Bearing Context Alignment Audit V1

## Purpose

`event_bearing_context_alignment_audit_v1` audits why richer recomputed market-breath rows still do not produce usable `BREATH_PHASE_KNOWN` and `BREATH_ALIGNMENT_KNOWN` profile buckets.

It is a research-only file audit. It does not create labels, modify runtime logic, or recommend trades.

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

Optional supporting input:

- `data/research/context_qualified_symbol_reaction_profile_audit_v1/context_qualified_profile_audit_rows_v1.csv`

## Important limitation

The current profile export has no timestamps.

That means this audit cannot perform a direct event-time join from profile rows to recompute rows.

V1 therefore uses:

- symbol-plus-context-bucket overlap
- context-builder rows as the timestamp-bearing bridge

This is deliberate and avoids inventing event timestamps that are not present in the profile file.

## Measures

Per symbol, the audit reports:

- `profile_row_count`
- `event_count_sum`
- `recompute_row_count`
- `recompute_known_breath_phase_rows`
- `recompute_known_breath_alignment_rows`
- `recompute_known_context_rows`
- `context_row_count`
- `context_overlap_count`
- `overlap_profile_row_count`
- `overlap_event_count`
- `known_rows_with_zero_profile_events`
- `profile_unknown_heavy_event_count`
- `issue_classification`

## Issue classifications

- `USABLE_CONTEXT_OVERLAP`
  - known recompute context overlaps event-bearing profile buckets
- `NO_RECOMPUTE_KNOWN_ROWS`
  - no recompute rows exist for the symbol
- `KNOWN_ROWS_NOT_EVENT_BEARING`
  - recompute known rows exist, but no event-bearing profile overlap exists
- `PROFILE_BUCKET_AGGREGATION_LOSSES`
  - known recompute rows overlap context-builder rows, but not event-bearing profile buckets
- `LIVE_SEMANTICS_UNKNOWN`
  - recompute rows exist but remain unknown under live-compatible semantics
- `UNKNOWN`
  - none of the above explained the symbol cleanly

## Output files

When `--write-files` is set:

```text
data/research/event_bearing_context_alignment_audit_v1/
  event_bearing_context_alignment_rows_v1.csv
  manifest_v1.json
```

## CLI

```bash
python -m src.research.run_event_bearing_context_alignment_audit_v1 \
  --write-files \
  --output summary
```

## Interpretation

This runner helps answer:

- whether known recompute context exists but never becomes event-bearing
- whether profile aggregation is hiding useful context overlap
- whether remaining unknown-heavy behavior is simply a valid live-semantics limitation

It does not:

- invent labels
- reduce `UNKNOWN`
- promote any strategy or execution action
