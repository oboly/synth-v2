# Position Lifecycle Event Chart V1

## Purpose

`run_position_lifecycle_event_chart_v1.py` renders research-only visual review
charts for selected lifecycle outcome rows.

It adds the missing visual inspection layer on top of:

- lifecycle outcome rows from `position_lifecycle_outcome_validation_v1`
- existing cockpit-style static HTML patterns
- existing read-only candle access patterns

It is not:

- lifecycle classification
- outcome validation logic
- strategy scoreboard logic
- paper trading
- live trading
- order intent
- execution

## Inputs

Primary input:

- `data/research/position_lifecycle_outcome_validation_v1/outcome_rows_v1.jsonl`

The runner reuses existing event rows directly and does not recalculate
lifecycle labels.

It also reads public candles from `obs_market_candle` for chart rendering only.

Defaults:

- `--input-rows data/research/position_lifecycle_outcome_validation_v1/outcome_rows_v1.jsonl`
- `--venue bitvavo`
- `--quote EUR`
- `--chart-interval 15m`
- `--before-hours 48`
- `--after-hours 24`
- `--max-charts 50`
- `--output-dir data/research/position_lifecycle_event_chart_v1`

## Filters And Sorting

Optional filters:

- `--bucket "RELOAD_REVIEW|APLUS_CONTEXT"`
- `--action RELOAD_REVIEW`
- `--symbol NEAR`

Sort choices:

- `adjusted4h_desc`
- `adjusted4h_asc`
- `event_ts_desc`
- `mae_desc`
- `mfe_desc`
- `opportunity_cost4h_desc`
- `avoided_drawdown4h_desc`

## Output Files

- `index.html`
- chart SVG files
- `manifest_v1.json`
- `selected_events_v1.jsonl`

## Chart Content

Each chart shows:

- 15m or requested-interval candles around the lifecycle event
- vertical event marker at `event_ts_utc`
- lifecycle action label
- `primary_reason_bucket`
- `secondary_reason_buckets` when available
- lifecycle trigger text when available
- raw forward returns at `15m`, `1h`, `4h`, `24h`
- adjusted score at `4h` and `24h`
- `MFE` / `MAE`
- entry / target / invalidation lines when available in the outcome row
- source modules and missing inputs when available

This lane uses existing row fields when available. It does not invent new
signals or recalculate lifecycle states.

## Index Page

The index page shows:

- report title
- explicit safety banner
- selected filters and sort
- review guidance legend:
  - `GOOD_TRIGGER`
  - `TOO_EARLY`
  - `TOO_LATE`
  - `NOISY`
  - `WRONG_ACTION`
  - `NEEDS_ZONE_CONTEXT`
- summary table with:
  - `symbol`
  - `event_ts_utc`
  - `action`
  - `primary_reason_bucket`
  - `adjusted4h`
  - `adjusted24h`
  - `raw4h`
  - `raw24h`
  - `mfe`
  - `mae`
  - chart link

These guidance labels are review aids only. They are not runtime labels and not
order instructions.

## Architecture Boundary

This runner is research-only visualization.

Allowed:

- read outcome rows from file
- read public candles
- render static HTML and SVG files under `data/research/...`

Forbidden:

- lifecycle classification changes
- outcome validation logic changes unless explicitly needed upstream
- dashboard/runtime changes
- `selection_engine` changes
- `decision_gate` changes
- `execution_planner` changes
- `executor` changes
- broker writes
- order submission
- paper fills
- live trading

## Safety

Manifest markers:

- `db_writes=0`
- `broker_calls=0`
- `broker_writes=0`
- `order_submission=0`
- `executor=none`
- `live_trading=false`
- `visualization_only=true`

## Smoke

Compile:

```bash
python -m py_compile src/research/run_position_lifecycle_event_chart_v1.py
```

Help:

```bash
python -m src.research.run_position_lifecycle_event_chart_v1 --help
```

Smoke summary:

```bash
python -m src.research.run_position_lifecycle_event_chart_v1 --max-charts 10 --output summary
```

Filtered smoke:

```bash
python -m src.research.run_position_lifecycle_event_chart_v1 --action RELOAD_REVIEW --max-charts 10 --output summary
python -m src.research.run_position_lifecycle_event_chart_v1 --bucket "RELOAD_REVIEW|APLUS_CONTEXT" --max-charts 10 --output summary
```

File output smoke:

```bash
python -m src.research.run_position_lifecycle_event_chart_v1 --max-charts 10 --write-files --output summary
```
