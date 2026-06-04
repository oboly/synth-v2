# context_touch_fakeout_shape_audit_v1

## Purpose

Audit whether touch/fakeout outcome shape is stable across context tiers, symbols, and time buckets.

This is a research-only decomposition of the existing event-level export. It does not create strategy permissions, advice, or execution intent.

Safety markers:

- `research_only=true`
- `broker_calls=0`
- `broker_writes=0`
- `order_submission=0`
- `executor=none`
- `db_writes=0`

## Input

- `data/research/event_level_symbol_reaction_profile_by_context_v1_event_range/event_level_symbol_reaction_profile_by_context_rows_v1.csv`

## Shape Buckets

Each event is grouped by:

- `context_quality_tier`
- `reaction_zone_touch` = `TRUE` / `FALSE` / `UNKNOWN`
- `fakeout_flag` = `TRUE` / `FALSE` / `UNKNOWN`

Missing touch/fakeout fields stay `UNKNOWN`. No new inference is allowed.

## Outputs

When `--write-files` is used:

- `context_touch_fakeout_shape_rows_v1.csv`
- `context_touch_fakeout_symbol_rows_v1.csv`
- `context_touch_fakeout_time_rows_v1.csv`
- `manifest_v1.json`

Default output dir:

- `data/research/context_touch_fakeout_shape_audit_v1/`

## Shape Row Fields

- `context_quality_tier`
- `reaction_zone_touch`
- `fakeout_flag`
- `event_count`
- `avg_return_4h_pct`
- `avg_return_24h_pct`
- `avg_mfe_pct`
- `avg_mae_pct`
- `mfe_mae_ratio`
- `sample_quality`

## Per-Symbol Shape Row Fields

- `symbol`
- `context_quality_tier`
- `reaction_zone_touch`
- `fakeout_flag`
- `event_count`
- `avg_return_24h_pct`
- `fakeout_rate`
- `touch_rate`
- `sample_quality`

## Time Bucket Fields

3-day buckets:

- `time_bucket_start_utc`
- `context_quality_tier`
- `reaction_zone_touch`
- `fakeout_flag`
- `event_count`
- `avg_return_24h_pct`
- `sample_quality`

## Stability Interpretation

The manifest includes a compact `stability_assessment` for the strongest-looking positive shape:

- `PLAUSIBLY_STABLE`
- `TARGET_SAMPLE_THIN`
- `SYMBOL_CONCENTRATED`
- `SYMBOL_OUTLIER_BIAS`
- `TIME_CONCENTRATED`
- `MIXED_TIME_SHAPE`

This is a research diagnostic only, not a trade recommendation.

## CLI

```bash
python -m src.research.run_context_touch_fakeout_shape_audit_v1 \
  --event-level-rows data/research/event_level_symbol_reaction_profile_by_context_v1_event_range/event_level_symbol_reaction_profile_by_context_rows_v1.csv \
  --write-files \
  --output summary \
  --output-dir data/research/context_touch_fakeout_shape_audit_v1
```
