# Breathline Symbol Timeline Report V1

## Purpose

`run_breathline_symbol_timeline_report_v1.py` is a research-only, read-only CLI
report for one or more symbols.

It shows a transparent combined read across:

- raw A+ Table 1 posture
- raw A+ Table 2 harmonic phase
- current Synth comparison bucket/context
- reload/curve context when available
- observed forward returns when public candle history is available

This is not a dashboard.

V1 focuses on clear CLI output:

- `table`
- `timeline`
- `json`

## Scope

This runner is:

- research-only
- read-only
- transparent

It does not:

- write to DB
- call brokers
- submit orders
- change `selection_engine`
- change `decision_gate`
- change `execution_planner`
- change `executor`

## Inputs

Required:

- Prime-17 Table 1 raw snapshot
- Prime-17 Table 2 raw snapshot

Optional / reused:

- `src.research.run_aplus_vs_synth_comparison_report_v1`
- `src.research.run_aplus_vs_synth_comparison_outcome_validation_v1`
- reload selected-event file when present
- public `obs_market_candle` history

## Phase Window Concept

Breath phases are treated as variable-duration intervals, not precise timestamps.

V1 uses conservative estimated windows:

- `early` / `forming`
  - snapshot to roughly `+2d`
- `confirmed`
  - roughly `-1d` to `+3d`
- `late` / `exhausted`
  - roughly `-2d` to `+1d`
- `reset` / `unclear`
  - unknown window

The report prints these as estimated windows only.
It does not claim precise phase timing.

## Table Output

Columns:

- `symbol`
- `snapshot_ts_utc`
- `aplus_phase`
- `aplus_field`
- `aplus_role`
- `aplus_bias`
- `harmonic_phase`
- `phase_state`
- `offset_band`
- `drift_direction`
- `quality`
- `extension_risk`
- `estimated_window_utc`
- `estimated_duration_days`
- `comparison_bucket`
- `synth_bucket`
- `selection_state`
- `setup_state`
- `zone_context_summary`
- `reload_context_summary`
- `volume_context_summary`
- `return_15m`
- `return_1h`
- `return_4h`
- `return_24h`
- `phase_read`
- `interpretation`

## Timeline Output

For each symbol, V1 prints a compact ASCII timeline:

- A+ posture
- harmonic phase
- Synth curve/reload context
- observed returns
- interpretation

This is intended for manual inspection, not machine scoring.

## Interpretation Labels

V1 uses explicit deterministic labels:

- `DIRTY_SQUEEZE`
  - A+ caution/deterioration but later return is positive
- `CONSTRUCTIVE_CURVE_WINDOW`
  - A+ constructive and Synth raw context is positive
- `BREATH_POSITIVE_TIMING_BLOCKED`
  - A+ constructive but Synth is blocked
- `CURVE_AGAINST_BREATH_CAUTION`
  - Synth raw context is positive while A+ is caution
- `WEAK_OR_LATE_PHASE`
  - both cautionary / late / weak
- `ALIGNED_CONSTRUCTIVE_WINDOW`
  - both sides align constructively
- `BREATH_POSITIVE_SYNTH_WAIT`
  - A+ constructive while Synth remains waiting
- `MIXED_OR_UNCLEAR`
  - catch-all mixed case

These are report labels only.
They are not trading rules.

## Missing Candles

If forward candles are missing:

- return fields stay `None`
- the report still prints cleanly
- no values are invented

## CLI

Compile:

```bash
python -m py_compile src/research/run_breathline_symbol_timeline_report_v1.py
```

Help:

```bash
python -m src.research.run_breathline_symbol_timeline_report_v1 --help
```

One-symbol timeline:

```bash
python -m src.research.run_breathline_symbol_timeline_report_v1 \
  --table1-raw data/aplus_raw/2026-05-29_1246_table1_prime17_focus_snapshot.txt \
  --table2-raw data/aplus_raw/2026-05-29_1246_table2_prime17_focus_snapshot.txt \
  --symbols RENDER \
  --output timeline
```

Multi-symbol timeline:

```bash
python -m src.research.run_breathline_symbol_timeline_report_v1 \
  --table1-raw data/aplus_raw/2026-05-29_1246_table1_prime17_focus_snapshot.txt \
  --table2-raw data/aplus_raw/2026-05-29_1246_table2_prime17_focus_snapshot.txt \
  --symbols RENDER XLM ETH \
  --output timeline
```

Table:

```bash
python -m src.research.run_breathline_symbol_timeline_report_v1 \
  --table1-raw data/aplus_raw/2026-05-29_1246_table1_prime17_focus_snapshot.txt \
  --table2-raw data/aplus_raw/2026-05-29_1246_table2_prime17_focus_snapshot.txt \
  --symbols RENDER XLM ETH \
  --output table
```

JSON:

```bash
python -m src.research.run_breathline_symbol_timeline_report_v1 \
  --table1-raw data/aplus_raw/2026-05-29_1246_table1_prime17_focus_snapshot.txt \
  --table2-raw data/aplus_raw/2026-05-29_1246_table2_prime17_focus_snapshot.txt \
  --symbols RENDER XLM ETH \
  --output json
```

## Safety

Safety markers remain explicit:

- `broker_calls=0`
- `broker_writes=0`
- `order_submission=0`
- `executor=none`
- `live_trading=false`
