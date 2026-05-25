# Strategy Scoreboard Regime Join V1

## Purpose

`run_strategy_scoreboard_regime_join_v1.py` joins strict-future-valid zone/fib replay rows with discovered market regimes.

The goal is to test whether the current scoreboard candidate buckets are robust across discovered regimes or only work in narrow regime contexts.

This is research/reporting only.
It is not live or paper permission.

## Scope

- research/reporting only
- file-input only
- deterministic
- no DB writes
- no runtime table writes
- no broker/account/order usage
- no `selection_engine`, `decision_gate`, `execution_planner`, or `executor` changes

Generated outputs are written under ignored run directories:

```text
data/research/strategy_scoreboard_regime_join_v1/run_<YYYYMMDDTHHMMSSZ>/
```

## Inputs

Required inputs:

- `historical_zone_fib_replay_audit_v1/run_<RUN>/zone_fib_replay_events_v1.csv`
- `market_regime_discovery_v1/run_<RUN>/discovered_regime_samples_v1.csv`
- `strategy_scoreboard_v1/run_<RUN>/strategy_scoreboard_v1.csv`

The scoreboard file is used as evidence context for the focused strict-future TP buckets.

## Join

V1 joins:

- zone/fib replay events
- discovered regime samples

on:

- `sample_ts_utc`

It preserves:

- `sample_ts_utc`
- `symbol`
- `leg_direction`
- `tp_alignment_label`
- `valid_future_tp_target`
- `discovered_regime_id`
- `discovered_regime_label_auto`

Only strict-future-valid rows are used:

- `valid_future_tp_target = 1`

Focused TP alignment buckets:

- `TP_NEAR_FIB_EXTENSION`
- `TP_FIB_EXTENSION_1272_1618`
- `TP_SR_ONLY`

## Metrics

Grouped by `tp_alignment_label + discovered_regime_id + horizon`:

- `event_count`
- `avg_return_pct`
- `median_return_pct`
- `winrate_pct`
- `profit_factor`
- `avg_winner_pct`
- `avg_loser_pct`
- `hit_tp_future_strict_4h_rate_pct`
- `hit_tp_future_strict_24h_rate_pct`
- `hit_tp_future_strict_48h_rate_pct`
- `baseline_all_avg_return_pct`
- `excess_vs_regime_baseline_pct`
- `promotion_state_regime_v1`
- `promotion_reason_regime_v1`

Grouped by `symbol + tp_alignment_label + discovered_regime_id + horizon`:

- the same core metrics

## Promotion Rules

V1 uses conservative regime-local promotion states:

- `REJECT_INSUFFICIENT_SAMPLE`
- `REJECT_NEGATIVE_EXPECTANCY`
- `WATCH_MORE_DATA`
- `RESEARCH_REGIME_CANDIDATE`

Rules require:

- enough samples within the discovered regime
- positive excess return vs the same-regime baseline
- positive median return or acceptable winrate/profit factor

No state here grants live permission.

## CLI

```bash
python -m src.research.run_strategy_scoreboard_regime_join_v1 \
  --zone-fib-run-dir data/research/historical_zone_fib_replay_audit_v1/run_20260525T052504Z \
  --regime-run-dir data/research/market_regime_discovery_v1/run_20260524T094933Z \
  --scoreboard-run-dir data/research/strategy_scoreboard_v1/run_20260525T120428Z \
  --write-files
```

## Outputs

- `strategy_scoreboard_regime_join_events_v1.csv`
- `summary_by_tp_alignment_regime_v1.csv`
- `summary_by_symbol_tp_alignment_regime_v1.csv`
- `summary_by_regime_v1.csv`
- `manifest_v1.json`

## Safety

Manifest markers:

- `db_writes=0`
- `broker_calls=0`
- `broker_writes=0`
- `order_submission=0`
- `decision_gate_changes=0`
- `execution_planner_changes=0`
- `executor=none`
- `account_tables_used=false`
