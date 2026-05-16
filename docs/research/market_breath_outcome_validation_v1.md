# Market Breath Outcome Validation V1

## Purpose

Market Breath outcome validation V1 is a research-only dry lane that measures forward market behavior after existing Market Breath V1 phase labels across historical as-of samples.

This is outcome measurement, not strategy. It does not recommend buys or sells, does not change thresholds, does not promote Market Breath to runtime logic, and does not write to the database.

## Why this follows calibration and neutral rest-bucket review

The prior sequence established the lane order:

```text
Market Breath V1.1 calibration
-> neutral rest-bucket review
-> outcome validation dry lane
-> optional threshold calibration only if needed
-> optional strategy candidate only after stronger validation
```

The calibration audit showed that `NEUTRAL_TRANSITION` is structurally dominant and that specific phases are selective. The neutral rest-bucket review decided to keep `NEUTRAL_TRANSITION` as the conservative rest bucket for now and validate only phases with enough sample mass first.

This runner therefore measures outcomes without changing Market Breath V1 labels or thresholds.

## Input data

The runner reads:

- `obs_market_candle`
- `asset` metadata
- existing Market Breath V1 observation logic

It does not read:

- A+ inputs
- PRO inputs
- symbolic labels
- account data
- broker data
- selection, advice, decision, execution, or order state

Default runtime parameters:

```text
venue=bitvavo
interval=4h
lookback_candles=120
sample_step_hours=24
output_dir=data/research/market_breath_outcome_validation_v1
```

## Sampling method

The runner reuses the same historical as-of selection approach as the V1.1 calibration audit:

- target one sample per day
- prefer 00:00 UTC when the sample step is 24 hours
- select the nearest available 4h close to each target timestamp
- de-duplicate selected close timestamps
- compute Market Breath V1 observations for all eligible enabled/tradeable assets at each as-of

For outcome validation, the default `to_ts` is the latest available candle minus the 24-candle outcome horizon. This keeps the default 60-day window focused on as-of samples that can have full 24-candle forward outcomes when future asset candles are present.

## Outcome horizons

For the 4h interval, the runner calculates close-to-close forward returns:

- `fwd_return_1c`
- `fwd_return_3c`
- `fwd_return_6c`
- `fwd_return_12c`
- `fwd_return_18c`
- `fwd_return_24c`

It also calculates:

- `max_fwd_return_24c`
- `min_fwd_return_24c`
- `max_drawdown_24c_from_asof_close`
- `max_runup_24c_from_asof_close`

Future candles are used only after each historical as-of timestamp and only to calculate research outcome metrics. Outcomes do not feed back into label creation, threshold logic, or runtime behavior.

## Output files

Per-row output:

```text
data/research/market_breath_outcome_validation_v1/outcome_rows_v1.jsonl
```

Summary output:

```text
data/research/market_breath_outcome_validation_v1/outcome_summary_v1.json
```

Initial generated summary:

```text
sample_count=60
asset_count_avg=41.0
row_count=2460
outcome_available_count=2135

EXHALE_EXPANSION count=165 available=145 avg_fwd_return_24c=-0.619549 median_fwd_return_24c=-2.330056 positive_rate_24c=37.241379
COLLAPSE_RESET count=89 available=77 avg_fwd_return_24c=2.712149 median_fwd_return_24c=3.409656 positive_rate_24c=77.922078
OVERBREATH_EXTENSION count=29 available=25 avg_fwd_return_24c=-0.975624 median_fwd_return_24c=-2.773642 positive_rate_24c=36.0
INHALE_ACCUMULATION count=16 available=8 avg_fwd_return_24c=-0.821763 median_fwd_return_24c=0.354712 positive_rate_24c=62.5
HOLD_COMPRESSION count=4 available=1 avg_fwd_return_24c=-3.382801 median_fwd_return_24c=-3.382801 positive_rate_24c=0.0
NEUTRAL_TRANSITION count=2157 available=1879 avg_fwd_return_24c=0.628198 median_fwd_return_24c=0.070389 positive_rate_24c=50.399148
```

## Phase interpretation rules

The summary assigns interpretation buckets:

- `EXHALE_EXPANSION`: `PRIMARY`
- `COLLAPSE_RESET`: `SECONDARY`
- `OVERBREATH_EXTENSION`: `EXPLORATORY`
- `INHALE_ACCUMULATION`: `EXPLORATORY`
- `HOLD_COMPRESSION`: `EXCLUDED_LOW_SAMPLE`
- `NEUTRAL_TRANSITION`: `BASELINE_REST_BUCKET`
- `INSUFFICIENT_DATA`: `EXCLUDED_LOW_SAMPLE`

Interpretation constraints:

- Do not declare strategy edge.
- Do not recommend buys or sells.
- Do not promote to runtime.
- Treat `EXHALE_EXPANSION` as the primary validation candidate.
- Treat `COLLAPSE_RESET` as the secondary validation candidate.
- Treat `OVERBREATH_EXTENSION` and `INHALE_ACCUMULATION` as exploratory only.
- Treat `HOLD_COMPRESSION` as excluded from conclusions due low sample count.
- Treat `NEUTRAL_TRANSITION` as the rest-bucket baseline.
- Treat this as first-pass outcome measurement only.

## Limitations

- This is a dry research lane, not a trading system.
- It uses deterministic V1 labels from historical candles and then measures future close-to-close returns.
- It does not account for fills, fees, slippage, sizing, portfolio constraints, or execution timing.
- It does not prove predictive value, profitability, or strategy suitability.
- Sparse phases may not have enough sample mass for stable conclusions.
- Missing future candles reduce `outcome_available_count` for some rows.

## No threshold changes

No Market Breath V1 threshold logic is changed by this runner.

Outcome measurements are not used to change phase labels, thresholds, scores, or confidence values. Any threshold calibration remains a separate optional research patch and must rerun the calibration audit before further interpretation.

## No strategy/runtime promotion

This output is not:

- a selection modifier
- advice
- a decision permission layer
- execution intent
- an order plan
- a broker instruction
- a runtime feature

Safety markers expected in output:

```text
broker_calls=0
broker_writes=0
order_submission=0
live_orders=0
db_writes=0
selection_engine_changes=0
advice_engine_changes=0
decision_gate_changes=0
execution_planner_changes=0
executor_changes=0
```

## CLI

Compile check:

```bash
python -m py_compile src/research/run_market_breath_outcome_validation_v1.py
```

Dry run:

```bash
python -m src.research.run_market_breath_outcome_validation_v1 \
  --venue bitvavo \
  --interval 4h \
  --lookback-candles 120 \
  --sample-step-hours 24 \
  --output table
```

Write files:

```bash
python -m src.research.run_market_breath_outcome_validation_v1 \
  --venue bitvavo \
  --interval 4h \
  --lookback-candles 120 \
  --sample-step-hours 24 \
  --write-files \
  --output table
```
