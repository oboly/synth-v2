# context_touch_fakeout_robustness_audit_v1

## Purpose

Audit whether the strongest-looking touch/fakeout shape survives simple concentration checks before any further research promotion:

- `context_quality_tier = MARKET_ONLY_CONTEXT`
- `reaction_zone_touch = TRUE`
- `fakeout_flag = FALSE`

This is research-only microscope mode. It does not create strategy, advice, or execution permissions.

Safety markers:

- `research_only=true`
- `broker_calls=0`
- `broker_writes=0`
- `order_submission=0`
- `executor=none`
- `db_writes=0`

## Input

- `data/research/event_level_symbol_reaction_profile_by_context_v1_event_range/event_level_symbol_reaction_profile_by_context_rows_v1.csv`

## Method

### Baseline

Compute baseline metrics for the target shape:

- `event_count`
- `avg_return_4h_pct`
- `avg_return_24h_pct`
- `avg_mfe_pct`
- `avg_mae_pct`
- `mfe_mae_ratio`

### Leave-one-symbol-out

Exclude each symbol once and recompute the same metrics.

Purpose:

- detect whether the target shape depends mainly on one symbol

### Leave-one-time-bucket-out

Use 3-day buckets. Exclude each bucket once and recompute the same metrics.

Purpose:

- detect whether the target shape depends mainly on one short time cluster

### Concentration Metrics

- `top_symbol_event_share`
- `top_symbol_return_contribution_share`
- `top_time_bucket_event_share`
- `top_time_bucket_return_contribution_share`

## Robustness Classification

Possible classifications:

- `ROBUST_ENOUGH_FOR_MORE_RESEARCH`
- `SYMBOL_CONCENTRATED`
- `TIME_CONCENTRATED`
- `SAMPLE_TOO_SMALL`
- `NOT_ROBUST`
- `UNKNOWN`

These are research diagnostics only, not trade recommendations.

## Output Files

When `--write-files` is used:

- `context_touch_fakeout_robustness_rows_v1.csv`
- `context_touch_fakeout_leave_one_symbol_rows_v1.csv`
- `context_touch_fakeout_leave_one_time_rows_v1.csv`
- `manifest_v1.json`

Default output dir:

- `data/research/context_touch_fakeout_robustness_audit_v1/`

## CLI

```bash
python -m src.research.run_context_touch_fakeout_robustness_audit_v1 \
  --event-level-rows data/research/event_level_symbol_reaction_profile_by_context_v1_event_range/event_level_symbol_reaction_profile_by_context_rows_v1.csv \
  --write-files \
  --output summary \
  --output-dir data/research/context_touch_fakeout_robustness_audit_v1
```
