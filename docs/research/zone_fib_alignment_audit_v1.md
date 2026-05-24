# Zone Fib Alignment Audit V1

## Purpose

`zone_fib_alignment_audit_v1` compares historical execution entry and take-profit zones against fib observation levels.

The goal is to measure whether entry and TP zones are:

- fib-aligned
- SR-only
- fallback extension style

## Scope And Boundaries

- research-only
- read-only DB
- no DB writes
- no broker
- no account
- no orders
- no dashboard
- no `selection_engine` changes
- no `decision_gate` changes
- no `execution_planner` changes
- no `executor` changes
- no logic tuning

Generated outputs are written under ignored run directories:

```text
data/research/zone_fib_alignment_audit_v1/run_<YYYYMMDDTHHMMSSZ>/
```

## Inputs

- `execution_zone_context`
- `fib_observation_v2` or compatibility `fib_observation`
- `zone_observation_v2` or compatibility `zone_observation`
- `obs_market_candle`
- `asset`

## CLI

```bash
python -m src.research.run_zone_fib_alignment_audit_v1 --help
```

Arguments:

- `--venue`
- `--interval`
- `--start-ts`
- `--end-ts`
- `--max-rows`
  - `0` means unlimited
- `--write-files` / `--no-write-files`
- `--output-root`

## Output Files

- `zone_fib_alignment_events_v1.csv`
- `summary_by_entry_alignment_v1.csv`
- `summary_by_tp_alignment_v1.csv`
- `summary_by_symbol_v1.csv`
- `summary_by_zone_type_v1.csv`
- `manifest_v1.json`

## Event Fields

- `symbol`
- `asof_ts_utc`
- `leg_direction`
- `entry_zone_type`
- `entry_zone_low/high`
- `tp_zone_type`
- `tp_zone_low/high`
- `fib_0500_price`
- `fib_0618_price`
- `fib_0786_price`
- `ext_1272_price`
- `ext_1618_price`
- `nearest_entry_fib_level`
- `entry_fib_distance_pct`
- `nearest_tp_fib_level`
- `tp_fib_distance_pct`
- `entry_alignment_label`
- `tp_alignment_label`
- `entry_is_fib_band`
- `tp_is_fib_extension_band`
- `distance_to_tp_pct`
- `forward_return_24h_pct`
- `forward_return_48h_pct`
- `hit_tp_24h`
- `hit_tp_48h`

## Interpretation Notes

- Entry alignment uses retracement-band overlap and nearest fib distance.
- TP alignment uses extension-band overlap and nearest extension distance.
- Future candles are used only for research outcome measurement.
- This runner does not modify execution context, zone logic, fib logic, or any runtime path.

## Smoke Example

```bash
python -m src.research.run_zone_fib_alignment_audit_v1 \
  --venue bitvavo \
  --interval 4h \
  --start-ts 2026-05-01T00:00:00Z \
  --end-ts 2026-05-10T23:59:59Z \
  --max-rows 200 \
  --write-files \
  --output table
```

## Full-ish Example

```bash
python -m src.research.run_zone_fib_alignment_audit_v1 \
  --venue bitvavo \
  --interval 4h \
  --start-ts 2026-04-01T00:00:00Z \
  --end-ts 2026-05-23T23:59:59Z \
  --max-rows 0 \
  --write-files \
  --output table
```
