# Pipeline Visual Backtest V1

Date: 2026-05-18

Status: research-only visual inspection runner.

## Purpose

`src/research/run_pipeline_visual_backtest_v1.py` creates deterministic
research-only simulated pipeline events and a Plotly candlestick chart for one
symbol over one time window.

The runner is intended to make the current setup/paper/zone pipeline inspectable
on a price path. It is not a trading engine, not a decision gate, and not an
execution simulator.

## Boundaries

Allowed:

- read `obs_market_candle`
- read `selection_state`
- read `trade_setup_filter_observation`
- read `paper_advice_observation`
- read `vw_paper_advice_execution_zone_context_v1` when available
- write requested local research artifacts, such as `/tmp/...html` and optional
  JSONL events

Forbidden:

- broker calls
- broker writes
- order submission
- decision gate logic
- execution planner logic
- executor logic
- operational `execution_zone_context` backfills
- systemd timer or live dashboard runner changes

The runner prints:

```text
broker_private_calls=0 broker_writes=0 order_submission=0 executor=none
```

## Inputs

Required CLI inputs:

```bash
python -m src.research.run_pipeline_visual_backtest_v1 \
  --symbol NEAR \
  --venue bitvavo \
  --interval 4h \
  --start-ts "2026-05-15 00:00:00" \
  --end-ts "2026-05-18 21:00:00" \
  --output-html /tmp/near-pipeline-backtest-v1.html \
  --output-events-jsonl /tmp/near-pipeline-backtest-v1.jsonl \
  --output table
```

`market_price_snapshot` is not required for V1. Historical candles are the
primary price path.

## Event Model

The runner reads observations within the requested window and evaluates future
candles after each `asof_ts_utc`. It does not create real trades.

Generated event types:

- `SETUP_PASS`
- `SETUP_FAIL`
- `ENTER_SIM`
- `EXIT_TARGET_SIM`
- `EXIT_RISK_SIM`
- `MAP_INVALIDATED_PENDING_RECOMPUTE`
- `BLOCK_MARKET_DAMAGE_RISK`
- `BLOCK_AVOID_OR_DO_NOT_ADD`
- `TIMEOUT_SIM`

V1 policy:

- `BLOCK_MARKET_DAMAGE_RISK` when `setup_filter_reason` is
  `MARKET_DAMAGE_RISK`.
- `BLOCK_AVOID_OR_DO_NOT_ADD` when `advice_action` is one of
  `AVOID_NO_NEW_BUY`, `DO_NOT_ADD`, `BLOCK_FOR_24H`, or
  `CONTEXT_ONLY_WAIT_FOR_MARKET_SETUP`.
- `ENTER_SIM` only when `setup_filter_state = PASS` or `allowed_now` is true.
- `EXIT_TARGET_SIM` when future candle high/low reaches the target reference for
  the observed `leg_direction`.
- `EXIT_RISK_SIM` when invalidation is reached before target.
- `TIMEOUT_SIM` after `--max-bars`, default `12`, when no target or risk exit is
  observed.

## Zone Invalidation

`MAP_INVALIDATED_PENDING_RECOMPUTE` is a state marker, not a recompute action.

It is emitted when:

- `leg_direction = DOWN` and a future candle high or close is above
  `invalidation_price`
- `leg_direction = UP` and a future candle low or close is below
  `invalidation_price`

The runner never recomputes zones and never writes `execution_zone_context`.
Operational `execution_zone_context` must not be historically backfilled for this
analysis. Any future historical zone replay should write to a research/backtest
namespace such as `synth_bt` or an explicit `data/research/...` artifact.

## Chart Output

The HTML chart contains:

- Plotly candlesticks from `obs_market_candle`
- selection timestamp guide lines
- entry zone band when context is available
- target zone band when context is available
- invalidation line when context is available
- markers for simulated entry, target exit, risk exit, map invalidation, and
  block events

Marker hover text includes timestamp, event type, setup filter reason, advice
action, selection state, leg direction, entry zone, target reference, and
invalidation price.

## Interpretation

This is a visual backtest aid. It is useful for seeing whether current pipeline
labels line up with the next candles in a small window.

It is not sufficient to validate strategy edge. Forward-return validation should
still proceed through the separate sequence:

1. Same-window buy-and-hold baseline.
2. `selection_state` forward return validation.
3. `trade_setup_filter_v1` pass/fail/reason validation.
4. `paper_advice_policy_v1` label validation after point-in-time A+ and zone
   replay sources exist.
5. Rotation preview retrospective review only.
