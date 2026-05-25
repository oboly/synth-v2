# Strategy Scoreboard V1

## Purpose

`run_strategy_scoreboard_v1.py` builds a research/reporting scoreboard from replay outputs.

It is the bridge from:

- Synth can observe structure/context historically

to:

- specific buckets may be strong enough to consider for later paper-only promotion work

It is not live permission.
It is not a trade instruction.

## Scope

- research/reporting only
- deterministic
- file-output only
- no runtime table writes
- no broker/account/order usage
- no `decision_gate`, `execution_planner`, or `executor` changes

## Inputs

Primary input:

- latest local `historical_zone_fib_replay_audit_v1` run by default

Optional input:

- explicit `--zone-fib-run-dir`
- explicit `--rotation-run-dir`

V1 uses the zone/fib replay as the actual scoring source.
If a rotation run is passed, it is recorded in the input manifest but not used for scoring in this first version.

## Baseline

`BUY_AND_HOLD_BASELINE` is derived from the replay rows themselves.

Because the replay forward return is leg-adjusted:

- `UP` rows keep the raw forward return
- `DOWN` rows invert the replay return back into raw buy-and-hold market return

This gives a simple passive comparator on the same sampled event universe without introducing a separate operational dependency.

## Initial Scoreboard Families

- `BUY_AND_HOLD_BASELINE`
- `TP_ALIGNMENT`
- `TP_ALIGNMENT_STRICT_FUTURE`
- `TP_SIDE`
- `VALID_FUTURE_TP_TARGET`

`TP_ALIGNMENT_STRICT_FUTURE` uses only rows where `valid_future_tp_target = 1`.

## Metrics

Per row:

- `strategy_key`
- `strategy_family`
- `signal_bucket`
- `horizon_hours`
- `sample_count`
- `avg_return_pct`
- `median_return_pct`
- `winrate_pct`
- `profit_factor`
- `max_drawdown_pct`
- `avg_winner_pct`
- `avg_loser_pct`
- `baseline_buy_hold_avg_pct`
- `excess_return_vs_baseline_pct`
- `hit_tp_future_strict_4h_rate_pct`
- `hit_tp_future_strict_24h_rate_pct`
- `hit_tp_future_strict_48h_rate_pct`
- `fee_slippage_placeholder_bps`
- `promotion_state`
- `promotion_reason`

## Promotion Rules V1

States:

- `REJECT_INSUFFICIENT_SAMPLE`
- `REJECT_NEGATIVE_EXPECTANCY`
- `WATCH_MORE_DATA`
- `RESEARCH_PROMOTION_CANDIDATE`
- `READY_FOR_PAPER_ONLY`
- `BLOCKED_NEEDS_REPLAY_SAFE_VALIDATION`

Rules are conservative and deterministic.

High level:

- baseline rows are comparator-only and stay blocked
- broad `TP_ALIGNMENT` and `TP_SIDE` rows stay blocked until strict-future-valid evidence is used
- invalid future TP target rows stay blocked
- positive expectancy alone is not enough
- positive excess return vs buy-and-hold is required
- sample count thresholds must be met before candidate or paper-only states are allowed

No state here grants live permission.

## HTML

The runner writes a simple static HTML table sorted by:

1. `promotion_state`
2. `excess_return_vs_baseline_pct`

Top note:

`Research scoreboard only. No row is a trade instruction.`

## CLI

```bash
python -m src.research.run_strategy_scoreboard_v1 \
  --venue bitvavo \
  --interval 4h \
  --start-ts 2026-04-01T00:00:00Z \
  --end-ts 2026-05-23T23:59:59Z \
  --write-files
```

Smoke example:

```bash
python -m src.research.run_strategy_scoreboard_v1 \
  --venue bitvavo \
  --interval 4h \
  --start-ts 2026-05-01T00:00:00Z \
  --end-ts 2026-05-05T23:59:59Z \
  --symbols BTC,ETH,SOL \
  --max-samples 10 \
  --write-files
```

## Outputs

Default output root:

`data/research/strategy_scoreboard_v1/run_<UTC_RUN_ID>/`

Files:

- `strategy_scoreboard_v1.csv`
- `strategy_scoreboard_v1.jsonl`
- `strategy_scoreboard_v1.html`
- `scoreboard_inputs_manifest_v1.json`
- `manifest_v1.json`

Generated outputs are ignored by git.

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

Manifest also records input completeness fields for inspection:

- `scoreboard_rows`
- `zone_fib_input_event_count`
- `zone_fib_filtered_event_count`
- `rotation_rows_loaded`
- `rotation_rows_used_in_v1`
- `source_file_based=true`
