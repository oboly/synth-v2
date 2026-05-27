# Reload Reaction Scalp Parameter Sweep V1

## Purpose

`run_reload_reaction_scalp_parameter_sweep_v1.py` is a research-only parameter
sweep for one strategy candidate:

- `RELOAD_REACTION_SCALP_V1`

This tunes one candidate lane only.
It does not tune the whole bot.

It exists to test whether reload-after-spike / reaction-zone logic behaves more
like a short reaction scalp than a long hold.

## Why This Exists

The motivating chart review case was a `LINK` `RELOAD_REVIEW`
`APLUS_CONTEXT` event.

Observed visual pattern:

- the zone looked plausible
- the trigger looked too late
- `MFE` was positive
- `24h` return was weak or flat

That suggests a hypothesis:

- some reload review events may work as reaction scalps
- the same events may not work well as passive 24h holds

This runner tests that hypothesis repeatedly across a parameter grid.

## Inputs

Primary input:

- `data/research/position_lifecycle_outcome_validation_v1/outcome_rows_v1.jsonl`

Optional secondary input:

- `data/research/fibo_target_map_v1/fibo_target_map_rows_v1.csv`

Current safety guard:

- latest symbol-level fibo map rows are not point-in-time safe for historical
  lifecycle events
- therefore fib target modes are guarded and skipped unless a safe historical
  fib source exists

The runner does not create fills and does not claim real execution PnL.

## Scope

This lane is:

- research-only
- account-aware read-only only because lifecycle outcome rows come from the
  lifecycle validation lane
- non-executable

Forbidden:

- orders
- paper fills
- executor
- `decision_gate`
- `execution_planner`
- `selection_engine` changes

## Base Event Filter

Base event universe:

- `position_lifecycle_action == RELOAD_REVIEW`
- `current_price` present
- `entry_zone_low` and `entry_zone_high` present
- prefer `leg_direction == UP`
- skip stale or missing critical inputs as needed

CLI filters:

- `--action RELOAD_REVIEW`
- `--primary-bucket APLUS_CONTEXT` or `ALL`
- `--symbols BTC,ETH,...`

## Parameter Grid

Swept families:

1. `reload_zone_part`
- `entry_low`
- `entry_mid`
- `entry_high`

2. `near_zone_threshold_pct`
- `0.5`
- `1.0`
- `1.5`
- `2.0`
- `3.0`

3. `trigger_basis`
- `current_price_near_zone`
- `current_price_inside_zone`
- `current_price_above_entry_high_max_late`

4. `max_late_distance_above_zone_pct`
- `0.25`
- `0.5`
- `1.0`

5. `target_mode`
- `local_reaction`
- `fib_1272_if_available`
- `fib_1618_if_available`

6. `max_hold_horizon`
- `15m`
- `30m`
- `1h`
- `2h`
- `4h`
- `24h`

7. `require_aplus_context`
- `false`
- `true`

## Return Model

This runner uses:

- `POLICY_PROXY_RETURN`

It is not real PnL.

Current proxy rule:

- if the candidate target return is less than or equal to event `MFE`, the
  sweep assumes the target could have been hit within the chosen horizon
- otherwise it falls back to the same-horizon close return already stored in the
  lifecycle outcome row

This is intentionally labeled:

- `POLICY_PROXY_RETURN`

because it is not a fill engine, not a live strategy result, and not a paper
execution result.

## Metrics

Per parameter set:

- `sample_count`
- `avg_strategy_return_pct`
- `median_strategy_return_pct`
- `avg_hold_return_pct`
- `median_hold_return_pct`
- `excess_return_vs_hold_pct`
- `winrate_pct`
- `avg_mfe_pct`
- `avg_mae_pct`
- `avg_opportunity_missed_pct`
- `max_drawdown_proxy_pct`
- `avg_drawdown_improvement_vs_hold_pct`
- `symbol_count`
- `top_symbol_concentration_pct`

## HOLD Baseline Rule

Every strategy candidate must be compared against:

- `HOLD` / buy-and-hold baseline

Required interpretation:

- report excess return versus `HOLD`
- report drawdown improvement versus `HOLD`
- profit alone is not sufficient

If a scalp variant is profitable in isolation but does not improve on the
matching hold baseline, it is not enough.

## Overfit And Concentration Guards

Default guard:

- `--min-samples 20`

Additional warnings:

- report symbol concentration
- flag overfit risk if one symbol is more than `30%` of the sample
- prefer transition-only lifecycle input rows when available/generated that way

This runner does not assume broad validity from one symbol-dominated bucket.

## Current Fibo Guard

The optional Fibo target map file is useful for future ladder-aware variants,
but the currently available latest symbol-level file is not point-in-time safe
for historical lifecycle events.

Therefore:

- `fib_1272_if_available`
- `fib_1618_if_available`

are currently guarded and skipped unless a point-in-time-safe fib source is
available later.

This avoids using latest context as historical truth.

## Outputs

When `--write-files` is enabled:

- `reload_reaction_scalp_parameter_sweep_rows_v1.csv`
- `reload_reaction_scalp_parameter_sweep_rows_v1.jsonl`
- `reload_reaction_scalp_top_candidates_v1.csv`
- `reload_reaction_scalp_rejected_candidates_v1.csv`
- `manifest_v1.json`

Default output root:

- `data/research/reload_reaction_scalp_parameter_sweep_v1`

## Terminal Summary

Summary output includes:

- report name/version
- events loaded
- events eligible
- parameter sets tested
- top candidates by `excess_return_vs_hold_pct`
- top candidates by drawdown improvement
- rejected variants with negative excess return
- safety markers

## Safety

This runner must remain:

- `broker_calls=0`
- `broker_writes=0`
- `order_submission=0`
- `executor=none`
- `live_trading=false`
- `research_only=true`

It does not create order intents.

## CLI

Compile:

```bash
python -m py_compile src/research/run_reload_reaction_scalp_parameter_sweep_v1.py
```

Help:

```bash
python -m src.research.run_reload_reaction_scalp_parameter_sweep_v1 --help
```

Smoke:

```bash
python -m src.research.run_reload_reaction_scalp_parameter_sweep_v1 \
  --max-events 5000 \
  --min-samples 20 \
  --output summary
```

Write-files smoke:

```bash
python -m src.research.run_reload_reaction_scalp_parameter_sweep_v1 \
  --max-events 5000 \
  --min-samples 20 \
  --write-files \
  --output summary
```
