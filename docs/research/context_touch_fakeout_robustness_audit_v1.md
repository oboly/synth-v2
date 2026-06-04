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

## Conclusion

Current conclusion from `context_touch_fakeout_robustness_audit_v1`:

- the target shape stays **research-only**
- it is **not robust enough for strategy/advice promotion**
- it must **not** be used downstream in runtime, selection, advice, decision, execution, or dashboard actioning

Reason:

- the apparent positive edge is too concentrated in one symbol and one short date cluster
- excluding `XLM` drops `avg_return_24h_pct` materially
- excluding the `2026-05-25` 3-day bucket drops `avg_return_24h_pct` materially
- `XLM` contributes roughly `79.7%` of target-shape return contribution
- the `2026-05-25` bucket contributes roughly `75.6%` of target-shape return contribution

Interpretation:

- the observed shape is still useful as a diagnostic research lead
- it is **not** eligible for promotion into strategy logic
- it is **not** eligible for promotion into advice logic
- it is **not** eligible for paper-routing shortcuts or runtime policy

Optional future work:

- widen the event window and rerun the same robustness audit
- run an `XLM`-specific explanatory audit to understand why the target shape clusters there
- keep any follow-up strictly research-only until concentration risk is reduced materially
