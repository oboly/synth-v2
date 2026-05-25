# Historical Zone/Fib Replay Audit V1

## Purpose

`run_historical_zone_fib_replay_audit_v1.py` replays zone/fib context historically from point-in-time market structure tables.

It is research-only.

It does not use:

- `execution_zone_context` as the historical source
- broker/account/order inputs
- dashboard/runtime outputs

## Historical Source Rules

Inputs:

- `fib_observation_v2` when available, otherwise `fib_observation`
- `zone_observation_v2` when available, otherwise `zone_observation`
- `obs_market_candle`
- `asset`

For each sampled historical timestamp:

1. use only fib and zone rows with `asof_ts_utc = sample_ts_utc`
2. reconstruct entry and TP zones from those rows
3. use future candles only for outcome measurement

If any input timestamp is greater than `sample_ts_utc`, the row is flagged as leakage.

## Replay Logic

The replay rebuilds a minimal historical execution-style context from stored observations:

- entry zone:
  - choose the best fib zone from `FIB_RETRACEMENT` and `FIB_DEEP`
  - score uses stored zone strength, confluence, and overlap bonus with SR zones
- TP zone:
  - for `UP`, prefer strongest `SR_RESISTANCE`
  - for `DOWN`, prefer strongest `SR_SUPPORT`
  - if missing, fall back to fib extension band from `ext_1272_price` and `ext_1618_price`

This is intended to mirror the stored market-structure context closely enough for retrospective alignment studies, not to claim replay-safe execution behavior.

## Alignment Labels

Entry labels:

- `ENTRY_FIB_PRIMARY_0500_0618`
- `ENTRY_FIB_DEEP_0618_0786`
- `ENTRY_SR_ONLY`
- `ENTRY_UNKNOWN`

TP labels:

- `TP_FIB_EXTENSION_1272_1618`
- `TP_NEAR_FIB_EXTENSION`
- `TP_SR_ONLY`
- `TP_UNKNOWN`

## Hit-TP Sanity Diagnostics

The runner now distinguishes raw TP-touch counts from directional TP-hit diagnostics.
It also adds strict future-only TP-hit diagnostics that exclude the sample candle from the hit window.

Added event fields:

- `tp_side_label`
- `tp_already_crossed_at_sample`
- `directional_distance_to_tp_pct`
- `hit_tp_directional_4h`
- `hit_tp_directional_8h`
- `hit_tp_directional_12h`
- `hit_tp_directional_24h`
- `hit_tp_directional_48h`
- `max_high_4h`
- `min_low_4h`
- `max_high_24h`
- `min_low_24h`
- `hit_tp_sanity_note`
- `forward_window_first_candle_ts_4h`
- `forward_window_first_candle_ts_24h`
- `forward_window_candle_count_4h`
- `forward_window_candle_count_24h`
- `hit_tp_future_strict_4h`
- `hit_tp_future_strict_8h`
- `hit_tp_future_strict_12h`
- `hit_tp_future_strict_24h`
- `hit_tp_future_strict_48h`
- `future_strict_hit_note`
- `valid_future_tp_target`
- `invalid_future_tp_reason`

`tp_side_label` values:

- `TP_ABOVE_PRICE`
- `TP_BELOW_PRICE`
- `TP_AT_OR_NEAR_PRICE`
- `TP_WRONG_SIDE_FOR_LEG`
- `TP_UNKNOWN`

Directional rules:

- `UP` TP should be above sample close
- `DOWN` TP should be below sample close
- if `UP` target is already at or below sample close, it is marked as already crossed
- if `DOWN` target is already at or above sample close, it is marked as already crossed
- directional future hit is only counted when the target is still on the correct side at sample time

This keeps legacy `hit_tp_*` fields for continuity while exposing whether those counts were inflated by already-crossed or wrong-side targets.

Strict future-only rules:

- sample candle high/low is excluded from strict future TP-hit tests
- strict hit uses only candles with `candle_ts > sample_ts_utc`
- `valid_future_tp_target=false` when:
  - target was already crossed at sample
  - target is on the wrong side for the leg
  - target is at or near sample price
  - no future candles exist

`invalid_future_tp_reason` values:

- `ALREADY_CROSSED_AT_SAMPLE`
- `WRONG_SIDE_FOR_LEG`
- `AT_OR_NEAR_PRICE`
- `NO_FUTURE_CANDLES`
- `VALID`

## Outputs

Default output root:

`data/research/historical_zone_fib_replay_audit_v1/run_<UTC_RUN_ID>/`

Files:

- `zone_fib_replay_events_v1.csv`
- `summary_by_entry_alignment_v1.csv`
- `summary_by_tp_alignment_v1.csv`
- `summary_by_tp_alignment_directional_v1.csv`
- `summary_by_tp_alignment_future_strict_v1.csv`
- `summary_by_symbol_v1.csv`
- `summary_by_leg_direction_v1.csv`
- `summary_by_tp_alignment_and_leg_v1.csv`
- `summary_by_tp_side_label_v1.csv`
- `summary_by_tp_side_future_strict_v1.csv`
- `summary_by_tp_alignment_and_side_v1.csv`
- `summary_by_tp_alignment_and_side_future_strict_v1.csv`
- `summary_by_valid_future_tp_target_v1.csv`
- `manifest_v1.json`
- `leakage_guard_report_v1.json`

Generated outputs are ignored by git.

## CLI

```bash
python -m src.research.run_historical_zone_fib_replay_audit_v1 \
  --venue bitvavo \
  --interval 4h \
  --start-ts 2026-04-01T00:00:00Z \
  --end-ts 2026-05-23T23:59:59Z \
  --sample-every-n 1 \
  --max-samples 0 \
  --horizons-hours 4,8,12,24,48 \
  --write-files
```

Spaced horizons are also accepted:

```bash
python -m src.research.run_historical_zone_fib_replay_audit_v1 \
  --venue bitvavo \
  --interval 4h \
  --start-ts 2026-04-01T00:00:00Z \
  --end-ts 2026-05-23T23:59:59Z \
  --horizons-hours 4 8 12 24 48 \
  --write-files
```

Smoke example:

```bash
python -m src.research.run_historical_zone_fib_replay_audit_v1 \
  --venue bitvavo \
  --interval 4h \
  --start-ts 2026-05-01T00:00:00Z \
  --end-ts 2026-05-05T23:59:59Z \
  --max-samples 10 \
  --write-files
```

## Leakage Guard

`leakage_guard_report_v1.json` records:

- point-in-time source usage
- future-candle usage boundary
- `max_input_ts_gt_sample_ts_rows`
- directional hit field presence
- strict future hit field presence
- sample-candle exclusion from strict hit tests

Expected safe result:

- `max_input_ts_gt_sample_ts_rows = 0`

## Boundaries

- research-only
- point-in-time only
- no DB writes
- no broker calls
- no broker writes
- no order submission
- no account tables
- no `selection_engine` changes
- no `decision_gate` changes
- no `execution_planner` changes
- no `executor` changes
