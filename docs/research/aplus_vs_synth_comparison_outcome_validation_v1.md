# A+ vs Synth Comparison Outcome Validation V1

## Purpose

`run_aplus_vs_synth_comparison_outcome_validation_v1.py` is a research-only,
read-only validator for the existing A+ vs Synth comparison buckets.

It asks one narrow question:

- after the Prime-17 snapshot was taken, did the comparison buckets show any
  forward-return edge by cohort?

It does not:

- create orders
- change `selection_engine`
- change `decision_gate`
- change `execution_planner`
- change `executor`
- change paper/live trading behavior

## Inputs

Required:

- Prime-17 Table 1 raw snapshot
- Prime-17 Table 2 raw snapshot

Reused logic:

- `src/research/run_aplus_vs_synth_comparison_report_v1.py`
- `src/research/run_aplus_prime17_opportunity_report_v1.py`

Read-only market data:

- `obs_market_candle`

Optional Synth context is reused exactly through the existing comparison report
builder. Missing optional tables degrade to `unavailable`.

## Event Time

The validator infers a single snapshot timestamp from the raw filenames, for
example:

- `2026-05-29_1246_table1_prime17_focus_snapshot.txt`

This timestamp is interpreted as Europe/Amsterdam local time and converted to
UTC for point-in-time candle lookup.

That inferred snapshot timestamp is used as the event time for all Prime-17
tokens in the run.

## Output

The validator builds the current comparison rows first, then measures forward
returns by `comparison_bucket`.

Per-token outcome rows include:

- `token`
- `snapshot_ts_utc`
- `comparison_bucket`
- `synth_bucket`
- `aplus_bucket`
- `reference_price`
- `base_candle_ts_utc`
- `return_15m`
- `return_1h`
- `return_4h`
- `return_24h`
- `return_72h`
- `return_168h`
- `complete_15m`
- `complete_1h`
- `complete_4h`
- `complete_24h`
- `complete_72h`
- `complete_168h`
- `avg_mfe`
- `avg_mae`

Bucket summary includes:

- `count`
- `avg_return_15m`
- `avg_return_1h`
- `avg_return_4h`
- `avg_return_24h`
- `avg_return_72h`
- `avg_return_168h`
- `winrate_15m`
- `winrate_1h`
- `winrate_4h`
- `winrate_24h`
- `winrate_72h`
- `winrate_168h`
- `avg_mfe`
- `avg_mae`

## Missing Candles

Missing future candles do not fail the run.

Instead:

- the relevant horizon return stays `null`
- the relevant `complete_*` flag stays `false`
- bucket metrics are computed only from available rows

This is deliberate. The validator must fail open on missing future history and
report incomplete horizons explicitly rather than inventing outcomes.

## Safety

Hard boundaries:

- read-only
- research-only
- no DB writes
- no broker calls
- no broker writes
- no order submission
- no `selection_engine` changes
- no `decision_gate` changes
- no `execution_planner` changes
- no `executor` changes

Safety markers stay explicit in output:

- `broker_calls=0`
- `broker_writes=0`
- `order_submission=0`
- `executor=none`

## CLI

Compile:

```bash
python -m py_compile src/research/run_aplus_vs_synth_comparison_outcome_validation_v1.py
```

Help:

```bash
python -m src.research.run_aplus_vs_synth_comparison_outcome_validation_v1 --help
```

Smoke:

```bash
python -m src.research.run_aplus_vs_synth_comparison_outcome_validation_v1 \
  --table1-raw data/aplus_raw/2026-05-29_1246_table1_prime17_focus_snapshot.txt \
  --table2-raw data/aplus_raw/2026-05-29_1246_table2_prime17_focus_snapshot.txt \
  --output table
```

JSON:

```bash
python -m src.research.run_aplus_vs_synth_comparison_outcome_validation_v1 \
  --table1-raw data/aplus_raw/2026-05-29_1246_table1_prime17_focus_snapshot.txt \
  --table2-raw data/aplus_raw/2026-05-29_1246_table2_prime17_focus_snapshot.txt \
  --output json
```

## Interpretation

This validator is cohort evidence only.

It does not promote a comparison bucket into a strategy rule.

Use it to inspect whether:

- `BOTH_AGREE_UP` behaves better than `A_PLUS_ONLY_WAIT`
- conflict buckets behave worse than aligned buckets
- caution buckets still carry upside noise or downside risk

Any future promotion still needs broader validation, more samples, and a proper
baseline review.
