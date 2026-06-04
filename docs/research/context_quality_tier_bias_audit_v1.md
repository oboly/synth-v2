# context_quality_tier_bias_audit_v1

## Purpose

Audit whether the observed ordering of `context_quality_tier` outcomes is robust or mostly explained by:

- symbol concentration
- time-bucket bias
- breath subtype sparsity
- fakeout / touch distribution

This is a research-quality diagnostic only. It does not promote any tier to strategy, advice, or execution.

Safety markers:

- `research_only=true`
- `broker_calls=0`
- `broker_writes=0`
- `order_submission=0`
- `executor=none`
- `db_writes=0`

## Inputs

Primary event-level source:

- `data/research/event_level_symbol_reaction_profile_by_context_v1_event_range/event_level_symbol_reaction_profile_by_context_rows_v1.csv`

Optional comparison input:

- `data/research/context_quality_tier_outcome_evaluation_v1/context_quality_tier_outcome_rows_v1.csv`

## Scope

Use only existing event-level fields.

Missing fields stay blank / `UNKNOWN`.
No new labels are invented.
No recommendation to trade is produced.

## Output Views

### 1. Per-symbol tier rows

File:

- `context_quality_tier_symbol_bias_rows_v1.csv`

Fields:

- `symbol`
- `context_quality_tier`
- `event_count`
- `avg_mfe_pct`
- `avg_mae_pct`
- `mfe_mae_ratio`
- `avg_return_4h_pct`
- `avg_return_24h_pct`
- `fakeout_rate`
- `reaction_zone_touch_rate`
- `sample_quality`

### 2. Time-bucket rows

File:

- `context_quality_tier_time_bias_rows_v1.csv`

Uses 3-day buckets to expose short-window skew.

Fields:

- `event_date`
- `time_bucket_start_utc`
- `context_quality_tier`
- `event_count`
- `tier_distribution_in_bucket`
- `avg_mfe_pct`
- `avg_mae_pct`
- `mfe_mae_ratio`
- `avg_return_4h_pct`
- `avg_return_24h_pct`
- `sample_quality`

### 3. Breath subtype rows

File:

- `context_quality_tier_breath_subtype_rows_v1.csv`

Only for `BREATH_CONTEXT`.

Fields:

- `breath_phase`
- `breath_alignment`
- `event_count`
- `avg_return_4h_pct`
- `avg_return_24h_pct`
- `fakeout_rate`
- `touch_rate`
- `sample_quality`

### 4. Fakeout / touch cross-tab

File:

- `context_quality_tier_fakeout_touch_rows_v1.csv`

Fields:

- `context_quality_tier`
- `reaction_zone_touch`
- `fakeout_flag`
- `event_count`
- `avg_mfe_pct`
- `avg_mae_pct`
- `mfe_mae_ratio`
- `avg_return_4h_pct`
- `avg_return_24h_pct`
- `sample_quality`

## Bias Interpretation

The audit is meant to answer whether:

- `BREATH_CONTEXT` is just too thin to compare fairly
- one or two symbols dominate its negative sample
- specific breath phase/alignment subtypes drive the weakness
- `MARKET_ONLY_CONTEXT` looks strong mostly because of event timing or touch distribution

The manifest includes a compact `bias_assessment` field such as:

- `BREATH_SAMPLE_TOO_THIN`
- `BREATH_SUBTYPE_CONCENTRATED`
- `SYMBOL_OUTLIER_BIAS`
- `LIKELY_BIASED_OR_CONTEXT_THIN`
- `PLAUSIBLY_ROBUST`

These are research diagnostics only, not trade permissions.

## CLI

```bash
python -m src.research.run_context_quality_tier_bias_audit_v1 \
  --event-level-rows data/research/event_level_symbol_reaction_profile_by_context_v1_event_range/event_level_symbol_reaction_profile_by_context_rows_v1.csv \
  --write-files \
  --output summary \
  --output-dir data/research/context_quality_tier_bias_audit_v1
```

## Output Files

When `--write-files` is used:

- `context_quality_tier_symbol_bias_rows_v1.csv`
- `context_quality_tier_time_bias_rows_v1.csv`
- `context_quality_tier_breath_subtype_rows_v1.csv`
- `context_quality_tier_fakeout_touch_rows_v1.csv`
- `manifest_v1.json`
