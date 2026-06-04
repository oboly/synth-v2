# Event-Level Symbol Reaction Profile By Context v1

## Purpose

Preserve per-event historical context before aggregate symbol/context profiling collapses it into bucket rows.

This runner is research-only. It does not create strategy permissions, trading decisions, broker calls, or DB writes.

Safety markers:

- `research_only=true`
- `broker_calls=0`
- `broker_writes=0`
- `order_submission=0`
- `executor=none`
- `db_writes=0`

## Inputs

Primary event source:

- `data/research/position_lifecycle_outcome_validation_v1/outcome_rows_v1.jsonl`

Primary context source:

- `data/research/historical_breath_regime_context_builder_v1/historical_breath_regime_context_rows_v1.csv|jsonl`

Optional upstream fallback:

- `data/research/historical_market_breath_source_recompute_v1/historical_market_breath_source_recomputed_rows_v1.csv`

Optional fibo source:

- `data/research/fibo_target_map_v1/fibo_target_map_rows_v1.csv`

## Join Contract

- Join by `symbol`.
- Use nearest `asof_ts_utc <= event_ts_utc`.
- Respect the same staleness window used by the aggregate profile builder.
- Keep `UNKNOWN` when no supported source exists.
- Never overwrite known context-builder values with recompute `UNKNOWN`.
- Use recompute rows only as conservative fallback when context-builder fields remain `UNKNOWN`.

## Output Rows

One output row per lifecycle/reaction event.

Fields:

- `symbol`
- `event_ts_utc`
- `venue`
- `interval`
- `context_asof_ts_utc`
- `recompute_asof_ts_utc`
- `breath_phase`
- `breath_alignment`
- `market_regime`
- `btc_context`
- `symbol_regime`
- `fibo_context`
- `context_quality_state`
- `context_confidence_bucket`
- `current_price`
- `entry_zone_low`
- `entry_zone_high`
- `entry_zone_mid`
- `retrace_to_entry_low_pct`
- `retrace_to_entry_mid_pct`
- `retrace_to_entry_high_pct`
- `max_favorable_excursion_pct`
- `max_adverse_excursion_pct`
- `drawdown_after_event_pct`
- `forward_return_15m`
- `forward_return_30m`
- `forward_return_1h`
- `forward_return_4h`
- `forward_return_24h`
- `reaction_zone_touch`
- `fakeout_flag`
- `context_quality_tier` — one of `BREATH_CONTEXT`, `SYMBOL_REGIME_CONTEXT`, `MARKET_ONLY_CONTEXT`, `UNKNOWN_CONTEXT`
- `source_refs`
- `research_only=true`

If the event source does not carry a metric, the field stays blank / `UNKNOWN` rather than being invented.

## Context Quality Tier

Each event row carries a `context_quality_tier` derived from its embedded context fields:

| Tier | Condition |
|---|---|
| `BREATH_CONTEXT` | `breath_phase` or `breath_alignment` is known |
| `SYMBOL_REGIME_CONTEXT` | `symbol_regime` known; breath fields UNKNOWN |
| `MARKET_ONLY_CONTEXT` | `market_regime` or `btc_context` known; breath and symbol_regime UNKNOWN |
| `UNKNOWN_CONTEXT` | all context fields UNKNOWN |

Tier assignment is deterministic from field values. UNKNOWN remains UNKNOWN — tiers are never invented or upgraded.

## Why This Exists

`run_symbol_reaction_profile_by_context_v1` groups events into symbol/context buckets. That is useful for profile summaries, but it can hide whether a specific event actually had known context before aggregation.

This runner keeps the event rows intact so later audits can answer:

- did the event itself have known context?
- did recompute/context-builder overlap exist at the exact event timestamp?
- did aggregate profiling collapse useful event-level context into broader unknown-heavy buckets?

## Output Files

When `--write-files` is used:

- `event_level_symbol_reaction_profile_by_context_rows_v1.csv`
- `event_level_symbol_reaction_profile_by_context_rows_v1.jsonl`
- `manifest_v1.json`

Default output dir:

- `data/research/event_level_symbol_reaction_profile_by_context_v1/`

## CLI

```bash
python -m src.research.run_event_level_symbol_reaction_profile_by_context_v1 \
  --symbols XLM \
  --context-rows data/research/historical_breath_regime_context_builder_v1_xlm_full/historical_breath_regime_context_rows_v1.csv \
  --recompute-rows data/research/historical_market_breath_source_recompute_v1_xlm_full/historical_market_breath_source_recomputed_rows_v1.csv \
  --write-files \
  --output summary \
  --output-dir data/research/event_level_symbol_reaction_profile_by_context_v1_xlm_full
```

## Boundary

This runner is an audit/export layer only.

It must not:

- write DB state
- call broker APIs
- create orders
- change selection / decision / execution logic
- reinterpret research labels as trade permission
