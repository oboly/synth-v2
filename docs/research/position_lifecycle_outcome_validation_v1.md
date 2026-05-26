# Position Lifecycle Outcome Validation V1

## Purpose

`run_position_lifecycle_outcome_validation_v1.py` is a research-only runner that
measures what happened after account-aware position lifecycle review labels.

This is outcome validation only.

It is not:

- a strategy backtest
- paper execution
- simulated fills
- live trading
- executor enablement

The labels being measured are manual review states, not orders:

- `TRIM_REVIEW`
- `REDUCE_REVIEW`
- `HOLD`
- `RELOAD_REVIEW`

## Questions

Primary questions:

- Did `TRIM_REVIEW` occur before pullback or drawdown?
- Did `REDUCE_REVIEW` avoid poor forward outcomes, or is it too conservative?
- Did `HOLD` outperform trim/reduce review labels?
- Are target-touch trim labels useful on `15m`, `30m`, `1h`, `2h`, `4h`, `8h`,
  and `24h` horizons?

## Boundary

This lane is account-aware read-only research because it validates lifecycle
review for existing positions.

Allowed:

- read `account_position_snapshot`
- read historical `paper_advice_observation`
- read public `market_price_snapshot`
- read public `obs_market_candle`
- reconstruct lifecycle review events for research
- write research artifacts under `data/research/...`

Forbidden:

- broker calls
- broker writes
- order submission
- paper fills
- executor
- live trading
- changing `selection_engine`
- changing `decision_gate`
- changing `execution_planner`

## Reconstruction Rule

There is currently no stored historical lifecycle-event table and no reliable
historical `position_rotation_preview` output history.

There is also no reliable historical `execution_zone_context` series for this
lane. Operational `execution_zone_context` is latest-only.

Therefore the runner reconstructs historical lifecycle review events from:

- `account_position_snapshot`
- historical `paper_advice_observation` zone fields
- historical `market_price_snapshot` when available
- historical `obs_market_candle` 15m path data

If this reconstruction is not possible because required history is missing, the
runner fails closed and reports exact blockers.

## Event Fields

Each reconstructed event row can include:

- `event_ts_utc`
- `symbol`
- `venue`
- `quote`
- `interval`
- `trading_account_id`
- `position_lifecycle_action`
- `position_lifecycle_reason`
- `paper_action`
- `policy_action`
- `position_review_state`
- `setup_fail_reason`
- target / reaction / invalidation context when available
- `current_price`
- `position_qty`
- `position_value`
- `source_modules`
- `missing_inputs`
- intrabar target-touch context when available

## Outcome Horizons

Forward outcomes are measured on:

- `15m`
- `30m`
- `1h`
- `2h`
- `4h`
- `8h`
- `24h`

The current runner derives all horizons from 15m public candle history. If a
separate 30m table is absent, that is reported as a warning, not a blocker.

## Metrics

Per event:

- forward return per horizon
- `max_favorable_excursion_pct`
- `max_adverse_excursion_pct`
- `drawdown_after_event_pct`
- `hit_target_like_move`
- `broke_invalidation_like_move`
- per-horizon completeness flags

Per lifecycle action summary:

- count
- complete horizon counts
- average and median forward return by horizon
- average and median MFE / MAE

## Sampling Modes

Repeated lifecycle rows can be highly autocorrelated.

Supported modes:

- `--event-mode all`
  - every reconstructed event row is used
- `--event-mode transition-only`
  - only rows where `symbol` changes lifecycle action versus the previous row
- `--event-mode cooldown`
  - keeps the first `symbol + lifecycle_action` row
  - skips repeated rows of that same `symbol + lifecycle_action` until
    `--cooldown-minutes` has elapsed

This does not make the study causal. It only reduces repeated-state inflation.

## Interpretation Rules

Interpret results narrowly.

- `TRIM_REVIEW` means trim/harvest review context only, not an executed trim.
- `REDUCE_REVIEW` means defensive review context only, not a sell.
- `HOLD` means no stronger manual review edge was visible from current inputs.
- `RELOAD_REVIEW` means reload/support review context only, not proof that a
  prior trim happened.

Do not promote these labels into strategy logic or execution behavior without
validation.

Validation here still does not cover:

- fills
- fees
- slippage
- order timing
- capital sizing
- account constraints

## Safety

Required safety markers:

```text
broker_calls=0
broker_writes=0
order_submission=0
executor=none
live_trading=false
```

## Outputs

When `--write-files` is enabled:

```text
data/research/position_lifecycle_outcome_validation_v1/outcome_rows_v1.jsonl
data/research/position_lifecycle_outcome_validation_v1/outcome_summary_v1.json
data/research/position_lifecycle_outcome_validation_v1/manifest_v1.json
```
