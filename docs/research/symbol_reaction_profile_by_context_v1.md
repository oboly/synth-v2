# Symbol Reaction Profile By Context V1

## Purpose

`symbol_reaction_profile_by_context_v1` measures how individual symbols behave in reload / reaction / scalp-style situations when conditioned by historical context rows.

This runner is:

- research-only
- market-only
- account-agnostic
- file-input / file-output only

It is not a strategy backtest, not an execution path, and not a trade permission layer.

## Inputs

Primary files:

- `data/research/position_lifecycle_outcome_validation_v1/outcome_rows_v1.jsonl`
- `data/research/fibo_target_map_v1/fibo_target_map_rows_v1.csv`
- `data/research/historical_breath_regime_context_builder_v1/historical_breath_regime_context_rows_v1.jsonl`
  or
- `data/research/historical_breath_regime_context_builder_v1/historical_breath_regime_context_rows_v1.csv`

## Join contract

Context joins use:

- join by `symbol`
- nearest `context.asof_ts_utc <= event.event_ts_utc`
- max staleness threshold of 7 days in V1
- missing context becomes `UNKNOWN`
- default mode does not drop events solely because context is missing

## Context buckets

Each output row is keyed by:

```text
symbol
breath_phase
breath_alignment
market_regime
btc_context
symbol_regime
fibo_context
```

## Measured fields

Per symbol + context bucket:

```text
event_count
eligible_event_count
avg_retrace_to_entry_low_pct
avg_retrace_to_entry_mid_pct
avg_retrace_to_entry_high_pct
reaction_zone_touch_rate
bounce_15m_pct
bounce_30m_pct
bounce_1h_pct
bounce_4h_pct
bounce_24h_pct
avg_mfe_pct
avg_mae_pct
mfe_mae_ratio
fakeout_rate
best_reload_zone_part
best_hold_horizon
volatility_bucket
sample_quality
profile_label
```

## Profile labels

V1 uses deterministic research labels:

- `FAST_REACTOR`
- `DEEP_RETRACER`
- `SLOW_GRINDER`
- `FAKEOUT_PRONE`
- `CONTEXT_DEPENDENT`
- `INSUFFICIENT_SAMPLE`
- `MIXED`

These are descriptive research summaries only. They must not be treated as orders, permissions, or live strategy routes.

## CLI

```bash
python -m src.research.run_symbol_reaction_profile_by_context_v1 \
  --symbols WLD,NEAR,HYPE,TAO,FET,ALGO,XLM \
  --min-events 1 \
  --write-files \
  --output summary \
  --output-dir data/research/symbol_reaction_profile_by_context_v1
```

## Output files

When `--write-files` is used:

```text
data/research/symbol_reaction_profile_by_context_v1/
  symbol_reaction_profile_by_context_rows_v1.csv
  symbol_reaction_profile_by_context_rows_v1.jsonl
  manifest_v1.json
```

## Safety markers

```text
research_only=true
broker_calls=0
broker_writes=0
order_submission=0
executor=none
db_writes=0
```

## Notes

- V1 preserves symbol identity and does not aggregate symbols away.
- V1 prefers `UNKNOWN` over silently fabricating missing context.
- V1 uses fibo rows only as a conservative context hint, not as a trade plan.
- V1 is suitable as a downstream consumer of `historical_breath_regime_context_builder_v1`.

## Recommended next step

Use these profile rows to review which symbols behave like fast reactors, deep retracers, slow grinders, or fakeout-prone instruments under specific historical contexts before any later strategy design work.
