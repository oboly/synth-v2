# Incremental Multi Horizon Fib Backtest V1

## Purpose

`run_multi_horizon_fib_backtest_v1` is a research-only foundation for
continuous fib swing/backtest reconstruction across multiple symbols and trading
horizons.

It does not:

- write DB
- read account state
- call broker APIs
- create orders
- change runtime or cockpit behavior

## Modes

- `bootstrap`
  - process all available trustworthy candles
  - create missing checkpoints
  - resume cleanly when outputs already exist
- `incremental`
  - load checkpoint per `symbol x fib_trading_horizon`
  - read new closed candles plus bounded overlap
  - recompute tail deterministically
  - merge/dedupe by stable event keys
- `rebuild`
  - ignore existing checkpoint state for the selected scope
  - recompute from raw candles

## Checkpoints

Stored under:

`data/research/multi_horizon_fib_backtest_v1/checkpoints/`

Minimum fields:

- symbol / venue / quote
- `fib_trading_horizon`
- primary/support interval metadata
- analysis and algorithm versions
- `last_processed_primary_close_ts`
- `last_processed_support_close_ts`
- `last_confirmed_pivot_ts`
- active swing identifiers/prices/timestamps/state
- active fib levels
- `completed_swing_count`
- overlap setting
- `updated_ts`
- source refs

Version mismatch fails closed and requires `--mode rebuild`.

## Outputs

When `--write-files` is passed:

- `swing_events_v1.csv`
- `swing_events_v1.jsonl`
- `active_swing_rows_v1.csv`
- `fib_level_outcomes_v1.csv`
- `profile_stats_v1.csv`
- `context_profile_stats_v1.csv`
- `checkpoint_index_v1.json`
- `checkpoints/<symbol>_<horizon>_checkpoint_v1.json`
- `coverage_summary_v1.csv`
- `failure_skip_summary_v1.csv`
- `manifest_v1.json`

Generated outputs are local artifacts and must not be committed.

## Context Handling

The runner preserves optional historical context from existing read-only csv
sources when available:

- `market_regime`
- `symbol_regime`
- `breath_phase`
- `breath_alignment`

Unknown/missing context remains `UNKNOWN`.

## Fee Assumption

Default fee assumption is explicit:

- `fee_bps_per_side=25`

The manifest records the applied fee input. No undocumented fee is invented.

## Example

```bash
python -m src.research.run_multi_horizon_fib_backtest_v1 \
  --mode bootstrap \
  --horizons SHORT,MEDIUM,LONG \
  --symbols WLD,ONDO,NEAR \
  --venue bitvavo \
  --quote EUR \
  --workers 2 \
  --write-files \
  --output summary \
  --output-dir /tmp/multi_horizon_fib_backtest_v1_smoke
```

Incremental rerun on the same output directory:

```bash
python -m src.research.run_multi_horizon_fib_backtest_v1 \
  --mode incremental \
  --horizons SHORT,MEDIUM,LONG \
  --symbols WLD,ONDO,NEAR \
  --venue bitvavo \
  --quote EUR \
  --workers 2 \
  --write-files \
  --output summary \
  --output-dir /tmp/multi_horizon_fib_backtest_v1_smoke
```
