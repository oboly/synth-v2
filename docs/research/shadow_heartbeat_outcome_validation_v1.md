# Shadow Heartbeat Outcome Validation V1

## Purpose

`run_shadow_heartbeat_outcome_validation_v1.py` is a research-only runner that measures what happened after live-like shadow heartbeat states.

It validates heartbeat cohorts against forward market movement only:

- `ENTRY_CANDIDATE`: candidate-quality cohort
- `WAIT_RETEST`: setup-maturation cohort
- `NO_CANDIDATE`: baseline/noise cohort
- `BLOCKED`: safety/control cohort, not a bearish signal

This is outcome measurement only. It is not paper trading, not live trading, not execution, and not executor enablement.

## Inputs

The runner reads local heartbeat artifacts from:

- `data/research/live_like_shadow_chain_v1/run_*/chain_summary_v1.json`
- `data/research/live_like_shadow_chain_v1/run_*/manifest_v1.json`

When linked run dirs are still present, it also reads:

- candidate: `strategy_candidate_v1.json`
- decision: `decision_preview_v1.json`
- shadow event: `shadow_event_v1.json`

For forward outcomes, it reads market candles from `obs_market_candle` with explicit read-only research queries only.

Defaults:

- `--chain-root`: `data/research/live_like_shadow_chain_v1`
- `--output-dir`: `data/research/shadow_heartbeat_outcome_validation_v1`
- inferred `--symbol` from heartbeat history unless passed explicitly
- inferred `--venue` from heartbeat artifacts unless passed explicitly
- inferred `--interval` from heartbeat artifacts unless passed explicitly
- default interval fallback: `15m`

## Output files

Rows:

```text
data/research/shadow_heartbeat_outcome_validation_v1/outcome_rows_v1.jsonl
```

Summary:

```text
data/research/shadow_heartbeat_outcome_validation_v1/outcome_summary_v1.json
```

## Per-event output

Each event row includes:

- `event_ts`
- `symbol`
- derived cohort `state`
- raw `candidate_state`, `decision_state`, `execution_plan_state`
- `permission_state` when available
- available heartbeat labels such as `entry_state`, `label_state_15m`, `label_state_1h`
- `reference_price`
- future prices and returns at:
  - `15m`
  - `30m`
  - `1h`
  - `2h`
  - `4h`
  - `8h`
  - `24h`
- `max_forward_return_pct`
- `min_forward_return_pct`
- `mfe_pct`
- `mae_pct`
- hit flags for `+0.5%`, `+1.0%`, `-0.5%`, `-1.0%`
- sample completeness flags
- transition metadata from the prior heartbeat cohort for the same symbol

## Summary output

The summary groups rows by cohort state and shows:

- count
- complete count
- average and median returns per horizon
- average and median `mfe_pct`
- average and median `mae_pct`
- hit rates for `+0.5%`, `+1.0%`, `-0.5%`, `-1.0%`
- transition-aware counts when heartbeat history contains state changes

## Safety guarantees

This runner is bounded to research and read-only validation:

- read-only
- no DB writes
- `broker_calls=0`
- `broker_writes=0`
- `order_submission=0`
- `executor=none`
- `account_awareness=0`
- no strategy changes
- no decision gate changes
- no execution planner runtime changes
- no paper trading
- no live trading

It does not create orders, permissions, plans, or executor paths.

## Interpretation boundaries

Interpret these cohorts narrowly:

- `ENTRY_CANDIDATE`: measures candidate quality only
- `WAIT_RETEST`: measures setup maturation only
- `NO_CANDIDATE`: measures baseline/noise only
- `BLOCKED`: measures safety/control behavior only

Do not convert the results into strategy rules yet.

This runner is not performance validation in the execution sense. It does not model fills, fees, slippage, sizing, or account constraints.

## CLI

Compile:

```bash
python -m py_compile src/research/run_shadow_heartbeat_outcome_validation_v1.py
```

Help:

```bash
python -m src.research.run_shadow_heartbeat_outcome_validation_v1 --help
```

Smoke summary:

```bash
python -m src.research.run_shadow_heartbeat_outcome_validation_v1 \
  --max-events 20 \
  --output summary
```

Smoke summary plus files:

```bash
python -m src.research.run_shadow_heartbeat_outcome_validation_v1 \
  --max-events 20 \
  --write-files \
  --output summary
```
